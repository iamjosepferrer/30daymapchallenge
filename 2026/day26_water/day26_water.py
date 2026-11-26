"""Day 26, Water: how often it rains in Europe, and why Rome gets more rain than London.

E-OBS (version 32.0e) is the European gridded record of daily rainfall, built from weather stations on a 0.1° grid
(about 10 km). For each cell this counts the days with at least 1 mm of rain, the usual threshold for a rainy day, and
adds up the rain, in each full year from 2011 to 2024, then averages the years. A year counts for a cell only when the
cell has data on at least 95% of its days, and a cell is drawn only when 12 of the 14 years count.

The map shows the rainy days. The bars compare five cities in the cell over each one: Rome gets more rain in a year
than London, on far fewer days, because rain in the south falls in fewer, heavier bursts.
"""
import base64
import io
import sys
from pathlib import Path

import numpy as np
import requests
import shapely
import xarray as xr
from PIL import Image
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, byline, countries, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

EOBS_URL = ("https://knmi-ecad-assets-prd.s3.amazonaws.com/ensembles/data/Grid_0.1deg_reg_ensemble/"
            "rr_ens_mean_0.1deg_reg_2011-2025_v32.0e.nc")  # 292 MB
EOBS = DATA_DIR / "eobs_rr_0.1deg_2011-2025_v32.0e.nc"
YEARS = range(2011, 2025)  # the full years in the file
WET = 1.0  # mm in a day that make it a rainy day
CITIES = {"Genoa": (8.93, 44.41), "Amsterdam": (4.90, 52.37), "Rome": (12.50, 41.90), "London": (-0.13, 51.51), "Paris": (2.35, 48.86)}
# classes of rainy days a year, and their colours, from dry sand to deep blue
BREAKS = [50, 80, 110, 140, 170]
RAMP = ["#C08A3E", "#D9B878", "#9DB8CF", "#6F95C0", "#4470A6", "#22457A"]  # every class stands apart from the page
NO_DATA = "url(#no-data)"  # a grey hatch, so land without data does not read as a class

# 1. Data: rainy days and rain in each cell, averaged over the full years
if not EOBS.exists():
    print("Downloading E-OBS (292 MB)")
    with requests.get(EOBS_URL, stream=True, timeout=1800) as response:
        response.raise_for_status()
        with open(f"{EOBS}.part", "wb") as f:
            for chunk in response.iter_content(1 << 22):
                f.write(chunk)
    Path(f"{EOBS}.part").rename(EOBS)
cache = HERE / "rain_2011_2024.npz"
if cache.exists():
    saved = np.load(cache)
    days, total, lat, lon = saved["days"], saved["total"], saved["lat"], saved["lon"]
else:
    ds = xr.open_dataset(EOBS)
    lat, lon = ds.latitude.values, ds.longitude.values
    per_year = []
    for year in YEARS:
        rain = ds.rr.sel(time=str(year)).values  # mm a day, (day, lat, lon)
        ok = np.isfinite(rain)
        per_year.append((((rain >= WET) & ok).sum(0), np.nansum(rain, 0), ok.mean(0) >= 0.95))
    wet_days, rain_sum, full = (np.array(x) for x in zip(*per_year))
    good = full.sum(0)
    days = np.where(good >= 12, (wet_days * full).sum(0) / np.maximum(good, 1), np.nan)
    total = np.where(good >= 12, (rain_sum * full).sum(0) / np.maximum(good, 1), np.nan)
    np.savez_compressed(cache, days=days.astype(np.float32), total=total.astype(np.float32), lat=lat, lon=lon)
cell = lambda lo, la: (np.abs(lat - la).argmin(), np.abs(lon - lo).argmin())
city = {name: (float(days[cell(*xy)]), float(total[cell(*xy)])) for name, xy in CITIES.items()}
for name, (d, t) in city.items():
    print(f"{name:10s} {d:5.0f} rainy days  {t:6.0f} mm")
(rome_d, rome_t), (london_d, london_t) = city["Rome"], city["London"]
assert rome_t > london_t and rome_d < london_d  # the headline
bergen_d = float(days[cell(5.32, 60.39)])
assert 200 <= bergen_d < 220  # the note

# 2. Map: each pixel takes the class of the cell it falls in
MAP_TOP = 250
frame = Frame(2300000, 6900000, 1480000, 5140000, 0, 1080, MAP_TOP)
SCALE = 2
w, h = 1080 * SCALE, int(round(frame.ph * SCALE))
px, py = np.meshgrid(np.arange(w) + 0.5, np.arange(h) + 0.5)
mx, my = frame.x0 + px / (frame.k * SCALE), frame.y1 - py / (frame.k * SCALE)
plon, plat = Transformer.from_crs(3035, 4326, always_xy=True).transform(mx, my)
i = np.clip(np.round((plat - lat[0]) / (lat[1] - lat[0])).astype(int), 0, len(lat) - 1)
j = np.clip(np.round((plon - lon[0]) / (lon[1] - lon[0])).astype(int), 0, len(lon) - 1)
inside = (plat >= lat[0] - 0.05) & (plat <= lat[-1] + 0.05) & (plon >= lon[0] - 0.05) & (plon <= lon[-1] + 0.05)
value = np.where(inside, days[i, j], np.nan)
klass = np.digitize(value, BREAKS)
rgb = np.array([[int(c[k:k + 2], 16) for k in (1, 3, 5)] for c in RAMP], np.uint8)
img = np.zeros((h, w, 4), np.uint8)
img[..., :3] = rgb[klass]
img[..., 3] = np.where(np.isfinite(value), 255, 0)
buffer = io.BytesIO()
Image.fromarray(img, "RGBA").save(buffer, "PNG", optimize=True)
uri = base64.b64encode(buffer.getvalue()).decode()
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0)
land = world.geometry.intersection(frame.box()).union_all()
borders = shapely.union_all([g.boundary for g in world.geometry.intersection(frame.box().buffer(1)) if not g.is_empty]).intersection(frame.box())
border_d = "".join("M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in (frame.xy(*c) for c in g.coords))
                   for g in getattr(borders, "geoms", [borders]) if g.geom_type == "LineString")
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
       f'<clipPath id="land"><path d="{geom_path(land, frame)}"/></clipPath><g clip-path="url(#map)">',
       f'<defs><pattern id="no-data" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
       f'<rect width="6" height="6" fill="{C["quiet_land"]}"/><line x1="0" y1="0" x2="0" y2="6" stroke="{C["ctx"]}" stroke-width="1.6"/></pattern></defs>',
       f'<path d="{geom_path(land, frame)}" fill="{NO_DATA}"/>',
       f'<g clip-path="url(#land)"><image x="0" y="{MAP_TOP}" width="1080" height="{h / SCALE:.1f}" href="data:image/png;base64,{uri}"/></g>',
       f'<path d="{border_d}" fill="none" stroke="#CFCAC1" stroke-width=".7" stroke-linejoin="round"/>',
       fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
       f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
for name in ("Rome", "London"):
    x, y = frame.xy(*to3035.transform(*CITIES[name]))
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="4" fill="{C["ink"]}" stroke="#FFFFFF" stroke-width="1.5"/>')
    svg.append(text(x + 8, y + 5, name, 15, 700, C["ink"], halo="#FFFFFF"))

# Legend over the Atlantic, on the left margin
LX, LY = 60, MAP_TOP + 124  # over the Atlantic, between Iceland and Ireland
svg.append(text(flush("D", 17, 700, LX), LY, "Days with rain in a year", 17, 700))
labels = [f"under {BREAKS[0]}"] + [f"{a} to {b - 1}" for a, b in zip(BREAKS, BREAKS[1:])] + [f"{BREAKS[-1]} or more"]
for k, (colour, label) in enumerate(zip(RAMP, labels)):
    yy = LY + 26 + k * 21
    svg.append(f'<rect x="{LX + 1}" y="{yy - 12}" width="18" height="14" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 28, yy, label, 14, 400, C["ink2"]))
svg.append(f'<rect x="{LX + 1}" y="{LY + 26 + 6 * 21 - 12}" width="18" height="14" rx="2" fill="{NO_DATA}"/>')
svg.append(text(LX + 28, LY + 26 + 6 * 21, "no data", 14, 400, C["ink2"]))

# One note, over the North Sea, pointing at Bergen
NOTE = ["Bergen: rain on", f"{bergen_d:.0f} days a year"]
nx, ny, step = 222, MAP_TOP + 165, 23
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="19" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx}" dy="{step if k else 0}">{line}</tspan>' for k, line in enumerate(NOTE)) + "</text>")
tx, ty = frame.xy(*to3035.transform(5.0, 60.39))
tx, ty = tx - 7, ty + 1
# from under the note, dipping a little, then rising into Bergen from the west
sx, sy = nx + 128, ny + step + 11  # east of the Shetlands
qx, qy = (sx + tx) / 2 - 6, max(sy, ty) + 20
angle = np.arctan2(ty - qy, tx - qx)
head = " ".join(f"L{tx + 11 * np.cos(angle + np.pi + t):.1f} {ty + 11 * np.sin(angle + np.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 3. Bars: rain in a year and rainy days, for five cities
TOP = MAP_TOP + frame.ph + 24
svg.append(text(flush("R", 19, 700), TOP, "Rain in a year, and the days it falls on", 19, 700))
order = sorted(city, key=lambda n: -city[n][1])
top_mm = max(t for _, t in city.values())
for r, name in enumerate(order):
    d, t = city[name]
    yy = TOP + 16 + r * 21
    strong = name in ("Rome", "London")
    svg.append(text(flush(name, 14, 700 if strong else 600), yy + 12, name, 14, 700 if strong else 600, C["ink"]))
    bar = 330 * t / top_mm
    svg.append(f'<rect x="170" y="{yy}" width="{bar:.1f}" height="15" rx="2" fill="{RAMP[4] if strong else RAMP[2]}"/>')
    svg.append(text(170 + bar + 8, yy + 12, f"{t:,.0f} mm", 13, 700, C["ink"]))
    svg.append(text(640, yy + 12, f"on {d:.0f} days", 14, 700 if strong else 400, C["ink"] if strong else C["ink2"]))
BASE = TOP + 16 + len(order) * 21

# 4. Headline, dek, byline and footer
HEAD = [(80, "Rome gets more rain than London,", 46, 800, C["ink"]), (130, "on far fewer days", 46, 800, C["ink"]),
        (170, f"Rome: {rome_t:,.0f} mm a year on {rome_d:.0f} rainy days. London: {london_t:,.0f} mm on {london_d:.0f}. In the south,", 22, 400, C["ink2"]),
        (198, "rain comes in fewer, heavier bursts. Averages for 2011 to 2024.", 22, 400, C["ink2"])]
for yy, words, size, weight, colour in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour))
svg.append(byline(232, "30DayMapChallenge #26: Water").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", f"a rainy day has {WET:.0f} mm of rain or more. Averages for 2011 to 2024 in 10 km cells; each city is the cell over it."),
    ("Source:", "E-OBS 32.0e (Cornes et al., 2018). We acknowledge the E-OBS dataset and the data providers in the ECA&D project. Borders: Natural Earth."),
], x=round(flush("M", 17, 700), 1), y=BASE + 28, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day26_rain.png")
with open(HERE / "rain_by_city.csv", "w") as f:
    f.write("city,rainy_days_a_year,mm_a_year\n" + "".join(f"{n},{d:.0f},{t:.0f}\n" for n, (d, t) in city.items()))
