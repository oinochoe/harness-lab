# Travel Planner canonical data — 1.0

Use this schema for the working trip JSON. Keep absent factual values null rather than guessing. English or Korean prose is supported.

## Canonical JSON

Required: `schema_version: "1.0"`, `trip_id: string`, `revision: integer >=1`, `title: string`, `start_date/end_date: YYYY-MM-DD`, `language: "ko" or "en"`, `base_currency: currency code`, `audience: "private" or "shared"`, `requested_outputs: ["html"], ["pdf"], or ["html","pdf"]`, `days: []`.

Optional: `subtitle`, `country_label`, `timezone` (IANA or null), `is_fictional_demo`, `party: {adults,children}`, `notice`, `preferences` (object or null, not an array; omit when unused), `constraints: [{kind:"max_daily_walk_km"|"min_rest_minutes",value:"decimal",unit,source_ids:[]}]`.

- `places: [{id,name,address:null|string,lat:null|number,lng:null|number,timezone:null|string,source_ids:[]}]`. Never fabricate coordinates. Maps can show named-place links without a tile map.
- `bookings: [{id,type:"stay"|"flight"|"activity"|"transport",name,status:"confirmed"|"proposed"|"unknown"|"fictional",place_id:null|string,source_ids:[],locked_fields:[]}]`.
  - stay: `check_in/check_out` dates; `check_in_time/check_out_time`, `address`, `phone`, `conditions`, `nights` optional. Unknown values null. Region lives in linked place.
  - flight/transport/activity: `start_at/end_at` ISO date-time with explicit offset or null; `origin`, `destination`, `flight_number`, `time_note` optional.
  - Private booking fields: `booking_reference`, `passenger_names`, `private_notes`, `source_path`; never share automatically.
- `days: [{date,title,subtitle,pace,region,place_ids:[],summary:{agenda,transit,stay,purpose},important_notes:[],activities:[],guide:{intro,sections:[{heading,body,source_ids:[]}],fallback_title,fallback},alternatives:{weather|fatigue|delay:{title,description,effect,source_ids:[]}}}]`.
  - activities: `{id,title,description,time_label,start_at,end_at,place_id,booking_id,status,type,icon,note,walk_km,rest_minutes,source_ids:[]}`. Nullable ISO times; never compare text labels. Type includes travel/stay/activity/food/walk/rest. `icon` is a fixed local allowlist.
  - A transfer already represented as a `type:"travel"` activity should also carry `from_place_id` and `to_place_id` together. The validator compares the preceding activity's destination to the next activity's origin, so it does not demand a second transfer for time already allocated in the timeline. Do not infer endpoints or verified duration from prose or `type:"travel"` alone. Keep estimated transfers `proposed`; they remain subject to route/time confirmation. A sourced flight/transport booking with matching start/end times supplies the published schedule, not proof of an actual reservation.
  - Important notes and prose may contain `[S01]` source references; render as safe links when source exists. Alternative is prewritten; choosing it never changes canonical itinerary.
- `legs: [{id,from_activity_id,to_activity_id,min_minutes,max_minutes,status,source_ids:[]}]`. Unknown minutes null. Range upper bound not established => not confirmed feasible.
- `availability: [{id,place_id,date,closed:boolean,start_at,end_at,status,source_ids:[]}]` per-date checked operating interval. Source absence/unknown means not confirmed open. More than one interval is allowed.
- `overnight_exceptions: [{date,reason,booking_id:null|string}]`.
- `costs: [{id,category,total_amount:null|decimal-string,paid_amount:null|decimal-string,currency,booking_id:null|string,status,unit_amount:null|decimal-string,quantity:null|decimal-string,source_ids:[]}]`. Only costs feed totals; do not add bookings again. No binary-float money. One cost per linked booking unless differentiated `component` strings.
- `declared_totals: [{currency,total_amount,source_ids:[]}]`; `exchange_rates: [{from_currency,to_currency,rate,checked_at,source_ids:[]}]` optional.
- `checklist: [{id,text,checked:boolean}]`.
- `sources: [{id,title,type:"web"|"document"|"user",url:null|https-url,checked_at:null|date,public:boolean,file_name,page,private_path}]`. Shared output retains only explicitly public web sources, without private file metadata.
- `media: [{id,role:"hero"|"stay"|"place",place_id:null|string,data_uri:"data:image/jpeg;base64,..."|png|webp,alt,caption,creator,source_url,license,license_url,depicts:"landscape"|"property",checked_at,verified_property:boolean,identity_source_url,identity_note}]`. Hero is always city/region landscape. Stay photos require an exact place_id, depicts:property, verified_property:true and identity source/note; region photos do not fill a hotel slot. The photo helper handles researched assets; no renderer network fetches. Per-item 15 MiB decoded max; safe raster only.
- `photo_policy: "auto"` (default) or `"off"` only for an explicit user no-photo request; `photo_note` records that request.
- `photo_attempts: [{role:"hero"|"stay"|"place",place_id:null|string,reason,checked_at}]` records concrete acquisition failures. No local paths or internal logs in reason.
- `changes: [{target_id,field,reason}]` is descriptive only, not edit permission.

Optional computed output fields injected by generation coordinator: `generation:{id,generated_at,template_version}`, `validation:{errors:[],conflicts:[],warnings:[],totals:{CURRENCY:decimal-string},conversion:null|object}`. Issue objects `{code,path,message}`. No internal report JSON is automatically delivered.
Movement and opening-hours issues may include `date` and `activity_ids` to identify affected dates and places. HTML and PDF group actionable checks using these references; raw codes, separate-currency notices and baseline bookkeeping are not departure tasks. Raw diagnostics remain available internally. Do not suppress unresolved movement/opening checks just because an example is fictional.

## Script interfaces

The coordinator uses `scripts/trip_core.py`, `validate_trip.py`, and `generate.py`.

`trip_core.py` will export:
- `load_trip(path) -> dict`; `validate_trip(trip, baseline=None, allow_changes=None) -> report`; blocking `errors` => no rendering, `conflicts/warnings` shown in generated output.
- `display_trip(trip, report, generation) -> dict`: deep copy for private, strict public projection for shared. Renderer input is this result; do not mutate it.
- `safe_url(value) -> str` HTTPS/HTTP only; `money(value,currency) -> str`; `date_label(date,language="ko") -> str`; `duration_nights(booking) -> int|None`.

HTML renderer uses `scripts/render_dashboard.py`, `assets/dashboard.html` (+CSS/JS if needed) only. Public function `render_dashboard(trip: dict, output_path: Path, pdf_href: str|None=None) -> dict` returning `{"path":...,"format":"html"}`. Python standard library only. May import trip_core helpers. `pdf_href` supplied only after selected PDF successfully exists. Private output embeds full canonical JSON + current checks; shared projection must not export full JSON. Do not invent source schema variants.

PDF renderer uses `scripts/render_travelbook.py`, optional `assets/travelbook.*` only. Public function `render_travelbook(trip: dict, output_path: Path) -> dict` returning `{path,format:"pdf",pages,...}`. Use ReportLab (+Pillow if necessary) and package-relative fonts. Dynamic pagination with cover, overview, reservations, daily timeline/details, costs/checklist, sources. 160×240mm; Pretendard 9.5/13.2 body and Noto Serif KR 18.5 titles. No hardcoded trip dates/places/page count. Keep meaningful headings with content; paragraph/table split. Bookmarks and clickable overview→day, day→overview. No implicit remote reads. If dependency unavailable, actionable failure without installation. The PDF engine is ReportLab; an intermediate print HTML is not required.

Renderer scripts may provide standalone CLIs but must validate via trip_core before writing if standalone. Main `generate.py INPUT --out-dir DIR [--baseline FILE] [--allow-changes FILE] [--export-json]` reads requested_outputs from JSON (never defaults to both); outputs only selected final files (`travel.html`, `travelbook.pdf`). `--export-json` explicit backup only. Preserve existing outputs on failures using temporary staging and publish selected successful outputs only with explicit partial status. No source writes; no silent format substitution.

## Change authorization

Separate trusted CLI allow file: `{"bookings":{"booking-id":["field", "*"]},"delete_bookings":["id"]}`. Never use candidate `changes[]` as permission. Baseline locked fields (or fixed defaults for confirmed bookings) remain protected even if candidate clears locks. Missing baseline means no claim of checked preservation. Revision unchanged for check-only; canonical travel changes require higher revision. Shared redacted input cannot replace a private baseline.

`validation.media: {status:"ready"|"needs_review"|"opted_out",ready,required,missing:[{role,place_id,label,reason}]}` records cover and hotel coverage. Missing required photos make generation `needs_review` without blocking useful draft files. A successful image decode does not verify property identity or reuse rights.
