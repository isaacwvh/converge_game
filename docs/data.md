# Country data contract

CSV columns: `code` (unique ISO alpha-3), `name`, `aliases` (pipe-separated), `population` (people), `area_km2` (km²), `gdp_per_capita_usd` (USD per person), `temp_c` (annual mean Celsius), `capital`, `capital_lat`, `capital_lon` (WGS84 degrees), and `provenance` (JSON object describing each source and reference year).

Use a reviewed common reference year for economic metrics and a stated climate reference period. Choose one capital per country and retain it consistently. Imports validate shape, ranges, and unique country codes. The operator publishes a new immutable label. Existing puzzles keep their old dataset version. A scheduled production process should import and review data, then explicitly activate a new version before scheduling future puzzles.

The bundled CSV is only a development fixture. Its values are approximate and must be replaced before public launch.
