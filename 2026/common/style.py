"""Shared style, data downloads and rendering for the 2026 maps."""
import asyncio
import base64
import html
import io
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import requests
from PIL import ImageFont
from playwright.async_api import async_playwright
from shapely.geometry import box

YEAR_DIR = Path(__file__).resolve().parents[1]
DATA_DIR = YEAR_DIR / "data"
FONT_DIR = YEAR_DIR / "common" / "fonts"

# Canvas in px. Screenshots are taken at 2x.
W, H = 1080, 1350

# Oat palette
C = dict(
    page="#F5EFE3", card="#DDD3C1", rule="#DFD5C3", ink="#1F2433", ink2="#4B5060",
    muted="#4B5060", blue="#2E5A93", apricot="#B36F1E", sage="#3A8758",
    ctx="#A8A196", ctxl="#CFC5B3", quiet_land="#E9E1D2",
)

UCDB_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_UCDB_GLOBE_R2024A/"
    "GHS_UCDB_REGION_GLOBE_R2024A/GHS_UCDB_REGION_EUROPE_R2024A/V1-2/"
    "GHS_UCDB_REGION_EUROPE_R2024A_V1_2.zip"
)
UCDB_LAYER = "GHSL_UCDB_THEME_GENERAL_CHARACTERISTICS_GLOBE_R2024A"
COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_50m_admin_0_countries.geojson"
)
FONT_URLS = {
    "Gabarito.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/gabarito/Gabarito%5Bwght%5D.ttf",
    "ShantellSans.ttf": "https://raw.githubusercontent.com/google/fonts/main/ofl/shantellsans/ShantellSans%5BBNCE%2CINFM%2CSPAC%2Cwght%5D.ttf",
}


def _download(url, path):
    if path.exists():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {path.name}")
    response = requests.get(url, timeout=300)
    response.raise_for_status()
    path.write_bytes(response.content)
    return path


def ucdb_path():
    """Download the European GHS Urban Centre Database once and return its path."""
    path = DATA_DIR / "GHS_UCDB_REGION_EUROPE_R2024A.gpkg"
    if not path.exists():
        print("Downloading GHS-UCDB Europe (35 MB)")
        response = requests.get(UCDB_URL, timeout=600)
        response.raise_for_status()
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            archive.extract(path.name, DATA_DIR)
    return path


def load_urban_centres():
    """Return urban centres with names, population and WGS84 and EPSG:3035 positions."""
    columns = ["ID_UC_G0", "GC_UCN_MAI_2025", "GC_CNT_GAD_2025", "GC_POP_TOT_2025"]
    gdf = gpd.read_file(ucdb_path(), layer=UCDB_LAYER, columns=columns)
    gdf.columns = ["id", "name", "cnt", "pop", "geometry"]
    points = gdf.geometry.representative_point()
    wgs84 = points.to_crs(4326)
    laea = points.to_crs(3035)
    gdf["lon"], gdf["lat"] = wgs84.x, wgs84.y
    gdf["X"], gdf["Y"] = laea.x, laea.y
    return gdf


def countries():
    path = _download(COUNTRIES_URL, DATA_DIR / "ne_50m_admin_0_countries.geojson")
    return gpd.read_file(path)[["ADMIN", "geometry"]]


class Frame:
    """Maps EPSG:3035 metres to canvas pixels."""

    def __init__(self, x0, x1, y0, y1, px0, px1, py0):
        self.x0, self.x1, self.y0, self.y1 = x0, x1, y0, y1
        self.px0, self.py0 = px0, py0
        self.k = (px1 - px0) / (x1 - x0)
        self.ph = (y1 - y0) * self.k
        self.pw = px1 - px0

    def xy(self, x, y):
        return self.px0 + (x - self.x0) * self.k, self.py0 + (self.y1 - y) * self.k

    def box(self):
        return box(self.x0, self.y0, self.x1, self.y1)


def geom_path(geom, frame):
    """Turn a polygon or multipolygon into an SVG path."""
    out = []
    polygons = geom.geoms if geom.geom_type.startswith("Multi") else [geom]
    for polygon in polygons:
        if polygon.is_empty:
            continue
        for ring in [polygon.exterior, *polygon.interiors]:
            coords = np.array(ring.coords)[:, :2]
            xs, ys = frame.xy(coords[:, 0], coords[:, 1])
            out.append("M" + "L".join(f"{a:.1f} {b:.1f}" for a, b in zip(xs, ys)) + "Z")
    return "".join(out)


def land_paths(frame, with_data):
    """Return paths for land without data (quiet) and land with data."""
    land = countries().to_crs(3035)
    land["geometry"] = land.geometry.buffer(0).intersection(frame.box())
    land = land[~land.geometry.is_empty]
    inside = land[land.ADMIN.isin(with_data)].union_all()
    outside = land[~land.ADMIN.isin(with_data)].union_all()
    return geom_path(outside, frame), geom_path(inside, frame)


def text(x, y, words, size, weight=400, fill=None, anchor="start", halo=None):
    colour = fill or C["ink"]
    style = (
        f' style="paint-order:stroke;stroke:{halo};stroke-width:5px;stroke-linejoin:round"'
        if halo else ""
    )
    return (
        f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" '
        f'fill="{colour}" text-anchor="{anchor}"{style}>{html.escape(words)}</text>'
    )


def fade_defs():
    """Gradients that fade the land into the card at the map edges."""
    stops = (
        f'<stop offset="0" stop-color="{C["card"]}"/>'
        f'<stop offset="1" stop-color="{C["card"]}" stop-opacity="0"/>'
    )
    return (
        f'<defs><linearGradient id="fade-top" x1="0" y1="0" x2="0" y2="1">{stops}</linearGradient>'
        f'<linearGradient id="fade-bottom" x1="0" y1="1" x2="0" y2="0">{stops}</linearGradient>'
        f'<linearGradient id="fade-right" x1="1" y1="0" x2="0" y2="0">{stops}</linearGradient></defs>'
    )


def byline(y, series=None):
    """The byline, optionally followed by the challenge day, such as "30DayMapChallenge #8: Utopia"."""
    words = "Map by Josep Ferrer, @iamjosepferrer on LinkedIn and X, databites.tech"
    if series:
        words += f". {series}"
    return text(60, y, words, 20, 600, C["ink2"])


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
            words = html.escape(words, quote=False)
            first = f'<tspan font-weight="700" fill="{C["ink2"]}">{label}</tspan> ' if row == 0 else ""
            out.append(f'<text x="{x}" y="{y}" font-size="{size}" fill="{C["muted"]}">{first}{words}</text>')
            y += line_height
    return out


def page(body):
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
        f'<rect width="{W}" height="{H}" fill="{C["card"]}"/>'
        f"{body}</svg>"
    )


def _css():
    for name, url in FONT_URLS.items():
        _download(url, FONT_DIR / name)
    gabarito = base64.b64encode((FONT_DIR / "Gabarito.ttf").read_bytes()).decode()
    shantell = base64.b64encode((FONT_DIR / "ShantellSans.ttf").read_bytes()).decode()
    return f"""@font-face{{font-family:Gabarito;src:url(data:font/ttf;base64,{gabarito});font-weight:400 900}}
@font-face{{font-family:Shantell;src:url(data:font/ttf;base64,{shantell});font-weight:300 800}}
html,body{{margin:0;padding:0;width:{W}px;height:{H}px;background:{C['page']}}}
svg{{display:block}} text{{font-family:Gabarito,sans-serif}} .note{{font-family:Shantell,cursive;font-weight:500}}"""


async def _screenshot(svg, out):
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        tab = await browser.new_page(viewport=dict(width=W, height=H), device_scale_factor=2)
        await tab.set_content(f"<!doctype html><meta charset=utf-8><style>{_css()}</style>{svg}")
        await tab.evaluate("document.fonts.ready")
        await tab.wait_for_timeout(300)
        await tab.screenshot(path=str(out))
        await browser.close()


def save_png(svg, out):
    asyncio.run(_screenshot(svg, out))
    print(f"Saved {out}")
