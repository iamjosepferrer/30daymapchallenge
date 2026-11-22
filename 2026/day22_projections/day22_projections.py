"""Day 22, Projections: how much bigger flat web maps draw each country than it really is.

Flat web maps use Web Mercator (EPSG:3857). It keeps local shapes, so streets meet at the right angles, but it scales
everything by 1 / cos(latitude): sizes are true at the equator, and areas grow 1.7 times at 40°N, 4 times at 60°N and
8.5 times at 70°N. Here every country is drawn twice: its outline as Web Mercator draws it, and a solid shape at its
true size. The solid shape is the country in an equal-area projection centred on it (Lambert azimuthal equal-area),
at the scale Web Mercator has at the equator, placed at the centre of the outline.

True areas are measured on the WGS84 ellipsoid, and drawn areas in Web Mercator. Borders come from Natural Earth.
Only countries whose main landmass fits on the map get a solid shape, and parts outside the map (Svalbard, the
Canary Islands, the Azores) are left out of every number.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Geod, Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, Frame, byline, countries, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

ON, PAIR = "#2E5A93", "#E0603F"  # true size, and the two countries of the headline
WEST, EAST, SOUTH, NORTH = -27, 59.5, 34.5, 71.5  # the map, in degrees
GEOD = Geod(ellps="WGS84")
to3857 = Transformer.from_crs(4326, 3857, always_xy=True)
SHORT = {"United Kingdom": "UK", "Republic of Serbia": "Serbia", "Bosnia and Herzegovina": "Bosnia"}


def project(geom, transformer):
    return shapely.transform(geom, lambda c: np.column_stack(transformer.transform(c[:, 0], c[:, 1])))


# 1. Data: each country, cut to the map
world = countries()
world["geometry"] = world.geometry.buffer(0)
# Natural Earth draws Crimea with Russia. It is Ukraine's by international law, so it joins Ukraine here.
crimea = shapely.box(32.3, 44.3, 36.65, 46.3)
ru, ua = world.index[world.ADMIN == "Russia"][0], world.index[world.ADMIN == "Ukraine"][0]
world.loc[ua, "geometry"] = world.geometry[ua].union(world.geometry[ru].intersection(crimea))
world.loc[ru, "geometry"] = world.geometry[ru].difference(crimea)
# Natural Earth splits off Åland and northern Cyprus. Both belong to the country they sit in.
world["ADMIN"] = world.ADMIN.replace({"Aland": "Finland", "Northern Cyprus": "Cyprus"})
world = world.dissolve("ADMIN").reset_index()
area = shapely.box(WEST, SOUTH, EAST, NORTH)
world = world[world.intersects(area)].reset_index(drop=True)


def true_km2(geom):
    return abs(GEOD.geometry_area_perimeter(geom)[0]) / 1e6


rows = []
for name, geom in zip(world.ADMIN, world.geometry):
    parts = list(getattr(geom, "geoms", [geom]))
    main = max(parts, key=true_km2)
    shown = geom.intersection(area)
    rows.append(dict(country=name, fits=main.within(area), geom=shown, true_km2=true_km2(shown),
                     drawn_km2=project(shown, to3857).area / 1e6))
table = pd.DataFrame(rows)
table["times"] = table.drawn_km2 / table.true_km2
solid = table[table.fits].set_index("country")
print(solid.sort_values("true_km2", ascending=False)[["true_km2", "drawn_km2", "times"]].head(12).round(2))

# The headline and the note
fi, es, ice, pt = (solid.loc[c] for c in ("Finland", "Spain", "Iceland", "Portugal"))
looks, really = fi.drawn_km2 / es.drawn_km2, fi.true_km2 / es.true_km2
assert 1.95 < looks < 2.15 and 0.63 < really < 0.70, (looks, really)  # "twice as big", "a third smaller"
ice_looks, ice_really = ice.drawn_km2 / pt.drawn_km2, ice.true_km2 / pt.true_km2
assert 3.6 < ice_looks < 4.0 and 1.1 < ice_really < 1.2, (ice_looks, ice_really)  # the note

# 2. Map: every country as Web Mercator draws it, and the solid ones at their true size
MAP_TOP = 250
(x0, x1), (y0, y1) = to3857.transform([WEST, EAST], [SOUTH, NORTH])
frame = Frame(x0, x1, y0, y1, 0, 1080, MAP_TOP)
drawn = {name: project(geom, to3857) for name, geom in zip(table.country, table.geom)}
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">']
for name, geom in drawn.items():
    svg.append(f'<path d="{geom_path(geom, frame)}" fill="{C["quiet_land"]}" stroke="{C["ctx"]}" stroke-width=".7" stroke-linejoin="round"/>')
centres = {}
for name, row in solid.iterrows():
    centre = drawn[name].centroid
    lon, lat = row["geom"].centroid.x, row["geom"].centroid.y
    laea = Transformer.from_crs(4326, f"+proj=laea +lat_0={lat} +lon_0={lon} +ellps=WGS84", always_xy=True)
    true = shapely.affinity.translate(project(row["geom"], laea), centre.x, centre.y)  # metres, as at the equator
    centres[name] = true
    colour = PAIR if name in ("Finland", "Spain") else ON
    svg.append(f'<path d="{geom_path(true, frame)}" fill="{colour}" fill-opacity=".9" stroke="#FFFFFF" stroke-width=".6" stroke-linejoin="round"/>')

# Parallels, each with how much Web Mercator blows up areas there
for lat in (40, 50, 60, 70):
    _, py = frame.xy(0, to3857.transform(0, lat)[1])
    svg.append(f'<line x1="0" x2="1080" y1="{py:.1f}" y2="{py:.1f}" stroke="{C["ink2"]}" stroke-width=".8" stroke-dasharray="3 4" opacity=".55"/>')
    times = 1 / np.cos(np.radians(lat)) ** 2
    label = f"{lat}°N: drawn {times:.1f}× too big".replace(".0×", "×")
    svg.append(text(flush(label, 14, 600), py - 6, label, 14, 600, C["ink2"], halo=C["card"]))
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Labels for the headline pair
for name, dx, dy in (("Finland", 0, 18), ("Spain", 0, 0)):
    c = centres[name].centroid
    px, py = frame.xy(c.x, c.y)
    svg.append(text(px + dx, py + dy + 5, name, 15, 700, "#FFFFFF", "middle"))

# Legend over the Atlantic, on the left margin
LX, LY = 60, MAP_TOP + 410
svg.append(text(flush("E", 17, 700, LX), LY, "Each country twice", 17, 700))
for i, (fill, stroke, label) in enumerate(((C["quiet_land"], C["ctx"], "On a flat web map"), (ON, "#FFFFFF", "Its true size"))):
    yy = LY + 30 + i * 24
    svg.append(f'<rect x="{LX + 1}" y="{yy - 12}" width="16" height="14" rx="2" fill="{fill}" stroke="{stroke}"/>')
    svg.append(text(LX + 26, yy, label, 15, 400, C["ink2"]))

# One note, over the Norwegian Sea, pointing at Iceland
NOTE = ["Iceland looks almost", "4 times as big as", "Portugal, but they're", "about the same size"]  # 3.8 times, and 15% bigger
print(NOTE)
nx, ny, step = 262, MAP_TOP + 138, 23
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="19" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx}" dy="{step if i else 0}">{line}</tspan>' for i, line in enumerate(NOTE)) + "</text>")

tx, ty = frame.xy(*to3857.transform(-13.2, 65.6))  # Iceland's east coast
tx, ty = tx + 6, ty - 4
sx, sy, qx, qy = nx - 10, ny - 6, tx + 40, ny - 4
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 12 * np.cos(angle + np.pi + t):.1f} {ty + 12 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 3. Bars: true size and drawn size of the biggest countries that fit
TOP = MAP_TOP + frame.ph + 24
top = solid.sort_values("true_km2", ascending=False).head(8)
svg.append(text(flush("T", 19, 700), TOP, "True size (solid) and size on a flat web map (outline)", 19, 700))
scale = 300 / top.drawn_km2.max()
for i, (name, row) in enumerate(top.iterrows()):
    col, row_i = i // 4, i % 4
    bx, yy = 60 + col * 490, TOP + 16 + row_i * 22
    colour = PAIR if name in ("Finland", "Spain") else ON
    label = SHORT.get(name, name)
    svg.append(text(flush(label, 14, 600, bx), yy + 12, label, 14, 600, C["ink"]))
    svg.append(f'<rect x="{bx + 110}" y="{yy + .5}" width="{row.drawn_km2 * scale:.1f}" height="14" rx="2" fill="none" stroke="{colour}" stroke-width="1.2"/>')
    svg.append(f'<rect x="{bx + 110}" y="{yy}" width="{row.true_km2 * scale:.1f}" height="15" rx="2" fill="{colour}"/>')
    svg.append(text(bx + 110 + row.drawn_km2 * scale + 6, yy + 12, f"{row.times:.1f}×", 13, 700, C["ink"]))
BASE = TOP + 16 + 4 * 22

# 4. Headline, dek, byline and footer
HEAD = [(80, "Finland looks twice as big as Spain", 46, 800, C["ink"]), (130, "on a flat web map", 46, 800, C["ink"]),
        (170, "Flat web maps enlarge areas more the farther they are from the equator. They draw", 22, 400, C["ink2"]),
        (198, f"Finland {fi.times:.1f} times too big and Spain {es.times:.1f} times. Finland is a third smaller than Spain.", 22, 400, C["ink2"])]
for yy, words, size, weight, colour in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour))
svg.append(byline(232, "30DayMapChallenge #22: Projections").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", "true areas are measured on the WGS84 ellipsoid, and drawn areas in Web Mercator (EPSG:3857), the projection of most web map "
                "tiles. Each solid shape is the country in an equal-area projection, at Web Mercator's scale at the equator."),
    ("Source:", "borders from Natural Earth. Parts outside the map, such as Svalbard and the Canary Islands, are left out. "
                "Countries cut by its edge, such as Russia, get no solid shape."),
], x=round(flush("M", 17, 700), 1), y=BASE + 27, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day22_web_mercator.png")
out = table[table.fits].drop(columns=["geom", "fits"]).sort_values("true_km2", ascending=False)
out.round({"true_km2": 0, "drawn_km2": 0, "times": 2}).to_csv(HERE / "true_vs_drawn.csv", index=False)
