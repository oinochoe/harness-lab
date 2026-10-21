# Output acceptance

## Shared content

Use the same `trip.json` and generation ID for both selected outputs. Overall dates, daily titles, hotel nights, fixed times, cost totals and unknown states must agree. Separate currencies unless an explicit, sourced exchange rate permits an estimated conversion. A cost's paid amount is part of its total, never an extra expense. Unknown cost is not zero. Preserve explicit timezone offsets and local dates.

## HTML

Keep the existing editorial hierarchy: real/typographic cover, trip facts, whole itinerary, reservation summary, daily timeline/map/guide, accommodation, costs/checklist, sources. Responsive sidebar and mobile navigation should take users to the same content. Test at 1280px and 390px; use 320px for long text or cramped dialogs. No horizontal document overflow, clipped long addresses, or unreadable disabled controls. Charts explain currency groups; avoid a cross-currency pie.

Check every overview-day link and that the matching day/guide/map updates. Important cautions stay outside collapsed details. Test three alternatives and their copy request; the base schedule remains unchanged. Test checklist toggling, reload, unavailable storage, export and the stated revision. A saved browser checklist that conflicts with the file must be presented for user choice. Private and shared storage keys are separate. With a valid trip timezone, use that timezone to select today during the trip and label upcoming/past trips. Without a timezone, retain manual day selection. Test both light and dark themes, including chart captions and controls; theme persistence must tolerate unavailable browser storage.

HTML includes CSS, JS libraries and photographs; it uses system fonts, while the PDF embeds bundled fonts. It needs no CDN for its core content. Interactive map tiles and external source/map links need internet. Missing coordinates show named place links or a clear fallback; a regional map is labeled as a region, never a hotel pin. Only show the PDF button if the same run produced the selected PDF successfully. Files need to be together for that relative link to resolve; hosting is a separate step.

## PDF

160×240mm portrait, cream background, dark forest ink, muted copper details. Body 9.5pt/13.2pt with bundled Pretendard; serif section headings about18.5pt and cover about24pt. Do not inflate fonts or force one day per page if this wastes half a page. Do not shrink text to cram an arbitrary fixed page count. The layout engine should split genuinely long content and keep headings with their first paragraph.

Front: cover, overview table with day links, flights/stays/confirmed booking details. Then daily timeline and practical guide, costs/checklist, sources and image credits. Use PDF bookmarks and overview/day links. Keep text selectable/searchable, embed Korean fonts, retain hyperlinks. No screenshot-only book.

Render every page to images and inspect small type, text spill, empty-looking pages, photo crops and table breaks. Extract text to check dates, costs, missing glyphs and total content; extraction alone does not verify layout. Inspect PDF annotations/bookmarks. Files viewed in a desktop renderer or emulated mobile viewport are not proof of physical phone/KakaoTalk/printed performance. Record those as untested unless actually exercised.

HTML must not display internal generation IDs, template versions, or generation timestamps in its footer. Preserve generation metadata inside the editable trip data for consistency checks.

Photo acceptance: city/region photograph on the HTML main screen and PDF cover; verified photographs of the exact hotels in accommodation sections; optional place photographs beside relevant days. Check displayed pixels, not just JSON media entries or credits. Missing required photos must be disclosed and retained as needs_review. Hotel images must not be substituted into the city cover.

Property photos preserve the full frame so portrait buildings and room details are not cut off. The city cover can crop; inspect its landmark at the target screen size. PDF credits use a bundled Noto Sans JP fallback for characters absent from Pretendard; still inspect names and source text in each new output.
