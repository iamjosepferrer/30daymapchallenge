"""Day 4, Clusters: a third of the land in the EU, Norway and Switzerland is just three empty patches."""
import base64
import io
import sys
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
import requests
from PIL import Image
from scipy import ndimage

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

GRID_URL = "https://gisco-services.ec.europa.eu/census/2021/Eurostat_Census-GRID_2021_V3.zip"
GRID_TIFF = "ESTAT_Census_2021_V3.tiff"
LAND_TIFF = "ESTAT_Census_2021_LAND_SURFACE_V3.tiff"
LIGHT_BLUE = "#B3C5DB"  # other empty land: same family as the three patches, but light
POPULATED_BAND = 14  # 1 = people live in the cell, 0 = nobody does
COUNTRIES = {
    "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland", "CY": "Cyprus", "CZ": "Czechia",
    "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "EL": "Greece", "ES": "Spain", "FI": "Finland",
    "FR": "France", "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IT": "Italy", "LI": "Liechtenstein",
    "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia", "MT": "Malta", "NL": "Netherlands", "NO": "Norway",
    "PL": "Poland", "PT": "Portugal", "RO": "Romania", "SE": "Sweden", "SI": "Slovenia", "SK": "Slovakia",
}


def grid_files():
    """Download the Census 2021 grid once (566 MB) and keep only the two GeoTIFFs."""
    paths = [DATA_DIR / GRID_TIFF, DATA_DIR / LAND_TIFF]
    if not all(path.exists() for path in paths):
        print("Downloading the Census 2021 grid (566 MB)")
        response = requests.get(GRID_URL, timeout=1800)
        response.raise_for_status()
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            for path in paths:
                member = next(name for name in archive.namelist() if name.endswith(path.name))
                path.write_bytes(archive.read(member))
    return paths


# 1. Data: 1 km cells where nobody lives, joined into patches when they share a side
grid_path, land_path = grid_files()
with rasterio.open(grid_path) as source:
    populated = source.read(POPULATED_BAND)
    nodata, transform = source.nodata, source.transform
with rasterio.open(land_path) as source:
    land = source.read(1)
in_grid = populated != nodata
empty = populated == 0
land_km2 = np.where(in_grid & (land > 0), land, 0)  # coastal cells are only partly land

patches, _ = ndimage.label(empty)
patch_km2 = ndimage.sum(land_km2, patches, index=np.arange(patches.max() + 1))
patch_km2[0] = 0
largest = np.argsort(patch_km2)[::-1][:3]
total_km2, empty_km2 = land_km2.sum(), land_km2[empty].sum()
big3_km2 = patch_km2[largest].sum()
print(f"Land {total_km2:,.0f} km2, empty {empty_km2 / total_km2:.1%}, three largest patches {big3_km2 / total_km2:.1%}")

# Where each of the three patches sits, for its label
rows = []
for rank, patch in enumerate(largest, start=1):
    ys, xs = np.nonzero(patches == patch)
    rows.append({"rank": rank, "km2": patch_km2[patch], "cells": len(ys),
                 "x": transform.c + (xs.mean() + 0.5) * 1000, "y": transform.f - (ys.mean() + 0.5) * 1000})
results = pd.DataFrame(rows)
print(results.round(0).to_string(index=False))

# 2. Map frame: all three patches, full-bleed
MAP_TOP = 410
frame = Frame(1680000, 6920000, 1450000, 5450000, 0, 1080, MAP_TOP)
background = countries().to_crs(3035).geometry.buffer(0).intersection(frame.box()).union_all()

# The grid as one image: blue for the three largest patches, light blue for other empty cells, light for cells with people
colours = np.zeros(populated.shape + (4,), dtype=np.uint8)
hex_rgb = lambda value: tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))
colours[in_grid & ~empty] = (*hex_rgb(C["page"]), 255)
colours[empty] = (*hex_rgb(LIGHT_BLUE), 255)
colours[np.isin(patches, largest)] = (*hex_rgb(C["blue"]), 255)
col0 = int((frame.x0 - transform.c) // 1000)
row0 = int((transform.f - frame.y1) // 1000)
width_cells, height_cells = int((frame.x1 - frame.x0) // 1000), int((frame.y1 - frame.y0) // 1000)
canvas = np.zeros((height_cells, width_cells, 4), dtype=np.uint8)
src_r0, src_c0 = max(row0, 0), max(col0, 0)
src_r1, src_c1 = min(row0 + height_cells, colours.shape[0]), min(col0 + width_cells, colours.shape[1])
canvas[src_r0 - row0:src_r1 - row0, src_c0 - col0:src_c1 - col0] = colours[src_r0:src_r1, src_c0:src_c1]
png = io.BytesIO()
Image.fromarray(canvas).save(png, format="PNG", optimize=True)
image = base64.b64encode(png.getvalue()).decode()

svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{geom_path(background, frame)}" fill="{C["quiet_land"]}"/>',
    f'<image href="data:image/png;base64,{image}" x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.1f}" preserveAspectRatio="none"/>',
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>',
    "</g>",
]

# 3. Labels for the three patches, placed in the sea next to each one
def patch_name(row):
    if row.y > 3500000:
        return "Nordic patch"
    return "Iberian patch" if row.x < 4000000 else "South-east patch"


LABEL_AT = {"Nordic patch": (372, 604, "start"), "Iberian patch": (40, 1150, "start"), "South-east patch": (880, 1010, "start")}
for row in results.itertuples():
    name = patch_name(row)
    x, y, anchor = LABEL_AT[name]
    svg.append(text(x, y, name, 18, 700, C["ink"], anchor))
    svg.append(text(x, y + 21, f"{round(row.km2, -3):,.0f} km²", 18, 400, C["ink"], anchor))
results["name"] = results.apply(patch_name, axis=1)

# One handwritten note with a curved arrow over the Atlantic
note_x, note_y = 30, 606
svg.append(
    f'<text class="note" x="{note_x}" y="{note_y}" font-size="23" fill="{C["ink"]}">'
    f'<tspan x="{note_x}">You could cross from</tspan><tspan x="{note_x}" dy="28">Portugal to France</tspan>'
    f'<tspan x="{note_x}" dy="28">without entering one</tspan><tspan x="{note_x}" dy="28">square km where</tspan>'
    f'<tspan x="{note_x}" dy="28">anyone lives</tspan></text>'
)
x0, y0 = note_x + 90, note_y + 128
x1, y1 = 232, 1036
svg.append(f'<path d="M{x0} {y0} C {x0 - 10} {y0 + 50}, {x1 - 20} {y1 - 60}, {x1:.1f} {y1:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{x1 - 9:.1f} {y1 - 10:.1f} L{x1:.1f} {y1:.1f} L{x1 + 6:.1f} {y1 - 12:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# 4. Legend
LEG_X, LEG_Y = 812, 584
svg.append(f'<rect x="{LEG_X - 14}" y="{LEG_Y - 24}" width="262" height="110" rx="6" fill="{C["card"]}" fill-opacity=".92"/>')
svg.append(text(LEG_X, LEG_Y, "1 km squares, 2021 census", 17, 700, C["ink"]))
legend_rows = [
    (f'fill="{C["blue"]}"', "Empty: the three largest patches"),
    (f'fill="{LIGHT_BLUE}"', "Empty: smaller patches"),
    (f'fill="{C["page"]}" stroke="{C["ink2"]}" stroke-width=".6"', "People live here"),
]
for row, (style, label) in enumerate(legend_rows):
    y = LEG_Y + 14 + row * 24
    svg.append(f'<rect x="{LEG_X}" y="{y}" width="16" height="16" rx="3" {style}/>')
    svg.append(text(LEG_X + 24, y + 13, label, 15, 400, C["ink2"]))

# 5. Bar: what the land is
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"{total_km2 / 1e6:.2f} million km² of land in the EU, Norway and Switzerland", 21, 700))
segments = [
    (big3_km2 / total_km2, C["blue"], "Three empty patches"),
    ((empty_km2 - big3_km2) / total_km2, LIGHT_BLUE, "Other empty land"),
    (1 - empty_km2 / total_km2, C["page"], "Land with residents"),
]
x = BAR_X
for share, colour, label in segments:
    width = BAR_W * share
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    svg.append(text(x, BAR_Y + BAR_H + 23, f"{share:.0%}", 22, 700))
    svg.append(text(x, BAR_Y + BAR_H + 44, label, 17, 400, C["ink2"]))
    x += width

# 6. Headline, dek, byline and footer
svg.append(text(60, 90, "A third of the land in the EU, Norway and", 50, 800))
svg.append(text(60, 146, "Switzerland is just three empty patches", 50, 800))
svg.append(text(60, 190, f"Nobody lives on {empty_km2 / total_km2:.0%} of that land, counted in 1 km squares. Most of the", 25, 400, C["ink2"]))
svg.append(text(60, 220, "empty land joins up into three huge patches.", 25, 400, C["ink2"]))
svg.append(byline(252))
FOOTER = [
    ("Method:", "1 km squares where the 2021 census counted no usual residents join into one patch when they share a side."),
    ("Source:", "Eurostat, Census 2021 population grid (version 3), ©\u00a0European Union. Patches are own calculations. Base: Natural Earth."),
    ("Comments:", "empty means nobody lives there, not unused land. The grid covers the EU, Norway, Switzerland and Liechtenstein, and countries place residents on it slightly differently. 0.1% of residents could not be placed on the grid, none in Spain or Portugal."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)

save_png(page("".join(svg)), HERE / "day04_clusters.png")
results[["rank", "name", "km2", "cells", "x", "y"]].round(0).to_csv(HERE / "results.csv", index=False)
