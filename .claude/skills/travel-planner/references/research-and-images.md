# Research and image decisions

Use source IDs to connect facts to `sources`. Web entries need the actual page URL, title, date inspected, and `public:true` only when safe to share. Tickets/vouchers use `type:document`, filename/page and optional private path, with `public:false`. User preferences can use `type:user`. Keep unsupported assertions out of the source register.

For a future trip, an operator's current general description is not confirmation of the exact future departure, fare, opening hours, or weather. Distinguish published timetable, general duration, estimate, and unknown. Compute timezone-aware comparisons from explicit ISO offsets; ask when a ticket's local date or offset cannot be established. Do not compare “afternoon” labels as timestamps. Use availability entries only for checked dates/intervals. Record transfers, walking to platforms, waiting and baggage time separately from a vehicle's travel time. Never turn missing route data into a zero-minute journey.

Before adding an attraction, check fixed bookings, realistic transport, date-specific closures, and the user's walking/rest constraints. Use constraints only where the user supplied them; do not infer a medical diagnosis or guaranteed accessibility. Ask about relevant mobility needs in practical terms. Alternatives should identify what is reduced, what booking remains, and what still needs checking. A suggestion does not change the itinerary until the user asks for the change.

## Photo acquisition workflow (required by default)

1. Identify the destination city and each distinct named hotel from the trip. Start with the hotel's official property/gallery page and compare its branch, city and address to the booking. For an ambiguous hotel, do not choose a similarly named property. Request only the missing identifying detail if it prevents the match.
2. Use the host's web/image search tools to find a representative city image and one actual photograph per hotel. Prefer the user's own images, explicitly reusable official media, or attributed open-license photos. Official provenance proves identity, not permission to redistribute; check the source's reuse terms. If an official asset cannot be reused, try a licensed photo of the same property. Do not label a neighborhood photo as a hotel. No generated lookalikes.
3. Inspect each actual image using the host's image viewer, image search preview or browser. The source page must identify what is shown. An exterior of the actual building containing the hotel is acceptable with that exact caption; a random tower is not. For a room image, state that it is a representative room unless the booked room category matches.
4. Obtain the real direct image URL from the source page's download link, observed image URL or supported browser asset tool; never guess CDN filenames. The host can acquire a local file, or the helper can download this verified HTTPS URL. Do not hand a webpage URL to the image decoder. Use a permitted equivalent tool if the host lacks image search; no paid service or API key is required.
5. Record source/creator/license and prepare the manifest below. Run the helper, inspect its result and actual optimized images, then validate/render. JPEG/PNG/WebP are decoded, EXIF orientation is applied, identifying EXIF metadata is removed, and the long edge is reduced to 1800px. Renderers embed the resulting bytes and never hotlink.
6. Confirm the HTML main cover shows the city and hotel cards show the correct properties. In PDF, check the city cover and hotel images in the accommodation section. If optional place photos are included, inspect their relevant day placement too.

### Manifest and command

Write this to the working directory, not the skill package. Replace the example fields with researched values. `items` may have hero, stay and place entries; use **exactly one** `path` (relative to manifest or absolute) or `download_url` per item. Search/inspect first: do not mark verification true merely because a download succeeds.

```json
{
  "items": [
    {
      "id": "city-cover", "role": "hero", "place_id": "city-place-id",
      "path": "assets/city.jpg", "depicts": "landscape",
      "alt": "Recognizable view of the destination city",
      "caption": "City landmark · photographer / license",
      "creator": "Actual photographer", "source_url": "https://source.example/image-page",
      "license": "Actual reuse license", "license_url": "https://source.example/terms",
      "checked_at": "2026-09-21", "visually_verified": true
    },
    {
      "id": "hotel-exterior", "role": "stay", "place_id": "hotel-place-id",
      "download_url": "https://source.example/actual-image.jpg", "depicts": "property",
      "alt": "Exterior of the exact booked hotel", "caption": "Exact hotel branch exterior · photographer / license",
      "creator": "Actual photographer", "source_url": "https://source.example/image-page",
      "license": "Actual reuse license", "license_url": "https://source.example/terms",
      "checked_at": "2026-09-21", "visually_verified": true,
      "verified_property": true, "identity_source_url": "https://hotel.example/official-property-page",
      "identity_note": "Compared official hotel name, branch and address with the booking; the photographed building is that property."
    }
  ],
  "unavailable": []
}
```

```sh
python3 "<skill-root>/scripts/preflight.py" --formats html pdf --photos
python3 "<skill-root>/scripts/media_pipeline.py" "<work>/trip.json" --manifest "<work>/media-plan.json" --out "<work>/trip-with-media.json"
python3 "<skill-root>/scripts/validate_trip.py" "<work>/trip-with-media.json"
python3 "<skill-root>/scripts/generate.py" "<work>/trip-with-media.json" --out-dir "<work>/result-r1"
```

Use only selected formats in preflight and `requested_outputs`. Pillow is needed to prepare photos; prefer the host's bundled Python/runtime. If unavailable, install only in the permitted task environment or report the limitation. The helper leaves its input, bookings, costs and existing unrelated photos intact. It replaces only a supplied photo ID. It never searches for, verifies the meaning of, or licenses an image on its own.

### When collection fails

For a required photo that cannot be acquired, add an `unavailable` entry such as `{"role":"stay","place_id":"hotel-place-id","reason":"Official gallery could not be downloaded; no reusable photo of this exact property was found.","checked_at":"YYYY-MM-DD"}`. Use the actual reason; log source checks internally. Try the official source plus an appropriate alternative, then stop if both fail. Never falsely claim network restrictions without an actual tool failure. Do not silently change `photo_policy` to off.

Missing hero or property photos keep `validation.media.status` and generation status `needs_review`; files may still be produced with clear missing-photo notices. In the final answer name what is missing and why. An empty `media` array is not completed photo collection. An explicit user no-photo request uses `photo_policy:"off"` with `photo_note` recording that request; the typographic layout remains available for that choice.

Document ingestion and researched editorial facts still require human/AI source comparison. The validator checks structured consistency; it cannot prove that a transcribed digit or source assertion matches the original.
