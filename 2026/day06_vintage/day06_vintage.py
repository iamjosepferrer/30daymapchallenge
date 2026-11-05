"""Day 6, Vintage: half of Europe's people live on land Rome once ruled."""
import base64
import io
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import rasterio.features
import rasterio.transform
import rasterio.warp
import requests
from PIL import Image
from pyproj import Transformer
from shapely.geometry import box

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

AWMC = ("https://raw.githubusercontent.com/AWMC/geodata/master/Cultural-Data/political_shading/"
        "roman_empire_ce_117_extent/roman_empire_ce_117_extent.geojson")
COUNTRIES_10M = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
POP_NAME = "GHS_POP_E2025_GLOBE_R2023A_4326_30ss_V1_0"  # the same file as compute_europe_population.py on Day 1
POP_URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
           f"GHS_POP_E2025_GLOBE_R2023A_4326_30ss/V1-0/{POP_NAME}.zip")
# The same Europe as Day 1: west of 60°E, without Turkey or Cyprus
SCOPE = {
    "United Kingdom", "Ireland", "France", "Spain", "Portugal", "Germany", "Netherlands",
    "Belgium", "Luxembourg", "Switzerland", "Austria", "Italy", "Denmark", "Norway", "Sweden",
    "Finland", "Iceland", "Estonia", "Latvia", "Lithuania", "Poland", "Czechia", "Slovakia",
    "Hungary", "Slovenia", "Croatia", "Bosnia and Herzegovina", "Republic of Serbia",
    "Montenegro", "Kosovo", "North Macedonia", "Albania", "Greece", "Bulgaria", "Romania",
    "Moldova", "Ukraine", "Belarus", "Russia", "Malta", "Jersey", "Andorra", "Liechtenstein",
    "Monaco", "San Marino", "Vatican", "Guernsey", "Isle of Man", "Faroe Islands", "Aland",
    "Gibraltar",
}
to_map = Transformer.from_crs(4326, 3035, always_xy=True)

# 1. Data: count every GHS-POP cell whose centre lies inside Rome's greatest extent, AD 117
raster = DATA_DIR / f"{POP_NAME}.tif"
if not raster.exists():
    print("Downloading GHS-POP (461 MB)")
    response = requests.get(POP_URL, timeout=1800)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extract(raster.name, DATA_DIR)
empire_4326 = gpd.read_file(_download(AWMC, DATA_DIR / "roman_empire_ce_117_extent.geojson")).to_crs(4326).buffer(0).union_all()
empire = gpd.GeoSeries([empire_4326], crs=4326).to_crs(3035).buffer(0).iloc[0]
world_10m = gpd.read_file(_download(COUNTRIES_10M, DATA_DIR / "ne_10m_admin_0_countries.geojson"))[["ADMIN", "geometry"]]
world_10m = world_10m[world_10m.ADMIN.isin(SCOPE)].reset_index(drop=True)
world_10m["geometry"] = world_10m.geometry.buffer(0).intersection(box(-32, 27, 60, 82))
with rasterio.open(raster) as source:
    window = source.window(-32, 27, 60, 82).round_offsets().round_lengths()
    people = source.read(1, window=window).astype(np.float64)
    transform, pop_crs = source.window_transform(window), source.crs
people[people < 0] = 0
# Like Day 1, every cell touching Europe's boundaries counts, so coastal cells are not cut off
in_europe = rasterio.features.rasterize(
    [(world_10m.geometry.union_all(), 1)], out_shape=people.shape, transform=transform, fill=0, dtype="uint8", all_touched=True) == 1
people[~in_europe] = 0
inside = rasterio.features.rasterize([(empire_4326, 1)], out_shape=people.shape, transform=transform, fill=0, dtype="uint8") == 1
total, in_rome = people.sum(), people[inside].sum()
share = in_rome / total
print(f"{total / 1e6:.1f}M people, {in_rome / 1e6:.1f}M inside ({share:.1%})")
near_coast = rasterio.features.rasterize([(gpd.GeoSeries([empire], crs=3035).buffer(3000).to_crs(4326).buffer(0).iloc[0], 1)],
                                         out_shape=people.shape, transform=transform, fill=0, dtype="uint8") == 1
print(f"With 3 km around the borders: {people[near_coast].sum() / total:.1%}")

labels = rasterio.features.rasterize(
    ((shape, i + 1) for i, shape in enumerate(world_10m.geometry)), out_shape=people.shape, transform=transform, fill=0, dtype="int32")
rows = []
for i, name in enumerate(world_10m.ADMIN):
    here = labels == i + 1
    if people[here].sum() > 0:
        rows.append({"country": name, "people": int(people[here].sum()), "inside": int(people[here & inside].sum())})
results = pd.DataFrame(rows).sort_values("people", ascending=False)
results["share_inside"] = (results.inside / results.people).round(3)
germany = results.set_index("country").loc["Germany", "share_inside"]
print(results.head(16).to_string(index=False))

# 2. Map frame: the same Europe as Day 1, running edge to edge
MAP_TOP = 410
frame = Frame(2470000, 7300000, 1220000, 1220000 + (1232 - MAP_TOP) / 1080 * 4830000, 0, 1080, MAP_TOP)
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(frame.box().buffer(100000))
world = world[~world.geometry.is_empty]
in_scope = world[world.ADMIN.isin(SCOPE)].geometry.union_all()
out_scope = world[~world.ADMIN.isin(SCOPE)].geometry.union_all()
rome_shape = empire.intersection(frame.box().buffer(100000))

# 3. People: blocks at the printed resolution, blue inside the empire and grey outside, darker where more people live
res = 1 / (frame.k * 2)
w, h = int(1080 * 2), int(frame.ph * 2)
block_transform = rasterio.transform.from_origin(frame.x0, frame.y1, res, res)


def to_blocks(values):
    out = np.zeros((h, w), dtype=np.float64)
    rasterio.warp.reproject(values, out, src_transform=transform, src_crs=pop_crs, dst_transform=block_transform, dst_crs="EPSG:3035",
                            resampling=rasterio.warp.Resampling.sum)
    return out


block_in, block_out = to_blocks(people * inside), to_blocks(people * ~inside)
hex_rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
dots = np.zeros((h, w, 4), dtype=np.uint8)
for values, colour in ((block_out, C["ctx"]), (block_in, C["blue"])):
    hit = values >= 25  # GHS-POP spreads small modelled values over empty land; this keeps the settled areas
    dots[hit, :3] = hex_rgb(colour)
    dots[hit, 3] = (np.clip(0.10 + 0.24 * np.log10(values[hit]), 0.30, 1.0) * 255).astype(np.uint8)
png = io.BytesIO()
Image.fromarray(dots).save(png, format="PNG", optimize=True)

# 4. Land, the empire as a blue band like the eclipse paths on Day 5, and the people on top
svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{geom_path(out_scope, frame)}" fill="{C["quiet_land"]}"/>',
    f'<path d="{geom_path(in_scope, frame)}" fill="{C["page"]}"/>',
    f'<path d="{geom_path(rome_shape, frame)}" fill="{C["blue"]}" fill-opacity=".13" stroke="{C["blue"]}" stroke-width="1.4"/>',
    f'<image href="data:image/png;base64,{base64.b64encode(png.getvalue()).decode()}" x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.1f}" preserveAspectRatio="none"/>',
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>',
    "</g>",
]

# 5. City labels: a few inside the empire, a few outside
CITIES = {
    "Rome": (12.50, 41.90, 8, 5, "start"), "Paris": (2.35, 48.86, 8, 5, "start"), "Barcelona": (2.17, 41.39, 8, 5, "start"),
    "London": (-0.12, 51.51, -8, 5, "end"), "Cologne": (6.96, 50.94, -8, 4, "end"), "Vienna": (16.37, 48.21, 8, -3, "start"),
    "Athens": (23.73, 37.98, 8, 5, "start"), "Lisbon": (-9.14, 38.72, 8, 5, "start"), "Berlin": (13.40, 52.52, 8, 5, "start"),
    "Warsaw": (21.01, 52.23, 8, 5, "start"), "Stockholm": (18.07, 59.33, 8, 5, "start"), "Kyiv": (30.52, 50.45, 8, 5, "start"),
    "Moscow": (37.62, 55.75, 8, 5, "start"),
}
for name, (lon, lat, dx, dy, anchor) in CITIES.items():
    x, y = frame.xy(*to_map.transform(lon, lat))
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{C["card"]}" stroke="{C["ink"]}" stroke-width="1.5"/>')
    svg.append(text(x + dx, y + dy, name, 15, 600, C["ink"], anchor, halo=C["page"]))

# 6. Direct labels, as on Day 5
svg.append(text(28, 898, "Roman Empire, AD 117", 18, 700, C["blue"]))
svg.append(text(28, 919, f"{in_rome / 1e6:.0f} million people", 16, 400, C["ink"]))
svg.append(text(28, 939, "live inside its borders", 16, 400, C["ink"]))

# 7. One handwritten note on the frontier in Germany
note_x, note_y = 742, 472
svg.append(
    f'<text class="note" x="{note_x}" y="{note_y}" font-size="23" fill="{C["ink"]}">'
    f'<tspan x="{note_x}">The old frontier cuts</tspan><tspan x="{note_x}" dy="28">Germany: {germany:.0%} of people</tspan><tspan x="{note_x}" dy="28">are on the Roman side</tspan></text>'
)
ax, ay = frame.xy(*to_map.transform(12.3, 49.0))
ax, ay = ax + 2, ay - 4
sx, sy = note_x + 40, note_y + 70
svg.append(f'<path d="M{sx} {sy} C {sx - 60} {sy + 90}, {ax + 80} {ay - 110}, {ax:.1f} {ay:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{ax + 1:.1f} {ay - 13:.1f} L{ax:.1f} {ay:.1f} L{ax + 13:.1f} {ay - 3:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 8. Headline, dek, byline, bar and footer
svg.append(text(60, 90, "Half of Europe's people live", 50, 800))
svg.append(text(60, 146, "on land Rome once ruled", 50, 800))
svg.append(text(60, 190, "Where people live in 2025, against the Roman Empire at its greatest extent in AD 117.", 25, 400, C["ink2"]))
svg.append(text(60, 220, "Blue squares are inside its borders, grey ones outside.", 25, 400, C["ink2"]))
svg.append(byline(252))
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"Europe's roughly {round(total / 1e8) * 100} million people in 2025", 21, 700))
x = BAR_X
for i, (value, colour, label) in enumerate(((in_rome, C["blue"], "Inside Rome's borders"), (total - in_rome, C["ctx"], "Outside"))):
    width = BAR_W * value / total
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    svg.append(text(x, BAR_Y + BAR_H + 23, f"{value / total:.0%}", 22, 700))
    svg.append(text(x, BAR_Y + BAR_H + 44, label, 17, 400, C["ink2"]))
    x += width
FOOTER = [
    ("Method:", "a 1 km population cell counts as inside when its centre lies within the AD 117 borders."),
    ("Source:", "Roman Empire: Ancient World Mapping Center (UNC), ODbL. Population: GHS-POP R2023A (European Commission, JRC), 2025 estimates. Base: Natural Earth."),
    ("Comments:", "Turkey and Cyprus are excluded. Overseas territories such as the Canaries are counted but off the map. Ancient Roman borders are approximate."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)

save_png(page("".join(svg)), HERE / "day06_vintage.png")
results.to_csv(HERE / "results.csv", index=False)
