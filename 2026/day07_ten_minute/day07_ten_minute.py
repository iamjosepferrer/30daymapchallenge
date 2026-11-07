"""Day 7, 10 minute map: a quick sketch of the EU's farthest point from the sea, about 660 km inland, in Slovakia."""
import base64
import io
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
import requests
from PIL import Image
from pyproj import CRS, Transformer
from rasterio.features import rasterize
from scipy import ndimage
from shapely.geometry import Point, box
from shapely.ops import nearest_points

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
GRID_URL = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V3.zip"
GRID_TIFF = "ESTAT_Census_2021_V3.tiff"
EU = ["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland", "France",
      "Germany", "Greece", "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands",
      "Poland", "Portugal", "Romania", "Slovakia", "Slovenia", "Spain", "Sweden"]
# Distance bands, in km, from the coast inland, light to dark
BANDS = [(0, 50, "#D5DFEA", "Under 50 km"), (50, 200, "#A9BDD5", "50 to 200 km"),
         (200, 400, "#7193BC", "200 to 400 km"), (400, 10000, C["blue"], "Over 400 km")]
EUROPE = box(-40, 20, 60, 80)


def census_grid():
    """Eurostat's Census 2021 population grid, the same file as Days 4 and 5."""
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
        return np.where(people > 0, people, 0), source.transform, source.shape


# 1. Data: distance from every 1 km square to the nearest sea, on the census grid
people, transform, shape = census_grid()
ocean = gpd.read_file(_download(NE + "ne_10m_ocean.geojson", DATA_DIR / "ne_10m_ocean.geojson")).clip(EUROPE)
world = gpd.read_file(_download(NE + "ne_10m_admin_0_countries.geojson", DATA_DIR / "ne_10m_admin_0_countries.geojson"))
world = world.clip(EUROPE)
sea = rasterize(((g, 1) for g in ocean.to_crs(3035).geometry), out_shape=shape, transform=transform, all_touched=True, dtype="uint8")
eu_land = rasterize(((g, 1) for g in world[world.ADMIN.isin(EU)].to_crs(3035).geometry), out_shape=shape,
                    transform=transform, all_touched=True, dtype="uint8").astype(bool) & (sea == 0)
km = ndimage.distance_transform_edt(sea == 0)  # each cell is 1 km

# The farthest square, then its true distance to each nearby sea, measured from that point
row, col = np.unravel_index(np.argmax(np.where(eu_land, km, -1)), shape)
far_x, far_y = transform.c + (col + 0.5) * 1000, transform.f - (row + 0.5) * 1000
far_lon, far_lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(far_x, far_y)
local = CRS.from_proj4(f"+proj=aeqd +lat_0={far_lat} +lon_0={far_lon} +datum=WGS84 +units=m")
SEAS = {"Adriatic": (12, 40, 20, 46), "Black Sea": (27, 40, 42, 47.5), "Baltic": (10, 53, 30, 66)}
to_3035 = Transformer.from_crs(local, 3035, always_xy=True)
nearest = {}
for name, bounds in SEAS.items():
    water = ocean.clip(box(*bounds)).to_crs(local).geometry.union_all()
    point = nearest_points(Point(0, 0), water)[1]
    nearest[name] = (water.distance(Point(0, 0)) / 1000, to_3035.transform(point.x, point.y))
farthest_km = min(d for d, _ in nearest.values())
print(f"Farthest point {far_lat:.3f} N {far_lon:.3f} E: " + ", ".join(f"{n} {d:.0f} km" for n, (d, _) in nearest.items()))

# 2. A quick sketch: simplified, wobbly outlines and hand-drawn lines, with the exact distances
MAP_TOP, MAP_BOTTOM = 300, 1250
frame = Frame(4250000, 6400000, 0, 0, 0, 1080, MAP_TOP)
height_m = (MAP_BOTTOM - MAP_TOP) / frame.k
frame = Frame(4250000, 6400000, 3740000 - height_m, 3740000, 0, 1080, MAP_TOP)
rng = np.random.default_rng(7)


def wobbly(geom, tolerance=7000, wobble=1.4):
    """Simplify a shape, then let the line drift gently from side to side, so it looks drawn by hand."""
    parts = []
    geom = geom.simplify(tolerance).segmentize(6000)
    for polygon in getattr(geom, "geoms", [geom]):
        if polygon.area < 4e8:  # skip small islands, as a quick sketch would
            continue
        xy = np.array([frame.xy(x, y) for x, y in polygon.exterior.coords])
        along = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
        drift = np.zeros_like(xy)
        for axis in (0, 1):
            for wavelength in (90, 31):
                drift[:, axis] += wobble * np.sin(along / wavelength * 2 * np.pi + rng.uniform(0, 2 * np.pi))
        xy = xy + drift
        parts.append("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in xy) + "Z")
    return "".join(parts)


view = frame.box().buffer(200000)
land = world.to_crs(3035).geometry.buffer(0).intersection(view).union_all()
slovakia = world[world.ADMIN == "Slovakia"].to_crs(3035).geometry.iloc[0]
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{wobbly(land, tolerance=12000, wobble=0)}" fill="{C["page"]}"/>',
       f'<path d="{wobbly(land, tolerance=12000)}" fill="none" stroke="{C["ink"]}" stroke-width="1.6" stroke-linejoin="round"/>',
       f'<path d="{wobbly(slovakia, tolerance=6000, wobble=2)}" fill="{C["blue"]}" fill-opacity=".25" stroke="{C["ink"]}" stroke-width="1.6" stroke-linejoin="round"/>',
       "</g>"]
HALO = f' stroke="{C["page"]}" stroke-width="6" stroke-linejoin="round" paint-order="stroke"'


def scrawl(x, y, words, size=22, tilt=0.0, colour=C["ink"], anchor="start", weight=500):
    """Handwritten text, slightly crooked, as if written in a hurry."""
    return (f'<text class="note" x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{colour}" '
            f'text-anchor="{anchor}" transform="rotate({tilt} {x:.1f} {y:.1f})"{HALO}>{words}</text>')


# Three quick straight lines from the farthest point to the nearest Adriatic, Black Sea and Baltic
fx, fy = frame.xy(far_x, far_y)
LABEL_AT = {"Adriatic": (-12, 34, "end", -4), "Black Sea": (10, 36, "start", 3), "Baltic": (14, -10, "start", -3)}
for name, (dist, (sx, sy)) in nearest.items():
    px, py = frame.xy(sx, sy)
    angle = np.arctan2(py - fy, px - fx)
    ex, ey = px + 6 * np.cos(angle), py + 6 * np.sin(angle)  # a little overshoot, as in a rush
    svg.append(f'<path d="M{fx:.1f} {fy:.1f} L{ex:.1f} {ey:.1f}" stroke="{C["blue"]}" stroke-width="2.8" stroke-linecap="round"/>')
    for side in (-1, 1):
        hx, hy = px - 16 * np.cos(angle + side * 0.5), py - 16 * np.sin(angle + side * 0.5)
        svg.append(f'<path d="M{hx:.1f} {hy:.1f} L{ex:.1f} {ey:.1f}" stroke="{C["blue"]}" stroke-width="2.8" stroke-linecap="round"/>')
    dx, dy, anchor, tilt = LABEL_AT[name]
    svg.append(scrawl(px + dx, py + dy, f"{dist:.0f} km", 28, tilt, C["blue"], anchor, 700))
    svg.append(scrawl(px + dx, py + dy + 27, f"to the {name}", 20, tilt, C["ink"], anchor))
# The farthest point: an X with a quick circle round it
for (ax, ay), (bx, by) in (((-9, -9), (9, 9)), ((-9, 9), (9, -9))):
    svg.append(f'<path d="M{fx + ax:.1f} {fy + ay:.1f} L{fx + bx:.1f} {fy + by:.1f}" stroke="{C["ink"]}" stroke-width="3" stroke-linecap="round"/>')
svg.append(f'<path d="M{fx + 20:.1f} {fy - 4:.1f} C {fx + 22:.1f} {fy - 24:.1f}, {fx - 20:.1f} {fy - 26:.1f}, {fx - 22:.1f} {fy:.1f} '
           f'S {fx + 14:.1f} {fy + 26:.1f}, {fx + 24:.1f} {fy - 10:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(scrawl(fx + 30, fy - 24, "here! near Trebišov", 21, -2))

# 3. Headline, dek, byline and footer
svg.append(text(60, 90, "The EU's farthest point from the sea", 50, 800))
svg.append(text(60, 146, f"is {round(farthest_km, -1):.0f} km inland, in Slovakia", 50, 800))
svg.append(text(60, 190, "Drawn in ten minutes. From one spot in eastern Slovakia, the Adriatic, the Baltic and", 25, 400, C["ink2"]))
svg.append(text(60, 220, "the Black Sea are all about the same distance away.", 25, 400, C["ink2"]))
svg.append(byline(252))
FOOTER = [
    ("Method:", "straight-line distance from every 1 km square in the EU to the nearest sea. Lakes don't count."),
    ("Source:", "seas and land: Natural Earth. Grid: Eurostat, Census 2021, © European Union."),
    ("Comments:", "a rough sketch. The distances use the full coastline."),
]
svg += footer(FOOTER, x=60, y=1282, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day07_ten_minute.png")
rows = [{"measure": "Farthest point, latitude", "value": round(far_lat, 4)}, {"measure": "Farthest point, longitude", "value": round(far_lon, 4)}]
rows += [{"measure": f"Farthest point to the {n} (km)", "value": round(d, 1)} for n, (d, _) in nearest.items()]
import pandas as pd  # noqa: E402
pd.DataFrame(rows).to_csv(HERE / "results.csv", index=False)
