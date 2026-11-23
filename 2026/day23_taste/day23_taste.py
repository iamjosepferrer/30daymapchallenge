"""Day 23, Taste: where wineries outnumber breweries, and where beer wins.

Every place that Overture Maps (release 2026-11-18.0) lists with the main category 'winery' or 'brewery', read by
extract_places.py. The map smooths both counts with an 8 km Gaussian kernel and colours each pixel by the share of
wineries among the two: blue where wine wins, amber where beer wins. Pixels with few places fade out.

A place counts for the country whose land it stands on (Natural Earth borders, Crimea with Ukraine), and places in the
sea within 1 km of the coast count for the nearest country. Every number on the chart counts only what the map shows.
"""
import base64
import io
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from PIL import Image
from pyproj import Transformer
from scipy.ndimage import gaussian_filter

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

WINE, BEER = C["blue"], C["apricot"]


def soften(hex_, share=0.15):
    """A pastel version of a colour: mixed with the page colour."""
    rgb_ = [int(hex_[i:i + 2], 16) for i in (1, 3, 5)]
    page_ = [int(C["page"][i:i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a + (b - a) * share):02X}" for a, b in zip(rgb_, page_))


WINE_MAP, BEER_MAP = soften(WINE), soften(BEER)  # pastel on the map, full colour on the bars
RIVERS_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_rivers_lake_centerlines.zip"
SHORT = {"United Kingdom": "UK", "Republic of Serbia": "Serbia", "Bosnia and Herzegovina": "Bosnia"}

# 1. Data: wineries and breweries, and the land each one stands on
raw = pd.read_parquet(HERE / "wineries_breweries.parquet")  # from extract_places.py
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
x, y = to3035.transform(raw.lon.values, raw.lat.values)
places = gpd.GeoDataFrame(raw, geometry=gpd.points_from_xy(x, y), crs=3035)
MAP_TOP = 204
frame = Frame(2380000, 6680000, 1480000, 5140000, 0, 1080, MAP_TOP)  # Day 21's frame, a little closer in
places = places[places.within(frame.box())].reset_index(drop=True)  # every number on the chart counts what the map shows
world = countries()
world["geometry"] = world.geometry.buffer(0)
# Natural Earth draws Crimea with Russia. It is Ukraine's by international law, so it joins Ukraine here.
crimea = shapely.box(32.3, 44.3, 36.65, 46.3)
ru, ua = world.index[world.ADMIN == "Russia"][0], world.index[world.ADMIN == "Ukraine"][0]
world.loc[ua, "geometry"] = world.geometry[ua].union(world.geometry[ru].intersection(crimea))
world.loc[ru, "geometry"] = world.geometry[ru].difference(crimea)
world = world.to_crs(3035)
on_land = gpd.sjoin(places, world[["ADMIN", "geometry"]], how="left", predicate="within")
places["country"] = on_land[~on_land.index.duplicated()].ADMIN
sea = places.country.isna()
coast = shapely.STRtree(world.geometry.values)  # a place in the sea within 1 km of the coast stands on a coastline drawn too simply
near, far = coast.query_nearest(places.geometry[sea].values, max_distance=1000, return_distance=False)
places.loc[places.index[sea][near], "country"] = world.ADMIN.values[far]
by_country = places.groupby(["country", "kind"]).size().unstack(fill_value=0).astype(int)
by_country["total"] = by_country.winery + by_country.brewery
by_country["wine_share"] = by_country.winery / by_country.total
wineries, breweries = int((places.kind == "winery").sum()), int((places.kind == "brewery").sum())
de = by_country.loc["Germany"]
print(f"{wineries:,} wineries, {breweries:,} breweries; Germany {int(de.winery):,} / {int(de.brewery):,} = {de.winery / de.brewery:.2f}")
assert 2.85 < de.winery / de.brewery < 3.15  # the README: Germany has three wineries for every brewery
beer = set(by_country[(by_country.total >= 100) & (by_country.wine_share < 0.5)].index)
assert beer == {"United Kingdom", "Ireland", "Belgium", "Netherlands", "Norway", "Sweden", "Finland", "Denmark", "Latvia",
                "Ukraine", "Russia", "Turkey"}  # the dek: where beer wins, among countries with 100+ places
four = by_country.sort_values("total", ascending=False).head(4)
assert set(four.index) == {"France", "Italy", "Germany", "Spain"} and (four.wine_share > 0.5).all()  # the dek
assert four.total.sum() / by_country.total.sum() > 2 / 3  # "two thirds of them"
# For the README: how many of Germany's wineries lie within 15 km of the Rhine or the Mosel (Natural Earth spells both several ways)
rivers = gpd.read_file(_download(RIVERS_URL, DATA_DIR / "ne_10m_rivers_lake_centerlines.zip"))
rhine_mosel = rivers[rivers.name.isin(["Rhine", "Rhein", "Rhin", "Mosel"])].to_crs(3035).union_all()
german = places[(places.country == "Germany") & (places.kind == "winery")]
by_rivers = (german.distance(rhine_mosel) <= 15_000).mean()
print(f"{by_rivers:.1%} of Germany's wineries lie within 15 km of the Rhine or the Mosel")
assert 0.5 <= by_rivers < 0.56  # "half"

# 2. Map: smoothed counts, coloured by the share of wineries, fading where there are few places
SCALE = 2
w, h = 1080 * SCALE, int(round(frame.ph * SCALE))
pixel = 1 / (frame.k * SCALE)  # metres per pixel
counts = {}
for kind in ("winery", "brewery"):
    sub = places[places.kind == kind]
    px = ((sub.geometry.x.values - frame.x0) / pixel).astype(int)
    py = ((frame.y1 - sub.geometry.y.values) / pixel).astype(int)
    grid = np.zeros((h, w))
    keep = (px >= 0) & (py >= 0) & (px < w) & (py < h)
    np.add.at(grid, (py[keep], px[keep]), 1)
    counts[kind] = gaussian_filter(grid, sigma=8_000 / pixel) / (pixel / 1000) ** 2  # places per km²
total = counts["winery"] + counts["brewery"]
share = np.where(total > 0, counts["winery"] / np.maximum(total, 1e-12), 0.5)
rgb = lambda hex_: np.array([int(hex_[i:i + 2], 16) for i in (1, 3, 5)], float)
mid = rgb(C["quiet_land"])  # an even mix fades into the land
t = share[..., None]
colour = np.where(t < 0.5, rgb(BEER_MAP) + (mid - rgb(BEER_MAP)) * (t / 0.5), mid + (rgb(WINE_MAP) - mid) * ((t - 0.5) / 0.5))
FULL = 0.03  # places per km² that make a pixel fully coloured: one every 33 km², about a 6 km square
SEE_THROUGH = 0.78  # the strongest colour still lets the borders show
alpha = np.clip(np.sqrt(total / FULL), 0, 1) * SEE_THROUGH
img = np.dstack([colour, alpha * 255]).astype(np.uint8)
buffer = io.BytesIO()
Image.fromarray(img, "RGBA").save(buffer, "PNG", optimize=True)
uri = base64.b64encode(buffer.getvalue()).decode()
land = world.geometry.intersection(frame.box()).union_all()
borders = shapely.union_all([g.boundary for g in world.geometry.intersection(frame.box().buffer(1)) if not g.is_empty]).intersection(frame.box())
lines = [g for g in getattr(borders, "geoms", [borders]) if g.geom_type == "LineString"]
border_d = "".join("M" + " L".join(f"{a:.1f} {b:.1f}" for a, b in (frame.xy(*c) for c in g.coords)) for g in lines)
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(land, frame)}" fill="{C["quiet_land"]}"/>',
       f'<image x="0" y="{MAP_TOP}" width="1080" height="{h / SCALE:.1f}" href="data:image/png;base64,{uri}"/>',
       f'<path d="{border_d}" fill="none" stroke="{C["ink2"]}" stroke-opacity=".75" stroke-width=".6" stroke-linejoin="round"/>',
       fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
       f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic, on the left margin: the colour ramp, then what fading means
LX, LY = 60, MAP_TOP + 185
svg.append(text(flush("W", 17, 700, LX), LY, "Wineries or breweries?", 17, 700))
svg.append(f'<defs><linearGradient id="ramp"><stop offset="0" stop-color="{BEER_MAP}"/><stop offset=".5" stop-color="{C["quiet_land"]}"/>'
           f'<stop offset="1" stop-color="{WINE_MAP}"/></linearGradient></defs>')
svg.append(f'<rect x="{LX + 1}" y="{LY + 14}" width="200" height="14" rx="2" fill="url(#ramp)" fill-opacity="{SEE_THROUGH}"/>')
svg.append(text(LX + 1, LY + 46, "More breweries", 14, 600, C["ink2"]))
svg.append(text(LX + 201, LY + 46, "More wineries", 14, 600, C["ink2"], "end"))
svg.append(text(flush("F", 14, 400, LX), LY + 70, "Fainter where there are few of either", 14, 400, C["ink2"]))

# 3. Bars: the five countries where wine wins most and the five where beer wins most, among those with 100 places or more
TOP = MAP_TOP + frame.ph + 24
ranked = by_country[by_country.total >= 100]
columns = [ranked.sort_values("wine_share", ascending=False).head(5), ranked.sort_values("wine_share").head(5)]
svg.append(text(flush("W", 19, 700), TOP, "Where wine wins most, and where beer wins most (wineries / breweries)", 19, 700))
for col, top in enumerate(columns):
    for row_i, (name, row) in enumerate(top.iterrows()):
        bx, yy = 60 + col * 490, TOP + 16 + row_i * 21
        label = SHORT.get(name, name)
        svg.append(text(flush(label, 14, 600, bx), yy + 12, label, 14, 600, C["ink"]))
        wine_w = 240 * row.wine_share
        svg.append(f'<rect x="{bx + 110}" y="{yy}" width="{wine_w:.1f}" height="15" fill="{WINE}"/>')
        svg.append(f'<rect x="{bx + 110 + wine_w:.1f}" y="{yy}" width="{240 - wine_w:.1f}" height="15" fill="{BEER}"/>')
        wine_pct = round(100 * row.wine_share)  # each bar names the share of the drink that wins
        if col == 0:
            svg.append(text(bx + 115, yy + 12, f"{wine_pct}% wineries", 12, 700, "#FFFFFF"))
        else:
            svg.append(text(bx + 345, yy + 12, f"{100 - wine_pct}% breweries", 12, 700, "#FFFFFF", "end"))
        svg.append(text(bx + 360, yy + 12, f"{int(row.winery):,} / {int(row.brewery):,}", 13, 600, C["ink2"]))
BASE = TOP + 16 + 5 * 21

# 4. Headline, dek, byline and footer
HEAD = [(80, "Where wine ends and beer begins", 46, 800, C["ink"]),
        (124, f"Overture Maps lists {wineries:,} wineries and {breweries:,} breweries. Beer wins in the British Isles, the", 22, 400, C["ink2"]),
        (152, "Low Countries, the Nordics, the Baltics, Ukraine, Russia and Turkey. Wine wins in the rest.", 22, 400, C["ink2"])]
for yy, words, size, weight, colour_ in HEAD:
    svg.append(text(flush(words, size, weight), yy, words, size, weight, colour_))
svg.append(byline(186, "30DayMapChallenge #23: Senses: Taste").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
svg += footer([
    ("Method:", "places whose main category is winery or brewery, smoothed over about 8 km. Bars: countries with 100+ places."),
    ("Source:", "Overture Maps places (release 2026-11-18), mostly from Meta and BrightQuery listings. Borders: Natural Earth."),
    ("Comments:", "listings are not official registers: some wine shops and bars are listed as wineries and breweries."),
], x=round(flush("M", 17, 700), 1), y=BASE + 28, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day23_wine_beer.png")
by_country.sort_values("total", ascending=False).round({"wine_share": 3}).rename_axis("country").to_csv(HERE / "wineries_breweries_by_country.csv")
