#!/usr/bin/env python3
"""Render canonical travel data into a compact, paginated PDF travelbook.

No network access or dependency installation occurs here. The coordinator passes
validated data after applying its private/shared projection.
"""
from __future__ import annotations

import base64
from datetime import datetime
from decimal import Decimal
from html import escape
from io import BytesIO
from pathlib import Path
import re
from urllib.parse import quote

try:
    from PIL import Image as PILImage
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfbase import pdfmetrics
    from reportlab.pdfbase.ttfonts import TTFont
    from reportlab.platypus import (
        BaseDocTemplate, CondPageBreak, Flowable, Frame, HRFlowable, KeepTogether,
        PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
    )
except ImportError as exc:
    raise RuntimeError(
        "PDF 생성에는 ReportLab과 Pillow가 필요합니다. 현재 Python 환경에서 "
        "두 패키지를 사용할 수 있는지 확인한 뒤 다시 실행하세요. 자동 설치하지 않았습니다. "
        "PDF requires ReportLab and Pillow in the selected Python environment."
    ) from exc

from trip_core import date_label, duration_nights, money, safe_url, traveler_checks
from media_pipeline import assess_media, property_photo

ROOT = Path(__file__).resolve().parents[1]
W, H = 160 * 72 / 25.4, 240 * 72 / 25.4
MARGIN, TOP, BOTTOM = 28, 48, 43
CW = W - 2 * MARGIN
PAPER = HexColor("#F7F4EC")
INK = HexColor("#203C33")
MUTED = HexColor("#697269")
RUST = HexColor("#A36645")
PALE = HexColor("#E7EBE0")
LINE = HexColor("#CCD2C6")
BLUE = HexColor("#416B77")


def _fonts():
    for name, filename in [
        ("TPBody", "Pretendard-Regular.ttf"),
        ("TPMedium", "Pretendard-Medium.ttf"),
        ("TPSerif", "NotoSerifKR-Regular.ttf"),
        ("TPJapanese", "NotoSansJP-Regular.ttf"),
    ]:
        path = ROOT / "assets" / "fonts" / filename
        if not path.is_file():
            raise RuntimeError(f"PDF font is missing: {path.name}. Restore assets/fonts from the skill ZIP.")
        if name not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont(name, str(path)))
    pdfmetrics.registerFontFamily("TPBody", normal="TPBody", bold="TPMedium", italic="TPBody", boldItalic="TPMedium")
    pdfmetrics.registerFontFamily("TPSerif", normal="TPSerif", bold="TPSerif", italic="TPSerif", boldItalic="TPSerif")
    pdfmetrics.registerFontFamily("TPJapanese", normal="TPJapanese", bold="TPJapanese", italic="TPJapanese", boldItalic="TPJapanese")


def escaped_text(value):
    """Preserve source names absent from the Korean body font using bundled glyphs."""
    primary = pdfmetrics.getFont('TPBody').face.charToGlyph
    fallbacks = [(name, pdfmetrics.getFont(name).face.charToGlyph) for name in ('TPJapanese', 'TPSerif')]
    parts = []
    for char in str(value):
        safe = escape(char)
        fallback = next((name for name, glyphs in fallbacks if ord(char) in glyphs), None) if ord(char) not in primary else None
        parts.append(f'<font name="{fallback}">{safe}</font>' if fallback else safe)
    return ''.join(parts)


class Photo(Flowable):
    """City covers crop; property photos retain the whole building or room."""
    def __init__(self, data_uri, width, height, fit='cover'):
        super().__init__()
        raw = base64.b64decode(data_uri.split(",", 1)[1], validate=True)
        if len(raw) > 15 * 1024 * 1024:
            raise ValueError("Photo exceeds the 15 MiB per-image limit")
        with PILImage.open(BytesIO(raw)) as im:
            if im.width * im.height > 60_000_000:
                raise ValueError("Photo is too large to render safely")
            im.load()
            # Re-encode only the bounded image needed for print. ReportLab never
            # attempts to read an image URL or an input-specified filesystem path.
            im = im.convert("RGB")
            im.thumbnail((1800, 1800))
            buf = BytesIO()
            im.save(buf, "JPEG", quality=88)
            self.reader = ImageReader(BytesIO(buf.getvalue()))
            self.iw, self.ih = im.size
        self.width, self.height = width, height
        self.fit = fit

    def draw(self):
        c = self.canv
        scale = (min if self.fit == 'contain' else max)(self.width / self.iw, self.height / self.ih)
        dw, dh = self.iw * scale, self.ih * scale
        c.saveState()
        if self.fit == 'contain':
            c.setFillColor(PALE)
            c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        path = c.beginPath()
        path.rect(0, 0, self.width, self.height)
        c.clipPath(path, stroke=0)
        c.drawImage(self.reader, (self.width - dw) / 2, (self.height - dh) / 2, dw, dh, mask="auto")
        c.restoreState()


class CoverMark(Flowable):
    """Typographic cover ornament, not an invented destination photograph."""
    def __init__(self, width, height=136):
        super().__init__()
        self.width, self.height = width, height

    def draw(self):
        c = self.canv
        c.setFillColor(INK)
        c.rect(0, 0, self.width, self.height, fill=1, stroke=0)
        c.setStrokeColor(HexColor("#698172"))
        c.setLineWidth(0.6)
        for y in (20, 35, 100, 115):
            c.line(20, y, self.width - 20, y)
        c.setFillColor(PALE)
        c.setFont("TPSerif", 18)
        c.drawString(22, 57, "TRAVEL NOTES")


class Heading(Paragraph):
    def __init__(self, text, style, key=None, outline=None, level=0, **kwargs):
        super().__init__(text, style, **kwargs)
        self.anchor_key, self.outline, self.level = key, outline, level

    def draw(self):
        if self.anchor_key:
            # A new day may begin halfway down a page. Its link must land on
            # that heading, not at the top of the preceding day's content.
            self.canv.bookmarkHorizontal(self.anchor_key, 0, self.height)
        super().draw()

    def split(self, availWidth, availHeight):
        parts = super().split(availWidth, availHeight)
        if parts:
            parts[0].anchor_key = self.anchor_key
            parts[0].outline = self.outline
            parts[0].level = self.level
        return parts


class TravelDoc(BaseDocTemplate):
    def __init__(self, path, trip, strings, **kwargs):
        super().__init__(str(path), pagesize=(W, H), leftMargin=MARGIN, rightMargin=MARGIN,
                         topMargin=TOP, bottomMargin=BOTTOM, allowSplitting=1, **kwargs)
        self.trip, self.strings = trip, strings
        self.sections = []
        self.page_count = 0
        frame = Frame(MARGIN, BOTTOM, CW, H - TOP - BOTTOM, leftPadding=0,
                      rightPadding=0, topPadding=0, bottomPadding=0, id="main")
        self.addPageTemplates([PageTemplate(id="travel", frames=frame, onPage=self.decorate)])

    def decorate(self, c, doc):
        self.page_count = doc.page
        c.saveState()
        c.setFillColor(PAPER)
        c.rect(0, 0, W, H, fill=1, stroke=0)
        c.setFillColor(MUTED)
        c.setFont("TPMedium", 7.6)
        c.drawString(MARGIN, H - 29, "TRAVEL NOTES")
        label = str(self.trip.get("country_label") or self.trip.get("title") or "")
        while label and pdfmetrics.stringWidth(label, "TPBody", 7.6) > CW - 108:
            label = label[:-1]
        c.setFont("TPBody", 7.6)
        c.drawRightString(W - MARGIN, H - 29, label)
        if doc.page > 1:
            c.setStrokeColor(LINE)
            c.setLineWidth(0.6)
            c.line(MARGIN, 34, W - MARGIN, 34)
            c.setFont("TPBody", 8)
            c.drawString(MARGIN, 20, self.strings["back"])
            c.linkRect("", "overview", (MARGIN, 14, MARGIN + 110, 30), thickness=0)
            c.drawRightString(W - MARGIN, 20, f"{doc.page:02d}")
        c.restoreState()

    def afterFlowable(self, flowable):
        if isinstance(flowable, Heading) and flowable.anchor_key:
            if flowable.outline:
                self.canv.addOutlineEntry(flowable.outline, flowable.anchor_key, flowable.level, closed=False)
                self.sections.append({"title": flowable.outline, "page": self.page, "anchor": flowable.anchor_key})


def render_travelbook(trip: dict, output_path: Path) -> dict:
    """Render a validated, audience-projected trip. Return output metadata."""
    _fonts()
    ko = trip.get("language", "ko") == "ko"
    def l(korean, english):
        return korean if ko else english
    unknown = l("확인 필요", "To confirm")
    labels = {"back": l("전체 일정으로 돌아가기", "Back to overview")}
    styles = {
        "body": ParagraphStyle("body", fontName="TPBody", fontSize=9.5, leading=13.2,
                               textColor=INK, spaceAfter=5, wordWrap="CJK", splitLongWords=True,
                               allowWidows=0, allowOrphans=0),
        "small": ParagraphStyle("small", fontName="TPBody", fontSize=8, leading=11.2,
                                textColor=MUTED, spaceAfter=4, wordWrap="CJK", splitLongWords=True),
        "title": ParagraphStyle("title", fontName="TPSerif", fontSize=18.5, leading=25,
                                textColor=INK, spaceAfter=10, keepWithNext=True, wordWrap="CJK"),
        "cover": ParagraphStyle("cover", fontName="TPSerif", fontSize=24, leading=32,
                                textColor=INK, spaceAfter=9, wordWrap="CJK"),
        "section": ParagraphStyle("section", fontName="TPMedium", fontSize=10.5, leading=15,
                                  textColor=INK, spaceBefore=10, spaceAfter=6, keepWithNext=True, wordWrap="CJK"),
        "section_split": ParagraphStyle("section_split", fontName="TPMedium", fontSize=10.5, leading=15,
                                        textColor=INK, spaceBefore=10, spaceAfter=6, wordWrap="CJK"),
        "source_heading": ParagraphStyle("source_heading", fontName="TPMedium", fontSize=10.5, leading=15,
                                         textColor=INK, spaceBefore=10, spaceAfter=6, keepWithNext=True, wordWrap="CJK"),
        "timeline_heading": ParagraphStyle("timeline_heading", fontName="TPMedium", fontSize=10.5, leading=15,
                                           textColor=INK, spaceBefore=10, spaceAfter=6, wordWrap="CJK"),
        "source_date": ParagraphStyle("source_date", fontName="TPBody", fontSize=9.5, leading=13.2,
                                      textColor=INK, spaceAfter=5, keepWithNext=True, wordWrap="CJK"),
        "kicker": ParagraphStyle("kicker", fontName="TPMedium", fontSize=8.2, leading=11.5,
                                 textColor=RUST, spaceBefore=5, spaceAfter=7, keepWithNext=True),
        "table": ParagraphStyle("table", fontName="TPBody", fontSize=9, leading=12.5,
                                textColor=INK, wordWrap="CJK", splitLongWords=True),
        "note": ParagraphStyle("note", fontName="TPBody", fontSize=9.5, leading=13.2,
                               textColor=INK, backColor=PALE, borderPadding=9, spaceBefore=13,
                               spaceAfter=14, wordWrap="CJK", splitLongWords=True),
    }
    sources = trip.get("sources") or []
    source_anchors = {s["id"]: f"source-{i}" for i, s in enumerate(sources)}
    media = [] if trip.get('photo_policy') == 'off' else trip.get("media") or []
    places = {p["id"]: p for p in trip.get("places") or []}
    story, diagnostics = [], []

    def rich(value):
        text = escaped_text(value if value is not None else unknown)
        # Links are created only from source IDs in the projected source list.
        def reference(match):
            sid = match.group(1)
            anchor = source_anchors.get(sid)
            if anchor:
                return f'<a href="#{anchor}" color="#416B77">[{escape(sid)}]</a>'
            return match.group(0)
        return re.sub(r"\[([\w.-]+)\]", reference, text).replace("\n", "<br/>")

    def p(value, style="body", markup=False):
        return Paragraph(str(value) if markup else rich(value), styles[style])

    def add(value, style="body", markup=False):
        story.append(p(value, style, markup))

    def heading(title, kicker=None, key=None):
        if kicker:
            add(kicker, "kicker")
        story.append(Heading(rich(title), styles["title"], key, str(title) if key else None))

    def section(title, body=None):
        # Short paragraphs remain with their heading. For a long paragraph,
        # reserve only a heading and two lines, then permit natural splitting.
        body_height = p(body).wrap(CW, H)[1] if body else 0
        if body_height > 140:
            paragraph = p(title, "section_split")
            _, height = paragraph.wrap(CW, H)
            story.append(CondPageBreak(min(height + 43, H - TOP - BOTTOM)))
            story.append(paragraph)
        else:
            add(title, "section")

    def field(title, value):
        add(f"<b>{rich(title)}</b>  {rich(value)}", markup=True)

    def refs(ids, body=""):
        return " ".join(f"[{sid}]" for sid in (ids or []) if sid in source_anchors and f"[{sid}]" not in str(body))

    def line():
        story.append(HRFlowable(width="100%", thickness=0.6, color=LINE, spaceBefore=5, spaceAfter=7))

    def link(label, url, style="small"):
        url = safe_url(url)
        if url:
            add(f'<a href="{escape(url, quote=True)}" color="#416B77">{rich(label)}</a>', style, markup=True)

    def date(value):
        return date_label(value, trip.get("language", "ko")) if value else unknown

    def instant(value):
        if not value:
            return unknown
        try:
            dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            offset = dt.strftime("%z")
            offset = offset[:3] + ":" + offset[3:] if offset else "?"
            return f"{dt:%Y-%m-%d %H:%M} (UTC{offset})"
        except ValueError:
            return unknown

    def status(value):
        pairs = {
            "confirmed": ("예약 확인", "Confirmed"), "proposed": ("제안", "Proposed"),
            "unknown": ("확인 필요", "To confirm"), "fictional": ("가상 예시", "Fictional example"),
            "optional": ("선택 일정", "Optional"), "planned": ("계획", "Planned"),
        }
        return l(*pairs[value]) if value in pairs else str(value or unknown)

    def table(rows, widths, repeat=1, append=True):
        t = Table(rows, colWidths=widths, repeatRows=repeat, hAlign="LEFT", splitByRow=1, splitInRow=1)
        commands = [("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("LEFTPADDING", (0, 0), (-1, -1), 6), ("RIGHTPADDING", (0, 0), (-1, -1), 6),
                    ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
                    ("LINEBELOW", (0, 0), (-1, -1), 0.5, LINE)]
        if repeat:
            commands.append(("BACKGROUND", (0, 0), (-1, 0), PALE))
        t.setStyle(TableStyle(commands))
        if append:
            story.append(t)
        return t

    def photo(item, height):
        if not item or not item.get("data_uri"):
            return False
        try:
            flow = Photo(item["data_uri"], CW, height, fit='contain' if item.get('role') == 'stay' else 'cover')
        except (ValueError, OSError, KeyError) as exc:
            diagnostics.append({"code": "PHOTO_UNAVAILABLE", "id": item.get("id"), "message": str(exc)})
            return False
        story.append(flow)
        story.append(Spacer(1, 5))
        caption = item.get("caption") or item.get("alt") or ""
        if item.get("depicts") == "landscape" and item.get("role") == "stay":
            caption += l(" · 지역 풍경, 숙소 사진 아님", " · Regional landscape, not a property photo")
        if caption:
            add(caption, "small")
        return True

    # Cover: the same layout works with a real photograph or without one.
    add("A PERSONAL TRAVELBOOK", "kicker")
    story.append(Heading(rich(trip["title"]), styles["cover"], "cover", trip["title"]))
    if trip.get("subtitle"):
        add(trip["subtitle"])
    story.append(Spacer(1, 10))
    hero = next((m for m in media if m.get("role") == "hero" and m.get('depicts') == 'landscape'), None)
    if not photo(hero, 220):
        story.append(CoverMark(CW))
    story.append(Spacer(1, 12))
    field(l("여행 기간", "Travel dates"), f'{trip["start_date"]} - {trip["end_date"]}')
    party = trip.get("party") or {}
    if party:
        members = []
        if party.get("adults") is not None:
            members.append(l(f'성인 {party["adults"]}명', f'{party["adults"]} adults'))
        if party.get("children"):
            members.append(l(f'어린이 {party["children"]}명', f'{party["children"]} children'))
        add(" · ".join(members))
    line()
    add(l("먼저 전체를 보고, 필요한 날을 자세히", "The whole journey first. Each day in detail."), "section")
    add(l("전체 일정과 예약 정보를 먼저 확인하세요. 날짜를 누르면 하루별 안내로 이동하고, 각 쪽 아래에서 전체 일정으로 돌아갈 수 있습니다.",
          "Start with the overview and reservations. Tap a date to open that day's guide; use the footer to return to the overview."))
    if trip.get("is_fictional_demo"):
        add(l("가상 여행 예시입니다. 실제 예약 또는 운행 확정을 의미하지 않습니다.",
              "Fictional travel example. It does not establish a real booking or confirmed service."), "small")
    if trip.get("notice"):
        add(trip["notice"], "small")
    generation = trip.get("generation") or {}
    edition = [f'{l("일정", "Revision")} r{trip["revision"]}',
               l("공유용", "Shared") if trip.get("audience") == "shared" else l("개인용", "Private")]
    if generation.get("generated_at"):
        edition.append(generation["generated_at"])
    add(" · ".join(edition), "small")

    # Overview grows naturally for a long trip and preserves date -> day links.
    story.append(PageBreak())
    heading(l("전체 여정, 한눈에", "Your journey at a glance"), "AT A GLANCE", "overview")
    add(l("날짜를 누르면 해당 날짜의 상세 안내로 이동합니다.", "Tap a date to open its detailed guide."), "small")
    rows = [[p(l("날짜", "Date"), "table"), p(l("일정 · 이동 · 숙박", "Agenda · transit · stay"), "table")]]
    for i, day in enumerate(trip.get("days") or []):
        summary = day.get("summary") or {}
        content = f'<b>{rich(day.get("title") or day["date"])}</b>'
        for key, name in [("agenda", l("일정", "Agenda")), ("transit", l("이동", "Transit")), ("stay", l("숙박", "Stay"))]:
            if summary.get(key):
                content += f'<br/>{rich(name)}: {rich(summary[key])}'
        rows.append([p(f'<a href="#day-{i}" color="#416B77">DAY {i+1:02d}<br/>{rich(date(day["date"]))}</a>', "table", True), p(content, "table", True)])
    if len(rows) > 1:
        table(rows, [82, CW - 82])
    else:
        add(l("날짜별 일정이 아직 입력되지 않았습니다.", "No daily itinerary has been supplied."))
    validation = trip.get("validation") or {}
    issues = traveler_checks(trip)
    update_notes = [issue for issue in validation.get('warnings', []) if issue.get('code') == 'baseline_absent' and trip.get('revision', 1) > 1]
    if issues:
        section(l("출발 전에 확인할 사항", "Confirm before departure"))
        for issue in issues:
            add(issue['title'] + ' · ' + issue['message'])
        add('<a href="#preparation" color="#416B77">' + rich(l("날짜·구간별 확인 내용은 뒤쪽 준비 섹션에서 확인하세요.", "See the preparation section for dates and routes to check.")) + '</a>', 'small', markup=True)
    else:
        add(l("예약 상태와 현지 시각은 아래 예약 요약에서 확인하세요.", "Check booking statuses and local times in the reservation summary."), "small")

    # A short overview and short reservation list can share a page. A section
    # starts on a fresh page only when there is too little room to be useful.
    story.append(CondPageBreak(190))
    story.append(Spacer(1, 14))
    heading(l("항공과 숙소, 예약 요약", "Flights, stays and reservations"), "ESSENTIALS", "reservations")
    add(l("시간은 각 출발·도착 지점의 현지 시각입니다. UTC 오프셋을 함께 표시합니다. 빈 정보는 추정하지 않습니다.",
          "Times are local to each departure or arrival point, with UTC offsets. Missing information is not estimated."), "small")
    bookings = trip.get("bookings") or []
    if not bookings:
        add(l("등록된 예약이 없습니다. 예약 자료가 제공되면 이곳에 정리합니다.", "No bookings supplied. Reservation documents are needed to complete this section."))
    for booking in bookings:
        line()
        section(f'{booking.get("name") or booking["id"]} · {status(booking.get("status"))}')
        place = places.get(booking.get("place_id"), {})
        if booking.get("type") == "stay":
            nights = duration_nights(booking)
            stay_dates = f'{date(booking.get("check_in"))} / {date(booking.get("check_out"))}'
            if nights is not None:
                stay_dates += l(f" · {nights}박", f" · {nights} nights")
            field(l("체크인 / 체크아웃", "Check-in / check-out"), stay_dates)
            field(l("체크인 / 체크아웃 시간", "Check-in / check-out time"), f'{booking.get("check_in_time") or unknown} / {booking.get("check_out_time") or unknown}')
            address = booking.get("address") or place.get("address")
            field(l("주소", "Address"), address)
            field(l("연락처", "Contact"), booking.get("phone"))
            if address:
                link(l("숙소 주소로 지도 열기", "Find the property address on a map"), "https://www.google.com/maps/search/?api=1&query=" + quote(address))
            else:
                add(l("주소 확인 전에는 숙소 위치를 확정하지 않습니다.", "The property's exact location remains unconfirmed until its address is provided."), "small")
        else:
            if booking.get("origin") or booking.get("destination"):
                field(l("이동 구간", "Route"), f'{booking.get("origin") or unknown} → {booking.get("destination") or unknown}')
            if booking.get("flight_number"):
                field(l("편명", "Flight number"), booking["flight_number"])
            field(l("시작 / 출발", "Start / departure"), instant(booking.get("start_at")))
            field(l("종료 / 도착", "End / arrival"), instant(booking.get("end_at")))
            if booking.get("time_note"):
                add(booking["time_note"], "small")
        if booking.get("conditions"):
            field(l("예약 조건", "Conditions"), booking["conditions"])
        if trip.get("audience") == "private":
            if booking.get("booking_reference"):
                field(l("예약 번호", "Booking reference"), booking["booking_reference"])
            if booking.get("passenger_names"):
                names = booking["passenger_names"]
                field(l("예약자 / 탑승객", "Guest / passengers"), ", ".join(names) if isinstance(names, list) else names)
            if booking.get("private_notes"):
                field(l("개인 메모", "Private note"), booking["private_notes"])
        booking_refs = refs(booking.get("source_ids"))
        if booking_refs:
            # A source-only paragraph can be stranded at the next page's top.
            # Attach citations to the final booking field instead; its normal
            # paragraph splitting/widow control still permits long conditions.
            previous = story[-1]
            if isinstance(previous, Paragraph):
                text = previous.text + f' <font size="8">{rich(booking_refs)}</font>'
                citation_style = ParagraphStyle("booking_citation", parent=previous.style,
                                                allowWidows=0, allowOrphans=0)
                story[-1] = Paragraph(text, citation_style)
            else:
                add(booking_refs, "small")

    # Hotel photos are explicitly linked to the booked property, not the region.
    pictured_stays = set()
    for booking in bookings:
        pid = booking.get('place_id')
        if booking.get('type') != 'stay' or not pid or pid in pictured_stays:
            continue
        item = next((m for m in media if property_photo(m, pid)), None)
        if item:
            story.append(CondPageBreak(175))
            section(booking.get('name') or places.get(pid, {}).get('name') or pid)
            photo(item, 125)
            pictured_stays.add(pid)

    # Day entries can span as many pages as the supplied content needs.
    pictured_places = set()
    for i, day in enumerate(trip.get("days") or []):
        # Keep enough room for a title and meaningful timeline content for the
        # next day; otherwise start fresh.
        # Day links and PDF bookmarks resolve correctly at either position.
        story.append(CondPageBreak(230))
        story.append(Spacer(1, 18))
        heading(day.get("title") or date(day["date"]), f'DAY {i+1:02d} / {date(day["date"])}', f"day-{i}")
        subtitle = " · ".join(str(day[k]) for k in ("region", "pace", "subtitle") if day.get(k))
        if subtitle:
            add(subtitle, "small")
        day_places = set(day.get('place_ids', [])) | {a.get('place_id') for a in day.get('activities', [])}
        for item in media:
            if item.get('role')=='place' and item.get('place_id') in day_places and item['id'] not in pictured_places:
                photo(item, 110)
                pictured_places.add(item['id'])
        for note in day.get("important_notes") or []:
            add(note, "note")
        guide = day.get("guide") or {}
        if guide.get("intro"):
            add(guide["intro"])
        summary = day.get("summary") or {}
        if summary.get("purpose"):
            field(l("오늘의 중심", "Today's focus"), summary["purpose"])
        activities = day.get("activities") or []
        if not activities:
            add(l("상세 일정은 아직 정해지지 않았습니다.", "The detailed itinerary is not set yet."))
        timeline = []
        for activity in activities:
            label = activity.get("time_label") or (instant(activity["start_at"]) if activity.get("start_at") else l("시간 미정", "Time to confirm"))
            title = f'<b>{rich(activity.get("title") or activity["id"])}</b>'
            if activity.get("status"):
                title += f' <font color="#697269">· {rich(status(activity["status"]))}</font>'
            detail = [p(title, markup=True)]
            if activity.get("description"):
                detail.append(p(activity["description"]))
            if activity.get("start_at") and activity.get("time_label"):
                detail.append(p(l("시작: ", "Start: ") + instant(activity["start_at"]), "small"))
            if activity.get("end_at"):
                detail.append(p(l("종료: ", "End: ") + instant(activity["end_at"]), "small"))
            if activity.get("note"):
                detail.append(p(activity["note"], "small"))
            practical = []
            if activity.get("walk_km") is not None:
                practical.append(l(f'보행 {activity["walk_km"]} km', f'Walking {activity["walk_km"]} km'))
            if activity.get("rest_minutes") is not None:
                practical.append(l(f'휴식 {activity["rest_minutes"]}분', f'Rest {activity["rest_minutes"]} min'))
            if practical:
                detail.append(p(" · ".join(practical), "small"))
            place = places.get(activity.get("place_id"), {})
            if place.get("name"):
                url = "https://www.google.com/maps/search/?api=1&query=" + quote(place.get("address") or place["name"])
                detail.append(p(f'<a href="{escape(url, quote=True)}" color="#416B77">{rich(l("지도: ", "Map: ") + place["name"])}</a>', "small", True))
            if activity.get("source_ids"):
                detail.append(p(refs(activity["source_ids"]), "small"))
            timeline.append([p(label, "small"), detail])
        if timeline:
            activity_tables = []
            frame_height = H - TOP - BOTTOM
            for index, row in enumerate(timeline):
                item = table([row], [70, CW - 70], repeat=0, append=False)
                _, height = item.wrap(CW, frame_height)
                # A normal activity moves as a whole: its title, times, map and
                # citations stay together. An oversized activity still splits.
                # The first row also reserves its timeline heading's height.
                reserve = 36 if index == 0 else 0
                item.splitInRow = 0 if height + reserve <= frame_height else 1
                if index == 0:
                    story.append(CondPageBreak(min(height + reserve, frame_height)))
                    add(l("하루 일정", "Daily itinerary"), "timeline_heading")
                activity_tables.append(item)
            story.extend(activity_tables)
        if guide.get("sections"):
            section(l("이동·보행·예약 안내", "Getting around and planning your day"))
            for item in guide["sections"]:
                body = item.get("body") or unknown
                section(item.get("heading") or l("현장 안내", "Practical guide"), body)
                additional = refs(item.get("source_ids"), body)
                add(body + (" " + additional if additional else ""))
        if guide.get("fallback"):
            section(guide.get("fallback_title") or l("상황에 맞춰 조정하기", "Adjusting the plan"))
            add(guide["fallback"])
        alternatives = day.get("alternatives") or {}
        if alternatives:
            section(l("날씨·컨디션·지연에 따른 대안", "Alternatives for weather, energy or delays"))
            add(l("아래는 선택 가능한 대안입니다. 기존 일정·예약은 자동으로 변경되지 않습니다.",
                  "These are optional alternatives. The original itinerary and reservations remain unchanged."), "small")
            for kind, name in [("weather", l("날씨", "Weather")), ("fatigue", l("피로", "Fatigue")), ("delay", l("지연", "Delay"))]:
                alternative = alternatives.get(kind)
                if not alternative:
                    continue
                section(f'{name} / {alternative.get("title") or l("대안", "Alternative")}', alternative.get("description"))
                if alternative.get("description"):
                    add(alternative["description"])
                if alternative.get("effect"):
                    field(l("달라지는 점", "Effect"), alternative["effect"])
                if alternative.get("source_ids"):
                    add(refs(alternative["source_ids"]), "small")

    story.append(CondPageBreak(175))
    story.append(Spacer(1, 14))
    heading(l("비용과 떠나기 전 준비", "Costs and getting ready"), "BEFORE YOU GO", "preparation")
    costs = trip.get("costs") or []
    totals = {}
    unknown_currencies = set()
    if costs:
        rows = [[p(l("항목", "Item"), "table"), p(l("총액", "Total"), "table"), p(l("결제액 / 상태", "Paid / status"), "table")]]
        for cost in costs:
            currency = cost.get("currency") or trip["base_currency"]
            amount, paid = cost.get("total_amount"), cost.get("paid_amount")
            if amount is None:
                unknown_currencies.add(currency)
            else:
                totals[currency] = totals.get(currency, Decimal(0)) + Decimal(str(amount))
            rows.append([p(cost.get("category") or cost["id"], "table"),
                         p(money(amount, currency) if amount is not None else unknown, "table"),
                         p((money(paid, currency) if paid is not None else unknown) + " / " + status(cost.get("status")), "table")])
        table(rows, [CW * .33, CW * .30, CW * .37])
        section(l("통화별 합계", "Totals by currency"))
        for currency in sorted(set(totals) | unknown_currencies):
            qualifier = l(" · 금액 미정 항목 제외", " · excludes unknown amounts") if currency in unknown_currencies else ""
            add(money(str(totals.get(currency, Decimal(0))), currency) + qualifier)
        add(l("서로 다른 통화는 합산하지 않았습니다. 예약 금액을 비용 항목과 중복 계산하지 않습니다.",
              "Different currencies are not combined. Bookings are not added again to the cost ledger."), "small")
    else:
        add(l("입력된 비용이 없습니다. 금액을 추정해 채우지 않았습니다.", "No costs have been supplied. No amounts have been estimated."))
    if issues:
        section(l("날짜·구간별 확인 사항", "Checks by date and route"))
        for issue in issues:
            section(issue['title'], issue['message'])
            add(issue['message'])
            by_date = {}
            for context in issue['contexts']:
                by_date.setdefault(context['date'], []).append(context['text'])
            for day, texts in by_date.items():
                add((date(day) + ' · ' if day else '') + ' / '.join(t for t in texts if t), 'small')
    if trip.get("checklist"):
        section(l("출발 전 체크리스트", "Departure checklist"))
        items = [p(f'{"[x]" if item.get("checked") else "[ ]"} {item.get("text") or item["id"]}')
                 for item in trip["checklist"]]
        story.extend(items[:-2])
        # Keep only the final pair together, not the entire checklist. Very long
        # entries remain splittable by Platypus when the pair exceeds a page.
        story.append(KeepTogether(items[-2:]))
        add(l("체크 표시는 입력 자료의 확인 상태입니다. 실시간 예약·운행 검증을 대신하지 않습니다.",
              "Checks reflect the supplied checklist state; they do not replace current booking or service verification."), "small")
    if update_notes:
        section(l("일정 수정 확인", "Revision check"))
        for issue in update_notes:
            add(issue["message"], "small")

    story.append(CondPageBreak(150))
    story.append(Spacer(1, 14))
    heading(l("출처와 사진 안내", "Sources and image credits"), "SOURCES & CREDITS", "sources")
    for missing in assess_media(trip)['missing']:
        add(missing['label'] + ' · ' + missing['reason'], 'small')
    if not sources:
        add(l("공개 가능한 출처가 입력되지 않았습니다.", "No sources are available for this output."))
    for i, source in enumerate(sources):
        story.append(Heading(rich(f'[{source["id"]}] {source.get("title") or source["id"]}'), styles["source_heading"], source_anchors[source["id"]]))
        if source.get("checked_at"):
            add(l("확인일: ", "Checked: ") + source["checked_at"], "source_date" if source.get("url") else "body")
        if source.get("url"):
            link(source["url"], source["url"])
        elif source.get("file_name"):
            detail = source["file_name"]
            if source.get("page") is not None:
                detail += l(f' · {source["page"]}쪽', f' · p. {source["page"]}')
            add(detail, "small")
        elif not source.get("checked_at"):
            add(l("사용자가 제공한 정보", "User-provided information"), "small")
    if media:
        section(l("사진 출처", "Image credits"))
        for item in media:
            add(item.get("caption") or item.get("alt") or item["id"])
            detail = " · ".join(str(item[k]) for k in ("creator", "license") if item.get(k))
            if detail:
                add(detail, "small")
            link(l("사진 원문", "Image source"), item.get("source_url"))
            link(l("이용 조건", "License"), item.get("license_url"))
    line()
    add(l("여행 정보는 확인 시점 이후 바뀔 수 있습니다. 날짜별 영업·운행·예약 조건은 실제 방문일 기준으로 다시 확인하세요.",
          "Travel information can change after its check date. Verify opening hours, transport and reservation rules for your actual visit."), "small")
    if generation.get("id"):
        add(l("생성 ID: ", "Generation ID: ") + generation["id"], "small")
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    doc = TravelDoc(output_path, trip, labels, title=trip["title"], author="Travel Planner",
                    subject=l("여행 일정과 예약·현장 안내", "Travel itinerary, reservations and practical guide"))
    doc.build(story)
    return {"path": str(output_path), "format": "pdf", "pages": doc.page_count,
            "sections": doc.sections, "warnings": diagnostics, "engine": "ReportLab"}
