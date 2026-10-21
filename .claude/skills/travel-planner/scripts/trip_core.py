"""Portable trip validation and safe, explicit output projection. Python 3.10+."""
from __future__ import annotations
import base64
import copy
import json
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from pathlib import Path
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = '1.1.0'
COLLECTIONS = ('places','bookings','days','legs','availability','overnight_exceptions','costs','declared_totals','exchange_rates','checklist','sources','media','photo_attempts','constraints','changes')
STATUSES = {'confirmed','proposed','unknown','fictional'}
FIXED_BOOKING_FIELDS = {'type','name','place_id','start_at','end_at','origin','destination','flight_number','check_in','check_out','check_in_time','check_out_time','address','phone','conditions','booking_reference','passenger_names'}
DATE_RE = re.compile(r'^\d{4}-\d{2}-\d{2}$')
DECIMAL_RE = re.compile(r'^\d+(?:\.\d+)?$')
ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,99}$')

def load_trip(path):
    def no_duplicates(pairs):
        out = {}
        for k,v in pairs:
            if k in out: raise ValueError('Duplicate JSON key: '+k)
            out[k] = v
        return out
    with Path(path).open(encoding='utf-8-sig') as f:
        result = json.load(f, object_pairs_hook=no_duplicates, parse_constant=lambda x: (_ for _ in ()).throw(ValueError('Non-finite JSON number')))
    if not isinstance(result,dict): raise ValueError('Trip JSON must be an object')
    return result

def safe_url(value):
    if not isinstance(value,str) or not value or any(ord(c)<32 for c in value): return ''
    try:
        u=urlsplit(value)
        if u.scheme.lower() not in ('https','http') or not u.hostname or u.username or u.password: return ''
        return value
    except ValueError: return ''

def _date(v):
    if not isinstance(v,str) or not DATE_RE.fullmatch(v): return None
    try: return date.fromisoformat(v)
    except ValueError: return None

def _time(v):
    if not isinstance(v,str) or 'T' not in v: return None
    try:
        t=datetime.fromisoformat(v.replace('Z','+00:00'))
        return t if t.utcoffset() is not None else None
    except (ValueError,OverflowError): return None

def _decimal(v):
    if not isinstance(v,str) or not DECIMAL_RE.fullmatch(v) or len(v)>40: return None
    try:
        d=Decimal(v)
        return d if d.is_finite() and d>=0 else None
    except InvalidOperation: return None

def money(value,currency):
    d=_decimal(value)
    if d is None: return '미확인'
    return f'{d:,.0f}' + f' {currency}' if d == d.to_integral() else f'{d:,.2f} {currency}'

def date_label(value,language='ko'):
    d=_date(value)
    if not d: return str(value or '미정')
    return f'{d.month}월 {d.day}일 {"월화수목금토일"[d.weekday()]}요일' if language=='ko' else d.strftime('%b %d, %a')

def duration_nights(booking):
    a,b=_date(booking.get('check_in')),_date(booking.get('check_out'))
    return (b-a).days if a and b else None

def activity_places(activity):
    """An explicit transfer has distinct start/end locations; prose is not evidence."""
    if activity.get('type') == 'travel' and activity.get('from_place_id') and activity.get('to_place_id'):
        return activity['from_place_id'], activity['to_place_id']
    return activity.get('place_id'), activity.get('place_id')

def traveler_checks(trip):
    """Group actionable diagnostics, retaining dates/routes without exposing codes."""
    ko = trip.get('language', 'ko') == 'ko'
    places = {p['id']: p for p in trip.get('places', [])}
    activities = {a['id']: a for d in trip.get('days', []) for a in d.get('activities', [])}
    titles = {
        'missing_leg': ('이동시간 보완', 'Add transfer times'),
        'travel_unverified': ('배정한 이동시간 재확인', 'Check planned transfer times'),
        'travel_buffer': ('이동 여유시간 확인', 'Check transfer buffers'),
        'travel_impossible': ('이동시간 부족', 'Insufficient transfer time'),
        'hours_unverified': ('방문 장소·운영시간 확인', 'Check venues and opening hours'),
        'closed': ('휴무일과 일정 충돌', 'Visit falls on a closed day'),
        'outside_hours': ('운영시간과 일정 충돌', 'Visit outside opening hours'),
    }
    groups = {}
    def location(pid, fallback=''):
        return places.get(pid, {}).get('name') or fallback
    for severity in ('conflicts', 'warnings'):
        for issue in trip.get('validation', {}).get(severity, []):
            code = issue.get('code')
            # These remain in the machine report and their relevant sections;
            # neither is a departure task or an itinerary defect.
            if code in ('separate_currencies', 'baseline_absent'):
                continue
            message = issue.get('message') or ('추가 확인이 필요합니다.' if ko else 'Further checking is needed.')
            key = (severity, code, message)
            title = titles.get(code, ('일정 충돌 확인' if severity == 'conflicts' else '추가 확인',
                                      'Review conflict' if severity == 'conflicts' else 'Additional check'))[0 if ko else 1]
            group = groups.setdefault(key, dict(title=title, message=message, severity=severity, contexts=[]))
            rows = [activities[i] for i in issue.get('activity_ids', []) if i in activities]
            context = ''
            if code in ('missing_leg', 'travel_unverified', 'travel_buffer', 'travel_impossible') and rows:
                if len(rows) > 1:
                    fr, to = activity_places(rows[0])[1], activity_places(rows[-1])[0]
                else:
                    fr, to = activity_places(rows[0])
                context = location(fr, rows[0].get('title', '')) + ' → ' + location(to, rows[-1].get('title', ''))
            elif rows:
                context = ', '.join(dict.fromkeys(location(a.get('place_id'), a.get('title', '')) for a in rows))
            day = issue.get('date')
            path = issue.get('path', '')
            match = re.match(r'days\[(\d+)\]', path)
            if not day and match and int(match[1]) < len(trip.get('days', [])):
                day = trip['days'][int(match[1])]['date']
            if not context:
                match = re.match(r'bookings\[(\d+)\]', path)
                if match and int(match[1]) < len(trip.get('bookings', [])):
                    context = trip['bookings'][int(match[1])].get('name', '')
            entry = dict(date=day, text=context)
            if (day or context) and entry not in group['contexts']:
                group['contexts'].append(entry)
    return list(groups.values())

def validate_trip(trip,baseline=None,allow_changes=None):
    r={'errors':[],'conflicts':[],'warnings':[],'totals':{},'conversion':None}
    def add(level,code,path,message,**context): r[level].append({'code':code,'path':path,'message':message,**context})
    def err(code,path,message): add('errors',code,path,message)
    def warn(code,path,message,**context): add('warnings',code,path,message,**context)
    def conflict(code,path,message,**context): add('conflicts',code,path,message,**context)
    if not isinstance(trip,dict):
        err('shape','$','여행 데이터는 JSON 객체여야 합니다.'); return r
    for k in ('trip_id','title','base_currency'):
        if not isinstance(trip.get(k),str) or not trip[k].strip(): err('required',k,'필수 문자열을 입력하세요.')
    if not ID_RE.fullmatch(str(trip.get('trip_id',''))): err('id','trip_id','안정적인 영문·숫자 ID를 사용하세요.')
    if trip.get('schema_version')!='1.0': err('schema','schema_version','지원하는 데이터 버전은 1.0입니다.')
    if type(trip.get('revision')) is not int or trip.get('revision',0)<1: err('revision','revision','revision은 1 이상의 정수여야 합니다.')
    if trip.get('language') not in ('ko','en'): err('language','language','language는 ko 또는 en이어야 합니다.')
    if trip.get('audience') not in ('private','shared'): err('audience','audience','공유 범위를 private 또는 shared로 정하세요.')
    outputs=trip.get('requested_outputs')
    if not isinstance(outputs,list) or not outputs or any(x not in ('html','pdf') for x in outputs) or len(set(map(str,outputs)))!=len(outputs): err('outputs','requested_outputs','사용자가 선택한 html, pdf 또는 두 형식을 지정하세요.')
    if not re.fullmatch('[A-Z]{3}',str(trip.get('base_currency',''))): err('currency','base_currency','통화는 대문자 3자리 코드여야 합니다.')
    start,end=_date(trip.get('start_date')),_date(trip.get('end_date'))
    if not start: err('date','start_date','실제 존재하는 YYYY-MM-DD 날짜가 필요합니다.')
    if not end: err('date','end_date','실제 존재하는 YYYY-MM-DD 날짜가 필요합니다.')
    if start and end and end<start: err('date_order','end_date','여행 종료일이 시작일보다 빠릅니다.')
    if start and end and (end-start).days>730: err('date_span','end_date','한 여행의 검증 범위는 최대 731일입니다. 여행을 나누세요.')
    for k in COLLECTIONS:
        if k in trip and (not isinstance(trip[k],list) or any(not isinstance(x,dict) for x in trip[k])): err('shape',k,'이 항목은 객체의 배열이어야 합니다.')
    if not isinstance(trip.get('days'),list) or not trip.get('days'): err('required','days','날짜별 일정이 필요합니다.')
    # Stop before traversing malformed structures.
    if any(x['code']=='shape' for x in r['errors']): return r
    for k in ('party','preferences'):
        if k in trip and trip[k] is not None and not isinstance(trip[k],dict): err('shape',k,'객체를 사용하세요.')
    for di,d in enumerate(trip.get('days',[])):
        for k in ('activities','important_notes','place_ids'):
            if k in d and not isinstance(d[k],list): err('shape',f'days[{di}].{k}','배열을 사용하세요.')
        if isinstance(d.get('activities'),list) and any(not isinstance(a,dict) for a in d['activities']): err('shape',f'days[{di}].activities','활동은 객체의 배열이어야 합니다.')
        for k in ('summary','guide','alternatives'):
            if k in d and not isinstance(d[k],dict): err('shape',f'days[{di}].{k}','객체를 사용하세요.')
        g=d.get('guide',{})
        if isinstance(g,dict) and ('sections' in g) and (not isinstance(g['sections'],list) or any(not isinstance(x,dict) for x in g['sections'])): err('shape',f'days[{di}].guide.sections','섹션은 객체의 배열이어야 합니다.')
        al=d.get('alternatives',{})
        if isinstance(al,dict) and any(not isinstance(v,dict) for v in al.values()): err('shape',f'days[{di}].alternatives','대안은 객체여야 합니다.')
    if any(x['code']=='shape' for x in r['errors']): return r
    # Reject containers masquerading as scalar fields before any dictionary lookup
    # or public projection. Unknown extension fields remain private and untouched.
    string_fields=set('id trip_id title subtitle country_label notice agenda transit stay purpose name description time_label start_at end_at date check_in check_out check_in_time check_out_time address phone conditions origin destination flight_number time_note booking_reference private_notes source_path status type icon note region pace intro heading body fallback_title fallback effect text currency base_currency total_amount paid_amount unit_amount quantity component from_currency to_currency rate checked_at url file_name private_path data_uri role alt caption creator source_url license license_url depicts kind value unit reason target_id field photo_policy photo_note identity_source_url identity_note'.split())
    string_lists={'source_ids','place_ids','locked_fields','passenger_names','important_notes'}
    boolean_fields={'checked','public','closed','is_fictional_demo','redacted','verified_property'}
    known_fields=string_fields|string_lists|boolean_fields|set(COLLECTIONS)|set('activities schema_version revision language audience requested_outputs start_date end_date timezone party adults children summary guide alternatives sections weather fatigue delay lat lng min_minutes max_minutes nights walk_km rest_minutes place_id from_place_id to_place_id booking_id from_activity_id to_activity_id source_ids place_ids locked_fields'.split())
    def shapes(obj,path='$'):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if k not in known_fields: continue
                p=path+'.'+k
                if k in string_fields and v is not None and not isinstance(v,str): err('shape',p,'이 필드에는 문자열 또는 null만 사용할 수 있습니다.')
                if k in string_lists and (not isinstance(v,list) or any(not isinstance(x,str) for x in v)): err('shape',p,'문자열 배열을 사용하세요.')
                if k in ('adults','children') and (type(v) is not int or v<0): err('shape',p,'인원은 0 이상의 정수여야 합니다.')
                if k in ('walk_km','rest_minutes') and v is not None and (type(v) not in (str,int,float) or _decimal(str(v)) is None): err('shape',p,'보행량·휴식량은 0 이상의 숫자여야 합니다.')
                if k in boolean_fields and type(v) is not bool: err('shape',p,'true 또는 false를 사용하세요.')
                shapes(v,p)
        elif isinstance(obj,list):
            for i,v in enumerate(obj): shapes(v,f'{path}[{i}]')
    shapes(trip)
    if any(x['code']=='shape' for x in r['errors']): return r
    if trip.get('photo_policy', 'auto') not in ('auto','off'):
        err('photo_policy','photo_policy','사진 정책은 auto 또는 off여야 합니다.')
    if trip.get('photo_policy')=='off' and not trip.get('photo_note'):
        err('photo_policy','photo_note','사용자가 사진을 원하지 않은 이유나 요청을 기록하세요.')
    indexes={}
    for k in ('places','bookings','legs','availability','costs','checklist','sources','media'):
        indexes[k]={}
        for i,item in enumerate(trip.get(k,[])):
            id_=item.get('id'); path=f'{k}[{i}]'
            if not isinstance(id_,str) or not ID_RE.fullmatch(id_): err('id',path+'.id','안정적인 영문·숫자 ID가 필요합니다.'); continue
            if id_ in indexes[k]: err('duplicate_id',path+'.id','ID가 중복됩니다.')
            indexes[k][id_]=item
    activities={}; dated=[]
    for di,d in enumerate(trip.get('days',[])):
        path=f'days[{di}]'; day=_date(d.get('date'))
        if not day: err('date',path+'.date','일정 날짜가 유효하지 않습니다.')
        else: dated.append(day)
        if day and start and end and not start<=day<=end: err('date_range',path+'.date','여행 기간 밖의 일정입니다.')
        for ai,a in enumerate(d.get('activities',[])):
            aid=a.get('id'); ap=f'{path}.activities[{ai}]'
            if not isinstance(aid,str) or not ID_RE.fullmatch(aid): err('id',ap+'.id','활동 ID가 필요합니다.'); continue
            if aid in activities: err('duplicate_id',ap+'.id','활동 ID가 중복됩니다.')
            activities[aid]=a
            fr,to=a.get('from_place_id'),a.get('to_place_id')
            if fr is not None or to is not None:
                if a.get('type')!='travel' or not fr or not to:
                    err('travel_endpoints',ap,'이동 일정에는 출발·도착 장소를 함께 지정하고 type을 travel로 설정하세요.')
                if a.get('place_id') is not None and a.get('place_id')!=to:
                    err('travel_destination',ap,'이동 일정의 place_id는 도착 장소와 같아야 합니다.')
            if not a.get('title'): err('required',ap+'.title','활동 제목이 필요합니다.')
            at=_time(a.get('start_at'))
            if at and day and at.date()!=day: conflict('activity_date',ap,'활동 시작의 현지 날짜가 배치된 날짜와 다릅니다.')
        timed=[a for a in d.get('activities',[]) if _time(a.get('start_at')) and _time(a.get('end_at'))]
        timed.sort(key=lambda a:_time(a['start_at']))
        for prev,nxt in zip(timed,timed[1:]):
            if _time(prev['end_at'])>_time(nxt['start_at']): conflict('overlap',path,'같은 날의 활동 시간이 겹칩니다.')
        if any(not _time(a.get('start_at')) or not _time(a.get('end_at')) for a in d.get('activities',[])):
            warn('unknown_time',path,'일부 활동의 시작·종료 시각이 미정이어서 시간 충돌을 모두 확인할 수 없습니다.')
    if len(dated)!=len(set(dated)): err('duplicate_date','days','같은 날짜가 두 번 들어 있습니다.')
    if dated!=sorted(dated): err('date_order','days','날짜별 일정을 날짜순으로 정렬하세요.')
    if start and end and 0<=(end-start).days<=730:
        expected={start+timedelta(days=i) for i in range((end-start).days+1)}
        if expected!=set(dated): err('missing_day','days','여행 기간의 모든 날짜를 한 번씩 포함해야 합니다.')
    indexes['activities']=activities
    def walk(obj,path='$'):
        if isinstance(obj,dict):
            for k,v in obj.items():
                if k not in known_fields: continue
                p=path+'.'+k
                if k in ('place_id','from_place_id','to_place_id','booking_id','from_activity_id','to_activity_id') and v is not None:
                    group={'place_id':'places','from_place_id':'places','to_place_id':'places','booking_id':'bookings','from_activity_id':'activities','to_activity_id':'activities'}[k]
                    if not isinstance(v,str) or v not in indexes[group]: err('reference',p,'참조 대상 ID가 없습니다.')
                if k in ('source_ids','place_ids','locked_fields'):
                    if not isinstance(v,list) or any(not isinstance(x,str) for x in v): err('shape',p,'문자열 ID 배열이 필요합니다.')
                    elif k!='locked_fields':
                        group='sources' if k=='source_ids' else 'places'
                        if any(x not in indexes[group] for x in v): err('reference',p,'참조 대상 ID가 없습니다.')
                if k in ('start_at','end_at') and v is not None and not _time(v): err('datetime',p,'시간대 오프셋이 포함된 ISO 날짜·시각이 필요합니다.')
                if k=='timezone' and v is not None:
                    try: ZoneInfo(v)
                    except (ZoneInfoNotFoundError,ValueError,TypeError): err('timezone',p,'유효한 IANA 시간대가 필요합니다.')
                walk(v,p)
            a,b=_time(obj.get('start_at')),_time(obj.get('end_at'))
            if a and b and b<=a: err('time_order',path,'종료 시각이 시작 시각보다 늦어야 합니다.')
        elif isinstance(obj,list):
            for i,v in enumerate(obj): walk(v,f'{path}[{i}]')
    walk(trip)
    for i,p in enumerate(trip.get('places',[])):
        lat,lng=p.get('lat'),p.get('lng')
        if (lat is None)!=(lng is None): err('coordinates',f'places[{i}]','위도와 경도는 함께 지정하거나 둘 다 비워두세요.')
        for key,limit in (('lat',90),('lng',180)):
            v=p.get(key)
            if v is not None and (type(v) not in (float,int) or not -limit<=v<=limit): err('coordinates',f'places[{i}].{key}','좌표 범위가 유효하지 않습니다.')
    stays=[]
    for i,b in enumerate(trip.get('bookings',[])):
        bp=f'bookings[{i}]'
        if b.get('type') not in ('stay','flight','activity','transport'): err('booking_type',bp,'예약 유형이 필요합니다.')
        if b.get('status') not in STATUSES: err('status',bp,'예약 확정 상태를 명시하세요.')
        if not b.get('name'): err('required',bp+'.name','예약 이름이 필요합니다.')
        if b.get('type')=='stay':
            ci,co=_date(b.get('check_in')),_date(b.get('check_out'))
            for k in ('check_in','check_out'):
                if b.get(k) is not None and not _date(b[k]): err('date',bp+'.'+k,'숙박 날짜가 유효하지 않습니다.')
            if ci and co:
                if co<=ci: err('stay_order',bp,'체크아웃은 체크인 다음 날 이후여야 합니다.')
                else:
                    stays.append((ci,co,b))
                    if b.get('nights') is not None and (type(b['nights']) is not int or b['nights']!=(co-ci).days): err('nights',bp,'숙박 박수와 체크인·체크아웃 날짜가 다릅니다.')
            else: warn('unknown_stay_date',bp,'숙박 날짜가 미확인입니다.')
            if not b.get('address'): warn('unknown_address',bp,'숙소의 실제 주소가 미확인입니다. 지역 지도는 숙소 위치를 뜻하지 않습니다.')
        elif b.get('type')=='flight' and (not _time(b.get('start_at')) or not _time(b.get('end_at'))): warn('unknown_flight_time',bp,'항공편의 현지 출발·도착 날짜와 시각을 확인해야 합니다.')
        if b.get('status')=='confirmed' and not b.get('source_ids'): warn('booking_evidence',bp,'확정 예약의 원자료 출처가 없습니다.')
    exceptions=set()
    for i,x in enumerate(trip.get('overnight_exceptions',[])):
        dt=_date(x.get('date'))
        if not dt or not x.get('reason'): err('overnight_exception',f'overnight_exceptions[{i}]','숙박 예외에는 유효한 날짜와 이유가 필요합니다.')
        else: exceptions.add(dt)
    if start and end and 0<=(end-start).days<=730:
        for offset in range((end-start).days):
            dt=start+timedelta(days=offset); covered=[b for ci,co,b in stays if ci<=dt<co]
            if not covered and dt not in exceptions: conflict('overnight_gap','bookings',f'{dt.isoformat()} 밤의 숙소 또는 야간 이동 설명이 없습니다.')
            if len(covered)>1: conflict('overnight_overlap','bookings',f'{dt.isoformat()} 밤에 숙박 예약이 겹칩니다. 여러 객실인지 확인하세요.')
    # Physical travel and operating hours are only as strong as explicit, sourced inputs.
    legpairs=set()
    for i,leg in enumerate(trip.get('legs',[])):
        lp=f'legs[{i}]'; fr,to=activities.get(leg.get('from_activity_id')),activities.get(leg.get('to_activity_id'))
        legpairs.add((leg.get('from_activity_id'),leg.get('to_activity_id')))
        lo,hi=leg.get('min_minutes'),leg.get('max_minutes')
        for k,v in (('min_minutes',lo),('max_minutes',hi)):
            if v is not None and (type(v) not in (int,float) or not 0<=v<=100000): err('duration',lp+'.'+k,'이동시간은 0 이상의 분 단위 숫자여야 합니다.')
        if type(lo) in (int,float) and type(hi) in (int,float) and hi<lo: err('duration_order',lp,'최대 이동시간이 최소 이동시간보다 작습니다.')
        if not fr or not to: continue
        a,b=_time(fr.get('end_at')),_time(to.get('start_at'))
        ctx={'activity_ids':[fr['id'],to['id']], 'date':a.date().isoformat() if a else None}
        if a and b and type(lo) in (int,float) and (b-a).total_seconds()/60<lo: conflict('travel_impossible',lp,'다음 활동까지 확보한 시간이 최소 이동시간보다 짧습니다.',**ctx)
        elif a and b and type(hi) in (int,float) and (b-a).total_seconds()/60<hi: warn('travel_buffer',lp,'확보한 시간이 추정 이동시간 범위 안에 있어 연결 가능 여부를 확정할 수 없습니다.',**ctx)
        if not a or not b or hi is None or leg.get('status')!='confirmed' or not leg.get('source_ids'): warn('travel_unverified',lp,'실제 이동시간과 경로를 확인해 배정한 시간이 충분한지 점검하세요.',**ctx)
    for di,d in enumerate(trip.get('days',[])):
        acts=d.get('activities',[])
        for ai,a in enumerate(acts):
            if a.get('type')=='travel' and a.get('from_place_id') and a.get('to_place_id'):
                booking=indexes['bookings'].get(a.get('booking_id'),{}) if isinstance(a.get('booking_id'),str) else {}
                sourced_schedule=(booking.get('type') in ('flight','transport') and booking.get('source_ids')
                                  and _time(a.get('start_at')) and _time(a.get('end_at'))
                                  and a.get('start_at')==booking.get('start_at') and a.get('end_at')==booking.get('end_at'))
                if not sourced_schedule and (a.get('status')!='confirmed' or not a.get('source_ids') or not _time(a.get('start_at')) or not _time(a.get('end_at'))):
                    warn('travel_unverified',f'days[{di}].activities[{ai}]','실제 이동시간과 경로를 확인해 배정한 시간이 충분한지 점검하세요.',date=d.get('date'),activity_ids=[a['id']])
        for ai,(a,b) in enumerate(zip(acts,acts[1:])):
            fr,to=activity_places(a)[1],activity_places(b)[0]
            if fr and to and fr!=to and (a.get('id'),b.get('id')) not in legpairs:
                warn('missing_leg',f'days[{di}].activities[{ai+1}]','장소가 바뀌는 구간의 이동시간을 일정에 추가하세요.',date=d.get('date'),activity_ids=[a['id'],b['id']])
    for i,op in enumerate(trip.get('availability',[])):
        if not _date(op.get('date')): err('date',f'availability[{i}].date','운영일 날짜가 필요합니다.')
        if type(op.get('closed')) is not bool: err('availability',f'availability[{i}]','휴무 여부를 true 또는 false로 명시하세요.')
    for di,d in enumerate(trip.get('days',[])):
        unchecked=[]
        for a in d.get('activities',[]):
            if not a.get('place_id') or a.get('type') in ('stay','rest','travel'): continue
            ops=[o for o in trip.get('availability',[]) if o.get('place_id')==a.get('place_id') and o.get('date')==d.get('date')]
            known=[o for o in ops if o.get('status')=='confirmed' and o.get('source_ids')]
            if any(o.get('closed') is True for o in known): conflict('closed',f'days[{di}]','방문 예정 장소에 해당 날짜의 휴무 정보가 있습니다.'); continue
            at,bt=_time(a.get('start_at')),_time(a.get('end_at'))
            intervals=[(_time(o.get('start_at')),_time(o.get('end_at'))) for o in known if not o.get('closed')]
            intervals=[(s,e) for s,e in intervals if s and e]
            if at and bt and intervals and not any(s<=at and bt<=e for s,e in intervals): conflict('outside_hours',f'days[{di}]','방문 시각이 확인된 운영시간 안에 들어가지 않습니다.')
            elif not intervals or not at or not bt: unchecked.append(a['id'])
        if unchecked: warn('hours_unverified',f'days[{di}]','방문할 장소와 해당 날짜의 운영시간·약속 시간을 확인하세요.',date=d.get('date'),activity_ids=unchecked)
    totals={}; linked={}
    for i,c in enumerate(trip.get('costs',[])):
        cp=f'costs[{i}]'; currency=c.get('currency')
        if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency): err('currency',cp,'비용 통화는 대문자 3자리 코드여야 합니다.'); continue
        vals={}
        for k in ('total_amount','paid_amount','unit_amount','quantity'):
            v=c.get(k); vals[k]=_decimal(v)
            if v is not None and vals[k] is None: err('money',cp+'.'+k,'금액·수량은 0 이상의 십진수 문자열이어야 합니다.')
        total,paid=vals['total_amount'],vals['paid_amount']
        if total is None: warn('unknown_cost',cp,'금액 미확인 항목은 합계에서 제외되어 있습니다.')
        else: totals[currency]=totals.get(currency,Decimal(0))+total
        if paid is not None and total is not None and paid>total: err('paid_exceeds_total',cp,'기지급액이 총액보다 큽니다.')
        if vals['unit_amount'] is not None and vals['quantity'] is not None and total is not None and vals['unit_amount']*vals['quantity']!=total: err('unit_total',cp,'단가 × 수량이 총액과 다릅니다.')
        bid=c.get('booking_id')
        if bid:
            component=c.get('component')
            if bid in linked and (not component or None in linked[bid] or component in linked[bid]): err('duplicate_booking_cost',cp,'같은 예약의 비용이 중복될 수 있습니다. 별도 구성요소를 명시하세요.')
            linked.setdefault(bid,set()).add(component)
    r['totals']={k:format(v,'f') for k,v in totals.items()}
    for i,t in enumerate(trip.get('declared_totals',[])):
        val=_decimal(t.get('total_amount')); curr=t.get('currency')
        if val is None: err('money',f'declared_totals[{i}]','선언 합계에는 십진수 문자열이 필요합니다.')
        elif totals.get(curr,Decimal(0))!=val: conflict('total_mismatch',f'declared_totals[{i}]','입력된 합계와 항목별 합계가 다릅니다.')
    rates={}
    for i,rate in enumerate(trip.get('exchange_rates',[])):
        v=_decimal(rate.get('rate'))
        if v is None or v<=0 or not _date(rate.get('checked_at')) or not rate.get('source_ids'): err('exchange_rate',f'exchange_rates[{i}]','환율에는 양수 십진수·확인일·출처가 필요합니다.'); continue
        pair=(rate.get('from_currency'),rate.get('to_currency'))
        if pair in rates: err('duplicate_rate',f'exchange_rates[{i}]','같은 통화 쌍의 환율이 중복됩니다.')
        rates[pair]=v
    base=trip.get('base_currency'); other=[k for k in totals if k!=base]
    if other and all((k,base) in rates for k in other):
        value=sum((v if k==base else v*rates[(k,base)] for k,v in totals.items()),Decimal(0))
        r['conversion']={'currency':base,'total_amount':format(value,'f'),'estimated':True,'rates':copy.deepcopy(trip.get('exchange_rates',[]))}
    elif other: warn('separate_currencies','costs','환율 근거가 없는 통화는 각각 합산합니다. 서로 다른 통화를 더하지 않습니다.')
    for i,c in enumerate(trip.get('constraints',[])):
        v=_decimal(c.get('value')); kind=c.get('kind')
        if v is None or kind not in ('max_daily_walk_km','min_rest_minutes'): err('constraint',f'constraints[{i}]','지원하는 제약과 십진수 값을 입력하세요.'); continue
        key='walk_km' if kind=='max_daily_walk_km' else 'rest_minutes'
        for di,d in enumerate(trip.get('days',[])):
            acts=d.get('activities',[]); values=[_decimal(str(a[key])) for a in acts if a.get(key) is not None]
            if any(x is None for x in values): err('constraint_value',f'days[{di}]','보행량·휴식량 수치가 유효하지 않습니다.'); continue
            total=sum(values,Decimal(0))
            if kind=='max_daily_walk_km' and total>v: conflict('walking_limit',f'days[{di}]','명시된 하루 보행량이 사용자의 상한을 넘습니다.')
            if kind=='min_rest_minutes' and total<v: conflict('rest_minimum',f'days[{di}]','명시된 휴식시간이 사용자의 최소 기준보다 짧습니다.')
            if len(values)<len(acts): warn('constraint_unknown',f'days[{di}]','보행량·휴식량이 모두 입력되지 않아 제약 충족을 확정할 수 없습니다.')
    for i,s in enumerate(trip.get('sources',[])):
        if s.get('url') is not None and not safe_url(s['url']): err('unsafe_url',f'sources[{i}]','출처 URL은 정상적인 HTTP(S) 주소여야 합니다.')
        if s.get('checked_at') is not None and not _date(s['checked_at']): err('date',f'sources[{i}].checked_at','출처 확인일이 유효하지 않습니다.')
        if s.get('type') not in ('web','document','user'): err('source_type',f'sources[{i}]','출처 유형을 명시하세요.')
        if s.get('type')=='web' and not s.get('checked_at'): warn('source_unchecked',f'sources[{i}]','웹 출처의 확인일이 없습니다.')
    for i,m in enumerate(trip.get('media',[])):
        mp=f'media[{i}]'; uri=m.get('data_uri','')
        if m.get('role') not in ('hero','stay','place'): err('media_role',mp,'사진 배치 역할은 hero, stay, place 중 하나여야 합니다.')
        if m.get('role')=='hero' and m.get('depicts')!='landscape': err('media_hero',mp,'대표 사진은 여행 도시·지역 풍경이어야 합니다. 호텔 사진은 숙소 영역에 배치하세요.')
        match=re.fullmatch(r'data:image/(jpeg|png|webp);base64,([A-Za-z0-9+/=\s]+)',uri) if isinstance(uri,str) and len(uri)<22*1024*1024 else None
        valid=False
        if match:
            try:
                raw=base64.b64decode(re.sub(r'\s','',match[2]),validate=True)
                valid=0<len(raw)<=15*1024*1024 and ((match[1]=='jpeg' and raw.startswith(b'\xff\xd8\xff')) or (match[1]=='png' and raw.startswith(b'\x89PNG\r\n\x1a\n')) or (match[1]=='webp' and raw[:4]==b'RIFF' and raw[8:12]==b'WEBP'))
            except ValueError: pass
        if not valid: err('media',mp,'이미지는 15MiB 이하의 실제 JPEG·PNG·WebP 내장 데이터여야 합니다.')
        for k in ('source_url','license_url','identity_source_url'):
            if m.get(k) and not safe_url(m[k]): err('unsafe_url',mp+'.'+k,'이미지 링크는 HTTP(S) 주소여야 합니다.')
        if not m.get('alt'): warn('image_alt',mp,'이미지 설명이 없습니다.')
        if not m.get('license') or not m.get('creator'): warn('image_rights',mp,'이미지 사용 조건 또는 제작자 정보가 없습니다. 공개 전 확인하세요.')
    for i,a in enumerate(trip.get('photo_attempts',[])):
        if a.get('role') not in ('hero','stay','place') or not a.get('reason'):
            err('photo_attempt',f'photo_attempts[{i}]','사진 확보 실패에는 배치 역할과 구체적인 이유가 필요합니다.')
    # An input changes[] entry is commentary, never authorization.
    if baseline is None:
        warn('baseline_absent','revision','이전 원본이 없어 확정 예약 보존 비교는 수행하지 않았습니다.')
    elif not isinstance(baseline,dict): err('baseline','baseline','이전 원본은 JSON 객체여야 합니다.')
    else:
        base_report=validate_trip(baseline)
        if base_report['errors']:
            err('baseline_invalid','baseline','이전 원본 데이터가 유효하지 않아 예약 보존을 비교할 수 없습니다.')
            return r
        if trip.get('trip_id')!=baseline.get('trip_id'): err('trip_identity','trip_id','수정 시 원래 trip_id를 유지하세요.')
        if baseline.get('audience')=='private' and trip.get('redacted') is True: err('redacted_baseline','audience','공유용으로 축약한 데이터로 개인용 원본을 덮어쓸 수 없습니다.')
        permissions=allow_changes if isinstance(allow_changes,dict) else {}
        authorized=permissions.get('bookings',{}) if isinstance(permissions.get('bookings',{}),dict) else {}
        deletions=permissions.get('delete_bookings',[]) if isinstance(permissions.get('delete_bookings',[]),list) else []
        current={b.get('id'):b for b in trip.get('bookings',[])}
        for b in baseline.get('bookings',[]):
            if not isinstance(b,dict): continue
            bid=b.get('id'); locked=set(b.get('locked_fields') or [])
            if b.get('status')=='confirmed': locked |= FIXED_BOOKING_FIELDS | {'status'}
            if not locked: continue
            cand=current.get(bid)
            if cand is None:
                if bid not in deletions: err('locked_deleted','bookings','확정 또는 잠긴 예약을 삭제하려면 별도 변경 승인이 필요합니다.')
                continue
            permitted=authorized.get(bid,[])
            if not isinstance(permitted,list): permitted=[]
            for field in sorted(locked):
                if b.get(field)!=cand.get(field) and '*' not in permitted and field not in permitted: err('locked_field','bookings.'+str(bid)+'.'+field,'확정 또는 잠긴 예약 필드가 승인 없이 변경되었습니다.')
            # Preserve locks as data too; clearing them must not unlock a later round trip.
            if not set(b.get('locked_fields') or []).issubset(set(cand.get('locked_fields') or [])) and '*' not in permitted and 'locked_fields' not in permitted: err('lock_removed','bookings.'+str(bid),'기존 예약 잠금을 승인 없이 제거할 수 없습니다.')
        ignore={'revision','generation','validation','requested_outputs','audience','redacted','changes','exported_at'}
        def substantive(data):
            result={k:copy.deepcopy(v) for k,v in data.items() if k not in ignore}
            for item in result.get('checklist',[]): item.pop('checked',None)
            return result
        changed=substantive(trip)!=substantive(baseline)
        rev,old=trip.get('revision'),baseline.get('revision')
        if type(rev) is int and type(old) is int:
            if changed and rev<=old: err('revision_not_advanced','revision','여행 내용을 수정했으면 revision을 올리세요.')
            elif rev<old: err('revision_regressed','revision','revision을 이전 값보다 낮출 수 없습니다.')
    if not r['errors']:
        from media_pipeline import assess_media
        r['media'] = assess_media(trip)
    return r

# Shared output is a projection, including nested objects. Unknown fields are not copied.
SHARED_KEYS={
 'places':'id name address lat lng timezone source_ids',
 'bookings':'id type name status place_id source_ids check_in check_out check_in_time check_out_time address phone conditions nights start_at end_at origin destination flight_number time_note',
 'activities':'id title description time_label start_at end_at place_id from_place_id to_place_id booking_id status type icon note walk_km rest_minutes source_ids',
 'legs':'id from_activity_id to_activity_id min_minutes max_minutes status source_ids',
 'availability':'id place_id date closed start_at end_at status source_ids',
 'costs':'id category total_amount paid_amount currency booking_id status unit_amount quantity source_ids component',
 'declared_totals':'currency total_amount source_ids',
 'exchange_rates':'from_currency to_currency rate checked_at source_ids',
 'checklist':'id text checked',
 'sources':'id title type url checked_at public',
 'media':'id role place_id data_uri alt caption creator source_url license license_url depicts checked_at verified_property identity_source_url identity_note',
 'photo_attempts':'role place_id reason checked_at',
 'constraints':'kind value unit source_ids',
 'overnight_exceptions':'date reason booking_id',
}

def display_trip(trip,report,generation):
    if trip.get('audience')!='shared':
        out=copy.deepcopy(trip)
    else:
        def pick(obj,keys): return {k:copy.deepcopy(obj[k]) for k in keys.split() if k in obj}
        out=pick(trip,'schema_version trip_id revision title subtitle country_label start_date end_date language base_currency audience requested_outputs timezone is_fictional_demo notice photo_policy photo_note')
        out['party']=pick(trip.get('party') or {},'adults children')
        for group,keys in SHARED_KEYS.items(): out[group]=[pick(x,keys) for x in trip.get(group,[])]
        out['sources']=[s for s in out['sources'] if s.get('public') is True and s.get('type')=='web' and safe_url(s.get('url'))]
        public_ids={s['id'] for s in out['sources']}
        out['days']=[]
        for d in trip.get('days',[]):
            day=pick(d,'date title subtitle pace region place_ids important_notes')
            day['summary']=pick(d.get('summary',{}),'agenda transit stay purpose')
            day['activities']=[pick(a,SHARED_KEYS['activities']) for a in d.get('activities',[])]
            guide=d.get('guide',{}); day['guide']=pick(guide,'intro fallback_title fallback')
            day['guide']['sections']=[pick(s,'heading body source_ids') for s in guide.get('sections',[])]
            day['alternatives']={k:pick(v,'title description effect source_ids') for k,v in d.get('alternatives',{}).items() if k in ('weather','fatigue','delay')}
            out['days'].append(day)
        def scrub(obj):
            if isinstance(obj,dict):
                for k,v in list(obj.items()):
                    if k=='source_ids': obj[k]=[x for x in v if x in public_ids]
                    else: scrub(v)
            elif isinstance(obj,list):
                for v in obj: scrub(v)
        scrub(out)
        out['redacted']=True
    out['generation']=copy.deepcopy(generation)
    out['validation']=copy.deepcopy(report)
    if trip.get('audience')=='shared':
        # Keep only public itinerary references for contextual traveler checks.
        # Private paths, arbitrary metadata and conversion sources stay excluded.
        activity_ids={a['id'] for d in out['days'] for a in d.get('activities',[])}
        dates={d['date'] for d in out['days']}
        for level in ('errors','conflicts','warnings'):
            out['validation'][level]=[{'code':x['code'],'path':'','message':x['message'],
                                      'date':x.get('date') if x.get('date') in dates else None,
                                      'activity_ids':[i for i in x.get('activity_ids',[]) if i in activity_ids]}
                                     for x in report[level]]
        if out['validation'].get('conversion'):
            out['validation']['conversion']['rates']=out.get('exchange_rates',[])
    return out
