# Editing, preservation, and sharing

Choose the baseline deliberately. For multiple files, compare trip_id, revision, content, and generation timestamp. Do not merge different trips or prefer a timestamp over a contradictory user instruction. If no baseline exists, say preservation was not checked. A shared `redacted:true` copy is not a recoverable private master.

Keep booking/activity/source IDs stable. Keep the original file and create a revised working file. Pass the baseline when generating:

```sh
python3 "<skill-root>/scripts/generate.py" revised.json --baseline original.json --out-dir result-r2
```

Preserve previously delivered HTML/PDF files and their download paths as well as the working JSON. Use a new delivery folder for each generation; a format change never authorizes deletion of an old attachment. Attach only the current selection without cleaning up earlier responses.

The validator protects explicit `locked_fields` and core fields of baseline bookings marked confirmed. Clearing locks or changing IDs cannot bypass deletion checks. Changes in `changes[]` describe the user's request; they do not authorize it. If the user explicitly changes a fixed field, prepare a separate temporary authorization file for **only** those booking fields:

```json
{"bookings":{"stay-01":["check_in","check_out","nights"]},"delete_bookings":[]}
```

Use `--allow-changes authorized-fields.json` together with `--baseline`. Avoid wildcard authorization; it is reserved for an explicit whole-booking replacement. Deletion requires the matching ID under `delete_bookings`. Validate the rest of the trip again: an authorized booking change can still leave a missing night or invalid connection.

A trip-content edit increments revision; a checklist state change or export keeps revision and creates a new generation ID/time. Unknown private fields are preserved. HTML export carries current checklist state, canonical booking data, sources, nulls and embedded assets. Browser storage is convenience only; downloaded JSON is the explicit portable backup. Updating the HTML does not update a PDF already sent to someone—generate a new selected output and identify the changed revision.

For sharing, derive a new output with audience shared from the retained private data. The coordinator projects only allowed fields, removes booking references/passenger names/private notes/local source paths, omits non-public source records, and disables full JSON export. It does not merge shared browser state with the private scope. **Inspect prose and image pixels too:** a name or reservation number manually typed into a title/description or visible in a photograph cannot reliably be removed by field projection. Rewrite such prose and exclude voucher screenshots. Shared output is suitable only after this content review; it is not an automatic anonymizer.

Do not publish to a public host by default. If asked to host, confirm the requested audience from the user's instruction and use available hosting tools. Private/link-restricted requests must not be converted to public hosting merely because that is the only available service. Report the actual URL/access verification separately from file creation.
