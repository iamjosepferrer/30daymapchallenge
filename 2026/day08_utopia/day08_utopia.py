"""Day 8, Utopia: only 3% of people in the EU already breathe the clean air of a pollution-free future."""
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
from pyproj import Transformer
from rasterio.features import rasterize
from rasterio.warp import Resampling, reproject

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

GRID_URL = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V3.zip"
GRID_TIFF = "ESTAT_Census_2021_V3.tiff"
PM_URL = "https://sdi.eea.europa.eu/datashare/s/D9xrKSZSj3ci4tN/download"  # EEA, PM2.5 2024, validated, 1 km
PM_TIFF = "pm25_avg_24.tif"
NUTS0_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/geojson/NUTS_RG_01M_2021_3035_LEVL_0.geojson"
EU = "AT BE BG HR CY CZ DK EE FI FR DE EL HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE".split()
WHO, EU_2030 = 5, 10  # annual PM2.5, µg/m³: WHO's 2021 guideline and the EU's limit from 2030
LIGHT_BLUE, GREY = "#B3C5DB", "#BDB3A2"


def fetch_tiff(url, name, size):
    """Download a zipped GeoTIFF once and keep only the GeoTIFF."""
    path = DATA_DIR / name
    if not path.exists():
        print(f"Downloading {name} ({size})")
        response = requests.get(url, timeout=3600)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            member = next(m for m in archive.namelist() if m.endswith(name))
            path.write_bytes(archive.read(member))
    return path


# 1. Data: residents on the 1 km census grid, and 2024 PM2.5 on the same 1 km squares
with rasterio.open(fetch_tiff(GRID_URL, GRID_TIFF, "566 MB")) as source:
    people = source.read(1).astype(np.float64)
    transform, shape, nodata = source.transform, source.shape, source.nodata
people[(people < 0) | (people == nodata)] = 0
pm = np.full(shape, np.nan, dtype=np.float32)
with rasterio.open(fetch_tiff(PM_URL, PM_TIFF, "78 MB")) as source:
    reproject(source.read(1), pm, src_transform=source.transform, src_crs=source.crs, src_nodata=source.nodata,
              dst_transform=transform, dst_crs="EPSG:3035", dst_nodata=np.nan, resampling=Resampling.nearest)
pm[pm < 0] = np.nan  # the file also marks missing squares with -99
nuts = gpd.read_file(_download(NUTS0_URL, DATA_DIR / "NUTS_RG_01M_2021_3035_LEVL_0.geojson"))
nuts = nuts[nuts.CNTR_CODE.isin(EU)].reset_index(drop=True)
country = rasterize(((g, i + 1) for i, g in enumerate(nuts.geometry)), out_shape=shape, transform=transform, dtype="int16")

# 2. Who breathes what: EU residents in squares with a PM2.5 value
counted = (country > 0) & (people > 0) & np.isfinite(pm)
covered = people[counted].sum() / people[(country > 0) & (people > 0)].sum()
p, v = people[counted], pm[counted]
total = p.sum()
shares = {"who": p[v <= WHO].sum() / total, "eu2030": p[(v > WHO) & (v <= EU_2030)].sum() / total, "above": p[v > EU_2030].sum() / total}
codes = nuts.CNTR_CODE.to_numpy()[country[counted] - 1]
by_country = pd.DataFrame({"country": codes, "people": p, "who": p * (v <= WHO), "eu2030": p * (v <= EU_2030)}).groupby("country").sum()
by_country["share_who"] = by_country["who"] / by_country["people"]
by_country["share_eu2030"] = by_country["eu2030"] / by_country["people"]
print(f"{total / 1e6:.1f}M residents ({covered:.1%} of them have a PM2.5 value): "
      f"WHO level {shares['who']:.1%} ({p[v <= WHO].sum() / 1e6:.1f}M), EU 2030 {shares['eu2030']:.1%}, above {shares['above']:.1%}")
print(by_country.sort_values("share_who", ascending=False)[["share_who", "share_eu2030"]].head(6).round(3))

# 3. Map: every EU square coloured by its air, blue where it already meets WHO's guideline
MAP_TOP = 410
frame = Frame(1680000, 6920000, 1450000, 5450000, 0, 1080, MAP_TOP)
col0, row0 = int((frame.x0 - transform.c) // 1000), int((transform.f - frame.y1) // 1000)
w, h = int((frame.x1 - frame.x0) // 1000), int((frame.y1 - frame.y0) // 1000)
air, eu_land = np.full((h, w), np.nan, dtype=np.float32), np.zeros((h, w), dtype=bool)
r1, c1 = min(row0 + h, shape[0]), min(col0 + w, shape[1])  # the frame reaches past the grid's eastern edge
air[:r1 - row0, :c1 - col0] = pm[row0:r1, col0:c1]
eu_land[:r1 - row0, :c1 - col0] = country[row0:r1, col0:c1] > 0
hex_rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
rgba = np.zeros((h, w, 4), dtype=np.uint8)
rgba[eu_land & (air > EU_2030)] = (*hex_rgb(GREY), 255)
rgba[eu_land & (air > WHO) & (air <= EU_2030)] = (*hex_rgb(LIGHT_BLUE), 255)
rgba[eu_land & (air <= WHO)] = (*hex_rgb(C["blue"]), 255)
png = io.BytesIO()
Image.fromarray(rgba).save(png, format="PNG", optimize=True)
world = countries().to_crs(3035)
land = world.geometry.buffer(0).intersection(frame.box()).union_all()


def line_path(geom):
    """SVG path for lines, such as borders."""
    lines = [g for g in getattr(geom, "geoms", [geom]) if g.geom_type == "LineString"]
    for g in getattr(geom, "geoms", []):
        if g.geom_type == "MultiLineString":
            lines += list(g.geoms)
    return "".join("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in (frame.xy(*c) for c in line.coords)) for line in lines)


# Country borders on land only: every country's outline, minus the coast
coast = land.boundary.buffer(2500)
borders = world.geometry.buffer(0).boundary.union_all().intersection(frame.box()).difference(coast).simplify(1000)

svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{geom_path(land, frame)}" fill="{C["quiet_land"]}"/>',
    f'<image href="data:image/png;base64,{base64.b64encode(png.getvalue()).decode()}" x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.1f}" preserveAspectRatio="none"/>',
    f'<path d="{line_path(borders)}" fill="none" stroke="{C["page"]}" stroke-width="1" stroke-opacity=".9" stroke-linejoin="round"/>',
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>',
    "</g>",
]

# Legend, top left over the Atlantic
to_map = Transformer.from_crs(4326, 3035, always_xy=True)
LX, LY = 34, 470
svg.append(text(LX, LY, "Fine particles (PM2.5), yearly average 2024", 17, 700))
for i, (colour, label) in enumerate(((C["blue"], f"{WHO} µg/m³ or less, WHO's guideline"),
                                      (LIGHT_BLUE, f"{WHO} to {EU_2030}, within the EU's 2030 limit"),
                                      (GREY, f"Above {EU_2030}"))):
    y = LY + 14 + i * 24
    svg.append(f'<rect x="{LX}" y="{y}" width="16" height="16" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 24, y + 13, label, 15, 400, C["ink2"]))

# One handwritten note over the Norwegian Sea, with an arrow to Finland
fi = by_country.loc["FI", "share_who"]
note_x, note_y = 762, 500
svg.append(f'<text class="note" x="{note_x}" y="{note_y}" font-size="22" fill="{C["ink"]}">'
           f'<tspan x="{note_x}">In Finland, {fi:.0%} of people</tspan><tspan x="{note_x}" dy="27">already breathe it</tspan></text>')
ax, ay = frame.xy(*to_map.transform(25.5, 62.0))
sx, sy = note_x + 60, note_y + 40
svg.append(f'<path d="M{sx} {sy} C {sx - 10} {sy + 50}, {ax + 50} {ay - 30}, {ax:.1f} {ay:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{ax + 4:.1f} {ay - 13:.1f} L{ax:.1f} {ay:.1f} L{ax + 13:.1f} {ay + 2:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 4. Bar: the EU's residents by the air they breathe
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"{total / 1e6:.0f} million EU residents, by the air where they live", 21, 700))
parts = [("who", C["blue"], "WHO's guideline"), ("eu2030", LIGHT_BLUE, "Within the 2030 limit"), ("above", GREY, "Above it")]
rounded = {k: round(v * 100) for k, v in shares.items()}
x = BAR_X
for key, colour, label in parts:
    width = BAR_W * shares[key]
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{max(width - GAP, 2):.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    # the first label sits at the start of the bar; the others at the end of their segment, so the narrow blue one has room
    lx, anchor = (x, "start") if key == "who" else (x + width - GAP, "end")
    svg.append(text(lx, BAR_Y + BAR_H + 23, f"{rounded[key]}%", 22, 700, C["blue"] if key == "who" else None, anchor))
    svg.append(text(lx, BAR_Y + BAR_H + 44, label, 17, 400, C["ink2"], anchor))
    x += width

# 5. Headline, dek, byline and footer
svg.append(text(60, 90, f"Only {rounded['who']}% of people in the EU already", 50, 800))
svg.append(text(60, 146, "breathe the air of a cleaner future", 50, 800))
svg.append(text(60, 190, "Air as clean as the WHO recommends already exists in parts of the EU. In blue, where fine", 25, 400, C["ink2"]))
svg.append(text(60, 220, f"particles average {WHO} µg/m³ or less over the year, the World Health Organization's guideline.", 25, 400, C["ink2"]))
svg.append(byline(252, "30DayMapChallenge #8: Utopia"))
FOOTER = [
    ("Method:", "the 2024 average of fine particles (PM2.5) in each 1 km square, matched with its residents in the 2021 census."),
    ("Source:", "air: European Environment Agency, 2024 interpolated data (validated), CC BY 4.0. Residents: Eurostat, Census 2021 grid, © European Union. Base: Natural Earth."),
    ("Comments:", "air values are EEA estimates for each square from stations, models and satellites, not measurements or a legal compliance check. The Canaries, Madeira and the Azores are outside the air map."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day08_utopia.png")

results = pd.DataFrame([{"measure": f"Share of EU residents, {k}", "value": round(v, 4)} for k, v in shares.items()]
                       + [{"measure": "EU residents counted", "value": round(total)}, {"measure": "Share of residents with an air value", "value": round(covered, 4)}])
results.to_csv(HERE / "results.csv", index=False)
by_country[["people", "share_who", "share_eu2030"]].round(4).to_csv(HERE / "by_country.csv")
