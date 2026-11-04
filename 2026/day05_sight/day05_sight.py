"""Day 5, Senses, Sight: Spain gets two total solar eclipses in a year, but nobody lives in both paths."""
import base64
import io
import re
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
import shapely
from PIL import Image
from pyproj import Transformer
from shapely.geometry import Polygon

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

NASA = "https://eclipse.gsfc.nasa.gov/SEgoogle/SEgoogle2001/{}google.html"
ECLIPSES = {
    "2026": ("SE2026Aug12T", "Total eclipse, 12 Aug 2026", C["blue"]),
    "2027": ("SE2027Aug02T", "Total eclipse, 2 Aug 2027", C["apricot"]),
}
GRID_URL = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V3.zip"
GRID_TIFF = "ESTAT_Census_2021_V3.tiff"
COUNTRIES_10M = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
to_map = Transformer.from_crs(4326, 3035, always_xy=True)


def nasa_page(code):
    path = DATA_DIR / "nasa_eclipse" / f"{code}g.html"
    if not path.exists():
        print(f"Downloading the NASA path of {code}")
        response = requests.get(NASA.format(code), timeout=120)
        response.raise_for_status()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(response.text)
    return path.read_text()


def eclipse_path(code):
    """Northern and southern limits from NASA's interactive map page, as one polygon in EPSG:3035."""
    page_text = nasa_page(code)
    limits = {}
    for key, title in (("north", "Northern Limit"), ("south", "Southern Limit")):
        start = page_text.index(title)
        block = page_text[start:page_text.index('"#', start)]
        points = [(float(lon), float(lat)) for lat, lon in re.findall(r"GLatLng\(\s*(-?[\d.]+),\s*(-?[\d.]+)\)", block)]
        points = [(lon, lat) for lon, lat in points if -35 < lon < 45 and 20 < lat < 75]  # the European part
        limits[key] = [to_map.transform(lon, lat) for lon, lat in points]
    return Polygon(limits["north"] + limits["south"][::-1]).buffer(0), limits


def census_grid():
    """Eurostat's Census 2021 population grid, the same file as Day 4."""
    path = DATA_DIR / GRID_TIFF
    if not path.exists():
        print("Downloading the Census 2021 grid (566 MB)")
        response = requests.get(GRID_URL, timeout=1800)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            member = next(name for name in archive.namelist() if name.endswith(GRID_TIFF))
            path.write_bytes(archive.read(member))
    with rasterio.open(path) as source:
        people = source.read(1).astype(np.int64)
        transform = source.transform
    return np.where(people > 0, people, 0), transform


# 1. Data: who lives inside each path, counting every 1 km square by its centre
people, transform = census_grid()
rows, cols = np.nonzero(people)
centre_x = transform.c + (cols + 0.5) * 1000
centre_y = transform.f - (rows + 0.5) * 1000
paths, inside = {}, {}
for year, (code, _, _) in ECLIPSES.items():
    paths[year] = eclipse_path(code)
    inside[year] = shapely.contains_xy(paths[year][0], centre_x, centre_y)

# Spain, from the detailed Natural Earth file, which includes Ceuta and Melilla
spain_shape = gpd.read_file(_download(COUNTRIES_10M, DATA_DIR / "ne_10m_admin_0_countries.geojson")).set_index("ADMIN").to_crs(3035).loc["Spain", "geometry"]
in_spain = shapely.contains_xy(spain_shape.buffer(2000), centre_x, centre_y)
counts = people[rows, cols]
spain_total = counts[in_spain].sum()
in_2026, in_2027 = counts[inside["2026"] & in_spain].sum(), counts[inside["2027"] & in_spain].sum()
in_both = counts[inside["2026"] & inside["2027"]].sum()
from shapely.ops import nearest_points  # noqa: E402

# The gap over land: the closest points of the two paths inside Spain
spain_main = spain_shape.intersection(Polygon([(2600000, 1550000), (3800000, 1550000), (3800000, 2500000), (2600000, 2500000)]))
near_2026, near_2027 = nearest_points(paths["2026"][0].intersection(spain_main), paths["2027"][0].intersection(spain_main))
gap_km = near_2026.distance(near_2027) / 1000
print(f"Spain {spain_total / 1e6:.2f}M: 2026 path {in_2026 / 1e6:.2f}M, 2027 path {in_2027 / 1e6:.2f}M, both {in_both:,}, "
      f"paths {gap_km:.0f} km apart over land")
results = pd.DataFrame([
    {"eclipse": ECLIPSES[year][1], "people_in_path": int(counts[inside[year]].sum()),
     "of_which_spain": int(counts[inside[year] & in_spain].sum())} for year in ECLIPSES
])

# 2. Map frame: mainland Spain and the Balearics. The right edge sits just west of where the 2026 path ends at sunset,
# so both ends of the path run off the map
MAP_TOP = 410
frame = Frame(2400000, 3835000, 1410000, 2507500, 0, 1080, MAP_TOP)
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(frame.box())
others = world[world.ADMIN != "Spain"].geometry.union_all()
spain_land = world[world.ADMIN == "Spain"].geometry.union_all()

# Where people live: every populated 1 km square in Spain, coloured by the total eclipse path it sits in
col0, row0 = int((frame.x0 - transform.c) // 1000), int((transform.f - frame.y1) // 1000)
w, h = int((frame.x1 - frame.x0) // 1000), int((frame.y1 - frame.y0) // 1000)
window = people[row0:row0 + h, col0:col0 + w] > 0
wy, wx = np.nonzero(window)
cx, cy = frame.x0 + (wx + 0.5) * 1000, frame.y1 - (wy + 0.5) * 1000
keep = shapely.contains_xy(spain_shape.buffer(1500), cx, cy)
hex_rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
dots = np.zeros(window.shape + (4,), dtype=np.uint8)
dots[wy[keep], wx[keep]] = (*hex_rgb(C["ctx"]), 150)
for year in ("2026", "2027"):
    hit = keep & shapely.contains_xy(paths[year][0], cx, cy)
    dots[wy[hit], wx[hit]] = (*hex_rgb(ECLIPSES[year][2]), 235)
png = io.BytesIO()
Image.fromarray(dots).save(png, format="PNG", optimize=True)

svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{geom_path(others, frame)}" fill="{C["quiet_land"]}"/>',
    f'<path d="{geom_path(spain_land, frame)}" fill="{C["page"]}"/>',
]
for year in ("2026", "2027"):
    band = paths[year][0].intersection(frame.box().buffer(50000))
    svg.append(f'<path d="{geom_path(band, frame)}" fill="{ECLIPSES[year][2]}" fill-opacity=".13" stroke="{ECLIPSES[year][2]}" stroke-width="1.4"/>')
svg += [
    f'<image href="data:image/png;base64,{base64.b64encode(png.getvalue()).decode()}" x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.1f}" preserveAspectRatio="none"/>',
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>',
    "</g>",
]

# 3. The gap: where the two paths come closest over Spain, measured on the map
(gx0, gy0), (gx1, gy1) = frame.xy(near_2026.x, near_2026.y), frame.xy(near_2027.x, near_2027.y)
svg.append(f'<line x1="{gx0:.1f}" y1="{gy0:.1f}" x2="{gx1:.1f}" y2="{gy1:.1f}" stroke="{C["ink"]}" stroke-width="1.6"/>')
for gx, gy in ((gx0, gy0), (gx1, gy1)):
    svg.append(f'<circle cx="{gx:.1f}" cy="{gy:.1f}" r="3" fill="{C["ink"]}"/>')
print(f"Closest points: 2026 path at {near_2026}, 2027 path at {near_2027}")

# 4. Cities: a dot and a name
CITIES = {
    "Madrid": (-3.7038, 40.4168, -8, -6, "end"), "Barcelona": (2.1686, 41.3874, 8, 5, "start"),
    "Valencia": (-0.3763, 39.4699, 8, -6, "start"), "Bilbao": (-2.935, 43.263, 14, -16, "start"),
    "Seville": (-5.9845, 37.3891, 8, 5, "start"), "Málaga": (-4.4214, 36.7213, 8, -6, "start"),
}
for name, (lon, lat, dx, dy, anchor) in CITIES.items():
    x, y = frame.xy(*to_map.transform(lon, lat))
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{C["card"]}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    svg.append(text(x + dx, y + dy, name, 15, 600, C["ink"], anchor))

# 5. Direct labels on each path, in the sea
PATH_LABELS = {"2026": (30, 470, "start"), "2027": (34, 1108, "start")}
for year, (x, y, anchor) in PATH_LABELS.items():
    total = {"2026": in_2026, "2027": in_2027}[year]
    svg.append(text(x, y, ECLIPSES[year][1], 18, 700, ECLIPSES[year][2], anchor))
    svg.append(text(x, y + 21, f"{total / 1e6:.1f} million people in the path", 16, 400, C["ink"], anchor))

# 6. One handwritten note in the Mediterranean, with a short arrow to the gap
note_x, note_y = 762, 1030
svg.append(
    f'<text class="note" x="{note_x}" y="{note_y}" font-size="22" fill="{C["ink"]}">'
    f'<tspan x="{note_x}">The paths stay</tspan><tspan x="{note_x}" dy="26">{round(gap_km, -1):.0f} km apart</tspan><tspan x="{note_x}" dy="26">over land</tspan></text>'
)
x0, y0 = note_x - 8, note_y - 10
x1, y1 = (gx0 + gx1) / 2 + 8, (gy0 + gy1) / 2 + 2
svg.append(f'<path d="M{x0} {y0} C {x0 - 30} {y0 - 30}, {x1 + 40} {y1 - 10}, {x1:.1f} {y1:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{x1 + 12:.1f} {y1 - 7:.1f} L{x1:.1f} {y1:.1f} L{x1 + 11:.1f} {y1 + 8:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 7. Bar: Spain's people and the two total eclipses
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"Spain's {spain_total / 1e6:.0f} million people", 21, 700))
segments = [
    (in_2026 / spain_total, C["blue"], "In the 2026 path"),
    (in_2027 / spain_total, C["apricot"], "In the 2027 path"),
    (1 - (in_2026 + in_2027) / spain_total, C["page"], "In neither"),
]
x = BAR_X
for share, colour, label in segments:
    width = BAR_W * share
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    last = colour == C["page"]  # the last segment is labelled from its right end, so it never meets the narrow 2027 one
    label_x, anchor = (BAR_X + BAR_W, "end") if last else (x, "start")
    svg.append(text(label_x, BAR_Y + BAR_H + 23, f"{share:.0%}", 22, 700, None, anchor))
    svg.append(text(label_x, BAR_Y + BAR_H + 44, label, 17, 400, C["ink2"], anchor))
    x += width

# 8. Headline, dek, byline and footer
svg.append(text(60, 90, "Spain gets two total eclipses in a year,", 50, 800))
svg.append(text(60, 146, "but nobody lives in both paths", 50, 800))
svg.append(text(60, 190, "Paths of totality and the people living inside them. The shadow crossed the north", 25, 400, C["ink2"]))
svg.append(text(60, 220, "in August 2026 and will cross the far south in August 2027.", 25, 400, C["ink2"]))
svg.append(byline(252))
FOOTER = [
    ("Method:", "a 1 km census square counts as inside a path when its centre lies between NASA's northern and southern limits."),
    ("Source:", "eclipse paths by Fred Espenak, NASA/GSFC. Population: Eurostat, Census 2021 population grid, © European Union. Base: Natural Earth."),
    ("Comments:", "population is from the 2021 census, and clouds decide who actually sees it. Squares at a path's edge can go either way, so totals are rounded. Only Spain is counted: fewer than 20 people in Portugal live in either path."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)

save_png(page("".join(svg)), HERE / "day05_sight.png")
results.to_csv(HERE / "results.csv", index=False)
