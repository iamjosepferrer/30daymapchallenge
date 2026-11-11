"""Day 12, Power: the Netherlands has the most solar panels per person in the EU.

Solar photovoltaic capacity at the end of 2024 from Eurostat, per resident on 1 January 2025. The background is the
yearly output of 1 kW of panels at the best angle, from the European Commission's PVGIS tool, on a half-degree grid
saved in sun_grid.csv. Delete that file to fetch the grid again (about 4,500 requests, several minutes).
"""
import base64
import io
import itertools
import json
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from PIL import Image
from pyproj import Transformer
from scipy.interpolate import griddata

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

PV_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/nrg_inf_epcrw"
          "?format=JSON&lang=EN&siec=RA420&unit=MW&plant_tec=CAP_NET_ELC&time=2024")
POP_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/demo_pjan"
           "?format=JSON&lang=EN&sex=T&age=TOTAL&time=2025")
NAMES = {"BE": "Belgium", "BG": "Bulgaria", "CZ": "Czechia", "DK": "Denmark", "DE": "Germany", "EE": "Estonia",
         "IE": "Ireland", "EL": "Greece", "ES": "Spain", "FR": "France", "HR": "Croatia", "IT": "Italy", "CY": "Cyprus",
         "LV": "Latvia", "LT": "Lithuania", "LU": "Luxembourg", "HU": "Hungary", "MT": "Malta", "NL": "Netherlands",
         "AT": "Austria", "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SI": "Slovenia", "SK": "Slovakia",
         "FI": "Finland", "SE": "Sweden"}
SPOT = {"AT": (14.6, 47.6), "BE": (4.6, 50.6), "BG": (25.3, 42.7), "HR": (16.2, 45.6), "CY": (33.1, 35.0),
        "CZ": (15.4, 49.8), "DK": (9.3, 56.1), "EE": (25.8, 58.7), "FI": (26.0, 62.8), "FR": (2.5, 46.8),
        "DE": (10.3, 51.1), "EL": (22.0, 39.6), "HU": (19.4, 47.2), "IE": (-8.0, 53.2), "IT": (12.6, 42.9),
        "LV": (25.2, 56.9), "LT": (23.9, 55.3), "LU": (6.1, 49.8), "MT": (14.4, 35.9), "NL": (5.6, 52.3),
        "PL": (19.3, 52.1), "PT": (-8.1, 39.6), "RO": (25.0, 45.9), "SK": (19.6, 48.7), "SI": (14.8, 46.1),
        "ES": (-3.7, 40.2), "SE": (15.0, 61.5)}


PVGIS_URL = "https://re.jrc.ec.europa.eu/api/v5_3/PVcalc?lat={lat}&lon={lon}&peakpower=1&loss=14&optimalangles=1&outputformat=json"


def pvgis(point):
    """Yearly output in kWh of 1 kW of panels at the best angle, or nothing over the sea or outside PVGIS's data."""
    lon, lat = point
    for _ in range(3):
        try:
            with urllib.request.urlopen(PVGIS_URL.format(lat=lat, lon=lon), timeout=60) as reply:
                return lon, lat, json.load(reply)["outputs"]["totals"]["fixed"]["E_y"]
        except urllib.error.HTTPError as error:
            if error.code == 400:
                return lon, lat, np.nan
        except OSError:
            pass
    return lon, lat, np.nan


def sun_grid():
    """Every half degree of land from 11°W to 36°E and 34°N to 71°N, fetched once and saved next to this script."""
    path = HERE / "sun_grid.csv"
    if not path.exists():
        land = countries().geometry.buffer(0).union_all()
        points = [(lon, lat) for lat in np.arange(34, 71.01, 0.5) for lon in np.arange(-11, 36.01, 0.5)
                  if land.intersects(shapely.Point(lon, lat).buffer(0.3))]
        with ThreadPoolExecutor(12) as pool:
            rows = list(pool.map(pvgis, points))
        pd.DataFrame(rows, columns=["lon", "lat", "kwh_per_kw"]).to_csv(path, index=False)
    return pd.read_csv(path).dropna()


def eurostat(url, name):
    raw = json.loads(_download(url, DATA_DIR / name).read_text())
    dims = raw["id"]
    cats = [sorted(raw["dimension"][k]["category"]["index"], key=raw["dimension"][k]["category"]["index"].get) for k in dims]
    rows = [dict(zip(dims, combo), value=raw["value"].get(str(i))) for i, combo in enumerate(itertools.product(*cats))]
    return pd.DataFrame(rows).dropna().set_index("geo")["value"]


# 1. Watts of solar per resident
capacity = eurostat(PV_URL, "nrg_inf_epcrw_pv_2024.json")
population = eurostat(POP_URL, "demo_pjan_2025_total.json")
eu = pd.DataFrame({"name": NAMES})
eu["mw"] = capacity.reindex(eu.index)
eu["residents"] = population.reindex(eu.index)
eu["watts"] = eu.mw * 1e6 / eu.residents
eu_watts = capacity["EU27_2020"] * 1e6 / eu.residents.sum()

# 2. Sunshine: how much power 1 kW of panels makes in a year, averaged over each country's land
sun = sun_grid()
world = countries()
eu_shapes = world[world.ADMIN.isin(NAMES.values())].set_index("ADMIN").geometry.buffer(0)
assert len(eu_shapes) == 27
for code, name in NAMES.items():
    inside = shapely.contains_xy(eu_shapes[name], sun.lon, sun.lat)
    near = sun[inside] if inside.sum() >= 3 else sun.iloc[np.argsort(np.hypot(sun.lon - SPOT[code][0], sun.lat - SPOT[code][1]))[:4]]
    eu.loc[code, "sun"] = near.kwh_per_kw.mean()  # small countries: the nearest grid points
print(eu.sort_values("watts", ascending=False)[["mw", "residents", "watts", "sun"]].round(0).to_string())
nl, es = eu.loc["NL"], eu.loc["ES"]
print(f"EU {eu_watts:.0f} W per person; NL/ES watts {nl.watts / es.watts:.2f}; ES/NL sun {es.sun / nl.sun:.2f}")
assert eu.watts.idxmax() == "NL" and 1.8 < nl.watts / es.watts < 2  # "the most" and "almost twice as many as Spain"

# 3. Map: sunshine as a warm background on land, a blue circle per country sized by watts per person
MAP_TOP = 275  # the map comes right after the byline, the column chart goes under it
frame = Frame(1680000, 6920000, 1190000, 4950000, 0, 1080, MAP_TOP)
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
gx, gy = to3035.transform(sun.lon.to_numpy(), sun.lat.to_numpy())
SCALE = 2  # background pixels per canvas pixel
cols, rows = 1080 * SCALE, int(frame.ph * SCALE)
px_x = frame.x0 + (np.arange(cols) + 0.5) / SCALE / frame.k
px_y = frame.y1 - (np.arange(rows) + 0.5) / SCALE / frame.k
mx, my = np.meshgrid(px_x, px_y)
field = griddata((gx, gy), sun.kwh_per_kw.to_numpy(), (mx, my), method="linear")
land3035 = world.to_crs(3035).geometry.buffer(0).intersection(frame.box().buffer(50000))
eu_land = land3035[world.ADMIN.isin(NAMES.values())].union_all()
on_eu = shapely.contains_xy(eu_land, mx, my)
LOW, HIGH = 900, 1700  # kWh per kW per year, the ends of the colour ramp
t = np.clip((field - LOW) / (HIGH - LOW), 0, 1)
pale, warm = np.array([245, 239, 227]), np.array([232, 170, 92])  # page colour to a warm sand
rgb = pale + t[..., None] * (warm - pale)
alpha = np.where(on_eu & ~np.isnan(field), 255, 0)
img = np.dstack([np.nan_to_num(rgb, nan=245), alpha]).astype(np.uint8)
buffer = io.BytesIO()
Image.fromarray(img, "RGBA").save(buffer, "PNG")
sun_png = base64.b64encode(buffer.getvalue()).decode()

svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(land3035.union_all(), frame)}" fill="{C["quiet_land"]}"/>',
       f'<path d="{geom_path(eu_land, frame)}" fill="{C["page"]}"/>',
       f'<image x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.1f}" href="data:image/png;base64,{sun_png}"/>']
borders = shapely.union_all([g.boundary for g in land3035[world.ADMIN.isin(NAMES.values())]]).intersection(frame.box())
lines = [g for g in getattr(borders, "geoms", [borders]) if g.geom_type == "LineString"]
svg.append(f'<path d="{"".join("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in (frame.xy(*c) for c in g.coords)) for g in lines)}" '
           f'fill="none" stroke="#FFFFFF" stroke-opacity=".7" stroke-width=".8" stroke-linejoin="round"/>')

eu["x"], eu["y"] = zip(*(frame.xy(*to3035.transform(*SPOT[c])) for c in eu.index))
eu["r"] = 0.62 * np.sqrt(eu.watts)  # circle area follows watts per person
ox, oy = eu.x.to_numpy().copy(), eu.y.to_numpy().copy()
px, py, r = ox.copy(), oy.copy(), np.where(eu.r >= 17, eu.r, eu.r + 15).astype(float)
for _ in range(400):  # nudge circles apart, each pulled back towards its own country
    dx, dy = px[:, None] - px[None, :], py[:, None] - py[None, :]
    dist = np.hypot(dx, dy) + np.eye(len(px))
    push = np.clip(r[:, None] + r[None, :] + 2 - dist, 0, None) * (1 - np.eye(len(px)))
    px += 0.25 * (push * dx / dist).sum(axis=1) + 0.02 * (ox - px)
    py += 0.25 * (push * dy / dist).sum(axis=1) + 0.02 * (oy - py)
eu["x"], eu["y"] = px, py
for c, row in eu.iterrows():
    svg.append(f'<circle cx="{row.x:.1f}" cy="{row.y:.1f}" r="{row.r:.1f}" fill="{C["blue"]}" stroke="{C["page"]}" stroke-width="1.2"/>')
    label = f"{row.watts:,.0f}"
    if row.r >= 17:
        svg.append(text(row.x, row.y + 5, label, 15, 700, "#FFFFFF", "middle"))
    else:
        svg.append(text(row.x, row.y + row.r + 15, label, 14, 700, C["ink2"], "middle"))
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Note over the Atlantic, at the left edge, pointing at the Netherlands
note_x, note_y = 34, 700
svg.append(f'<text class="note" x="{note_x}" y="{note_y}" font-size="22" fill="{C["ink"]}"><tspan x="{note_x}">About three panels for</tspan>'
           f'<tspan x="{note_x}" dy="27">every Dutch resident</tspan></text>')
nx, ny, nr = eu.loc["NL", "x"], eu.loc["NL", "y"], eu.loc["NL", "r"]
sx, sy = note_x + 256, note_y - 10
ax, ay = nx - nr - 4, ny
svg.append(f'<path d="M{sx} {sy} C {sx + 60} {sy}, {ax - 70} {ay}, {ax:.1f} {ay:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{ax - 11:.1f} {ay - 7:.1f} L{ax:.1f} {ay:.1f} L{ax - 11:.1f} {ay + 7:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# Legend over the Atlantic: circles, then the sunshine ramp
LX, LY = 34, 340
svg.append(text(LX, LY, "Solar panels per person", 17, 700))
svg.append(f'<circle cx="{LX + 14}" cy="{LY + 30}" r="{0.62 * np.sqrt(1000):.1f}" fill="{C["blue"]}"/>')
svg.append(text(LX + 14, LY + 35, "1,000", 13, 700, "#FFFFFF", "middle"))
svg.append(text(LX + 44, LY + 35, "Circle area shows watts per person", 15, 400, C["ink2"]))
svg.append(text(LX, LY + 80, "Sunshine: electricity 1 kW of panels makes in a year", 15, 700))
svg.append('<defs><linearGradient id="sun"><stop offset="0" stop-color="#F5EFE3"/><stop offset="1" stop-color="#E8AA5C"/></linearGradient></defs>')
svg.append(f'<rect x="{LX}" y="{LY + 90}" width="240" height="12" rx="2" fill="url(#sun)"/>')
svg.append(text(LX, LY + 120, f"{LOW:,} kWh", 14, 400, C["ink2"]))
svg.append(text(LX + 240, LY + 120, f"{HIGH:,} kWh", 14, 400, C["ink2"], "end"))

# Column chart under the map: each country's share of the EU's solar capacity, all in grey (blue is kept for the map)
total = capacity["EU27_2020"]
top = ["DE", "ES", "IT", "FR", "NL", "PL"]
columns = [(eu.loc[c, "mw"] / total, NAMES[c], "#C2B7A3") for c in top]
columns.append((1 - sum(v for v, _, _ in columns), "21 others", "#C2B7A3"))
CHART_TITLE_Y, BASE_Y, MAX_H = MAP_TOP + frame.ph + 34, MAP_TOP + frame.ph + 150, 76
svg.append(text(60, CHART_TITLE_Y, f"Share of the EU's {total / 1000:.0f} GW of installed solar capacity, by country", 21, 700))
step = 960 / len(columns)
tallest = max(v for v, _, _ in columns)
for i, (value, label, fill) in enumerate(columns):
    cx, h = 60 + step * (i + 0.5), MAX_H * value / tallest
    svg.append(f'<rect x="{cx - step * 0.36:.1f}" y="{BASE_Y - h:.1f}" width="{step * 0.72:.1f}" height="{h:.1f}" rx="3" fill="{fill}"/>')
    svg.append(text(cx, BASE_Y - h - 8, f"{value:.0%}", 20, 700, None, "middle"))
    svg.append(text(cx, BASE_Y + 20, label, 15, 400, C["ink2"], "middle"))

# Headline, dek, byline and footer
svg.append(text(60, 90, "The Netherlands has the most solar", 50, 800))
svg.append(text(60, 146, "panels per person in the EU", 50, 800))
svg.append(text(60, 190, f"Watts of solar panels per person, end of 2024. The Netherlands has almost twice as", 25, 400, C["ink2"]))
svg.append(text(60, 220, f"many as Spain, where the same panel makes {es.sun / nl.sun - 1:.0%} more electricity a year.", 25, 400, C["ink2"]))
svg.append(byline(252, "30DayMapChallenge #12: Power"))
FOOTER = [
    ("Method:", "installed solar capacity at the end of 2024, divided by residents on 1 January 2025. Sunshine is the "
                "electricity 1 kW of panels at the best angle makes in a year, averaged over each country's land."),
    ("Source:", "Eurostat (solar capacity and population), the European Commission's PVGIS (sunshine), Natural Earth (map)."),
    ("Comments:", "Austria and Finland report their panels' rated power, about 10% to 20% above the inverter output others report."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day12_power.png")
eu[["name", "mw", "residents", "watts", "sun"]].round(1).to_csv(HERE / "solar_per_person.csv")
