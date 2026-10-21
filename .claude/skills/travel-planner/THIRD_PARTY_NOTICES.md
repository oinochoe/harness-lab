# Bundled resources

- Noto Sans JP regular static instance (weight 400): official Google Fonts source, SIL Open Font License 1.1; used as a PDF glyph fallback for Japanese photo credits/place names. Source, conversion and SHA are in `assets/fonts/font_sources.json`; license is `assets/fonts/notosansjp-OFL.txt`.

- Chart.js 4.5.1: MIT, `assets/vendor/CHART_LICENSE.txt`; https://www.chartjs.org/
- Leaflet 1.9.4: BSD-2-Clause, `assets/vendor/LEAFLET_LICENSE.txt`; https://leafletjs.com/
- Pretendard 1.3.9: SIL OFL, `assets/fonts/pretendard-LICENSE.txt`; upstream/source hashes in `assets/fonts/font_sources.json`.
- Noto Serif KR regular static instance: SIL OFL, `assets/fonts/notoserifkr-OFL.txt`; upstream and instance process recorded in the same metadata file.
- Swiss example photos are embedded in `examples/sample-trip.json` and retain creator/source/license fields: Oeschinensee (Günter Seggebäing, CC BY-SA 3.0); Lucerne (Ymblanter, CC BY-SA 4.0); Grindelwald (Sabrina Schreiber, CC BY-SA 4.0). Each rendered output includes attribution. Landscape images do not depict actual booked hotels.
- Interactive maps request OpenStreetMap tiles and display attribution. Core travel information remains usable without tiles. Links may require network access.

ReportLab and Pillow are runtime dependencies, not vendored software. The package does not include an AI model, credentials, a booking service or a hosting account.
