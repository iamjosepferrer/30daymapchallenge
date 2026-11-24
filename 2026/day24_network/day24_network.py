"""Day 24, Network: Europe drawn only by its power lines.

Every power line and cable of 110 kV or more that OpenStreetMap maps across the map, read from Overture Maps (release
2026-11-18.0) by extract_grid.py. There is no land and no border: the grid draws the continent by itself. Lines are
painted on a dark page as light, brighter and wider the higher their voltage, with a soft glow under the lines of
380 kV or more.

The five orange dots are the main lines (220 kV or more) that cross from Spain to France. The script joins the ways
into continuous routes and counts a crossing where a route runs at least 1 km on each side of the border (Natural
Earth's 1:10m borders). It finds the same five that Red Eléctrica, Spain's grid operator, lists.
"""
import base64
import io
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from PIL import Image, ImageDraw
from pyproj import Transformer
from scipy.ndimage import gaussian_filter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, flush, footer, page, save_png, text  # noqa: E402

# A night version of the house colours, for this map only
C.update(card="#111722", page="#111722", ink="#F2ECE0", ink2="#B4AEA2", muted="#B4AEA2")
NIGHT = (17, 23, 34)
HOT = "#E0603F"  # the five crossings
COUNTRIES_10M = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_admin_0_countries.zip"
# voltage classes: lowest kV, label, colour, line width in output pixels, brightness
CLASSES = [(380, "380 kV and more", (255, 214, 150), 0.9, 0.9),
           (220, "220 to 330 kV", (126, 170, 226), 0.6, 0.75),
           (110, "110 to 200 kV", (92, 120, 160), 0.35, 0.6)]
KEEP = 1000  # metres a route must run on each side of the border to count as crossing it

# 1. Data: power lines and cables, in the map's frame
raw = pd.read_parquet(HERE / "power_lines.parquet")  # from extract_grid.py: already cut to the map, km measured on the ellipsoid
lines = gpd.GeoDataFrame(raw.drop(columns="wkb"), geometry=shapely.from_wkb(raw.wkb.values), crs=4326)
MAP_TOP = 204
frame = Frame(2300000, 6900000, 1480000, 5140000, 0, 1080, MAP_TOP)
lines = lines.to_crs(3035)
lines["cls"] = np.select([lines.kv >= 380, lines.kv >= 220], [0, 1], 2)
km = lines.groupby("cls").km.sum()
print({CLASSES[i][1]: round(v) for i, v in km.items()}, round(km.sum()))

# 2. The crossings from Spain to France: join the main lines into routes, follow each route across the border
world = gpd.read_file(_download(COUNTRIES_10M, DATA_DIR / "ne_10m_admin_0_countries.zip"))[["ADMIN", "geometry"]].to_crs(3035)
spain, france = (world.geometry[world.ADMIN == name].iloc[0].buffer(0) for name in ("Spain", "France"))
crossings = []
main = lines[lines.kv >= 220]
for dc in (False, True):
    ways = main[main.dc.fillna(False) == dc]
    merged = shapely.line_merge(shapely.union_all(ways.geometry.intersection(spain.union(france).buffer(30000)).values))
    for route in getattr(merged, "geoms", [merged]):
        pts = shapely.get_coordinates(shapely.segmentize(route, 100))
        if len(pts) < 2:
            continue
        owner = np.where(shapely.contains_xy(spain, pts[:, 0], pts[:, 1]), 1, np.where(shapely.contains_xy(france, pts[:, 0], pts[:, 1]), 2, 0))
        dist = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(pts, axis=0).T))])
        cuts = np.flatnonzero(np.diff(owner) != 0) + 1
        runs = [(owner[s], dist[s], dist[e - 1], e) for s, e in zip(np.r_[0, cuts], np.r_[cuts, len(pts)])]
        solid = [r for r in runs if r[0] > 0 and r[2] - r[1] >= KEEP]
        for a, b in zip(solid, solid[1:]):
            if a[0] != b[0] and b[1] - a[2] < 3000:
                crossings.append(dict(x=pts[a[3] - 1][0], y=pts[a[3] - 1][1], dc=dc))
crossings = pd.DataFrame(crossings)
assert len(crossings) == 5 and crossings.dc.sum() == 1  # the note: Red Eléctrica's five, four AC lines and one DC

# 3. Map: each voltage class drawn 4 times too big, shrunk for smooth edges, then blurred for the glow
SCALE, SUPER = 2, 4
w, h = 1080 * SCALE, int(round(frame.ph * SCALE))
light = np.zeros((h, w, 3))
for cls in (2, 1, 0):
    _, _, colour, width, bright = CLASSES[cls]
    canvas = Image.new("L", (w * SUPER, h * SUPER), 0)
    draw = ImageDraw.Draw(canvas)
    k = frame.k * SCALE * SUPER
    for geom in lines.geometry[lines.cls == cls].simplify(100):
        for part in getattr(geom, "geoms", [geom]):
            if part.geom_type != "LineString":
                continue
            xy = shapely.get_coordinates(part)
            if len(xy) < 2:  # a very short line that the 30 m simplification collapsed
                continue
            px = (xy[:, 0] - frame.x0) * k
            py = (frame.y1 - xy[:, 1]) * k
            draw.line(list(zip(px, py)), fill=255, width=max(1, round(width * SCALE * SUPER)), joint="curve")
    layer = np.asarray(canvas.resize((w, h), Image.LANCZOS), float) / 255
    glow = gaussian_filter(layer, 5) * (1.2 if cls == 0 else 0.5)
    light += (layer * bright + glow * bright)[..., None] * np.array(colour) / 255
img = np.clip(np.array(NIGHT) / 255 + light, 0, 1)
buffer = io.BytesIO()
Image.fromarray((img * 255).astype(np.uint8), "RGB").save(buffer, "PNG", optimize=True)
uri = base64.b64encode(buffer.getvalue()).decode()
svg = [f'<image x="0" y="{MAP_TOP}" width="1080" height="{h / SCALE:.1f}" href="data:image/png;base64,{uri}"/>',
       f'<defs><linearGradient id="fade-top" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{C["card"]}"/>'
       f'<stop offset="1" stop-color="{C["card"]}" stop-opacity="0"/></linearGradient>'
       f'<linearGradient id="fade-bottom" x1="0" y1="1" x2="0" y2="0"><stop offset="0" stop-color="{C["card"]}"/>'
       f'<stop offset="1" stop-color="{C["card"]}" stop-opacity="0"/></linearGradient></defs>',
       f'<rect x="0" y="{MAP_TOP}" width="1080" height="30" fill="url(#fade-top)"/>',
       f'<rect x="0" y="{MAP_TOP + frame.ph - 40:.0f}" width="1080" height="40" fill="url(#fade-bottom)"/>']
for _, row in crossings.iterrows():
    px, py = frame.xy(row.x, row.y)
    svg.append(f'<circle cx="{px:.1f}" cy="{py:.1f}" r="3.4" fill="{HOT}" stroke="{C["card"]}" stroke-width="1"/>')

# Legend over the Atlantic, on the left margin
LX, LY = 60, MAP_TOP + 185
svg.append(text(flush("P", 17, 700, LX), LY, "Power lines and cables", 17, 700))
for i, (_, label, colour, width, bright) in enumerate(CLASSES):
    yy = LY + 28 + i * 22
    rgb = "#" + "".join(f"{round(c * bright):02X}" for c in colour)
    svg.append(f'<line x1="{LX + 1}" x2="{LX + 31}" y1="{yy - 5}" y2="{yy - 5}" stroke="{rgb}" stroke-width="{width * 1.6}" stroke-linecap="round"/>')
    svg.append(text(LX + 40, yy, label, 15, 400, C["ink2"]))

# One note, over the Bay of Biscay, pointing at the Pyrenees
NOTE = ["Only five main", "lines link Spain", "to France"]
nx, ny, step = 66, MAP_TOP + 520, 23
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="19" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx}" dy="{step if i else 0}">{line}</tspan>' for i, line in enumerate(NOTE)) + "</text>")
tx, ty = frame.xy(*Transformer.from_crs(4326, 3035, always_xy=True).transform(-1.1, 43.25))  # the western Pyrenees, near Hendaye
tx, ty = tx - 6, ty - 4
sx, sy, qx, qy = nx + 120, ny + 2 * step + 6, nx + 150, ty - 10
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 11 * np.cos(angle + np.pi + t):.1f} {ty + 11 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 4. One bar: each voltage class's share of the kilometres, largest first, with its label and length underneath
TOP = MAP_TOP + frame.ph + 44
share = (100 * km / km.sum()).round().astype(int)  # share of all the kilometres on the map
assert share.sum() == 100
svg.append(text(flush("K", 19, 700), TOP, "Kilometres of line on the map, by voltage", 19, 700))
x, width, y = round(flush("K", 19, 700), 1), 960, TOP + 16
for i in km.sort_values(ascending=False).index:  # the biggest share first
    _, label, colour, _, bright = CLASSES[i]
    rgb = "#" + "".join(f"{round(c * bright):02X}" for c in colour)
    w = width * km[i] / km.sum()
    svg.append(f'<rect x="{x:.1f}" y="{y}" width="{w - 3:.1f}" height="34" rx="2" fill="{rgb}"/>')
    ink = C["card"] if i == 0 else C["ink"]  # dark figures on the light yellow, light ones on the blues
    svg.append(text(x + 10, y + 23, f"{share[i]}%", 18, 800, ink))
    svg.append(text(x + 1, y + 56, label, 15, 600, C["ink"]))
    svg.append(text(x + 1, y + 75, f"({km[i]:,.0f} km)", 15, 400, C["ink2"]))
    x += w
BASE = y + 75

# 5. Headline, dek, byline and footer
HEAD = [(80, "Europe drawn only by its power lines", 46, 800, C["ink"]),
        (124, f"{km.sum():,.0f} km of power lines and cables of 110 kV or more, mapped in OpenStreetMap.", 22, 400, C["ink2"]),
        (152, "Land and borders aren't drawn. The brighter the line, the higher its voltage.", 22, 400, C["ink2"])]
for yy, words, size, weight, colour in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour))
svg.append(byline(186, "30DayMapChallenge #24: Network").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", "lengths follow each route on the WGS84 ellipsoid, so a line with two circuits counts once. Dots: the five lines of 220 kV or more that cross from Spain to France."),
    ("Source:", "© OpenStreetMap contributors, via Overture Maps (release 2026-11-18). Border for the crossings: Natural Earth."),
], x=round(flush("M", 17, 700), 1), y=BASE + 48, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day24_power_grid.png")
pd.DataFrame({"voltage": [c[1] for c in CLASSES], "km": km.round().astype(int).values}).to_csv(HERE / "power_lines_km_by_voltage.csv", index=False)
