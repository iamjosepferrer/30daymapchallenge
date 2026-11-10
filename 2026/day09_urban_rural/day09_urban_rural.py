"""Day 9, Urban-rural: most of the EU is set to have fewer people in 2050, while urban regions grow.

Eurostat's EUROPOP2025 baseline projection for the EU's 1,165 NUTS 3 regions, drawn region by region.
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

PROJ_URL = ("https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/proj_25rp5"
            "?format=JSON&lang=EN&sex=T&age=TOTAL&projection=BSL&time=2025&time=2050&time=2100")
NUTS3_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2024_3035_LEVL_3.geojson"
YEAR = "2050"
BANDS = [  # upper bound of the change in %, colour, legend label, bar label
    (-10, "#5F91A8", "Falls more than 10%", "Fall 10%+"),
    (-5, "#B6D2D6", "Falls 5% to 10%", "Fall 5% to 10%"),
    (5, "#FFFFFF", "Between −5% and 5%", "Between −5% and 5%"),
    (10, "#F2C6A1", "Grows 5% to 10%", "Grow 5% to 10%"),
    (np.inf, "#DF7F6F", "Grows more than 10%", "Grow 10%+"),
]
BORDER = "#3F3A34"  # country borders: a dark warm grey, thin, so it stands apart from the strong blue and the white


def band(change):
    """0 to 4, from falling most to growing most. A change of exactly -10% counts as falling 5% to 10%."""
    return np.digitize(change, [b[0] for b in BANDS[:-1]])


# 1. Data: the projection for every NUTS 3 region, and the regions' shapes and urban-rural type
raw = json.loads(_download(PROJ_URL, DATA_DIR / "proj_25rp5_total.json").read_text())
dims = raw["id"]
cats = [sorted(raw["dimension"][k]["category"]["index"], key=raw["dimension"][k]["category"]["index"].get) for k in dims]
rows = [dict(zip(dims, combo), value=raw["value"].get(str(i))) for i, combo in enumerate(itertools.product(*cats))]
proj = pd.DataFrame(rows).dropna().pivot(index="geo", columns="time", values="value")
proj["change"] = (proj[YEAR] / proj["2025"] - 1) * 100
proj["band"] = band(proj["change"])

nuts = gpd.read_file(_download(NUTS3_URL, DATA_DIR / "NUTS_RG_01M_2024_3035_LEVL_3.geojson"))
nuts = nuts[nuts.NUTS_ID.isin(proj.index)].set_index("NUTS_ID")
assert len(nuts) == len(proj), set(proj.index) - set(nuts.index)
nuts = nuts.join(proj[["change", "band"]])

# 2. The numbers on the chart
total = proj["2025"].sum()
eu_change = proj[YEAR].sum() / total - 1
shares = proj.groupby("band")["2025"].sum() / total  # residents in 2025, by their region's band
kind = proj.join(nuts["URBN_TYPE"]).groupby("URBN_TYPE")[["2025", YEAR]].sum()
# Eurostat's types: 1 predominantly urban, 2 intermediate, 3 predominantly rural, by the share of people living outside urban clusters
urban, intermediate, rural = (kind.loc[t, YEAR] / kind.loc[t, "2025"] - 1 for t in (1, 2, 3))
shrinking_regions = (nuts["change"] < 0).mean()
shrinking_area = nuts.geometry.area[nuts["change"] < 0].sum() / nuts.geometry.area.sum()
assert shrinking_regions > 0.5 and shrinking_area > 0.5  # "most of the EU", by regions and by land
ireland = nuts.loc[nuts.index.str.startswith("IE"), "change"]
assert ireland.min() > 10  # the note: every Irish region grows more than 10%
print(f"EU {total / 1e6:.1f}M in 2025, {eu_change:+.1%} by {YEAR}; urban {urban:+.1%}, rural {rural:+.1%}")
print(f"shrinking: {shrinking_regions:.1%} of regions, {shrinking_area:.1%} of land; residents by band {shares.round(3).to_dict()}")
print(f"Ireland's smallest gain {ireland.min():.1f}%")

# 3. Map: every region in its band's colour, with thin page-coloured lines between regions
MAP_TOP = 410
frame = Frame(1680000, 6920000, 1450000, 5450000, 0, 1080, MAP_TOP)
view = frame.box().buffer(20000)
land = countries().to_crs(3035).geometry.buffer(0).intersection(frame.box()).union_all()
svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{geom_path(land, frame)}" fill="{C["quiet_land"]}"/>',
]
OUTERMOST = ("ES70", "FRY", "PT20", "PT30")  # Canaries, French overseas regions, Azores, Madeira: counted, not drawn
shown = nuts[nuts.intersects(view) & ~nuts.index.str.startswith(OUTERMOST)]
for b, (_, colour, _, _) in enumerate(BANDS):
    regions = shown[shown["band"] == b].geometry.simplify(300).intersection(view).union_all()
    svg.append(f'<path d="{geom_path(regions, frame)}" fill="{colour}"/>')
outlines = "".join(geom_path(g, frame) for g in shown.geometry.simplify(300).intersection(view))
svg.append(f'<path d="{outlines}" fill="none" stroke="#E4DCCE" stroke-width=".5" stroke-linejoin="round"/>')
# Country outlines, coasts included, in soft grey. Each shared border is drawn once, from the merged outlines.
eu_countries = shown.dissolve("CNTR_CODE").geometry.simplify(300)
# islets under 50 km² keep their fill but get no outline, so archipelagos don't turn into grey smudges
big_parts = [shapely.MultiPolygon([q for q in getattr(g, "geoms", [g]) if q.area > 50e6]) for g in eu_countries]
outline = shapely.union_all([g.boundary for g in big_parts]).intersection(view)
lines = [g for g in getattr(outline, "geoms", [outline]) if g.geom_type == "LineString"]
border_d = "".join("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in (frame.xy(*c) for c in g.coords)) for g in lines)
svg.append(f'<path d="{border_d}" fill="none" stroke="{BORDER}" stroke-width=".9" stroke-linejoin="round" stroke-linecap="round"/>')
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic
LX, LY = 34, 470
svg.append(text(LX, LY, f"Population change by {YEAR}, by region", 17, 700))
for i, (_, colour, label, _) in enumerate(BANDS):
    y = LY + 14 + i * 24
    svg.append(f'<rect x="{LX}" y="{y}" width="16" height="16" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 24, y + 13, label, 15, 400, C["ink2"]))

# One handwritten note over the Atlantic, with an arrow to Ireland
note_x, note_y = 40, 905
svg.append(f'<text class="note" x="{note_x}" y="{note_y}" font-size="22" fill="{C["ink"]}">'
           f'<tspan x="{note_x}">Every region of Ireland is</tspan><tspan x="{note_x}" dy="27">projected to grow more</tspan>'
           f'<tspan x="{note_x}" dy="27">than 10%</tspan></text>')
ax, ay = frame.xy(*Transformer.from_crs(4326, 3035, always_xy=True).transform(-9.0, 52.6))
sx, sy = note_x + 120, note_y - 26
svg.append(f'<path d="M{sx} {sy} C {sx + 10} {sy - 40}, {ax - 40} {ay + 30}, {ax:.1f} {ay:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{ax - 13:.1f} {ay + 2:.1f} L{ax:.1f} {ay:.1f} L{ax - 3:.1f} {ay + 13:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 4. Bar: today's residents, by how their region changes
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
# No head count in the title: the projection starts from its own 2025 estimate, which differs slightly from the 2025 census count
svg.append(text(BAR_X, 314, f"EU residents in 2025, by how their region is projected to change by {YEAR}", 21, 700))
x = BAR_X
for b, (_, colour, _, short) in enumerate(BANDS):
    width = BAR_W * shares.get(b, 0)
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    lx = x + (width - GAP) / 2  # labels centred under their segment, so the narrow ones don't collide
    svg.append(text(lx, BAR_Y + BAR_H + 23, f"{shares.get(b, 0):.0%}", 22, 700, None, "middle"))
    svg.append(text(lx, BAR_Y + BAR_H + 43, short, 15, 400, C["ink2"], "middle"))
    x += width

# 5. Headline, dek, byline and footer
svg.append(text(60, 90, "Most of the EU is set to have fewer", 50, 800))
svg.append(text(60, 146, f"people in {YEAR} than it has today", 50, 800))
svg.append(text(60, 190, f"Projected change in each NUTS 3 region, 2025 to {YEAR}. Urban regions gain {urban:.1%}", 25, 400, C["ink2"]))
svg.append(text(60, 220, f"and rural ones lose {-rural:.1%}. The EU as a whole loses {-eu_change:.1%}.", 25, 400, C["ink2"]))
svg.append(byline(252, "30DayMapChallenge #9: Urban-rural"))
FOOTER = [
    ("Method:", f"population change from 2025 to {YEAR} in the baseline projection, for the EU's {len(proj):,} NUTS 3 regions. Urban and rural regions are Eurostat's predominantly urban and predominantly rural ones. Intermediate regions lose {-intermediate:.1%}."),
    ("Source:", "Eurostat, EUROPOP2025 regional population projections and NUTS 2024, © European Union. Base: Natural Earth."),
    ("Comments:", "projections assume current trends in births, deaths and migration continue. The Canaries and other outermost regions count but aren't shown."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day09_urban_rural.png")
table = nuts.drop(columns="geometry").join(proj[["2025", YEAR]])[["CNTR_CODE", "NAME_LATN", "URBN_TYPE", "2025", YEAR, "change"]]
table["URBN_TYPE"] = table["URBN_TYPE"].map({1: "urban", 2: "intermediate", 3: "rural"})
table.rename(columns={"CNTR_CODE": "country", "NAME_LATN": "region", "URBN_TYPE": "type", "change": "change_pct"}).round(2).sort_index().to_csv(HERE / "projection_by_region.csv")
