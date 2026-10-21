"""Render one portable travel dashboard from validated canonical trip data.

Only the map tiles require a connection. Trip media and vendor libraries are
embedded; this renderer never downloads anything. Call through generate.py.
"""
from __future__ import annotations

import base64
import html
import json
import re
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from urllib.parse import quote, urlsplit

from trip_core import date_label, duration_nights, money, safe_url, traveler_checks
from media_pipeline import assess_media, property_photo

ROOT = Path(__file__).resolve().parents[1]
ICONS = {"mountain", "grid", "calendar", "bed", "wallet", "check", "list",
         "download", "arrow", "up-right", "pin", "people", "train", "cup",
         "plane", "leaf", "cloud", "info", "menu", "close", "copy"}
COLORS = ["#284c3c", "#719166", "#a0ae83", "#c4cbb0", "#c2a587", "#b36941"]


def esc(value):
    return html.escape(str(value if value is not None else ""), quote=True)


def icon(name):
    return f'<svg class="icon" aria-hidden="true"><use href="#i-{name if name in ICONS else "pin"}"/></svg>'


def _json(value):
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":"))
            .replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
            .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))


def _image(value):
    if not isinstance(value, str) or not re.fullmatch(r"data:image/(?:jpeg|png|webp);base64,[A-Za-z0-9+/=]+", value):
        return ""
    try:
        raw = base64.b64decode(value.split(",", 1)[1], validate=True)
    except (ValueError, TypeError):
        return ""
    return value if len(raw) <= 15 * 1024 * 1024 else ""


def _pdf_link(value):
    if not value or not isinstance(value, str):
        return ""
    remote = safe_url(value)
    if remote:
        return remote
    # The coordinator supplies a sibling artifact, not an arbitrary file URI.
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.query or parts.fragment:
        return ""
    return quote(value) if re.fullmatch(r"[A-Za-z0-9_. -]+\.pdf", value) and ".." not in value else ""


def render_dashboard(trip: dict, output_path: Path, pdf_href: str | None = None) -> dict:
    ko = trip.get("language", "ko") == "ko"
    def t(kr, en):
        return kr if ko else en

    unknown = t("확인 필요", "To confirm")
    places = {x["id"]: x for x in trip.get("places", [])}
    sources = {x["id"]: x for x in trip.get("sources", [])}
    bookings = trip.get("bookings", [])
    stays = [x for x in bookings if x.get("type") == "stay"]
    movements = [x for x in bookings if x.get("type") in ("flight", "transport")]
    activities_booked = [x for x in bookings if x.get("type") == "activity"]
    private = trip.get("audience") == "private"
    days = trip["days"]
    media_review = assess_media(trip)
    visible_media = [] if trip.get('photo_policy') == 'off' else trip.get('media', [])

    def dated(value):
        return esc(date_label(value, trip.get("language", "ko"))) if value else unknown

    def timed(value):
        if not value:
            return unknown
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
        zone = stamp.strftime("%z")
        zone = f"UTC{zone[:3]}:{zone[3:]}" if zone else unknown
        return f'{stamp:%Y.%m.%d %H:%M} ({zone})'

    def status(value):
        return {"confirmed": t("예약 확정", "Confirmed"), "proposed": t("제안", "Proposed"),
                "fictional": t("가상 예시", "Fictional example"), "unknown": unknown,
                "checked": t("확인됨", "Checked")}.get(value, esc(value) if value else unknown)

    def refs(value, source_ids=None):
        def link(match):
            sid = match.group(1)
            source = sources.get(sid)
            if not source:
                return match.group(0)
            return f'<a class="source-ref" href="#source-{quote(sid, safe="")}" title="{esc(source.get("title"))}">[{esc(sid)}]</a>'
        result = re.sub(r"\[([A-Za-z][A-Za-z0-9_-]*)\]", link, esc(value)).replace("\n", "<br>")
        for sid in source_ids or []:
            if sid in sources and f"[{sid}]" not in str(value or ""):
                result += " " + link(re.match(r"\[([^]]+)\]", f"[{sid}]"))
        return result

    def map_href(query):
        return "https://www.google.com/maps/search/?api=1&query=" + quote(str(query), safe="")

    def cost_summary(booking_id):
        totals = defaultdict(Decimal)
        for cost in trip.get("costs", []):
            if cost.get("booking_id") == booking_id and cost.get("total_amount") is not None:
                totals[cost["currency"]] += Decimal(cost["total_amount"])
        return " · ".join(esc(money(str(value), currency)) for currency, value in sorted(totals.items())) or unknown

    nav_items = [("journey", "grid", t("여행 한눈에", "The whole journey")),
                 ("reservations", "plane", t("예약 한눈에", "Reservations")),
                 ("itinerary", "calendar", t("날짜별 일정", "Daily itinerary")),
                 ("bookings", "bed", t("머무는 곳", "Places to stay")),
                 ("budget", "wallet", t("여행 예산", "Budget")),
                 ("packing", "list", t("떠나기 전 준비", "Before you go"))]
    nav = ''.join(f'<a class="nav-item" href="#{anchor}">{icon(glyph)}{label}</a>' for anchor, glyph, label in nav_items)
    mobile = ''.join(f'<a href="#{anchor}">{icon(glyph)}{label}</a>' for anchor, glyph, label in [
        ("journey", "grid", t("전체", "Overview")), ("itinerary", "calendar", t("하루", "Days")),
        ("reservations", "bed", t("예약", "Bookings")), ("budget", "wallet", t("예산", "Budget")),
        ("packing", "list", t("준비물", "Packing"))])
    nights = (date.fromisoformat(trip["end_date"]) - date.fromisoformat(trip["start_date"])).days
    length = t(f"{nights}박 {len(days)}일", f"{nights} nights, {len(days)} days")
    start_year, end_year = trip["start_date"][:4], trip["end_date"][:4]
    year_prefix = start_year + t("년 ", " · ")
    end_prefix = end_year + t("년 ", " · ") if end_year != start_year else ""
    date_range = f'{year_prefix}{dated(trip["start_date"])} — {end_prefix}{dated(trip["end_date"])}'
    hero_media = next((m for m in visible_media if m.get("role") == "hero" and m.get('depicts') == 'landscape' and _image(m.get("data_uri"))), None)
    hero_image = f'<img class="hero-photo" src="{_image(hero_media["data_uri"])}" alt="{esc(hero_media.get("alt"))}" fetchpriority="high">' if hero_media else ''
    hero_caption = esc(hero_media.get("caption", "")) if hero_media else ''
    party = trip.get("party", {})
    party_label = " · ".join(t(f"성인 {party['adults']}명", f"{party['adults']} adults") if k == "adults" else t(f"아동 {party['children']}명", f"{party['children']} children") for k in ("adults", "children") if party.get(k))
    party_html = f'<span>{icon("people")}{party_label}</span>' if party_label else ''
    routes = []
    for index, stay in enumerate(stays):
        place = places.get(stay.get("place_id"), {})
        n = duration_nights(stay)
        routes.append(f'<div class="route-stop"><span class="route-num">{index+1:02}</span><div><strong>{esc(place.get("name") or stay["name"])}</strong><small>{dated(stay.get("check_in"))} — {dated(stay.get("check_out"))}{" · " + t(str(n)+"박", str(n)+" nights") if n is not None else ""}</small></div></div>')
    journey = ''.join(f'<li><a href="#itinerary" data-jump-day="{index}"><span class="journey-date"><small>DAY {index+1:02}</small><strong>{dated(day["date"])}</strong></span><span class="journey-agenda">{esc(day.get("summary", {}).get("agenda") or day["title"])}</span><span class="journey-transit">{esc(day.get("summary", {}).get("transit") or unknown)}</span><span class="journey-stay">{esc(day.get("summary", {}).get("stay") or unknown)}</span>{icon("arrow")}</a></li>' for index, day in enumerate(days))
    move_html = []
    for booking in movements:
        route = f'{esc(booking.get("origin") or unknown)} <span>→</span> {esc(booking.get("destination") or unknown)}'
        time_note = f'<p class="pending">{refs(booking.get("time_note"))}</p>' if booking.get("time_note") else ""
        if private and booking.get("booking_reference"):
            time_note += f'<p>{t("예약번호", "Reference")}: {esc(booking["booking_reference"])}</p>'
        if booking.get("conditions"):
            time_note += f'<p>{refs(booking["conditions"])}</p>'
        move_html.append(f'<article class="air-leg"><span class="small-label">{esc(booking["name"])} · {status(booking.get("status"))}</span><strong>{route}</strong><div><p>{esc(booking.get("flight_number") or "")}</p><p>{t("출발", "Departure")}: {timed(booking.get("start_at"))}<br>{t("도착", "Arrival")}: {timed(booking.get("end_at"))}</p>{time_note}{refs("", booking.get("source_ids"))}</div></article>')
    reservation_stays = []
    stay_cards = []
    for index, stay in enumerate(stays):
        place = places.get(stay.get("place_id"), {})
        address = stay.get("address") or place.get("address")
        media = next((m for m in visible_media if property_photo(m, stay.get("place_id")) and _image(m.get("data_uri"))), None)
        n = duration_nights(stay)
        ns = t(f"{n}박", f"{n} nights") if n is not None else unknown
        reservation_stays.append(f'<a class="stay-summary-row" href="#stay-{index}"><span><strong>{esc(stay["name"])}</strong><small>{dated(stay.get("check_in"))} — {dated(stay.get("check_out"))} · {ns}</small></span><span class="pending">{status(stay.get("status"))}</span>{icon("arrow")}</a>')
        fields = [(t("주소", "Address"), address), (t("체크인 / 아웃", "Check-in / out"), f'{stay.get("check_in_time") or unknown} / {stay.get("check_out_time") or unknown}'), (t("연락처", "Contact"), stay.get("phone")), (t("예약 조건", "Conditions"), stay.get("conditions"))]
        if private:
            fields += [(t("예약번호", "Reference"), stay.get("booking_reference")), (t("개인 메모", "Private notes"), stay.get("private_notes"))]
        dl = ''.join(f'<div><dt>{label}</dt><dd>{refs(value or unknown)}</dd></div>' for label, value in fields if value or label not in (t("예약번호", "Reference"), t("개인 메모", "Private notes")))
        photo = f'<img src="{_image(media["data_uri"])}" alt="{esc(media.get("alt"))}" loading="lazy">' if media else ''
        map_query = address or place.get("name")
        map_link = f'<a class="text-link stay-map" href="{map_href(map_query)}" target="_blank" rel="noopener noreferrer">{t("숙소 지도" if address else "지역 지도", "Property map" if address else "Area map")}{icon("up-right")}</a>' if map_query else ''
        missing = next((x for x in media_review['missing'] if x['role']=='stay' and x['place_id']==stay.get('place_id')), None)
        caption = media.get("caption") if media else (missing['reason'] if missing else t("사진 없는 구성입니다.", "Photos are omitted as requested."))
        if media and media.get("depicts") != "property":
            caption = t("지역 풍경 · 숙소 자체의 사진이 아닙니다.", "Area landscape, not the property.")
        copy_button = f'<button class="button copy-address" data-address="{esc(address)}">{t("주소 복사", "Copy address")}</button>' if address else ""
        stay_cards.append(f'<article class="stay" id="stay-{index}"><div class="stay-photo {"no-photo" if not media else ""}">{photo}<span class="stay-location">{esc(place.get("name") or stay["name"])}</span><span class="stay-nights">{ns}</span></div><div class="stay-body"><div class="stay-title"><div><h3>{esc(stay["name"])}</h3><div class="dates">{dated(stay.get("check_in"))} — {dated(stay.get("check_out"))}</div></div><div class="stay-price">{cost_summary(stay["id"])}<small>{status(stay.get("status"))}</small></div></div><details class="stay-details"><summary>{t("체크인·주소·예약 조건", "Check-in, address & conditions")}</summary><dl>{dl}</dl>{copy_button}{refs("", stay.get("source_ids"))}</details>{map_link}<div class="stay-caption"><span>{esc(caption)}</span></div></div></article>')
    extra_booking = ''.join(f'<article class="extra-booking"><strong>{esc(b["name"])}</strong><span>{status(b.get("status"))} · {timed(b.get("start_at"))}</span><p>{refs(b.get("conditions") or b.get("time_note") or unknown, b.get("source_ids"))}</p></article>' for b in activities_booked)
    view_days = []
    for index, day in enumerate(days):
        guide = day.get("guide") or {}
        parts = []
        for activity in day.get("activities", []):
            clock = activity.get("time_label")
            if not clock and activity.get("start_at"):
                clock = datetime.fromisoformat(activity["start_at"].replace("Z", "+00:00")).strftime("%H:%M")
            meta = []
            if activity.get("walk_km") is not None:
                meta.append(t("보행 ", "Walk ") + esc(activity["walk_km"]) + " km")
            if activity.get("rest_minutes") is not None:
                meta.append(t("휴식 ", "Rest ") + esc(activity["rest_minutes"]) + t("분", " min"))
            if activity.get("note"):
                meta.append(refs(activity["note"]))
            parts.append(f'<article class="timeline-item {"rest" if activity.get("type") == "rest" else ""}"><div class="timeline-time">{esc(clock or unknown)}</div><div class="timeline-dot">{icon(activity.get("icon"))}</div><div class="timeline-text"><h4>{esc(activity["title"])}<span class="timeline-type">{status(activity.get("status"))}</span></h4><p>{refs(activity.get("description"), activity.get("source_ids"))}</p>{"<small>" + " · ".join(meta) + "</small>" if meta else ""}</div></article>')
        guide_html = f'<p class="guide-intro">{refs(guide.get("intro"))}</p>' if guide.get("intro") else ''
        guide_html += ''.join(f'<div class="guide-section"><span>{j+1:02}</span><div><h4>{esc(section.get("heading"))}</h4><p>{refs(section.get("body"), section.get("source_ids"))}</p></div></div>' for j, section in enumerate(guide.get("sections", [])))
        if guide.get("fallback"):
            guide_html += f'<div class="guide-fallback"><h4>{esc(guide.get("fallback_title") or t("현장에서 조정하기", "Adjust on the day"))}</h4><p>{refs(guide["fallback"])}</p></div>'
        place_ids = list(dict.fromkeys(day.get("place_ids", []) + [a["place_id"] for a in day.get("activities", []) if a.get("place_id")]))
        photos = [m for m in visible_media if m.get('role')=='place' and m.get('place_id') in place_ids and _image(m.get('data_uri'))]
        if photos:
            parts.append('<div class="day-photos">' + ''.join(f'<figure><img src="{_image(m["data_uri"])}" alt="{esc(m.get("alt"))}" loading="lazy"><figcaption>{esc(m.get("caption") or m.get("alt"))}</figcaption></figure>' for m in photos) + '</div>')
        day_places = [places[p] for p in place_ids if p in places]
        view_days.append({"heading": f'<div class="day-heading"><span class="day-number">{index+1:02}</span><div><h3>{esc(day["title"])}</h3><p>{dated(day["date"])} · {esc(day.get("subtitle") or day.get("region") or "")}</p></div></div>' + (f'<span class="day-tag">{esc(day["pace"])}</span>' if day.get("pace") else ''),
                          "purpose": day.get("summary", {}).get("purpose") or '', "timeline": ''.join(parts) or f'<p class="empty-state">{t("아직 세부 일정이 없습니다.", "No detailed activities yet.")}</p>',
                          "notes": '<br>'.join(refs(x) for x in day.get("important_notes", [])), "guide": guide_html,
                          "places": day_places, "region": day.get("region", ""),
                          "map_url": map_href(day.get("region") or (day_places[0]["name"] if day_places else "")) if day.get("region") or day_places else '',
                          "alternative_keys": [key for key in ("weather", "fatigue", "delay") if day.get("alternatives", {}).get(key)]})
    tabs = ''.join(f'<button class="day-tab {"selected" if i == 0 else ""}" id="day-tab-{i}" role="tab" aria-selected="{str(i == 0).lower()}" aria-controls="day-panel" tabindex="{0 if i == 0 else -1}" data-day="{i}"><span class="day-top"><span>DAY {i+1:02}</span><span>{esc(d["date"][5:].replace("-", "."))}</span></span><strong>{esc(d["title"])}</strong></button>' for i, d in enumerate(days))
    # Arithmetic remains decimal; chart floats are presentation-only.
    amounts = defaultdict(lambda: defaultdict(Decimal))
    missing_costs = 0
    for cost in trip.get("costs", []):
        if cost.get("total_amount") is None:
            missing_costs += 1
        else:
            amounts[cost["currency"]][cost.get("category") or t("기타", "Other")] += Decimal(cost["total_amount"])
    budgets, charts = [], []
    for ci, (currency, categories) in enumerate(sorted(amounts.items())):
        total = sum(categories.values(), Decimal(0))
        entries = list(categories.items())
        rows = ''.join(f'<div class="budget-row"><i style="background:{COLORS[i % len(COLORS)]}"></i><span>{esc(category)}</span><strong>{esc(money(str(amount), currency))}</strong></div>' for i, (category, amount) in enumerate(entries))
        paid = sum((Decimal(c["paid_amount"]) for c in trip.get("costs", []) if c.get("currency") == currency and c.get("paid_amount") is not None), Decimal(0))
        paid_count = sum(1 for c in trip.get("costs", []) if c.get("currency") == currency and c.get("paid_amount") is not None)
        paid_text = t("기재된 결제액", "Recorded payments") + ": " + esc(money(str(paid), currency)) if paid_count else t("결제 여부 미확인", "Payment status unknown")
        budgets.append(f'<div class="budget-card"><div class="budget-head">{t("통화별 기재 금액", "Recorded amount by currency")}<span>{esc(currency)}</span></div><div class="budget-total">{esc(money(str(total), currency))}</div><div class="budget-note">{paid_text}</div><div class="budget-breakdown"><div class="chart-shell"><canvas id="budget-chart-{ci}" role="img" aria-label="{esc("; ".join(category + ": " + money(str(amount), currency) for category, amount in entries))}"></canvas><div class="chart-center"><span>{esc(currency)}</span><small>TRIP BUDGET</small></div></div><div class="budget-rows">{rows}</div></div></div>')
        charts.append({"id": f"budget-chart-{ci}", "labels": [x[0] for x in entries], "values": [float(x[1]) for x in entries], "formatted": [money(str(x[1]), currency) for x in entries]})
    if not budgets:
        budgets = [f'<div class="budget-card empty-state">{t("금액이 제공되지 않았습니다. 미확인 금액은 0원으로 계산하지 않습니다.", "No amounts supplied. Unknown costs are not counted as zero.")}</div>']
    budget_note = t("서로 다른 통화는 합산하지 않습니다. 금액 미확인 항목", "Currencies are kept separate. Items with unknown amounts") + f": {missing_costs}"
    checklist = ''.join(f'<label class="check-row"><input type="checkbox" data-check-id="{esc(x["id"])}" {"checked" if x.get("checked") else ""}><span>{esc(x["text"])}</span></label>' for x in trip.get("checklist", [])) or f'<p class="empty-state">{t("준비물 목록이 없습니다.", "No checklist supplied.")}</p>'
    validation = trip.get("validation", {})
    issues = traveler_checks(trip)
    warnings = ''
    if issues:
        items = []
        for item in issues:
            dates = defaultdict(list)
            for context in item['contexts']:
                dates[context['date']].append(context['text'])
            contexts = ''.join(f'<div class="check-context">{dated(day) + " · " if day else ""}{esc(" / ".join(text for text in texts if text))}</div>' for day, texts in dates.items())
            items.append(f'<li><strong>{esc(item["title"])}</strong><p>{esc(item["message"])}</p>{contexts}</li>')
        count = t(f'{len(issues)}개 항목', f'{len(issues)} items')
        warnings = f'<details class="validation-notice" {"open" if validation.get("conflicts") else ""}><summary>{t("출발 전 확인할 사항", "Before departure: items to check")} · {count}</summary><ul>{"".join(items)}</ul></details>'
    source_rows = []
    for sid, source in sources.items():
        url = safe_url(source.get("url"))
        title = f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{esc(source.get("title"))}</a>' if url else esc(source.get("title"))
        evidence = []
        if source.get("checked_at"):
            evidence.append(t("확인일 ", "Checked ") + esc(source["checked_at"]))
        if private and source.get("file_name"):
            evidence.append(esc(source["file_name"]) + (f' · p. {esc(source["page"])}' if source.get("page") else ''))
        source_rows.append(f'<li id="source-{quote(sid, safe="")}"><strong>[{esc(sid)}]</strong> {title}{" · " + " · ".join(evidence) if evidence else ""}</li>')
    media_rows = []
    if media_review['missing']:
        media_rows.append('<li>' + esc(t('사진 확보 미완료', 'Photo collection incomplete')) + ': ' + '; '.join(esc(x['label'] + ' — ' + x['reason']) for x in media_review['missing']) + '</li>')
    for media in visible_media:
        url, license_url = safe_url(media.get("source_url")), safe_url(media.get("license_url"))
        source_link = f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">{t("원본", "Source")}</a>' if url else t("출처 미기재", "Source unspecified")
        license_link = f'<a href="{esc(license_url)}" target="_blank" rel="noopener noreferrer">{esc(media.get("license") or t("라이선스", "License"))}</a>' if license_url else esc(media.get("license") or t("이용 조건 미기재", "Terms unspecified"))
        media_rows.append(f'<li>{esc(media.get("alt") or media.get("caption") or media.get("id"))} · {esc(media.get("creator") or t("제작자 미기재", "Creator unspecified"))} · {source_link} · {license_link}</li>')
    demo_notice = t("가상 여행 · 디자인 예시", "Fictional trip · design example") if trip.get("is_fictional_demo") else t("개인 여행", "Private trip") if private else t("공유용 여행 안내", "Shared travel guide")
    export = f'<button class="button export-button">{icon("download")}{t("수정용 여행 데이터 저장", "Save editable trip data")}</button>' if private else ''
    pdf = _pdf_link(pdf_href) if {"html", "pdf"}.issubset(trip.get("requested_outputs", [])) else ''
    pdf_link = f'<a class="button primary" href="{esc(pdf)}" download>{icon("download")}{t("PDF 여행북 받기", "Download travelbook PDF")}</a>' if pdf else ''
    labels = {"unknown": unknown, "copied": t("복사했습니다.", "Copied."), "manualCopy": t("선택된 내용을 직접 복사해 주세요.", "Copy the selected text manually."),
              "exported": t("다운로드를 시작했습니다. 저장된 파일을 확인해 주세요.", "Download started. Check your saved file."),
              "storageWarning": t("브라우저 저장을 사용할 수 없습니다. 페이지를 닫으면 변경한 체크 상태가 사라집니다.", "Browser storage is unavailable. Check changes will be lost when this page closes."),
              "mapUnavailable": t("지도 배경을 불러오지 못했습니다. 장소 링크를 이용해 주세요.", "Map tiles are unavailable. Use the place links below."),
              "coordinatesMissing": t("확인된 좌표가 없습니다. 장소 링크를 이용해 주세요.", "No verified coordinates supplied. Use the place links below."),
              "coordinatesPartial": t("일부 장소의 좌표가 없어 지도에는 확인된 위치만 표시합니다.", "Some places have no coordinates; the map shows verified positions only."),
              "weather": t("날씨", "Weather"), "fatigue": t("피로", "Fatigue"), "delay": t("지연", "Delay"),
              "alternativeNotice": t("미리 작성한 대안입니다. 실제 예보가 아니며 일정·예약·결제는 변경되지 않습니다.", "A prepared alternative, not a live forecast. It does not change the itinerary, bookings or payments."),
              "request": t("첨부한 여행 데이터의 {date} 일정을 검토해줘. 상황: {condition}. 검토할 대안: {title}. {description} 기존 고정 예약을 유지하고, 운영시간·이동·보행·비용을 확인해 변경안을 먼저 보여줘.", "Review {date} in the attached trip data. Situation: {condition}. Alternative: {title}. {description} Preserve fixed bookings; check hours, travel, walking and costs, then show the proposed changes first."),
              "appCopy": t("사용 중인 AI에 붙여넣어 주세요.", "Paste it into your AI assistant.")}
    labels.update({"tripUpcoming": t("여행 전", "Upcoming trip"), "tripActive": t("여행 중", "During your trip"),
                   "tripPast": t("지난 여행", "Past trip"), "localToday": t("현지 날짜", "Local date"),
                   "timezoneUnknown": t("시간대 미확인 · 날짜를 선택해 주세요.", "Timezone unconfirmed · choose a day."),
                   "darkMode": t("어두운 화면으로 전환", "Switch to dark theme"),
                   "lightMode": t("밝은 화면으로 전환", "Switch to light theme")})
    template = (ROOT / "assets/dashboard.html").read_text(encoding="utf-8")
    replace = {"LANG": trip.get("language", "ko"), "TITLE": esc(trip["title"]), "SUBTITLE": esc(trip.get("subtitle", "")), "NAV": nav, "MOBILE_NAV": mobile,
               "DATE_RANGE": date_range, "LENGTH": length, "COUNTRY": esc(trip.get("country_label") or "TRAVEL NOTES"), "NOTICE": refs(trip.get("notice") or demo_notice), "DEMO": demo_notice,
               "HERO_IMAGE": hero_image, "HERO_CAPTION": hero_caption, "PARTY": party_html, "ROUTES": ''.join(routes), "JOURNEY": journey,
               "MOVEMENTS": ''.join(move_html) or f'<p class="empty-state">{t("항공·교통 예약 정보가 없습니다.", "No flight or transport bookings supplied.")}</p>',
               "STAY_SUMMARY": ''.join(reservation_stays) or f'<p class="empty-state">{t("숙소 예약 정보가 없습니다.", "No stay bookings supplied.")}</p>', "EXTRA_BOOKINGS": extra_booking,
               "STAY_CARDS": ''.join(stay_cards) or f'<p class="empty-state">{t("숙소 정보는 자료를 받은 뒤 추가합니다.", "Stay information can be added when supplied.")}</p>',
               "DAY_TABS": tabs, "FIRST_HEADING": view_days[0]["heading"], "FIRST_PURPOSE": esc(view_days[0]["purpose"]), "FIRST_TIMELINE": view_days[0]["timeline"],
               "BUDGETS": ''.join(budgets), "BUDGET_NOTE": budget_note, "CHECKLIST": checklist, "WARNINGS": warnings,
               "SOURCES": '<ul>' + ''.join(source_rows) + '</ul>' if source_rows else f'<p>{t("근거 자료가 아직 등록되지 않았습니다.", "No evidence sources supplied yet.")}</p>',
               "MEDIA_CREDITS": '<ul>' + ''.join(media_rows) + '</ul>' if media_rows else '',
               "EXPORT": export, "PDF_LINK": pdf_link, "TRIP_DATA": _json(trip), "VIEW_DATA": _json({"days": view_days, "charts": charts, "labels": labels, "private": private, "colors": COLORS}),
               "EDIT_NOTE": t("저장한 여행 데이터를 Claude나 Codex에 전달하면 다음 수정에 사용할 수 있습니다.", "Give the saved trip data to Claude or Codex to continue editing.") if private else t("공유용 안내에는 예약번호와 원본 자료 등 개인 데이터가 포함되지 않습니다.", "This shared guide excludes booking references and private source records."),
               "CHECK_NOTE": t("체크는 이 브라우저에 저장됩니다. 실제 예약 확정과는 별개입니다.", "Checks are saved in this browser; they do not confirm bookings."),
               "TIMING_NOTE": t("시각은 각 일정의 현지 시간입니다. 시간 미기재·제안 항목은 확정 일정이 아닙니다.", "Times are local to each activity. Missing times and proposals are not confirmed bookings."),
               "NOJS": t("JavaScript가 꺼져 있어 날짜 전환·지도·체크 저장이 작동하지 않습니다. 전체 요약과 첫날 일정은 읽을 수 있습니다.", "JavaScript is disabled: day switching, map and saved checks are unavailable. The overview and first day remain readable.")}
    ui_labels = {"SKIP": ("일정으로 바로 가기", "Skip to itinerary"), "MENU_OPEN": ("여행 메뉴 열기", "Open travel menu"), "MENU_CLOSE": ("메뉴 닫기", "Close menu"),
                 "PREPARATION": ("여행 준비", "Preparation"), "MY_TRIP": ("나의 여행", "My trip"), "RESERVATIONS": ("예약 한눈에", "Reservations"), "WHOLE": ("전체 여정", "Whole journey"),
                 "JOURNEY_TITLE": ("여행을, 한눈에.", "Your journey, at a glance."), "JOURNEY_HELP": ("날짜를 누르면 상세 일정으로 이동합니다.", "Choose a date to explore the day."),
                 "DATE": ("날짜", "Date"), "AGENDA": ("오늘의 중심", "Focus"), "TRANSIT": ("이동", "Travel"), "STAY": ("머무는 곳", "Stay"),
                 "RESERVATIONS_TITLE": ("먼저 챙길, 여행의 기본.", "The essentials, within reach."), "FLIGHTS": ("항공·교통", "Flights & transport"), "STAY_DETAIL": ("숙소 상세 보기", "View stays"),
                 "ITINERARY_TITLE": ("하루씩, 오래 기억할 순간.", "A day at a time."), "DAY_SELECT": ("여행 날짜 선택", "Choose a travel day"), "GUIDE": ("이동·보행·예약 안내", "Travel, walking & reservations"),
                 "GUIDE_SUB": ("여행북의 현장 노트", "Notes for the journey"), "TODAY_PLACES": ("오늘의 장소", "Today's places"), "MAP_NOTE": ("점선은 장소 연결선이며 실제 이동 경로가 아닙니다.", "Dotted lines connect places, not actual routes."),
                 "OPEN_MAP": ("지도 앱에서 보기", "Open in maps"), "ALTERNATIVE": ("날씨·컨디션에 맞는 대안", "Make room for a change"), "ALTERNATIVE_SUB": ("현재 예약을 유지하며 살펴볼 수 있는 대안입니다.", "Explore a prepared alternative while keeping existing bookings."),
                 "ALTERNATIVE_OPEN": ("상황별 대안 보기", "Explore alternatives"), "STAYS_TITLE": ("여행의 끝에는, 편안한 머무름.", "Somewhere to settle in."), "BUDGET_TITLE": ("예산도, 마음 편하게.", "Keep the details in balance."),
                 "PACK_TITLE": ("설렘은 챙기고, 걱정은 덜고.", "A little preparation."), "CHECK_INTRO": ("하나씩 준비하고 있어요.", "One thing at a time."), "STORED": ("이 브라우저에 저장된 준비 상태가 있습니다.", "This browser has saved checklist changes."),
                 "RESTORE": ("저장 상태 이어보기", "Restore saved checks"), "KEEP_FILE": ("파일 상태 사용", "Use file checks"), "CREDITS": ("여행 안내·사진 출처", "Travel evidence & image credits"), "SOURCE_TITLE": ("정보의 근거", "Evidence sources"),
                 "SOURCE_NOTE": ("확인일 이후 운영시간·예약 조건은 달라질 수 있습니다. 방문일에 맞춰 확인하세요.", "Hours and booking conditions can change after the check date. Verify them for your visit."), "MEDIA_TITLE": ("사진 출처", "Image credits"),
                 "QUICK_NAV": ("빠른 이동", "Quick navigation"), "MODAL_TITLE": ("계획이 달라져도, 우리답게.", "Leave room for the unexpected."), "MODAL_CLOSE": ("대안 닫기", "Close alternatives"), "ORIGINAL": ("현재 일정", "Current plan"),
                 "PROPOSED": ("검토할 대안", "Alternative to consider"), "AI_REQUEST": ("AI에 전달할 일정 수정 요청", "Revision request for your AI assistant"), "COPY_REQUEST": ("수정 요청 복사", "Copy revision request"),
                 "THEME_LABEL": ("어두운 화면으로 전환", "Switch to dark theme"), "DATE_CHOICE": ("날짜를 선택해 주세요.", "Choose a day."), "TODAY_ACTION": ("오늘 일정", "Today's plan")}
    replace.update({key: t(*value) for key, value in ui_labels.items()})
    for tag, name in [("LEAFLET_CSS", "leaflet.css"), ("LEAFLET_JS", "leaflet.js"), ("CHART_JS", "chart.js")]:
        text = (ROOT / "assets/vendor" / name).read_text(encoding="utf-8")
        replace[tag] = '\n'.join(line for line in text.splitlines() if not line.strip().startswith("//# sourceMappingURL="))
    replace["LICENSES"] = '\n\n'.join((ROOT / "assets/vendor" / name).read_text(encoding="utf-8") for name in ("CHART_LICENSE.txt", "LEAFLET_LICENSE.txt")).replace("--", "—")
    rendered = re.sub(r"__([A-Z][A-Z_]*?)__", lambda match: replace[match.group(1)], template)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")
    return {"path": str(output_path), "format": "html"}
