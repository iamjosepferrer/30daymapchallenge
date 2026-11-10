"""Day 11, Senses: Sound: how many people in EU cities live with road noise above 55 dB.

Strategic noise maps that EU countries report to the EEA under the Environmental Noise Directive (2022 round, data
for 2021): residents of each city of more than 100,000 people by road-noise band (Lden, day-evening-night average).
The WHO recommends keeping road noise below 53 dB Lden. The EU bands start at 55 dB, so the counts here are a floor.
"""
import json
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

NOISE_URL = "https://sdi.eea.europa.eu/datashare/s/AXa6TQLwani5GHG/download"  # EEA, noise exposure END 2022, v02 (Nov 2024)
NOISE_FILE = "Summary_END_2022_cutoff241118_v4.xlsx"
GEOCODER = "https://gisco-services.ec.europa.eu/api?"
BANDS = ["b55", "b60", "b65", "b70", "b75"]  # 55-59, 60-64, 65-69, 70-74, 75 dB and more
ISO = {"Austria": "AT", "Belgium": "BE", "Bulgaria": "BG", "Croatia": "HR", "Cyprus": "CY", "Czech Republic": "CZ",
       "Denmark": "DK", "Estonia": "EE", "Finland": "FI", "France": "FR", "Germany": "DE", "Greece": "GR", "Hungary": "HU",
       "Ireland": "IE", "Italy": "IT", "Latvia": "LV", "Lithuania": "LT", "Luxembourg": "LU", "Malta": "MT", "Netherlands": "NL",
       "Poland": "PL", "Portugal": "PT", "Romania": "RO", "Slovakia": "SK", "Slovenia": "SI", "Spain": "ES", "Sweden": "SE"}
# Places the geocoder gets wrong or can't find, set by hand (lon, lat)
FIXED = {
    "Oulu": (25.4651, 65.0121), "Beauchamp": (2.1897, 49.0131), "Torcy": (2.6511, 48.8503), "Frankfurt on the Main": (8.6821, 50.1109),
    "Offenbach on the Main": (8.7761, 50.0956), "Milan-Monza": (9.2744, 45.5845), "Luxembourg_south": (5.9806, 49.4958),
    "Kosicka": (21.2611, 48.7164), "Baix Llobregat Nord": (2.0400, 41.3800), "Baix Llobregat Sud": (2.0100, 41.2800),
    "Barcelones Nord": (2.2450, 41.4500), "Valles Occidental II": (2.1180, 41.5140), "Vitoria - Gazteiz": (-2.6727, 42.8467),
    "Athens Center": (23.7275, 37.9838), "Athens North": (23.8000, 38.0500), "Ioannina": (20.8530, 39.6650),
    "Iraklion": (25.1442, 35.3387), "Larissa": (22.4191, 39.6390), "Patras": (21.7346, 38.2466), "Piraeus": (23.6460, 37.9420),
    "Thessaloniki": (22.9444, 40.6401), "Volos": (22.9420, 39.3620), "Venice": (12.3155, 45.4408),
}

# 1. Residents of each city by road-noise band
archive = _download(NOISE_URL, DATA_DIR / "eea_noise_exposure_end2022_v02.zip")
xlsx = DATA_DIR / NOISE_FILE
if not xlsx.exists():
    with zipfile.ZipFile(archive) as z:
        xlsx.write_bytes(z.read(next(n for n in z.namelist() if n.endswith(NOISE_FILE))))
raw = pd.read_excel(xlsx, "Aggl_Road_Data", header=None, skiprows=6).iloc[:, :12]
raw.columns = ["country", "eu", "name", "inh", "area", "b45", "b50", *BANDS]
cities = raw[(raw.eu == "EU27") & raw.name.notna()].copy()
for column in ["inh", *BANDS]:
    cities[column] = pd.to_numeric(cities[column], errors="coerce")  # "No data" becomes empty
cities["loud"] = cities[BANDS].sum(axis=1, min_count=len(BANDS))  # residents at 55 dB or more, only if every band is there
cities["share"] = cities.loud / cities.inh
reported = cities.dropna(subset=["loud"])

# 2. Where each city is: GISCO's geocoder, saved once, with hand fixes
places = HERE / "city_locations.csv"
if not places.exists():
    rows = []
    for _, city in cities.iterrows():
        query = GEOCODER + urllib.parse.urlencode({"q": city["name"], "limit": 5})
        found = [f for f in json.load(urllib.request.urlopen(query, timeout=30))["features"]
                 if f["properties"].get("countrycode") == ISO[city.country]]
        best = next((f for f in found if f["properties"].get("osm_value") in ("city", "town", "municipality", "administrative")),
                    found[0] if found else None)
        rows.append({"country": city.country, "name": city["name"],
                     "lon": best["geometry"]["coordinates"][0] if best else np.nan,
                     "lat": best["geometry"]["coordinates"][1] if best else np.nan})
        time.sleep(0.15)
    pd.DataFrame(rows).to_csv(places, index=False)
where = pd.read_csv(places).set_index(["country", "name"])
for name, (lon, lat) in FIXED.items():
    where.loc[where.index.get_level_values("name") == name, ["lon", "lat"]] = lon, lat
cities = cities.join(where, on=["country", "name"])
assert cities.lon.notna().all(), cities[cities.lon.isna()].name.tolist()

# 3. The numbers on the chart
total = reported.inh.sum()
loud_share = reported.loud.sum() / total
band_shares = {"below": 1 - loud_share, **{b: reported[b].sum() / total for b in BANDS}}
most_loud = (reported.share >= 0.5).sum()
paris = reported.set_index("name").loc["Paris"]
print(f"{len(reported)} of {len(cities)} EU cities report every band; {total / 1e6:.1f}M residents, {loud_share:.1%} at 55 dB or more")
print(f"{most_loud} cities where most people are at 55 dB or more; bands {({k: round(v, 3) for k, v in band_shares.items()})}")
print(f"Paris {paris.loud / 1e6:.2f}M of {paris.inh / 1e6:.2f}M ({paris.share:.0%})")
assert 0.45 < loud_share < 0.5  # "almost half"
assert most_loud == 106
cities.drop(columns=["eu"]).round(3).to_csv(HERE / "road_noise_by_city.csv", index=False)

# 4. Map: one circle per city, sized by residents; blue where most residents live with 55 dB or more
MAP_TOP = 410
# Zoomed to the cities: Lisbon to Cyprus, Valletta to Oulu. The Canaries and other outermost regions are counted but not drawn.
frame = Frame(2327500, 6792500, 1390000, 4800000, 0, 1080, MAP_TOP - 5)
land = countries().to_crs(3035).geometry.buffer(0).intersection(frame.box().buffer(50000))
EU_NAMES = [n.replace("Czech Republic", "Czechia") for n in ISO]
world = countries().to_crs(3035)
assert world.ADMIN.isin(EU_NAMES).sum() == 27
eu_land = world[world.ADMIN.isin(EU_NAMES)].geometry.buffer(0)
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(land.union_all(), frame)}" fill="{C["quiet_land"]}"/>',
       f'<path d="{geom_path(eu_land.intersection(frame.box().buffer(50000)).union_all(), frame)}" fill="{C["page"]}"/>']
xy = Transformer.from_crs(4326, 3035, always_xy=True)
cities["x"], cities["y"] = zip(*(frame.xy(*xy.transform(lon, lat)) for lon, lat in zip(cities.lon, cities.lat)))
# Greek cities come with no head count at all, so they get the smallest size, that of a city of 100,000
cities["r"] = 3 + 20 * np.sqrt(cities.inh.fillna(100_000) / 7_000_000)
QUIET, LOUD = "#C2B7A3", C["blue"]  # the same two colours in the bar and on the map: under 55 dB, 55 dB or more

for _, city in cities.sort_values("inh", ascending=False).iterrows():  # small ones on top
    if np.isnan(city.share):
        svg.append(f'<circle cx="{city.x:.1f}" cy="{city.y:.1f}" r="{city.r:.1f}" fill="none" stroke="{C["ink2"]}" stroke-width=".8" stroke-opacity=".5"/>')
    else:
        fill = LOUD if city.share >= 0.5 else QUIET
        svg.append(f'<circle cx="{city.x:.1f}" cy="{city.y:.1f}" r="{city.r:.1f}" fill="{fill}" stroke="{C["page"]}" stroke-width=".8"/>')
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over Russia, outside the EU, top right
LX, LY = 772, 452
svg.append(text(LX, LY, "Each circle is a city,", 17, 700))
svg.append(text(LX, LY + 21, "sized by residents", 17, 700))
LY += 21
legend = [(LOUD, f"Most residents at 55 dB or more ({most_loud})"), (QUIET, f"Most residents under 55 dB ({len(reported) - most_loud})")]
for i, (fill, label) in enumerate(legend):
    svg.append(f'<circle cx="{LX + 8}" cy="{LY + 22 + i * 25}" r="7.5" fill="{fill}"/>')
    svg.append(text(LX + 24, LY + 27 + i * 25, label, 15, 400, C["ink2"]))
y = LY + 22 + 2 * 25
svg.append(f'<circle cx="{LX + 8}" cy="{y}" r="7" fill="none" stroke="{C["ink2"]}" stroke-width=".8" stroke-opacity=".6"/>')
svg.append(text(LX + 24, y + 5, f"No data reported ({len(cities) - len(reported)})", 15, 400, C["ink2"]))

# Note on Paris, over the Channel
px, py = frame.xy(*xy.transform(2.35, 48.86))
note_x, note_y = 40, 792
svg.append(f'<text class="note" x="{note_x}" y="{note_y}" font-size="22" fill="{C["ink"]}"><tspan x="{note_x}">In Paris, {paris.loud / 1e6:.1f} million</tspan>'
           f'<tspan x="{note_x}" dy="27">people live with it</tspan></text>')
sx, sy = note_x + 222, note_y + 20
svg.append(f'<path d="M{sx} {sy} C {sx + 40} {sy + 10}, {px - 50} {py + 10}, {px - 26:.1f} {py:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{px - 38:.1f} {py - 5:.1f} L{px - 26:.1f} {py:.1f} L{px - 37:.1f} {py + 8:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# Bar: residents of the reporting cities by road-noise band
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"{total / 1e6:.0f} million residents of {len(reported)} EU cities, by road noise at home", 21, 700))
x = BAR_X
for value, label, fill in [(1 - loud_share, "Under 55 dB", QUIET), (loud_share, "55 dB or more", LOUD)]:
    width = BAR_W * value
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{fill}"/>')
    svg.append(text(x + (width - GAP) / 2, BAR_Y + BAR_H + 23, f"{value:.0%}", 22, 700, None, "middle"))
    svg.append(text(x + (width - GAP) / 2, BAR_Y + BAR_H + 43, label, 15, 400, C["ink2"], "middle"))
    x += width

svg.append(text(60, 90, "Almost half of people in EU cities live", 50, 800))
svg.append(text(60, 146, "with road noise louder than WHO advises", 50, 800))
svg.append(text(60, 190, f"Residents of {len(reported)} EU cities with road noise of 55 dB or more at home, 2021.", 25, 400, C["ink2"]))
svg.append(text(60, 220, "The WHO advises keeping it under 53 dB, so the real share is even higher.", 25, 400, C["ink2"]))
svg.append(byline(252, "30DayMapChallenge #11: Senses, Sound"))
FOOTER = [
    ("Method:", "each EU country models road noise in its cities of over 100,000 people and counts the residents in each 5 dB band, "
                "as EU law asks. A city is blue when most of its residents live with 55 dB or more."),
    ("Source:", "European Environment Agency (2022 round, data for 2021), WHO noise guidelines (2018), GISCO, Natural Earth."),
    ("Comments:", f"{len(cities) - len(reported)} of the {len(cities)} cities didn't report every band, among them all those in Bulgaria, "
                  "Greece, Hungary, Slovakia and Slovenia. Countries model noise in their own way, so compare cities within a country."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day11_sound.png")
