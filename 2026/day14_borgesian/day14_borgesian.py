"""Day 14, Borgesian map: Europe's rivers, by the sea they end in.

No borders and no coastlines: the map is only rivers and streams, from WWF's HydroRIVERS, each in the colour of the
sea its river reaches. The bar under the map shows how much of the EU's land drains into each sea.
"""
import base64
import io
import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import shapely
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, _download, byline, countries, footer, page, save_png, text  # noqa: E402

RIVERS_URL = "https://data.hydrosheds.org/file/HydroRIVERS/HydroRIVERS_v10_eu_shp.zip"
SEAS_URL = "https://naciscdn.org/naturalearth/10m/physical/ne_10m_geography_marine_polys.zip"
SEAS = {  # each named sea or gulf in Natural Earth, grouped into the sea a river ends in
    "Atlantic Ocean": ["North Atlantic Ocean", "Bay of Biscay", "Irish Sea", "Bristol Channel", "English Channel", "Denmark Strait",
                       "Greenland Sea", "Norwegian Sea", "Vestfjorden", "Sognefjorden", "Trondheimsfjorden", "Inner Seas"],
    "North Sea": ["North Sea", "Waddenzee", "Skagerrak", "Boknafjorden"],
    "Baltic Sea": ["Baltic Sea", "Gulf of Bothnia", "Gulf of Finland", "Gulf of Riga", "Kattegat", "Øresund", "Mecklenburger Bucht",
                   "Stettiner Haff", "Kaliningrad"],
    "Mediterranean": ["Mediterranean Sea", "Strait of Gibraltar", "Alboran Sea", "Balearic Sea", "Golfe du Lion", "Ligurian Sea",
                      "Tyrrhenian Sea", "Ionian Sea", "Adriatic Sea", "Aegean Sea", "Sea of Crete", "Gulf of Gabès", "Gulf of Sidra",
                      "Dardanelles", "Sea of Marmara"],
    "Black Sea": ["Black Sea", "Sea of Azov", "Bosporus"],
    "Arctic Ocean": ["Barents Sea", "White Sea"],
    "Caspian Sea": ["Caspian Sea"],
}
GROUP = {name: sea for sea, names in SEAS.items() for name in names}
COLOURS = {"Atlantic Ocean": "#2E5A93", "North Sea": "#3E8A86", "Baltic Sea": "#7A5C9E", "Mediterranean": "#C4553A",
           "Black Sea": "#D9A21B", "Arctic Ocean": "#8FB0CF", "Caspian or inland": "#A69C8A"}
EU = ["Austria", "Belgium", "Bulgaria", "Croatia", "Cyprus", "Czechia", "Denmark", "Estonia", "Finland", "France", "Germany", "Greece",
      "Hungary", "Ireland", "Italy", "Latvia", "Lithuania", "Luxembourg", "Malta", "Netherlands", "Poland", "Portugal", "Romania",
      "Slovakia", "Slovenia", "Spain", "Sweden"]
ASIA = ["Syria", "Iraq", "Iran", "Georgia", "Armenia", "Azerbaijan", "Lebanon", "Israel", "Jordan", "Kazakhstan"]

# The view, in EPSG:3035: Iceland to Cyprus, Crete to the North Cape
MAP_TOP, MAP_H = 218, 944
Y0, Y1 = 1400000, 5360000
K = MAP_H / (Y1 - Y0)  # canvas pixels per metre
X0, X1 = 4550000 - 540 / K, 4550000 + 540 / K
SS = 4  # drawing pixels per canvas pixel, shrunk to 2 at the end for smooth lines


class Canvas:
    """Draws hundreds of thousands of lines into one image, far faster and smaller than as SVG paths."""

    def __init__(self):
        self.img = Image.new("RGBA", (1080 * SS, MAP_H * SS), (0, 0, 0, 0))
        self.pen = ImageDraw.Draw(self.img)

    def lines(self, geoms, colour, widths):
        rgb = tuple(int(colour[i:i + 2], 16) for i in (1, 3, 5)) + (255,)
        for geom, width in zip(geoms, widths):
            for part in getattr(geom, "geoms", [geom]):
                xy = np.asarray(part.coords)
                points = np.column_stack([(xy[:, 0] - X0) * K * SS, (Y1 - xy[:, 1]) * K * SS])
                self.pen.line([tuple(p) for p in points], fill=rgb, width=max(1, round(width * SS)), joint="curve")

    def svg(self):
        buffer = io.BytesIO()
        self.img.resize((1080 * 2, MAP_H * 2), Image.LANCZOS).save(buffer, "PNG", optimize=True)
        uri = base64.b64encode(buffer.getvalue()).decode()
        return f'<image x="0" y="{MAP_TOP}" width="1080" height="{MAP_H}" href="data:image/png;base64,{uri}"/>'


# 1. Data: every river stretch in Europe and the Middle East, and the named seas
rivers_zip = _download(RIVERS_URL, DATA_DIR / "HydroRIVERS_v10_eu_shp.zip")
rivers = gpd.read_file(f"zip://{rivers_zip}!HydroRIVERS_v10_eu_shp/HydroRIVERS_v10_eu.shp",
                       columns=["HYRIV_ID", "MAIN_RIV", "UPLAND_SKM", "CATCH_SKM", "ENDORHEIC"]).to_crs(3035)
seas_zip = _download(SEAS_URL, DATA_DIR / "ne_10m_geography_marine_polys.zip")
seas = gpd.read_file(f"zip://{seas_zip}")
seas = seas[seas.name.isin(GROUP)].assign(sea=lambda s: s.name.map(GROUP)).to_crs(3035)

# 2. Each river system ends at its outlet stretch; the sea nearest that stretch's mouth is where all its water goes
outlets = rivers[rivers.HYRIV_ID == rivers.MAIN_RIV].copy()
outlets["geometry"] = outlets.geometry.apply(lambda g: shapely.Point(g.coords[-1]))
mouths = gpd.sjoin_nearest(outlets[["MAIN_RIV", "ENDORHEIC", "geometry"]], seas[["sea", "geometry"]], how="left")
mouths = mouths.drop_duplicates("MAIN_RIV").set_index("MAIN_RIV")
mouths.loc[(mouths.ENDORHEIC == 1) | (mouths.sea == "Caspian Sea"), "sea"] = "Caspian or inland"  # the Volga, and closed basins
rivers["sea"] = rivers.MAIN_RIV.map(mouths.sea)
assert rivers.sea.notna().all()

# 3. The share of EU land that drains into each sea: each stretch's own catchment, where the stretch lies in the EU
world = countries()
eu_land = world[world.ADMIN.isin(EU)].to_crs(3035).geometry.buffer(0).union_all()
middle = rivers.geometry.interpolate(0.5, normalized=True)
in_eu = shapely.contains_xy(eu_land, middle.x.values, middle.y.values)
share = rivers[in_eu].groupby("sea").CATCH_SKM.sum()
share = share / share.sum()
print(share.round(3).sort_values(ascending=False).to_string())
assert share.idxmax() == "Baltic Sea" and 0.28 < share["Baltic Sea"] < 0.35  # "about a third"

# 4. The rivers drawn: stretches draining at least 50 km² in view; those in Asia are drawn but not counted
view = shapely.box(X0 - 50000, Y0 - 50000, X1 + 50000, Y1 + 50000)
shown = rivers[(rivers.UPLAND_SKM >= 50) & rivers.intersects(view)].copy()
shown["width"] = 0.22 + 0.5 * np.log10(shown.UPLAND_SKM / 50)  # wider the more land a stretch drains
turkey = world[world.ADMIN == "Turkey"].geometry.iloc[0]
anatolia = max(getattr(turkey, "geoms", [turkey]), key=lambda g: g.area)  # Thrace, the European part, is the smaller piece
asia = gpd.GeoSeries([anatolia, *world[world.ADMIN.isin(ASIA)].geometry], crs=4326).to_crs(3035).buffer(0).union_all()
middle = shown.geometry.interpolate(0.5, normalized=True)
counted = int((~shapely.contains_xy(asia, middle.x.values, middle.y.values)).sum())
print(f"{len(shown):,} stretches drawn, {counted:,} of them in Europe")

canvas = Canvas()
for sea, colour in COLOURS.items():
    part = shown[shown.sea == sea].sort_values("UPLAND_SKM")  # big rivers on top of their tributaries
    canvas.lines(part.geometry.values, colour, part.width.values)
svg = [canvas.svg()]

# 5. Headline, dek and byline
svg.append(text(60, 78, "Europe's rivers, by the sea they end in", 46, 800))
svg.append(text(60, 116, f"{counted / 1000:.0f}k stretches of European river and stream, each draining at least 50 km².", 24, 400, C["ink2"]))
svg.append(text(60, 145, "About a third of the EU's land drains into the Baltic Sea.", 24, 400, C["ink2"]))
svg.append(byline(178))
svg.append(text(60, 204, "30DayMapChallenge, day 14: Borgesian map", 18, 600, C["ink2"]))

# 6. A small bar under the map: the share of EU land that drains into each sea, which doubles as the colour legend
LY = MAP_TOP + MAP_H + 16
svg.append(text(60, LY, "Share of EU land that drains into each sea", 17, 700))
BAR_Y, BAR_H, GAP = LY + 10, 14, 2
order = sorted(COLOURS, key=lambda sea: -share.get(sea, 0))
small = [sea for sea in order if share.get(sea, 0) < 0.05]
x = 60
for sea in order:
    width = 960 * share.get(sea, 0)
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{max(width - GAP, 1):.1f}" height="{BAR_H}" rx="2" fill="{COLOURS[sea]}"/>')
    if sea not in small:
        svg.append(text(x, BAR_Y + BAR_H + 19, f"{share[sea]:.0%}", 16, 700, C["ink"]))
        svg.append(text(x, BAR_Y + BAR_H + 37, sea.replace(" Ocean", ""), 15, 400, C["ink2"]))
    x += width
rest = sum(share.get(sea, 0) for sea in small)
svg.append(text(1020, LY, f"Arctic and Caspian, {rest:.0%} together", 15, 400, C["ink2"], "end"))
svg.append(f'<path d="M1016 {LY + 5} L1016 {BAR_Y - 2}" stroke="{C["ink2"]}" stroke-width="1"/>')
svg += footer([("Method:", "each river takes the colour of the sea nearest its mouth, and gets wider the more land it drains."),
               ("Source:", "Lehner and Grill (2013), HydroRIVERS, WWF HydroSHEDS. Seas from Natural Earth."),
               ("Comments:", "rivers in Asian Turkey are drawn but not counted. The shares are of EU land only.")],
              x=60, y=BAR_Y + BAR_H + 68, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day14_borgesian.png")
share.rename("share_of_eu_land").round(4).sort_values(ascending=False).to_csv(HERE / "eu_land_by_sea.csv", index_label="sea")
