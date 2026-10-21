#!/usr/bin/env python3
"""Generate only the formats selected in canonical trip JSON. No network/install."""
from __future__ import annotations
import argparse,json,os,sys,tempfile,uuid
from datetime import datetime,timezone
from pathlib import Path
from trip_core import VERSION,load_trip,validate_trip,display_trip

def generate(input_path,out_dir,baseline_path=None,allow_path=None,export_json=False):
 trip=load_trip(input_path)
 baseline=load_trip(baseline_path) if baseline_path else None
 allow=load_trip(allow_path) if allow_path else None
 report=validate_trip(trip,baseline,allow)
 if report['errors']: return {'status':'blocked','files':[],'validation':report},2
 if export_json and trip.get('audience')=='shared':
  return {'status':'blocked','files':[],'error':'공유본은 원본 JSON 백업을 내보내지 않습니다. 개인용 원본에서 별도로 요청하세요.'},2
 requested=trip['requested_outputs'];out_dir=Path(out_dir).resolve()
 names={'html':'travel.html','pdf':'travelbook.pdf'}
 for fmt,name in names.items():
  if fmt not in requested and (out_dir/name).exists():
   return {'status':'blocked','files':[],'error':'출력 폴더에 선택하지 않은 형식의 구본이 있습니다. 새 출력 폴더를 지정하세요. 기존 파일은 보존했습니다.'},2
 out_dir.mkdir(parents=True,exist_ok=True)
 for name in [names[f] for f in requested]+(['trip-backup.json'] if export_json else []):
  if (out_dir/name).resolve() in {Path(x).resolve() for x in (input_path,baseline_path,allow_path) if x}:
   return {'status':'blocked','files':[],'error':'원본 입력과 출력 경로가 같습니다. 새 출력 폴더를 지정하세요.'},2
 generation={'id':str(uuid.uuid4()),'generated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'template_version':VERSION}
 view=display_trip(trip,report,generation)
 successes={};failures=[]
 with tempfile.TemporaryDirectory(prefix='.travel-stage-',dir=out_dir) as stage:
  temp=Path(stage)
  # PDF first so HTML only links to a successful PDF from the same run.
  for fmt in ('pdf','html'):
   if fmt not in requested: continue
   target=temp/names[fmt]
   try:
    if fmt=='pdf':
     from render_travelbook import render_travelbook
     result=render_travelbook(view,target)
    else:
     from render_dashboard import render_dashboard
     result=render_dashboard(view,target,pdf_href=names['pdf'] if 'pdf' in successes else None)
    if not target.is_file() or target.stat().st_size==0: raise RuntimeError('생성기가 완성된 파일을 반환하지 않았습니다.')
    successes[fmt]=result
   except Exception as exc:
    failures.append({'format':fmt,'error':str(exc),'previous_file_preserved':(out_dir/names[fmt]).exists()})
  files=[]
  for fmt,result in list(successes.items()):
   if fmt not in successes: continue
   try:
    os.replace(temp/names[fmt],out_dir/names[fmt])
    files.append(dict(result,path=str(out_dir/names[fmt])))
   except OSError as exc:
    failures.append({'format':fmt,'error':'출력 파일 저장 실패: '+str(exc),'previous_file_preserved':(out_dir/names[fmt]).exists()})
    if fmt=='pdf' and 'html' in successes:
     try:
      from render_dashboard import render_dashboard
      successes['html']=render_dashboard(view,temp/names['html'],pdf_href=None)
     except Exception as html_exc:
      successes.pop('html',None)
      failures.append({'format':'html','error':'PDF 링크 제거 후 HTML 재생성 실패: '+str(html_exc),'previous_file_preserved':(out_dir/names['html']).exists()})
  if export_json and files:
   try:
    backup=temp/'trip-backup.json';backup.write_text(json.dumps(view,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    os.replace(backup,out_dir/backup.name);files.append({'format':'json','path':str(out_dir/backup.name)})
   except OSError as exc:
    failures.append({'format':'json','error':'백업 파일 저장 실패: '+str(exc)})
 status='partial' if failures and files else 'failed' if failures else 'needs_review' if report['conflicts'] or report.get('media',{}).get('status')=='needs_review' else 'complete'
 return {'status':status,'generation':generation,'requested_outputs':requested,'files':files,'failures':failures,'validation':report},1 if failures else 0

def main():
 p=argparse.ArgumentParser(description=__doc__)
 p.add_argument('input');p.add_argument('--out-dir',required=True);p.add_argument('--baseline');p.add_argument('--allow-changes');p.add_argument('--export-json',action='store_true')
 a=p.parse_args()
 try: result,code=generate(a.input,a.out_dir,a.baseline,a.allow_changes,a.export_json)
 except (ValueError,OSError,TypeError) as exc: result,code={'status':'invalid_input','files':[],'error':str(exc)},2
 print(json.dumps(result,ensure_ascii=False,indent=2));return code
if __name__=='__main__':sys.exit(main())
