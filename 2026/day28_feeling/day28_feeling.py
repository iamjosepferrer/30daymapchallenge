"""Day 28, Senses: Feeling: nights too hot to cool down, then and now.

A tropical night is one when the temperature never drops below 20°C, so a home without air conditioning stays warm
all night. count_nights.py counts them in every E-OBS cell (0.1°, about 10 km) and averages two decades: 1985 to 1994
and 2015 to 2024. The map shows the recent decade. Land outside Europe as
counted here is left plain.

The people counts hold the population fixed at GHS-POP's 2025 estimate, so the change comes from the nights alone,
not from people moving. Europe is the same as on Days 1, 6 and 25: west of 60°E, plus Cyprus and Turkey west of the
Bosphorus. Cells with no E-OBS data (some islands and coasts, about 2% of the people) are left out of the counts.
"""
import base64
import io
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features
import rasterio.warp
import shapely
from PIL import Image
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

COUNTRIES_10M = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
POP = DATA_DIR / "GHS_POP_E2025_GLOBE_R2023A_4326_30ss_V1_0.tif"  # the same file as Days 1, 6 and 25
SCOPE = {
    "United Kingdom", "Ireland", "France", "Spain", "Portugal", "Germany", "Netherlands",
    "Belgium", "Luxembourg", "Switzerland", "Austria", "Italy", "Denmark", "Norway", "Sweden",
    "Finland", "Iceland", "Estonia", "Latvia", "Lithuania", "Poland", "Czechia", "Slovakia",
    "Hungary", "Slovenia", "Croatia", "Bosnia and Herzegovina", "Republic of Serbia",
    "Montenegro", "Kosovo", "North Macedonia", "Albania", "Greece", "Bulgaria", "Romania",
    "Moldova", "Ukraine", "Belarus", "Russia", "Malta", "Jersey", "Andorra", "Liechtenstein",
    "Monaco", "San Marino", "Vatican", "Guernsey", "Isle of Man", "Faroe Islands", "Aland",
    "Gibraltar", "Cyprus", "Northern Cyprus",
}
MONTH = 30  # tropical nights a year: "a month of them"
BREAKS = [1, 10, 30, 60, 90]
RAMP = ["#EDE5D6", "#F1D39A", "#E3A857", "#CC7432", "#A8462A", "#6E2219"]  # from no hot nights to three months of them
NO_DATA = "url(#no-data)"

# 1. Data: tropical nights in each cell, and the people who live there
saved = np.load(HERE / "tropical_nights.npz")  # from count_nights.py
then, now, lat, lon = saved["then"], saved["now"], saved["lat"], saved["lon"]
grid = rasterio.transform.from_origin(lon[0] - 0.05, lat[-1] + 0.05, 0.1, 0.1)  # the E-OBS cells, north row first
world = gpd.read_file(_download(COUNTRIES_10M, DATA_DIR / "ne_10m_admin_0_countries.geojson"))[["ADMIN", "geometry"]]
world["geometry"] = world.geometry.buffer(0)
by_name = lambda *names: world[world.ADMIN.isin(names)].geometry.union_all()
thrace = next(part for part in by_name("Turkey").geoms if part.contains(shapely.Point(27.5, 41.5)))
europe = by_name(*SCOPE).union(thrace).intersection(shapely.box(-32, 27, 60, 82))
inside = rasterio.features.rasterize([(europe, 1)], out_shape=then.shape, transform=grid, fill=0, dtype="uint8")[::-1] == 1
people = np.zeros(then.shape)
with rasterio.open(POP) as source:
    window = source.window(lon[0] - 0.05, lat[0] - 0.05, lon[-1] + 0.05, lat[-1] + 0.05).round_offsets().round_lengths()
    pop = source.read(1, window=window).astype(np.float64)
    pop[pop < 0] = 0
    rasterio.warp.reproject(pop, people, src_transform=source.window_transform(window), src_crs=4326, dst_transform=grid,
                            dst_crs=4326, resampling=rasterio.warp.Resampling.sum)
people = people[::-1]  # south row first, like the nights
counted = inside & np.isfinite(then) & np.isfinite(now)
print(f"{people[counted].sum() / 1e6:.0f}M of {people[inside].sum() / 1e6:.0f}M people in cells with data")
LEVELS = [(10, "10 or more"), (MONTH, "30 or more"), (60, "60 or more")]
exposed = {k: (people[counted & (then >= k)].sum() / 1e6, people[counted & (now >= k)].sum() / 1e6) for k, _ in LEVELS}
for k, (a, b) in exposed.items():
    print(f"{k:3d}+ nights: {a:.0f}M then, {b:.0f}M now")
was, is_now = exposed[MONTH]
assert round(was) == 32 and round(is_now) == 80  # the headline and the dek
cell = lambda lo, la: (np.abs(lat - la).argmin(), np.abs(lon - lo).argmin())
bcn_then, bcn_now = float(then[cell(2.17, 41.39)]), float(now[cell(2.17, 41.39)])
assert round(bcn_then) == 26 and round(bcn_now) == 75  # the note

# 2. Map: each pixel takes the class of the cell it falls in
MAP_TOP = 250
frame = Frame(2300000, 6900000, 1280000, 4810000, 0, 1080, MAP_TOP)  # Day 26's frame, moved south, without the Arctic coast
SCALE = 2
w, h = 1080 * SCALE, int(round(frame.ph * SCALE))
px, py = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
plon, plat = Transformer.from_crs(3035, 4326, always_xy=True).transform(frame.x0 + px / (frame.k * SCALE), frame.y1 - py / (frame.k * SCALE))
i = np.clip(np.round((plat - lat[0]) / 0.1).astype(int), 0, len(lat) - 1)
j = np.clip(np.round((plon - lon[0]) / 0.1).astype(int), 0, len(lon) - 1)
covered = (plat >= lat[0] - 0.05) & (plat <= lat[-1] + 0.05) & (plon >= lon[0] - 0.05) & (plon <= lon[-1] + 0.05)
value = np.where(covered & inside[i, j], now[i, j], np.nan)  # only Europe as counted; other land stays plain
rgb = np.array([[int(c[k:k + 2], 16) for k in (1, 3, 5)] for c in RAMP], np.uint8)
img = np.zeros((h, w, 4), np.uint8)
img[..., :3] = rgb[np.digitize(np.nan_to_num(value), BREAKS)]
img[..., 3] = np.where(np.isfinite(value), 255, 0)
buffer = io.BytesIO()
Image.fromarray(img, "RGBA").save(buffer, "PNG", optimize=True)
uri = base64.b64encode(buffer.getvalue()).decode()

to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
countries = world.to_crs(3035)
land = countries.geometry.intersection(frame.box()).union_all()
europe_3035 = shapely.transform(europe, lambda c: np.column_stack(to3035.transform(c[:, 0], c[:, 1]))).intersection(frame.box())
borders = shapely.union_all([g.boundary for g in countries.geometry.intersection(frame.box().buffer(1)) if not g.is_empty]).intersection(frame.box())
border_d = "".join("M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in (frame.xy(*c) for c in g.coords))
                   for g in getattr(borders, "geoms", [borders]) if g.geom_type == "LineString")
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
       f'<clipPath id="land"><path d="{geom_path(land, frame)}"/></clipPath><g clip-path="url(#map)">',
       f'<defs><pattern id="no-data" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
       f'<rect width="6" height="6" fill="{C["quiet_land"]}"/><line x1="0" y1="0" x2="0" y2="6" stroke="{C["ctx"]}" stroke-width="1.6"/></pattern></defs>',
       f'<path d="{geom_path(land, frame)}" fill="{C["ctxl"]}"/>',  # land outside Europe as counted here
       f'<path d="{geom_path(europe_3035, frame)}" fill="{NO_DATA}"/>',
       f'<g clip-path="url(#land)"><image x="0" y="{MAP_TOP}" width="1080" height="{h / SCALE:.1f}" href="data:image/png;base64,{uri}"/></g>',
       f'<path d="{border_d}" fill="none" stroke="#FFFFFF" stroke-opacity=".75" stroke-width=".7" stroke-linejoin="round"/>',
       fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
       f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic, on the left margin
LX, LY = 60, MAP_TOP + 78  # over the Atlantic, just south of Iceland
svg.append(text(flush("T", 17, 700, LX), LY, "Tropical nights a year,", 17, 700))
svg.append(text(flush("2", 17, 700, LX), LY + 20, "2015 to 2024", 17, 700))
labels = ["none"] + [f"{a} to {b - 1}" for a, b in zip(BREAKS, BREAKS[1:])] + [f"{BREAKS[-1]} or more"]
for k, (colour, label) in enumerate(zip(RAMP, labels)):
    yy = LY + 46 + k * 21
    svg.append(f'<rect x="{LX + 1}" y="{yy - 12}" width="18" height="14" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 28, yy, label, 14, 400, C["ink2"]))
yy = LY + 46 + len(RAMP) * 21
svg.append(f'<rect x="{LX + 1}" y="{yy - 12}" width="18" height="14" rx="2" fill="{NO_DATA}"/>')
svg.append(text(LX + 28, yy, "no data", 14, 400, C["ink2"]))

# One note, over the Mediterranean, pointing at Barcelona
bx, by = frame.xy(*to3035.transform(2.17, 41.39))
NOTE = [f"Barcelona: from {bcn_then:.0f} to {bcn_now:.0f}", "tropical nights a year"]
nx, ny, step = bx - 40, by + 92, 22
svg.append(f'<text class="note" x="{nx:.1f}" y="{ny:.1f}" font-size="18" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx:.1f}" dy="{step if k else 0}">{line}</tspan>' for k, line in enumerate(NOTE)) + "</text>")
# from the top of the note, round the east of Menorca, up to Barcelona
tx, ty = bx + 7, by + 5
sx, sy, qx, qy = nx + 112, ny - 20, bx + 66, by + 26
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 11 * np.cos(angle + np.pi + t):.1f} {ty + 11 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx:.1f} {sy:.1f} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
svg.append(f'<circle cx="{bx:.1f}" cy="{by:.1f}" r="3.5" fill="{C["ink"]}" stroke="#FFFFFF" stroke-width="1.2"/>')

# 3. Bars: people living with that many tropical nights a year, then and now
TOP = MAP_TOP + frame.ph + 24
svg.append(text(flush("P", 19, 700), TOP, "People with this many tropical nights a year", 19, 700))
top = max(b for _, b in exposed.values())
for r, (k, label) in enumerate(LEVELS):
    yy = TOP + 16 + r * 34
    svg.append(text(flush(label, 14, 700), yy + 19, label, 14, 700, C["ink"]))
    for s, (n, colour, when) in enumerate(zip(exposed[k], (C["ctx"], RAMP[4]), ("1985 to 1994", "2015 to 2024"))):
        bar = 560 * n / top
        y2 = yy + s * 14
        svg.append(f'<rect x="170" y="{y2}" width="{bar:.1f}" height="12" rx="2" fill="{colour}"/>')
        svg.append(text(170 + bar + 8, y2 + 11, f"{n:.0f}M", 13, 700 if s else 400, C["ink"] if s else C["ink2"]))
        if r == 0:
            svg.append(text(170 + bar + 52, y2 + 11, when, 13, 400, C["ink2"]))
BASE = TOP + 16 + len(LEVELS) * 34

# 4. Headline, dek, byline and footer
HEAD = [(80, f"{is_now:.0f} million people in Europe now get", 46, 800, C["ink"]), (130, "a month of nights above 20°C", 46, 800, C["ink"]),
        (170, f"A tropical night never drops below 20°C. In 1985 to 1994, {was:.0f} million people got a month", 22, 400, C["ink2"]),
        (198, "of them. Both counts use today's population, so only the nights changed.", 22, 400, C["ink2"])]
for yy, words, size, weight, colour in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour))
svg.append(byline(232, "30DayMapChallenge #28: Senses: Feeling").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", "nights that stay above 20°C, counted in 10 km cells and averaged over each decade. People: GHS-POP 2025. "
                "Europe runs to 60°E, with Cyprus and Turkey west of the Bosphorus."),
    ("Source:", "E-OBS 32.0e (Cornes et al., 2018). We acknowledge the E-OBS dataset and the data providers in the ECA&D project. "
                "GHS-POP (European Commission, JRC). Borders: Natural Earth."),
], x=round(flush("M", 17, 700), 1), y=BASE + 28, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day28_tropical_nights.png")
with open(HERE / "people_by_tropical_nights.csv", "w") as f:
    f.write("tropical_nights_a_year,million_people_1985_1994,million_people_2015_2024\n"
            + "".join(f"{label},{a:.1f},{b:.1f}\n" for (k, label), (a, b) in zip(LEVELS, exposed.values())))
