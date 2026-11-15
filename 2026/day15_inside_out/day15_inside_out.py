"""Day 15, Inside out: the EU's waters as the map, with the land left blank.

Each EU country's exclusive economic zone from Marine Regions, compared with its land area from Eurostat. The EU's
outermost regions, such as the Canaries, the Azores and Réunion, are part of the EU and are counted. Overseas
territories outside the EU, such as Greenland and French Polynesia, are not.
"""
import json
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

EEZ_URL = ("https://geo.vliz.be/geoserver/MarineRegions/wfs?service=WFS&version=1.0.0&request=GetFeature"
           "&typeName=MarineRegions:eez&outputFormat=application/json&featureID=eez.{}")
# Marine Regions EEZ v12 features for the EU's waters, including joint zones and France's outermost regions
FEATURES = [28, 37, 62, 69, 82, 86, 97, 104, 109, 112, 121, 140, 156, 165, 171, 177, 191, 209, 210, 211, 212, 214, 215, 216,
            217, 218, 219, 220, 222, 231, 235, 238, 263, 274]
LAND_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/reg_area3?format=JSON&lang=EN"
            "&unit=KM2&landuse=L0008&time=2024")
CODE = {"Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Denmark": "DK", "Estonia": "EE", "Finland": "FI",
        "France": "FR", "Germany": "DE", "Greece": "EL", "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT",
        "Malta": "MT", "Netherlands": "NL", "Poland": "PL", "Portugal": "PT", "Azores": "PT", "Madeira": "PT", "Romania": "RO",
        "Slovenia": "SI", "Spain": "ES", "Canary Islands": "ES", "Sweden": "SE", "Guadeloupe": "FR", "Martinique": "FR",
        "French Guiana": "FR", "Réunion": "FR", "Mayotte": "FR", "Collectivity of Saint Martin": "FR"}
NAMES = {"AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CY": "Cyprus", "CZ": "Czechia", "DE": "Germany", "DK": "Denmark",
         "EE": "Estonia", "EL": "Greece", "ES": "Spain", "FI": "Finland", "FR": "France", "HR": "Croatia", "HU": "Hungary",
         "IE": "Ireland", "IT": "Italy", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta", "NL": "Netherlands",
         "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia"}

# 1. Sea: each country's exclusive economic zone, joint zones counted for the country listed first
paths = [_download(EEZ_URL.format(n), DATA_DIR / "eez" / f"eez.{n}.json") for n in FEATURES]
eez = pd.concat([gpd.read_file(p).to_crs(4326) for p in paths], ignore_index=True)
eez["code"] = eez.territory1.map(CODE)
assert eez.code.notna().all()
full = eez.copy()  # before the map clips everything outside Europe
sea = eez.groupby("code").area_km2.sum()

# Land: Eurostat's land area for each country, which includes its outermost regions
land_url = LAND_URL + "".join(f"&geo={c}" for c in NAMES)
raw = json.loads(_download(land_url, DATA_DIR / "eurostat_land_area_2024.json").read_text())
geo = {i: k for k, i in raw["dimension"]["geo"]["category"]["index"].items()}
area = {geo[int(i)]: v for i, v in raw["value"].items()}
eu = pd.DataFrame({"name": NAMES})
eu["land"] = [area[c] for c in eu.index]
eu["sea"] = sea.reindex(eu.index).fillna(0)
eu["ratio"] = eu.sea / eu.land
total_sea, total_land = eu.sea.sum(), eu.land.sum()
print(eu.sort_values("ratio", ascending=False).round(2).to_string())
print(f"EU sea {total_sea:,.0f} km², land {total_land:,.0f} km², {total_sea / total_land - 1:.0%} more sea")
assert 1.4 < total_sea / total_land < 1.55 and round(eu.loc["MT", "ratio"]) == 169

# 2. Map: blank land, the EU's waters in blue by how much sea each country has for each km² of land
MAP_TOP = 275
frame = Frame(550000, 6850000, 640000, 5420000, 0, 1080, MAP_TOP)
view = frame.box().buffer(30000)
BANDS = [(1, "#CFDCEB", "Less sea than land"), (2, "#9DB7D6", "1 to 2 times its land"), (5, "#5E86B8", "2 to 5 times"),
         (np.inf, C["blue"], "More than 5 times")]
eu["band"] = np.digitize(eu.ratio, [b[0] for b in BANDS[:-1]])
eez = eez.to_crs(3035)
eez["geometry"] = eez.geometry.simplify(1500).intersection(view)
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(view)
in_eu = world.ADMIN.isin(NAMES.values())
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">']
for b, (_, colour, _) in enumerate(BANDS):
    codes = eu.index[eu.band == b]
    shapes = eez[eez.code.isin(codes)].geometry.union_all()
    svg.append(f'<path d="{geom_path(shapes, frame)}" fill="{colour}" stroke="{C["card"]}" stroke-width=".7" stroke-linejoin="round"/>')
svg.append(f'<path d="{geom_path(world[~in_eu].union_all(), frame)}" fill="{C["quiet_land"]}"/>')
svg.append(f'<path d="{geom_path(world[in_eu].union_all(), frame)}" fill="{C["page"]}" stroke="{C["ctxl"]}" stroke-width=".5"/>')
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Labels on the sea for the countries with the most sea for their land
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
# (lon, lat, inside): inside its own waters in white, or just outside them in ink
LABELS = {"PT": (-26.4, 37.4, True), "ES": (-17.8, 26.9, True), "IE": (-14.6, 53.4, True), "EL": (21.0, 35.9, True),
          "CY": (33.4, 33.0, False), "MT": (14.6, 33.0, False)}
for c, (lon, lat, inside) in LABELS.items():
    x, y = frame.xy(*to3035.transform(lon, lat))
    colour = "#FFFFFF" if inside else C["ink"]
    halo = "" if inside else f' stroke="{C["quiet_land"]}" stroke-width="4" paint-order="stroke"'
    svg.append(f'<text x="{x:.1f}" y="{y:.1f}" font-size="16" font-weight="700" fill="{colour}" text-anchor="middle"{halo}>{NAMES[c]}</text>')
    svg.append(f'<text x="{x:.1f}" y="{y + 18:.1f}" font-size="14" fill="{colour}" text-anchor="middle"{halo}>{eu.loc[c, "ratio"]:.0f}× its land</text>')

# France's outermost regions, in boxes over Russia, at the same scale as the main map
colour_fr = BANDS[int(eu.loc["FR", "band"])][1]
INSETS = [("French Guiana", ["French Guiana"], (4.9, -52.3), 826, 330),
          ("Guadeloupe and Martinique", ["Guadeloupe", "Martinique", "Collectivity of Saint Martin"], (16.0, -61.6), 945, 330),
          ("Réunion", ["Réunion"], (-21.0, 55.5), 860, 484),
          ("Mayotte", ["Mayotte"], (-12.8, 45.2), 997, 484)]
PAD = 6
svg.append(text(826, 300, "France's overseas regions,", 15, 700))
svg.append(text(826, 318, "at the same scale", 15, 400, C["ink2"]))
for name, parts, (lat, lon), bx, by in INSETS:
    crs = f"+proj=laea +lat_0={lat} +lon_0={lon}"
    waters = full[full.territory1.isin(parts)].to_crs(crs).geometry.simplify(1500).union_all()
    x0, y0, x1, y1 = waters.bounds
    k, pad = frame.k, PAD / frame.k
    f = Frame(x0 - pad, x1 + pad, y0 - pad, y1 + pad, bx, bx + (x1 - x0) * k + 2 * PAD, by)
    bw, bh = f.pw, f.ph
    near = countries().to_crs(crs).geometry.buffer(0).intersection(f.box())
    svg.append(f'<rect x="{bx}" y="{by}" width="{bw:.1f}" height="{bh:.1f}" fill="{C["card"]}" stroke="{C["ctxl"]}" stroke-width=".8"/>')
    svg.append(f'<path d="{geom_path(waters, f)}" fill="{colour_fr}"/>')
    svg.append(f'<path d="{geom_path(near[~near.is_empty].union_all(), f)}" fill="{C["page"]}" stroke="{C["ctxl"]}" stroke-width=".5"/>')
    label = name.replace(" and ", " and\n").split("\n")
    for j, line in enumerate(label):
        svg.append(text(bx, by + bh + 15 + j * 15, line, 13, 600, C["ink2"]))

# Legend over the Atlantic, west of Ireland
LX, LY = 34, MAP_TOP + 40
svg.append(text(LX, LY, "Each country's waters, compared", 17, 700))
svg.append(text(LX, LY + 21, "with its land", 17, 700))
for i, (_, colour, label) in enumerate(BANDS):
    y = LY + 44 + i * 24
    svg.append(f'<rect x="{LX}" y="{y - 8}" width="18" height="16" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 28, y + 5, label, 15, 400, C["ink2"]))

# Bar under the map: the EU's land and its waters around Europe
BAR_Y = MAP_TOP + frame.ph + 30
svg.append(text(60, BAR_Y, "The EU's land and its waters, in million km²", 21, 700))
most = max(total_sea, total_land)
for i, (label, value, colour) in enumerate([("Land", total_land, C["page"]), ("Waters", total_sea, C["blue"])]):
    y = BAR_Y + 18 + i * 40
    svg.append(text(60, y + 22, label, 17, 700, C["ink"]))
    svg.append(f'<rect x="150" y="{y}" width="{820 * value / most:.1f}" height="30" rx="3" fill="{colour}" stroke="{C["ctxl"]}" stroke-width=".6"/>')
    svg.append(text(150 + 820 * value / most + 10, y + 22, f"{value / 1e6:.1f}", 18, 700, C["ink"]))

svg.append(text(60, 90, "The EU has more sea than land", 50, 800))
svg.append(text(60, 136, "Europe inside out: the land left blank and the EU's waters as the map.", 23, 400, C["ink2"]))
svg.append(text(60, 164, f"They cover {total_sea / total_land - 1:.0%} more than its land. Malta's are {eu.loc['MT', 'ratio']:.0f} times its own.", 23, 400, C["ink2"]))
svg.append(byline(200))
svg.append(text(60, 226, "30DayMapChallenge, day 15: Inside out", 18, 600, C["ink2"]))
svg += footer([
    ("Method:", "each country's exclusive economic zone, where it alone can fish and drill, including the EU's overseas regions."),
    ("Source:", "Flanders Marine Institute (2023), Marine Regions EEZ v12. Eurostat land areas. Natural Earth."),
    ("Comments:", "Greenland, French Polynesia and the Dutch Caribbean aren't in the EU, so their waters are left out."),
], x=60, y=BAR_Y + 112, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day15_inside_out.png")
(eu[["name", "land", "sea", "ratio"]].rename(columns={"land": "land_km2", "sea": "sea_km2", "ratio": "sea_per_km2_of_land"})
   .sort_values("sea_per_km2_of_land", ascending=False).round(2).to_csv(HERE / "sea_and_land.csv", index_label="code"))
