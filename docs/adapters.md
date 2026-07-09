# Adapter catalog

Each adapter takes a `locator` and returns a `RawRecord`. Locator semantics
vary per adapter.

## `url` — URL coord dispatch

`URLCoordAdapter()`.

Locator: a URL string from one of:

- `https://yandex.ru/maps/?ll=LON,LAT` or `?pt=LON,LAT` or `?q=LON,LAT`
- `https://maps.google.com/?q=LAT,LON` or `.../@LAT,LON,ZOOMz`
- `https://www.openstreetmap.org/?mlat=LAT&mlon=LON`
- `https://brouter.de/brouter/#lonlats=LON,LAT;LON,LAT&profile=river`

Important quirks:

- Yandex: `ll=` and `pt=` use **LON, LAT** order (must be flipped)
- Google: `q=` uses **LAT, LON** order
- BRouter: `lonlats=` uses **LON, LAT** order

The adapter always returns `(lat, lon)` tuples in `coord_hint`, regardless
of source format.

## `gpx` — GPX file or URL

`GPXAdapter()`.

Locator: local path or URL ending in `.gpx`.

Returns:

- `attrs['track_points']` — list of `(lat, lon)` tuples
- `attrs['waypoints']` — list of `{lat, lon, name, type}` dicts
- `coord_hint` — first track point or first waypoint

## `html` — static HTML

`HTMLAdapter()`.

Locator: any URL. Uses `BeautifulSoup` to extract `title` and `text`. Full
body preserved in `attrs['body']`. Use in combination with an Enricher that
knows the site's structure (Yandex price tables, Telegram preview, etc.).

## `api` — JSON API

`APIAdapter()`.

Locator: URL of a JSON endpoint. Optional `headers={...}` for auth tokens.

Returns: `attrs['json']` (the parsed payload), `coord_hint` is not auto-extracted.

## `overpass` — Overpass QL query

`OverpassAdapter()`.

Locator: an OverpassQL query body.

Posting to `https://maps.mail.ru/osm/tools/overpass/api/interpreter` (default)
as `data=<query>`. Use `nwr[...]` not `node[...]` to capture ways/relations
(~50% of fuel stations are ways). For way/relation coordinates use
`out center;`. Then call `enrichers.coords.canonicalize_osm_coords(elem)`
to canonicalize `center=[LAT,LON]` to `(lat, lon)`.

Example:

```python
q = '''[out:json][timeout:180];
area["ISO3166-1"="UA"]->.ua;
nwr["amenity"="fuel"](area.ua);
out center;'''
```

## When to write a new adapter

If the source is one of:

- HTML with custom DOM (Yandex price tables, Telegram preview, Minfin UA fuel)
- An authenticated JSON API (WOG, OKKO, AUTO.RIA — auth headers required)
- A binary format (CSV, protobuf, sqlite dump)

…then write a new Layer-1 module that returns `RawRecord`. The rest of the
pipeline (rate-limit, retry, sink, observability) is shared.
