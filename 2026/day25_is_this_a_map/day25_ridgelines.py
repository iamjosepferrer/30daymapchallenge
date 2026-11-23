"""Day 25, Is this a map?: where Europe's people live, drawn only as ridgelines.

GHS-POP 2025 (JRC) estimates residents in 30-arcsecond cells, about 1 km. Here it is moved onto the EU's 1 km grid
(EPSG:3035, adding up the people) and the land is cut into strips 35 km tall, running west to east. Each strip becomes
one line: flat where nobody lives, rising with the number of people in each 1 km column of the strip. Lines further
south are drawn in front and hide what is behind them. There is no coastline and no border: the shape of the land
comes from the lines alone.

Europe is the same as on Days 1 and 6: west of 60°E, with Cyprus and Turkey west of the Bosphorus. Land outside it,
such as Asian Turkey and North Africa, has no lines.
"""
import io
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import rasterio
import rasterio.features
import rasterio.warp
import requests
from scipy.ndimage import gaussian_filter1d
from pyproj import Transformer
from shapely.geometry import Point, box

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, _download, byline, flush, footer, page, save_png, text  # noqa: E402

COUNTRIES_10M = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_0_countries.geojson"
POP_NAME = "GHS_POP_E2025_GLOBE_R2023A_4326_30ss_V1_0"  # the same file as Days 1 and 6
POP_URL = ("https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
           f"GHS_POP_E2025_GLOBE_R2023A_4326_30ss/V1-0/{POP_NAME}.zip")
# Geographic Europe, as on Days 1 and 6: west of 60°E, plus Cyprus and Turkey west of the Bosphorus
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
STRIP = 35  # km of land in each line, north to south
X0, X1 = 2_470_000, 7_300_000  # the map's extent in EPSG:3035, west to east, as on Day 6
MAP_TOP, MAP_H = 215, 1040
Y0 = 1_250_000
Y1 = Y0 + MAP_H / 1080 * (X1 - X0)
TALLEST = 230  # pixels for the highest point of all

# 1. Data: Europe's outline, and GHS-POP inside it, moved onto the 1 km grid of the map
world = gpd.read_file(_download(COUNTRIES_10M, DATA_DIR / "ne_10m_admin_0_countries.geojson"))[["ADMIN", "geometry"]]
world["geometry"] = world.geometry.buffer(0)
by_name = lambda *names: world[world.ADMIN.isin(names)].geometry.union_all()
thrace = next(part for part in by_name("Turkey").geoms if part.contains(Point(27.5, 41.5)))  # Turkey west of the Bosphorus
europe = by_name(*SCOPE).union(thrace).intersection(box(-32, 27, 60, 82))  # west of 60°E
raster = DATA_DIR / f"{POP_NAME}.tif"
if not raster.exists():
    print("Downloading GHS-POP (461 MB)")
    response = requests.get(POP_URL, timeout=1800)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extract(raster.name, DATA_DIR)
with rasterio.open(raster) as source:
    window = source.window(-32, 27, 60, 82).round_offsets().round_lengths()
    people = source.read(1, window=window).astype(np.float64)
    transform = source.window_transform(window)
people[people < 0] = 0
# Like Days 1 and 6, every cell touching Europe's outline counts, so coastal cells are not cut off
inside = rasterio.features.rasterize([(europe, 1)], out_shape=people.shape, transform=transform, fill=0, dtype="uint8", all_touched=True)
people[inside == 0] = 0
print(f"{people.sum() / 1e6:.1f}M people in Europe")
cols, rows = round((X1 - X0) / 1000), round((Y1 - Y0) / 1000) // STRIP * STRIP
grid = np.zeros((rows, cols))
grid_transform = rasterio.transform.from_origin(X0, Y0 + rows * 1000, 1000, 1000)
rasterio.warp.reproject(people, grid, src_transform=transform, src_crs=4326, dst_transform=grid_transform, dst_crs=3035,
                        resampling=rasterio.warp.Resampling.sum)
land = rasterio.features.rasterize([(gpd.GeoSeries([europe], crs=4326).to_crs(3035).iloc[0], 1)], out_shape=grid.shape,
                                   transform=grid_transform, fill=0, dtype="uint8", all_touched=True) == 1
total = grid.sum()
print(f"{total / 1e6:.1f}M people on the map")

# 2. Ridges: one line per 35 km strip, the people in each 1 km column, smoothed a little from west to east
k = 1080 / (X1 - X0) * 1000  # pixels per km
n = rows // STRIP
strips = gaussian_filter1d(grid.reshape(n, STRIP, -1).sum(axis=1), 2, axis=1)
covered = land.reshape(n, STRIP, -1).any(axis=1)
scale = TALLEST / strips.max()
step = MAP_H / n
row, col = np.unravel_index(strips.argmax(), strips.shape)
peak_x, peak_y = X0 + (col + 0.5) * 1000, Y0 + rows * 1000 - (row + 0.5) * STRIP * 1000
print(f"highest peak at {peak_x:,.0f} E, {peak_y:,.0f} N")
moscow_x, moscow_y = Transformer.from_crs(4326, 3035, always_xy=True).transform(37.62, 55.75)
assert abs(peak_x - moscow_x) < 20_000 and abs(peak_y - moscow_y) < STRIP * 1000  # Moscow, which the note names
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP - 140}" width="1080" height="{MAP_H + 140}"/></clipPath><g clip-path="url(#map)">']
for i in range(n):  # north first, so each line to the south is drawn in front
    base = MAP_TOP + (i + 1) * step
    heights = strips[i] * scale
    on = np.flatnonzero(covered[i])
    for run in np.split(on, np.flatnonzero(np.diff(on) > 1) + 1) if on.size else []:  # stretches of land, split by the sea
        if run.size < 3:
            continue
        xs = (np.r_[run[0], run, run[-1]] + 0.5) * k
        ys = base - np.r_[0, heights[run], 0]
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
        svg.append(f'<polygon points="{pts}" fill="{C["card"]}" stroke="{C["ink"]}" stroke-width=".9" stroke-linejoin="round"/>')
svg.append("</g>")

# Legend in the empty north-west: a sample line, flat where nobody lives, with a peak of 100,000 people
LX, base = 60, MAP_TOP + 108
svg.append(text(flush("H", 17, 700, LX), MAP_TOP + 18, "How to read a line", 17, 700))
sample_x = np.linspace(0, 170, 86)
sample_y = 1e5 * scale * np.exp(-((sample_x - 85) / 7) ** 2)  # a peak as tall as 100,000 people
pts = " ".join(f"{LX + 1 + x:.1f},{base - y:.1f}" for x, y in zip(sample_x, sample_y))
svg.append(f'<polyline points="{pts}" fill="none" stroke="{C["ink"]}" stroke-width="1.2" stroke-linejoin="round"/>')
svg.append(text(LX + 1, base + 20, "Flat: nobody lives there", 14, 400, C["ink2"]))
svg.append(text(LX + 103, base - 1e5 * scale + 12, "Peak: 100,000 people", 14, 600, C["ink2"]))
svg.append(text(LX + 103, base - 1e5 * scale + 30, "in a column 1 km wide", 14, 400, C["ink2"]))

# One note, over the empty Barents Sea, pointing at the top of the tallest peak
px, py = (col + 0.5) * k, MAP_TOP + (row + 1) * step - TALLEST
NOTE = ["Moscow, the", "tallest peak"]
nx, ny, step_ = px - 235, py - 150, 23
svg.append(f'<text class="note" x="{nx:.1f}" y="{ny:.1f}" font-size="20" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx:.1f}" dy="{step_ if i else 0}">{line}</tspan>' for i, line in enumerate(NOTE)) + "</text>")
tx, ty = px - 6, py + 2
sx, sy, qx, qy = nx + 132, ny + step_ - 6, (nx + 132 + tx) / 2, ty - 10
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 11 * np.cos(angle + np.pi + t):.1f} {ty + 11 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx:.1f} {sy:.1f} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 3. Headline, dek, byline and footer
HEAD = [(76, f"Europe's population in {n} lines", 44, 800, C["ink"]),
        (114, f"{total / 1e6:.0f} million people in 2025. Each line is a {STRIP} km strip of land, running west to east,", 21, 400, C["ink2"]),
        (141, "and it rises with the people who live there. Coastlines and borders aren't drawn.", 21, 400, C["ink2"])]
for yy, words, size, weight, colour in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour))
svg.append(byline(172, "30DayMapChallenge #25: Is this a map?").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", f"people in 1 km squares, added up in strips {STRIP} km tall and drawn to scale. Europe runs to 60°E, with Cyprus and Turkey "
                "west of the Bosphorus. Islands off the map, such as the Canaries, aren't counted."),
    ("Source:", "GHS-POP (European Commission, JRC), a modelled estimate for 2025. Europe's outline: Natural Earth."),
], x=round(flush("M", 17, 700), 1), y=MAP_TOP + MAP_H + 30, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day25_ridgelines.png")
