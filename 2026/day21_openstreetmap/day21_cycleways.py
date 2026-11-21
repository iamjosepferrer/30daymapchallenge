"""Day 21, OpenStreetMap: every cycle path that volunteers have mapped in OpenStreetMap, and nothing else.

OpenStreetMap has two common ways to tag a path for bicycles: highway=cycleway, and a path, footway, pedestrian street
or bridleway tagged bicycle=designated. Countries lean on one or the other (the Netherlands on the first, Germany on
the second), so both count here. The paths come from Overture Maps' copy of OpenStreetMap (release 2026-11-18.0),
read with DuckDB by extract_osm.py, which sums their length in the 1 km cells of the EU's grid (EPSG:3035). Each pixel
of the map shows the length inside it, and every number on the chart counts only what the map shows.
"""
import base64
import io
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from PIL import Image
from rasterio import features
from affine import Affine

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, Frame, byline, countries, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

INK = (31, 52, 92)  # the colour of a pixel full of cycle paths
SHORT = {"United Kingdom": "UK", "Republic of Serbia": "Serbia", "Bosnia and Herzegovina": "Bosnia"}

# 1. Data: metres of cycle path in each 1 km cell, and the country each cell lies in
parts = {kind: pd.read_parquet(HERE / f"{kind}_1km.parquet") for kind in ("cycleways", "shared_paths")}  # from extract_osm.py
grid = pd.concat(parts.values()).groupby(["cx", "cy"], as_index=False).m.sum()
MAP_TOP = 250
frame = Frame(2300000, 6900000, 1480000, 5140000, 0, 1080, MAP_TOP)
inside = (grid.cx * 1000 >= frame.x0) & ((grid.cx + 1) * 1000 <= frame.x1) & (grid.cy * 1000 >= frame.y0) & ((grid.cy + 1) * 1000 <= frame.y1)
grid = grid[inside].reset_index(drop=True)  # every number on the chart counts what the map shows
world = countries()
world["geometry"] = world.geometry.buffer(0)
# Natural Earth draws Crimea with Russia. It is Ukraine's by international law, so it joins Ukraine here.
crimea = shapely.box(32.3, 44.3, 36.65, 46.3)
ru, ua = world.index[world.ADMIN == "Russia"][0], world.index[world.ADMIN == "Ukraine"][0]
world.loc[ua, "geometry"] = world.geometry[ua].union(world.geometry[ru].intersection(crimea))
world.loc[ru, "geometry"] = world.geometry[ru].difference(crimea)
world = world.to_crs(3035)
x0, y0 = grid.cx.min(), grid.cy.min()
cols, rows = grid.cx.max() - x0 + 1, grid.cy.max() - y0 + 1
cell = Affine(1000, 0, x0 * 1000, 0, -1000, (y0 + rows) * 1000)
# Each cell goes to the country that holds its centre. A cell on the coast that Natural Earth draws as sea goes to
# the country within 1.5 km, so paths along a beach or a harbour still count.
shapes = lambda geoms: [(g, i + 1) for i, g in enumerate(geoms)]
owner = features.rasterize(shapes(world.geometry), out_shape=(rows, cols), transform=cell, dtype=np.int32)
coast = features.rasterize(shapes(world.geometry.buffer(1500)), out_shape=(rows, cols), transform=cell, dtype=np.int32)
owner = np.where(owner > 0, owner, coast)[y0 + rows - 1 - grid.cy, grid.cx - x0]
grid["country"] = np.where(owner > 0, world.ADMIN.values[np.maximum(owner - 1, 0)], None)
km = grid.groupby("country").m.sum().div(1000).sort_values(ascending=False)
# Area of each country inside the map, so France counts without French Guiana and the rest of its overseas regions
area = world.set_index("ADMIN").geometry.intersection(frame.box()).area / 1e6
per_area = (km / area * 100).dropna().sort_values(ascending=False)  # km of cycle path per 100 km²
per_area = per_area[area[per_area.index] > 2000]  # leave out the microstates, where one path moves the figure a lot
total = grid.m.sum() / 1000
shared = parts["shared_paths"].m.sum() / 1000
print(f"{total:,.0f} km; by country {km.head(8).round().to_dict()}; per 100 km² {per_area.head(8).round(1).to_dict()}")

# 2. Map: each pixel darkens with the length of cycle path inside it
SCALE = 2
w, h = 1080 * SCALE, int(round(frame.ph * SCALE))
px = (((grid.cx + 0.5) * 1000 - frame.x0) * frame.k * SCALE).astype(int)
py = ((frame.y1 - (grid.cy + 0.5) * 1000) * frame.k * SCALE).astype(int)
keep = (px >= 0) & (py >= 0) & (px < w) & (py < h)
length = np.zeros((h, w))
np.add.at(length, (py[keep], px[keep]), grid.m.values[keep] / 1000)
full = (1 / (frame.k * SCALE) / 1000) * 1.2  # km of path that make a pixel fully dark: a little more than one line across it
alpha = np.clip(np.sqrt(length / full), 0, 1)
img = np.zeros((h, w, 4), np.uint8)
img[..., :3] = INK
img[..., 3] = (alpha * 255).astype(np.uint8)
buffer = io.BytesIO()
Image.fromarray(img, "RGBA").save(buffer, "PNG", optimize=True)
uri = base64.b64encode(buffer.getvalue()).decode()
land = world.geometry.intersection(frame.box()).union_all()
borders = shapely.union_all([g.boundary for g in world.geometry.intersection(frame.box().buffer(1)) if not g.is_empty]).intersection(frame.box())
lines = [g for g in getattr(borders, "geoms", [borders]) if g.geom_type == "LineString"]
border_d = "".join("M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in (frame.xy(*c) for c in g.coords)) for g in lines)
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(land, frame)}" fill="{C["quiet_land"]}"/>',
       f'<path d="{border_d}" fill="none" stroke="{C["ctx"]}" stroke-width=".6" stroke-linejoin="round"/>',
       f'<image x="0" y="{MAP_TOP}" width="1080" height="{h / SCALE:.1f}" href="data:image/png;base64,{uri}"/>',
       fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
       f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# A small key in the Bay of Biscay: the darker the pixel, the more path inside it
LX, LY = 60, MAP_TOP + 512
for i, words in enumerate(("Darker means more", "cycle path in that spot")):
    svg.append(text(flush(words, 15, 700, LX), LY + i * 18, words, 15, 700))
for i, share in enumerate((0.25, 0.5, 0.75, 1.0)):
    svg.append(f'<rect x="{LX + 1 + i * 22}" y="{LY + 30}" width="18" height="14" rx="2" fill="{C["quiet_land"]}"/>')
    svg.append(f'<rect x="{LX + 1 + i * 22}" y="{LY + 30}" width="18" height="14" rx="2" fill="rgb{INK}" fill-opacity="{share}"/>')

# One note, over the Atlantic, pointing at the Netherlands
NOTE = ["So many paths that", "the country turns", "solid"]
nx, ny, step = 66, MAP_TOP + 150, 24
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="20" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx}" dy="{step if i else 0}">{line}</tspan>' for i, line in enumerate(NOTE)) + "</text>")
from pyproj import Transformer
tx, ty = frame.xy(*Transformer.from_crs(4326, 3035, always_xy=True).transform(4.2, 52.9))  # just off the Dutch coast
tx, ty = tx - 4, ty - 6
sx, sy, qx, qy = nx + 232, ny - 7, tx - 40, ny - 10  # from just after the first line
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 12 * np.cos(angle + np.pi + t):.1f} {ty + 12 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 3. Bars: km of cycle path per 100 km² of land, by country
TOP = MAP_TOP + frame.ph + 28
top = per_area.head(6)
svg.append(text(flush("K", 19, 700), TOP, "Km of cycle path per 100 km² of each country", 19, 700))
for i, (name, v) in enumerate(top.items()):
    col, row = i // 3, i % 3
    bx, yy = 60 + col * 490, TOP + 16 + row * 22
    label = SHORT.get(name, name)
    svg.append(text(flush(label, 14, 600, bx), yy + 12, label, 14, 600, C["ink"]))
    width = 300 * v / top.max()
    svg.append(f'<rect x="{bx + 110}" y="{yy}" width="{width:.1f}" height="15" rx="2" fill="rgb{INK}"/>')
    svg.append(text(bx + 110 + width + 6, yy + 12, f"{v:.0f}", 13, 700, C["ink"]))
BASE = TOP + 16 + 3 * 22

# 4. Headline, dek, byline and footer
de, nl = km["Germany"], per_area["Netherlands"] / 100  # km of path per km² of land
assert km.index[0] == "Germany" and per_area.index[0] == "Netherlands" and 0.95 < nl < 1.05  # the dek
HEAD = [(80, "Every cycle path that volunteers", 46, 800, C["ink"]), (130, "have mapped in OpenStreetMap", 46, 800, C["ink"]),
        (170, f"{total:,.0f} km of paths for bicycles. Germany has the most, {de:,.0f} km, and the Netherlands", 22, 400, C["ink2"]),
        (198, "has about 1 km of path for every km² of the country.", 22, 400, C["ink2"])]
for yy, words, size, weight, colour in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour))
svg.append(byline(232, "30DayMapChallenge #21: OpenStreetMap").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", "ways tagged highway=cycleway, plus paths, footways, pedestrian streets and bridleways tagged bicycle=designated, summed in 1 km cells. "
                "Lanes recorded only as a tag on a road aren't counted. The bars leave out countries under 2,000 km²."),
    ("Source:", "© OpenStreetMap contributors, via Overture Maps (release 2026-11-18). Borders: Natural Earth."),
    ("Comments:", "only paths that volunteers have mapped are counted, so it misses any that nobody has added yet."),
], x=round(flush("M", 17, 700), 1), y=BASE + 34, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day21_cycle_paths.png")
table = pd.DataFrame({"km": km, "area_on_map_km2": area.reindex(km.index)})
table["km_per_100_km2"] = table.km / table.area_on_map_km2 * 100
table.round(1).rename_axis("country").to_csv(HERE / "cycle_paths_by_country.csv")
