"""Day 20, Hexagons: the EU cut into H3 hexagons that each hold at most 250,000 people.

Eurostat's 2021 census grid (1 km cells) is summed into Uber's H3 hexagons. A hexagon that holds more than
250,000 residents is split into seven smaller ones, again and again, down to the fifth size.

A 1 km cell belongs to the smallest hexagon its centre falls in, and to that hexagon's parents in H3's own family
tree. The seven children of an H3 hexagon don't trace its outline exactly, so a big hexagon's count can differ a little
from the people living strictly inside the outline drawn. France's five overseas regions lie outside the grid.
"""
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import h3
import numpy as np
import pandas as pd
import rasterio
import shapely
import shapely.affinity
from pyproj import Transformer
from rasterio import features

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

GRID_URL = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V2.2.zip"  # 590 MB
GRID_TIFF = "ESTAT_OBS-VALUE-T_2021_V2.tiff"  # total residents in each 1 km cell
NUTS_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_3035_LEVL_2.geojson"
ROADS_URL = "https://naciscdn.org/naturalearth/10m/cultural/ne_10m_roads.zip"  # 9 MB
EU = "AT BE BG CY CZ DE DK EE EL ES FI FR HR HU IE IT LT LU LV MT NL PL PT RO SE SI SK".split()
LIMIT = 250_000  # a hexagon with more residents than this is split
SIZES = [3, 4, 5, 6, 7]  # H3 resolutions, from the biggest hexagons to the smallest
COLOURS = {3: "#FFFFFF", 4: "#C5D5E2", 5: "#7FA6CC", 6: "#2E5A93", 7: "#E0603F"}  # the smallest size in an accent colour
EDGE = "#DDD7CB"  # the biggest hexagons are white, so they get a light grey outline to tell one from the next
SEE_THROUGH = 0.72  # how solid the hexagons are, so borders and roads show through them


def blend(colour, under, share=SEE_THROUGH):
    """The colour a see-through hexagon ends up with over the land, for the legend and the bars."""
    mix = [round(int(colour[i:i + 2], 16) * share + int(under[i:i + 2], 16) * (1 - share)) for i in (1, 3, 5)]
    return "#" + "".join(f"{v:02X}" for v in mix)


SHOWN = {size: blend(colour, C["quiet_land"]) for size, colour in COLOURS.items()}

# 1. Data: residents per 1 km cell, kept where the cell is in an EU country
tiff = DATA_DIR / GRID_TIFF
if not tiff.exists():
    archive = _download(GRID_URL, DATA_DIR / "Eurostat_Census-GRID_2021_V2.2.zip")
    with zipfile.ZipFile(archive) as z:
        z.extract(GRID_TIFF, DATA_DIR)
    archive.unlink()
with rasterio.open(tiff) as src:
    people = src.read(1)
    people = np.where((people == src.nodata) | (people < 0), 0, people).astype(float)
    transform, shape = src.transform, src.shape
nuts = gpd.read_file(_download(NUTS_URL, DATA_DIR / "NUTS_RG_01M_2024_3035_LEVL_2.geojson"))
eu = nuts[nuts.CNTR_CODE.isin(EU)].geometry
inside = features.rasterize(eu, out_shape=shape, transform=transform).astype(bool)
# cells on the coast have their centre in the sea, so populated cells within 1.5 km of the EU count too
near = features.rasterize(eu.buffer(1500), out_shape=shape, transform=transform).astype(bool)
rows, cols = np.nonzero(inside | (near & (people > 0)))
x, y = rasterio.transform.xy(transform, rows, cols)
lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(np.array(x), np.array(y))

# 2. Hexagons: every cell goes to its smallest hexagon, then hexagons are kept at the biggest size that fits the limit
cells = pd.DataFrame({"hexagon": [h3.latlng_to_cell(a, o, SIZES[-1]) for a, o in zip(lat, lon)], "people": people[rows, cols]})
cells = cells.groupby("hexagon", as_index=False)["people"].sum()
kept, left = [], np.ones(len(cells), bool)
for size in SIZES:
    parent = cells.hexagon.map(lambda h: h3.cell_to_parent(h, size))
    total = cells[left].groupby(parent[left])["people"].sum()
    fits = total if size == SIZES[-1] else total[total <= LIMIT]
    kept.append(pd.DataFrame({"hexagon": fits.index, "size": size, "people": fits.values}))
    left &= ~parent.isin(set(fits.index))
hexes = pd.concat(kept, ignore_index=True)
assert hexes.people.max() <= LIMIT and abs(hexes.people.sum() - cells.people.sum()) < 1
hexes["km2"] = hexes.hexagon.map(lambda h: h3.cell_area(h, unit="km^2"))
by_size = hexes.groupby("size").agg(count=("hexagon", "size"), people=("people", "sum"), km2=("km2", "sum"), typical=("km2", "median"))
by_size["people_share"] = by_size.people / by_size.people.sum()
by_size["area_share"] = by_size.km2 / by_size.km2.sum()
print(by_size.round(3).to_string())
print(f"{len(hexes):,} hexagons, {hexes.people.sum() / 1e6:.1f}M residents, median {hexes.people.median():,.0f}, empty {(hexes.people == 0).sum()}")

# 3. Map: each hexagon drawn whole, coloured by its size
MAP_TOP = 244
frame = Frame(1680000, 6920000, 1330000, 5330000, 0, 1080, MAP_TOP)
view = frame.box().buffer(150000).intersection(shapely.box(2500000, 0, 9e6, 9e6))  # Madeira and the Canaries fall outside
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(frame.box())
world = world[~world.is_empty]
land = world.union_all()
EU_NAMES = ["Austria", "Belgium", "Bulgaria", "Cyprus", "Czechia", "Germany", "Denmark", "Estonia", "Greece", "Spain", "Finland", "France",
            "Croatia", "Hungary", "Ireland", "Italy", "Lithuania", "Luxembourg", "Latvia", "Malta", "Netherlands", "Poland", "Portugal",
            "Romania", "Sweden", "Slovenia", "Slovakia"]
borders = world[world.ADMIN.isin(EU_NAMES)].copy()
assert len(borders) == 27
borders["geometry"] = borders.geometry.intersection(shapely.box(2500000, 0, 9e6, 9e6))  # without Madeira and the Canaries, at the map's left edge
# Below the hexagons: land, the borders of EU countries and the major highways (Natural Earth)
roads = gpd.read_file(_download(ROADS_URL, DATA_DIR / "ne_10m_roads.zip"), bbox=(-12, 33, 36, 72))
roads = roads[roads["type"] == "Major Highway"].to_crs(3035)
roads = roads.geometry.intersection(borders.union_all()).simplify(1500)
roads = roads[~roads.is_empty]
line_path = lambda geoms: "".join("M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in (frame.xy(*c) for c in part.coords))
                                  for g in geoms for part in getattr(g, "geoms", [g]) if part.geom_type == "LineString")
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
       f'<g clip-path="url(#map)"><path d="{geom_path(land, frame)}" fill="{C["quiet_land"]}"/>',
       f'<path d="{line_path(roads)}" fill="none" stroke="#68502F" stroke-opacity=".75" stroke-width=".8" stroke-linejoin="round" stroke-linecap="round"/>',
       f'<path d="{"".join(geom_path(g, frame) for g in borders.geometry.simplify(1500))}" fill="none" stroke="{C["ink"]}" stroke-opacity=".9" '
       f'stroke-width="1.1" stroke-linejoin="round"/>',
       f'<g opacity="{SEE_THROUGH}">']  # the hexagons are painted solid and made see-through together, so overlaps don't darken
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)


def outline(hexagon):
    """The hexagon's corners on the map's projection."""
    lats, lons = zip(*h3.cell_to_boundary(hexagon))
    return shapely.Polygon(zip(*to3035.transform(lons, lats)))


hexes["shape"] = hexes.hexagon.map(outline)
shown = hexes[[view.contains(s) for s in hexes["shape"]]]
for size in SIZES:
    d = "".join("M" + " L".join(f"{px:.1f} {py:.1f}" for px, py in (frame.xy(*c) for c in s.exterior.coords[:-1])) + "Z"
                for s in shown[shown["size"] == size]["shape"])
    svg.append(f'<path d="{d}" fill="{COLOURS[size]}" stroke="{EDGE if size == 3 else "#FFFFFF" if size < 6 else COLOURS[size]}" stroke-width="{0.7 if size < 6 else 0.5}" stroke-linejoin="round"/>')
svg += ["</g>", fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic: the five sizes, drawn at the map's scale where they are big enough to see
LX, LY = 60, MAP_TOP + 142
svg.append(text(flush("T", 17, 700, LX), LY, "Typical size of the hexagon", 17, 700))
for i, size in enumerate(SIZES):
    yy = LY + 38 + i * 38
    r = max(3.2, np.sqrt(by_size.typical[size] * 1e6 * 2 / (3 * np.sqrt(3))) * frame.k)  # corner radius of a regular hexagon
    r = min(r, 15)
    corners = " ".join(f"{LX + 15.4 + r * np.cos(np.pi / 3 * k):.1f},{yy + r * np.sin(np.pi / 3 * k):.1f}" for k in range(6))
    svg.append(f'<polygon points="{corners}" fill="{SHOWN[size]}" stroke="{blend(EDGE, C["quiet_land"]) if size == 3 else "#FFFFFF"}" stroke-width=".8"/>')
    area = by_size.typical[size]
    svg.append(text(LX + 40, yy - 1, f"{area:,.0f} km²" if area >= 10 else f"{area:.0f} km²", 15, 700))
    svg.append(text(LX + 40, yy + 15, f"{by_size['count'][size]:,} hexagons", 13, 400, C["ink2"]))

# One note, over the Norwegian Sea, pointing at a big hexagon in northern Sweden
paris = hexes[hexes.hexagon == h3.latlng_to_cell(48.8566, 2.3522, SIZES[-1])].iloc[0]  # central Paris is cut down to the smallest size
lapland = hexes[hexes.hexagon == h3.latlng_to_cell(66.6, 19.8, SIZES[0])].iloc[0]  # around Jokkmokk
ratio = lapland.km2 / paris.km2
print(f"Lapland hexagon {lapland.km2:,.0f} km², {lapland.people:,.0f} people; Paris hexagon {paris.km2:.1f} km², {paris.people:,.0f} people; ratio {ratio:,.0f}")
tx, ty = frame.xy(lapland["shape"].centroid.x, lapland["shape"].centroid.y)
NOTE = [f"{round(lapland.people, -3):,.0f} people live", "in this hexagon. It", f"is {round(ratio, -2):,.0f} times the", "size of the one over", "central Paris"]
nx, ny, step = 326, MAP_TOP + 46, 26
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="21" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx}"{f' dy="{step}"' if i else ""}>{line}</tspan>' for i, line in enumerate(NOTE)) + "</text>")
# The note must stay over the sea: check each line's box against the land, in pixels
note_box = shapely.union_all([shapely.box(nx - 2, ny + step * i - 18, nx + 11.2 * len(line), ny + step * i + 5) for i, line in enumerate(NOTE)])
to_pixels = [frame.k, 0, 0, -frame.k, frame.xy(0, 0)[0], frame.xy(0, 0)[1]]
assert not note_box.intersects(shapely.affinity.affine_transform(land, to_pixels))
sx, sy, qx, qy = nx + 11.2 * len(NOTE[0]) + 8, ny - 8, (nx + 11.2 * len(NOTE[0]) + tx) / 2, ny - 34  # from the end of the first line, in a gentle curve
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 14 * np.cos(angle + np.pi + t):.1f} {ty + 14 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 4. Two bars: how the hexagons of each size share the area and the people
TOP = MAP_TOP + frame.ph + 26
svg.append(text(flush("S", 19, 700), TOP, "Share of the hexagons' area and of the people, by hexagon size", 19, 700))
for j, (label, column) in enumerate((("Area", "area_share"), ("People", "people_share"))):
    by, bx = TOP + 16 + j * 44, 140
    svg.append(text(flush(label, 17, 600), by + 21, label, 17, 600, C["ink2"]))
    for size in SIZES:
        w = 880 * by_size[column][size]
        svg.append(f'<rect x="{bx:.1f}" y="{by}" width="{max(w - 2, 0.5):.1f}" height="30" rx="2" fill="{SHOWN[size]}"/>')
        if w > 44:
            svg.append(text(bx + (w - 2) / 2, by + 21, f"{by_size[column][size]:.0%}", 16, 700, "#FFFFFF" if size >= 5 else C["ink"], "middle"))
        bx += w

# 5. Headline, dek, byline and footer
small = by_size.loc[SIZES[-2:]]
HEAD = [(84, f"The EU in {len(hexes):,} hexagons that each", 46, 800, C["ink"]), (134, f"hold at most {LIMIT:,} people", 46, 800, C["ink"]),
        (174, f"A hexagon with more than {LIMIT:,} residents is split into seven smaller ones, so small hexagons", 22, 400, C["ink2"]),
        (202, f"mark crowded places. The two smallest sizes cover {small.area_share.sum():.0%} of the area and hold {small.people_share.sum():.0%} of the people.", 22, 400, C["ink2"])]
for y, words, size, weight, colour in HEAD:  # every line starts with its first letter exactly on the left margin
    svg.append(text(flush(words, size, weight), y, words, size, weight, colour))
svg.append(byline(234, "30DayMapChallenge #20: Hexagons").replace('x="60.0"', f'x="{flush("M", 20, 600):.1f}"'))
svg += footer([
    ("Method:", f"residents in Eurostat's 1 km census grid, added up in H3 hexagons. A hexagon with more than {LIMIT:,} is split, down to the smallest size shown. Hexagons are drawn whole, so they reach over the sea and across borders."),
    ("Source:", "Eurostat, Census 2021 population grid and NUTS 2024, © European Union. H3 by Uber. Borders and roads: Natural Earth."),
    ("Comments:", f"half of the hexagons hold under {round(hexes.people.median(), -3):,.0f} people. The Canaries, Madeira and the Azores count. France's five overseas regions aren't in the grid."),
], x=round(flush("M", 17, 700), 1), y=TOP + 122, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day20_hexagons.png")
hexes.assign(lat=hexes.hexagon.map(lambda h: h3.cell_to_latlng(h)[0]).round(4), lon=hexes.hexagon.map(lambda h: h3.cell_to_latlng(h)[1]).round(4),
             people=hexes.people.round().astype(int), km2=hexes.km2.round(1)).rename(columns={"size": "h3_resolution"})[
    ["hexagon", "h3_resolution", "people", "km2", "lat", "lon"]].to_csv(HERE / "hexagons.csv", index=False)
