"""Day 3, Polygons: half of Europe's tourist nights happen in just 102 of its 1,247 regions."""
import json
import sys
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, FONT_DIR, FONT_URLS, Frame, _download, byline, countries, fade_defs, geom_path, page, save_png, text  # noqa: E402
from PIL import ImageFont  # noqa: E402


def footer(items, x, y, width, size, line_height):
    """Footer notes: a bold label, then text wrapped to the given width."""
    for name, url in FONT_URLS.items():
        _download(url, FONT_DIR / name)
    regular = ImageFont.truetype(str(FONT_DIR / "Gabarito.ttf"), size)
    bold = ImageFont.truetype(str(FONT_DIR / "Gabarito.ttf"), size)
    bold.set_variation_by_axes([700])
    out = []
    for label, body in items:
        room = width - bold.getlength(label + " ")
        line, lines = "", []
        for word in body.split(" "):
            candidate = f"{line} {word}".strip()
            if regular.getlength(candidate) <= room:
                line = candidate
            else:
                lines.append(line)
                line, room = word, width
        lines.append(line)
        for row, words in enumerate(lines):
            words = words.replace("&", "&amp;")
            first = f'<tspan font-weight="700" fill="{C["ink2"]}">{label}</tspan> ' if row == 0 else ""
            out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{C["muted"]}">{first}{words}</text>')
            y += line_height
    return out

YEAR = "2025"
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
NIGHTS_QUERY = "tour_occ_nin3?format=JSON&lang=EN&c_resid=TOTAL&nace_r2=I551-I553&unit=NR&time=" + YEAR
POPULATION_QUERY = "demo_r_pjanaggr3?format=JSON&lang=EN&sex=T&age=TOTAL&unit=NR&time=" + YEAR
BOUNDARIES_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_10M_2024_3035.geojson"
LIGHT_BLUE = "#8DA7C6"


def cached(url, name):
    path = DATA_DIR / name
    if not path.exists():
        print(f"Downloading {name}")
        response = requests.get(url, timeout=300)
        response.raise_for_status()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        path.write_bytes(response.content)
    return path


def eurostat_by_region(query, name):
    """Read a Eurostat JSON-stat table with one value per region."""
    data = json.loads(cached(f"{EUROSTAT}/{query}", name).read_text())
    geo = data["dimension"]["geo"]["category"]
    codes = sorted(geo["index"], key=geo["index"].get)
    position = data["id"].index("geo")
    stride = 1
    for size in data["size"][position + 1:]:
        stride *= size
    rows = {codes[(int(key) // stride) % len(codes)]: value for key, value in data["value"].items()}
    return pd.Series(rows), geo["label"]


# 1. Data: NUTS 3 regions ranked by nights spent
nights, labels = eurostat_by_region(NIGHTS_QUERY, f"eurostat_nights_{YEAR}.json")
residents, _ = eurostat_by_region(POPULATION_QUERY, f"eurostat_population_{YEAR}.json")
table = pd.DataFrame({"nights": nights, "residents": residents}).dropna()
table = table[(table.index.str.len() == 5) & (table.residents > 0)].copy()
table["name"] = table.index.map(labels)
table = table.sort_values("nights", ascending=False)
table["rank"] = range(1, len(table) + 1)
table["share_of_nights"] = table.nights / table.nights.sum()
table["cumulative_share"] = table.share_of_nights.cumsum()
quarter = int((table.cumulative_share < 0.25).sum() + 1)
half = int((table.cumulative_share < 0.5).sum() + 1)
table["group"] = "other"
table.iloc[:half, table.columns.get_loc("group")] = "half"
table.iloc[:quarter, table.columns.get_loc("group")] = "quarter"
total_nights = table.nights.sum()
resident_share = table.residents[:half].sum() / table.residents.sum()
print(f"{len(table)} regions, {total_nights / 1e9:.2f} billion nights. A quarter in {quarter}, half in {half} regions, home to {resident_share:.1%} of residents")
print(table.head(12)[["name", "nights"]].assign(M=lambda d: (d.nights / 1e6).round(1))[["name", "M"]].to_string())

regions = gpd.read_file(cached(BOUNDARIES_URL, "NUTS_RG_10M_2024_3035.geojson"))
regions = regions[regions.LEVL_CODE == 3].set_index("NUTS_ID")
regions = regions[regions.index.isin(table.index)]
regions["group"] = table.group
FILL = {"quarter": C["blue"], "half": LIGHT_BLUE, "other": C["page"]}

# 2. Map, at the same scale as Day 2 but with less of the far north, to make room for the bar and the islands
MAP_TOP = 400
frame = Frame(2254651, 6545349, 1200000, 4520000, 0, 1080, MAP_TOP)
land = countries().to_crs(3035)
background = land.geometry.buffer(0).intersection(frame.box()).union_all()
main_regions = regions[regions.intersects(frame.box())]

svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{geom_path(background, frame)}" fill="{C["quiet_land"]}"/>',
]
for group in ("other", "half", "quarter"):
    for _, region in main_regions[main_regions.group == group].iterrows():
        svg.append(f'<path d="{geom_path(region.geometry, frame)}" fill="{FILL[group]}" stroke="{C["card"]}" stroke-width=".3"/>')
svg += [
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>',
    "</g>",
]

# 3. Insets for the overseas regions in the top 102, at the same scale as the map, below Spain
from pyproj import Transformer  # noqa: E402

to_map = Transformer.from_crs(4326, 3035, always_xy=True)
spain_tip_y = frame.xy(*to_map.transform(-5.6, 36.0))[1]
INSET_TOP, INSET_BOTTOM, PAD_M = int(spain_tip_y) + 8, MAP_TOP + int(frame.ph) - 6, 12000
inset_x = 30
inset_frames = {}
for label, codes in [("Canary Islands", [c for c in regions.index if c.startswith("ES70")]), ("Madeira", ["PT300"])]:
    islands = regions.loc[codes]
    # Centre on Madeira and Porto Santo. The region also includes the uninhabited Savage Islands, 300 km south.
    parts = gpd.GeoSeries([p for g in islands.geometry for p in getattr(g, "geoms", [g])], crs=islands.crs)
    focus = parts[parts.bounds.miny > 1400000] if label == "Madeira" else parts
    minx, miny, maxx, maxy = focus.total_bounds
    width = max(74, (maxx - minx + 2 * PAD_M) * frame.k)
    height = INSET_BOTTOM - INSET_TOP
    centre_x, centre_y = (minx + maxx) / 2, (miny + maxy) / 2 - 10000
    inset = Frame(centre_x - width / frame.k / 2, centre_x + width / frame.k / 2, centre_y - height / frame.k / 2, centre_y + height / frame.k / 2, inset_x, inset_x + width, INSET_TOP)
    inset_frames[label] = inset
    clip = "inset-" + label.split()[0].lower()
    svg.append(f'<clipPath id="{clip}"><rect x="{inset_x}" y="{INSET_TOP}" width="{width:.0f}" height="{height}" rx="4"/></clipPath>')
    svg.append(f'<rect x="{inset_x}" y="{INSET_TOP}" width="{width:.0f}" height="{height}" rx="4" fill="{C["card"]}" stroke="{C["ink2"]}" stroke-width=".6"/>')
    svg.append(f'<g clip-path="url(#{clip})">')
    for _, region in islands.iterrows():
        svg.append(f'<path d="{geom_path(region.geometry, inset)}" fill="{FILL[region.group]}" stroke="{C["ink2"]}" stroke-width=".4"/>')
    svg.append("</g>")
    svg.append(text(inset_x + 6, INSET_TOP + 15, label, 13, 600, C["ink2"]))
    inset_x += width + 8
for row, line in enumerate([
    "Overseas regions are counted but",
    "left off the map, except the",
    "Canary Islands and Madeira,",
    "which are blue too.",
]):
    svg.append(text(inset_x + 4, INSET_TOP + 15 + row * 16, line, 14, 400, C["ink2"]))

# 4. Five highlighted regions: a thick outline and a label with nights in millions
HIGHLIGHTS = {
    "ITI43": ("Rome province", 16, 10, "start"),
    "ES532": ("Mallorca", 0, -14, "middle"),
    "ES511": ("Barcelona\nprovince", 26, -2, "start"),
    "ITH35": ("Venice province", 12, -4, "start"),
}
for code, (name, dx, dy, anchor) in HIGHLIGHTS.items():
    region = regions.loc[code]
    x, y = frame.xy(*region.geometry.representative_point().coords[0])
    svg.append(f'<path d="{geom_path(region.geometry, frame)}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linejoin="round"/>')
    for row, line in enumerate(f"{name} {table.nights[code] / 1e6:.0f}M".split("\n")):
        svg.append(text(x + dx, y + dy + row * 20, line, 18, 700, C["ink"], anchor))

# Paris is only a few pixels wide at this scale, so it gets a magnifying lens over the Channel
paris_shape = regions.loc["FR101"].geometry
paris_cx, paris_cy = paris_shape.centroid.x, paris_shape.centroid.y
px_paris, py_paris = frame.xy(paris_cx, paris_cy)
LENS_X, LENS_Y, LENS_R, LENS_K = 316, 738, 36, 0.0024  # pixel centre, pixel radius, pixels per metre
half_m = LENS_R / LENS_K
lens = Frame(paris_cx - half_m, paris_cx + half_m, paris_cy - half_m, paris_cy + half_m, LENS_X - LENS_R, LENS_X + LENS_R, LENS_Y - LENS_R)
nearby = regions[regions.intersects(lens.box())]
svg.append(f'<line x1="{LENS_X + LENS_R * 0.6:.1f}" y1="{LENS_Y + LENS_R * 0.8:.1f}" x2="{px_paris:.1f}" y2="{py_paris:.1f}" stroke="{C["ink"]}" stroke-width="1.2"/>')
svg.append(f'<circle cx="{px_paris:.1f}" cy="{py_paris:.1f}" r="2.5" fill="{C["ink"]}"/>')
svg.append(f'<clipPath id="lens"><circle cx="{LENS_X}" cy="{LENS_Y}" r="{LENS_R}"/></clipPath><g clip-path="url(#lens)">')
svg.append(f'<circle cx="{LENS_X}" cy="{LENS_Y}" r="{LENS_R}" fill="{C["page"]}"/>')
for code, region in nearby.iterrows():
    svg.append(f'<path d="{geom_path(region.geometry, lens)}" fill="{FILL[region.group]}" stroke="{C["card"]}" stroke-width=".6"/>')
svg.append(f'<path d="{geom_path(paris_shape, lens)}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linejoin="round"/></g>')
svg.append(f'<circle cx="{LENS_X}" cy="{LENS_Y}" r="{LENS_R}" fill="none" stroke="{C["ink"]}" stroke-width="1.2"/>')
svg.append(text(LENS_X - LENS_R - 8, LENS_Y + 7, f'Paris {table.nights["FR101"] / 1e6:.0f}M', 18, 700, C["ink"], "end"))

# Legend, over Russia, where there is no data
LEG_X, LEG_Y = 812, 584
millions = lambda value: f"{value / 1e6:.1f}M"
dark_min, light_max, light_min = table.nights.iloc[quarter - 1], table.nights.iloc[quarter], table.nights.iloc[half - 1]
svg.append(f'<rect x="{LEG_X - 14}" y="{LEG_Y - 24}" width="256" height="110" rx="6" fill="{C["card"]}" fill-opacity=".92"/>')
svg.append(text(LEG_X, LEG_Y, "Tourist nights per region, 2025", 17, 700, C["ink"]))
legend_rows = [
    (f'fill="{C["blue"]}"', f"{millions(dark_min)} or more (top {quarter})"),
    (f'fill="{LIGHT_BLUE}"', f"{millions(light_min)} to {millions(light_max)} (next {half - quarter})"),
    (f'fill="{C["page"]}" stroke="{C["ink2"]}" stroke-width=".6"', f"Under {millions(light_min)} (other {len(table) - half:,})"),
]
for row, (style, label) in enumerate(legend_rows):
    y = LEG_Y + 14 + row * 24
    svg.append(f'<rect x="{LEG_X}" y="{y}" width="16" height="16" rx="3" {style}/>')
    svg.append(text(LEG_X + 24, y + 13, label, 15, 400, C["ink2"]))

# 5. Bar: where the nights happen
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"Where Europe's {total_nights / 1e9:.1f} billion tourist nights happen", 21, 700))
segments = [
    (0.25, C["blue"], f"{quarter} regions"),
    (table.cumulative_share.iloc[half - 1] - 0.25, LIGHT_BLUE, f"The next {half - quarter} regions"),
    (1 - table.cumulative_share.iloc[half - 1], C["page"], f"The other {len(table) - half:,} regions"),
]
x = BAR_X
for share, colour, label in segments:
    width = BAR_W * share
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    svg.append(text(x, BAR_Y + BAR_H + 23, f"{share:.0%}", 22, 700))
    svg.append(text(x, BAR_Y + BAR_H + 44, label, 17, 400, C["ink2"]))
    x += width

# One handwritten note with a curved arrow over Great Britain, which has no data
ireland = int(round(table.nights[table.index.str.startswith("IE")].sum() / 1e6))
note_x, note_y = 48, MAP_TOP + 76
svg.append(
    f'<text class="note" x="{note_x}" y="{note_y}" font-size="25" fill="{C["ink"]}">'
    f'<tspan x="{note_x}">Paris alone hosts more nights</tspan><tspan x="{note_x}" dy="30">than the whole of Ireland ({ireland}M)</tspan></text>'
)
x0, y0 = note_x + 250, note_y + 44
x1, y1 = LENS_X - 4, LENS_Y - LENS_R - 5
svg.append(f'<path d="M{x0} {y0} C {x0 - 4} {y0 + 90}, {x1 + 6} {y1 - 70}, {x1:.1f} {y1:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{x1 - 7:.1f} {y1 - 11:.1f} L{x1:.1f} {y1:.1f} L{x1 + 7:.1f} {y1 - 11:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 6. Headline, dek, byline and source
svg.append(text(60, 90, "Half of Europe's tourist nights happen", 50, 800))
svg.append(text(60, 146, f"in just {half} of its {len(table):,} regions", 50, 800))
svg.append(text(60, 190, f"Nights spent in hotels, holiday rentals and campsites in {YEAR}. The blue regions host half", 25, 400, C["ink2"]))
svg.append(text(60, 220, f"of all nights but hold {resident_share:.0%} of residents. The darkest {quarter} alone host a quarter.", 25, 400, C["ink2"]))
svg.append(byline(252))
FOOTER = [
    ("Method:", f"rank all {len(table):,} regions by nights, then add them up from the top. The first {quarter} hold a quarter of all nights, the first {half} half."),
    ("Source:", f"Eurostat (tour_occ_nin3, demo_r_pjanaggr3), {YEAR}: nights in registered accommodation by NUTS 3 region. ©\u00a0EuroGeographics for the administrative boundaries. Base: Natural Earth."),
    ("Comments:", "NUTS 3 regions are provinces, islands or districts. No regional data for the UK, Turkey, Ukraine and some Balkan countries. Iceland and the far north are counted but off the map."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)

save_png(page("".join(svg)), HERE / "day03_polygons.png")
table[["rank", "name", "nights", "residents", "share_of_nights", "cumulative_share", "group"]].round(4).to_csv(HERE / "results.csv", index_label="nuts3")
