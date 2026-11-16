"""Day 16, Collaborative map: where people move in the EU, region by region.

Eurostat's crude rate of net migration for 2024 in each of the EU's 1,165 NUTS 3 regions: people who moved in minus
people who moved out, per 1,000 residents (shown here as a % of residents), counting moves from abroad and from elsewhere in the same country.
"""
import itertools
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

YEAR = "2024"
MIGR_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/demo_r_gind3"
            f"?format=JSON&lang=EN&indic_de=CNMIGRATRT&indic_de=CNMIGRAT&indic_de=JAN&time={YEAR}")
NUTS3_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_3035_LEVL_3.geojson"
EU = ["AT", "BE", "BG", "CY", "CZ", "DE", "DK", "EE", "EL", "ES", "FI", "FR", "HR", "HU", "IE", "IT", "LT", "LU", "LV", "MT",
      "NL", "PL", "PT", "RO", "SE", "SI", "SK"]
CAPITALS = {"Lisbon": (-9.14, 38.72), "Dublin": (-6.26, 53.35), "Madrid": (-3.70, 40.42), "Paris": (2.35, 48.86),
            "Brussels": (4.35, 50.85), "Amsterdam": (4.90, 52.37), "Luxembourg": (6.13, 49.61), "Copenhagen": (12.57, 55.68),
            "Rome": (12.50, 41.90), "Berlin": (13.40, 52.52), "Valletta": (14.51, 35.90), "Prague": (14.44, 50.08),
            "Ljubljana": (14.51, 46.06), "Zagreb": (15.98, 45.81), "Vienna": (16.37, 48.21), "Bratislava": (17.11, 48.15),
            "Stockholm": (18.07, 59.33), "Budapest": (19.04, 47.50), "Warsaw": (21.01, 52.23), "Athens": (23.73, 37.98),
            "Sofia": (23.32, 42.70), "Riga": (24.11, 56.95), "Tallinn": (24.75, 59.44), "Helsinki": (24.94, 60.17),
            "Vilnius": (25.28, 54.69), "Bucharest": (26.10, 44.43), "Nicosia": (33.36, 35.17)}
BANDS = [  # upper bound per 1,000 residents, colour, legend label in % (10 per 1,000 is 1%)
    (-5, "#C9572F", "Lost more than 0.5%"),
    (0, "#EBB98A", "Lost up to 0.5%, or none"),
    (5, "#BBCDE3", "Gained up to 0.5%"),
    (10, "#6F94C2", "Gained 0.5% to 1%"),
    (np.inf, C["blue"], "Gained more than 1%"),
]
BORDER = "#3F3A34"


def band(rate):
    """0 to 4, from losing most to gaining most. Exactly 0 counts as losing up to 5."""
    return np.digitize(rate, [b[0] for b in BANDS[:-1]], right=True)


# 1. Data: net migration and residents for every NUTS 3 region, and the regions' shapes
raw = json.loads(_download(MIGR_URL, DATA_DIR / f"demo_r_gind3_migration_{YEAR}.json").read_text())
dims = raw["id"]
cats = [sorted(raw["dimension"][k]["category"]["index"], key=raw["dimension"][k]["category"]["index"].get) for k in dims]
rows = [dict(zip(dims, combo), value=raw["value"].get(str(i))) for i, combo in enumerate(itertools.product(*cats))]
data = pd.DataFrame(rows).dropna().pivot(index="geo", columns="indic_de", values="value")
nuts = gpd.read_file(_download(NUTS3_URL, DATA_DIR / "NUTS_RG_01M_2024_3035_LEVL_3.geojson"))
nuts = nuts[nuts.CNTR_CODE.isin(EU)].set_index("NUTS_ID").join(data)
assert len(nuts) == 1165 and nuts.CNMIGRATRT.notna().all()
nuts["band"] = band(nuts.CNMIGRATRT)

# 2. The numbers on the chart
gained = nuts.CNMIGRATRT > 0
share_regions = gained.mean()
share_people = nuts.JAN[gained].sum() / nuts.JAN.sum()
net = nuts.CNMIGRAT.sum()
assert 0.8 < share_regions < 0.9 and 2.4e6 < net < 2.6e6  # "more than 8 in 10 regions" and "2.5 million"
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
caps = gpd.GeoDataFrame(index=list(CAPITALS), geometry=gpd.points_from_xy(*zip(*CAPITALS.values())), crs=4326).to_crs(3035)
caps = gpd.sjoin(caps, nuts.reset_index()[["NUTS_ID", "NAME_LATN", "CNMIGRATRT", "geometry"]], predicate="within")
assert len(caps) == 27
caps = caps.sort_values("CNMIGRATRT", ascending=False)
paris = nuts.loc["FR101", "CNMIGRATRT"]
assert caps.CNMIGRATRT.idxmin() == "Paris"
print(f"{share_regions:.1%} of regions and {share_people:.1%} of residents gained; EU net {net:,.0f}")
print(caps[["NUTS_ID", "NAME_LATN", "CNMIGRATRT"]].to_string())

# 3. Map: every region in its band's colour, country outlines on top
MAP_TOP = 244
frame = Frame(1680000, 6920000, 1250000, 5116000, 0, 1080, MAP_TOP)
view = frame.box().buffer(20000)
land = countries().to_crs(3035).geometry.buffer(0).intersection(frame.box()).union_all()
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
       f'<g clip-path="url(#map)"><path d="{geom_path(land, frame)}" fill="{C["quiet_land"]}"/>']
OUTERMOST = ("ES70", "FRY", "PT20", "PT30")  # Canaries, French overseas regions, Azores, Madeira: counted, not drawn
shown = nuts[nuts.intersects(view) & ~nuts.index.str.startswith(OUTERMOST)]
for b, (_, colour, _) in enumerate(BANDS):
    regions = shown[shown.band == b].geometry.simplify(300).intersection(view).union_all()
    svg.append(f'<path d="{geom_path(regions, frame)}" fill="{colour}"/>')
outlines = "".join(geom_path(g, frame) for g in shown.geometry.simplify(300).intersection(view))
svg.append(f'<path d="{outlines}" fill="none" stroke="#E4DCCE" stroke-width=".4" stroke-linejoin="round"/>')
eu_countries = shown.dissolve("CNTR_CODE").geometry.simplify(300)
big_parts = [shapely.MultiPolygon([q for q in getattr(g, "geoms", [g]) if q.area > 50e6]) for g in eu_countries]
outline = shapely.union_all([g.boundary for g in big_parts]).intersection(view)
lines = [g for g in getattr(outline, "geoms", [outline]) if g.geom_type == "LineString"]
border_d = "".join("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in (frame.xy(*c) for c in g.coords)) for g in lines)
svg.append(f'<path d="{border_d}" fill="none" stroke="{BORDER}" stroke-width=".8" stroke-linejoin="round" stroke-linecap="round"/>')
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic
LX, LY = 34, MAP_TOP + 60
svg.append(text(LX, LY, f"Net migration in {YEAR},", 17, 700))
svg.append(text(LX, LY + 21, "as a share of residents", 17, 700))
for i, (_, colour, label) in enumerate(BANDS[::-1]):
    y = LY + 46 + i * 24
    svg.append(f'<rect x="{LX}" y="{y - 8}" width="18" height="16" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 28, y + 5, label, 15, 400, C["ink2"]))

# The outermost regions are in the numbers but off the map
svg.append(text(34, MAP_TOP + frame.ph - 58, "Not drawn but counted: the Canaries,", 13, 400, C["ink2"]))
svg.append(text(34, MAP_TOP + frame.ph - 42, "Madeira, the Azores and France's", 13, 400, C["ink2"]))
svg.append(text(34, MAP_TOP + frame.ph - 26, "overseas regions", 13, 400, C["ink2"]))

# One note, over the Atlantic, pointing at Paris
ax, ay = frame.xy(*to3035.transform(2.2, 48.86))
nx, ny = 34, MAP_TOP + 420
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="21" fill="{C["ink"]}"><tspan x="{nx}">The city of Paris lost</tspan>'
           f'<tspan x="{nx}" dy="26">{-paris / 10:.1f}% of its residents</tspan></text>')
sx, sy = nx + 222, ny + 8
svg.append(f'<path d="M{sx} {sy} C {sx + 60} {sy}, {ax - 60} {ay}, {ax - 6:.1f} {ay:.1f}" fill="none" stroke="{C["ink"]}" '
           f'stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{ax - 17:.1f} {ay - 7:.1f} L{ax - 6:.1f} {ay:.1f} L{ax - 17:.1f} {ay + 7:.1f}" fill="none" stroke="{C["ink"]}" '
           f'stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 4. Columns under the map: the region around each EU capital
TOP = MAP_TOP + frame.ph + 22
svg.append(text(60, TOP, f"Net migration in {YEAR} in the region of each EU capital, as a share of residents", 19, 700))
step, SCALE = 960 / 27, 2.4  # pixels per migrant per 1,000 residents
ZERO = TOP + 46 + caps.CNMIGRATRT.max() * SCALE
svg.append(f'<path d="M60 {ZERO:.1f} L1020 {ZERO:.1f}" stroke="{C["ctxl"]}" stroke-width="1"/>')
bottom = ZERO - caps.CNMIGRATRT.min() * SCALE
for i, (name, row) in enumerate(caps.iterrows()):
    cx = 60 + step * (i + 0.5)
    v = row.CNMIGRATRT
    top, h = (ZERO - v * SCALE, v * SCALE) if v > 0 else (ZERO, -v * SCALE)
    svg.append(f'<rect x="{cx - step * 0.36:.1f}" y="{top:.1f}" width="{step * 0.72:.1f}" height="{max(h, 1):.1f}" rx="2" '
               f'fill="{BANDS[int(band(v))][1]}"/>')
    label_y = top - 5 if v > 0 else ZERO - 5  # values above the bar, or above the zero line for losses
    svg.append(text(cx, label_y, f"{v / 10:.1f}%".replace("-0.0%", "0.0%").replace("-", "−"), 11, 700, C["ink"], "middle"))
    svg.append(f'<text x="{cx + 4:.1f}" y="{bottom + 12:.1f}" font-size="13" font-weight="600" fill="{C["ink2"]}" text-anchor="end" '
               f'transform="rotate(-45 {cx + 4:.1f} {bottom + 12:.1f})">{name}</text>')

# 5. Headline, dek, byline and footer
svg.append(text(60, 84, "More than 8 in 10 EU regions gained", 46, 800))
svg.append(text(60, 134, f"people through migration in {YEAR}", 46, 800))
svg.append(text(60, 174, "People who moved in minus those who moved out, from abroad or within the country, in each", 22, 400, C["ink2"]))
svg.append(text(60, 202, f"of the EU's {len(nuts):,} regions. The EU gained {net / 1e6:.1f} million people this way.", 22, 400, C["ink2"]))
# The byline with the challenge day, one size smaller than usual so the theme's name fits on the line
svg.append(byline(234, "30DayMapChallenge #16: Collaborative map").replace('font-size="20"', 'font-size="18"'))
svg += footer([
    ("Method:", f"net migration in {YEAR} as a share of residents, by NUTS 3 region, with Eurostat's statistical adjustment included."),
    ("Source:", "Eurostat, demo_r_gind3, and NUTS 2024, © European Union. Base: Natural Earth."),
    ("Comments:", "regions differ in size: Paris is the city alone, Stockholm the whole county. Topic picked together with friends."),
], x=60, y=bottom + 84, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day16_collaborative.png")
(nuts.drop(columns="geometry")[["CNTR_CODE", "NAME_LATN", "JAN", "CNMIGRAT", "CNMIGRATRT"]]
 .rename(columns={"CNTR_CODE": "country", "NAME_LATN": "region", "JAN": f"residents_1_jan_{YEAR}", "CNMIGRAT": "net_migration",
                  "CNMIGRATRT": "net_migration_per_1000"})
 .sort_index().to_csv(HERE / "net_migration_by_region.csv", index_label="nuts_id"))
