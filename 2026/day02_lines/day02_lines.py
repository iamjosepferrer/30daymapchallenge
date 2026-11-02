"""Day 2, Lines: Europe's biggest port is the nearest one for under 4% of city dwellers."""
import collections
import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import polyline
import requests
from pyproj import Transformer
from shapely.geometry import LineString
from shapely.ops import unary_union
from shapely.prepared import prep

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, Frame, byline, countries, fade_defs, land_paths, load_urban_centres, page, save_png, text  # noqa: E402

CACHE = HERE / "cache"
ROUTES = CACHE / "routes"
OSRM = "https://router.project-osrm.org"
HEADERS = {"User-Agent": "30DayMapChallenge personal map (low volume)"}

# Top 10 container ports by TEU, with approximate container terminal coordinates
PORTS = {
    "Rotterdam": (4.03, 51.96), "Antwerp-Bruges": (4.30, 51.30), "Hamburg": (9.93, 53.53),
    "Valencia": (-0.32, 39.44), "Bremerhaven": (8.55, 53.58), "Algeciras": (-5.44, 36.13),
    "Piraeus": (23.60, 37.96), "Gioia Tauro": (15.90, 38.45), "Barcelona": (2.16, 41.34),
    "Felixstowe": (1.33, 51.95),
}
PORT_NAMES = list(PORTS)
# Sensitivity check: Rotterdam measured from a terminal closer to the city
WAALHAVEN = (4.44, 51.89)
EXCLUDED = ["Russia", "Belarus", "Ukraine", "Iceland"]
NO_ROUTES_THROUGH = ["Ukraine", "Belarus", "Russia"]
LAND_WITH_DATA = {
    "United Kingdom", "Ireland", "France", "Spain", "Portugal", "Germany", "Netherlands",
    "Belgium", "Luxembourg", "Switzerland", "Austria", "Italy", "Denmark", "Norway", "Sweden",
    "Finland", "Estonia", "Latvia", "Lithuania", "Poland", "Czechia", "Slovakia", "Hungary",
    "Slovenia", "Croatia", "Bosnia and Herzegovina", "Republic of Serbia", "Montenegro", "Kosovo",
    "North Macedonia", "Albania", "Greece", "Bulgaria", "Romania", "Moldova", "Malta", "Andorra",
    "Liechtenstein", "Monaco", "San Marino", "Vatican", "Jersey", "Guernsey", "Isle of Man",
}


def get_json(url):
    for attempt in range(6):
        try:
            response = requests.get(url, headers=HEADERS, timeout=60)
            response.raise_for_status()
            return response.json()
        except requests.RequestException as error:
            print(f"Retrying after: {error}")
            time.sleep(8 * (attempt + 1))
    raise RuntimeError(f"OSRM request failed: {url}")


def driving_table(cities):
    """Driving times and distances from each city to each port. Cached after the first run."""
    path = CACHE / "table.npz"
    if path.exists():
        saved = np.load(path)
        if list(saved["ids"]) == list(cities.id):
            return saved["durations"], saved["distances"]
    destinations = [*PORTS.values(), WAALHAVEN]
    coords = ";".join(f"{lon},{lat}" for lon, lat in destinations)
    durations = np.full((len(cities), len(destinations)), np.nan)
    distances = durations.copy()
    batch = 85
    for start in range(0, len(cities), batch):
        chunk = cities.iloc[start:start + batch]
        sources = ";".join(f"{lon:.5f},{lat:.5f}" for lon, lat in zip(chunk.lon, chunk.lat))
        source_ids = ";".join(map(str, range(len(chunk))))
        destination_ids = ";".join(map(str, range(len(chunk), len(chunk) + len(destinations))))
        data = get_json(
            f"{OSRM}/table/v1/driving/{sources};{coords}"
            f"?sources={source_ids}&destinations={destination_ids}&annotations=duration,distance"
        )
        durations[start:start + batch] = np.array(data["durations"], dtype=float)
        distances[start:start + batch] = np.array(data["distances"], dtype=float)
        print(f"Driving table: {min(start + batch, len(cities))} of {len(cities)} cities", flush=True)
        time.sleep(1.2)
    CACHE.mkdir(exist_ok=True)
    np.savez(path, ids=cities.id.values, durations=durations, distances=distances)
    return durations, distances


def get_route(city, port):
    """Fetch one route, or read it from the cache."""
    path = ROUTES / f"{int(city.id)}_{port.replace(' ', '-')}.json"
    if path.exists():
        return json.loads(path.read_text())
    lon, lat = PORTS[port]
    data = get_json(
        f"{OSRM}/route/v1/driving/{city.lon:.5f},{city.lat:.5f};{lon},{lat}"
        "?overview=full&geometries=polyline&steps=false"
    )
    route = data["routes"][0]
    result = dict(g=route["geometry"], d=route["distance"], t=route["duration"])
    ROUTES.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result))
    time.sleep(1.05)
    return result


# 1. Cities in scope
cities = load_urban_centres()
cities = cities[(cities.lon <= 60) & (cities.lon > -10.5) & (~cities.cnt.isin(EXCLUDED))]
cities = cities.drop(columns="geometry").reset_index(drop=True)
print(f"{len(cities)} urban centres, {cities['pop'].sum() / 1e6:.0f} million people")

# 2. Nearest port by driving time, plus the Waalhaven sensitivity check
durations, distances = driving_table(cities)
checked = np.where(np.isnan(durations), np.inf, durations)
nearest = checked[:, :10].argmin(axis=1)
alternative = checked[:, [10, *range(1, 10)]].argmin(axis=1)
print(f"Rotterdam share measured from Waalhaven: {cities['pop'][alternative == 0].sum() / cities['pop'].sum():.2%}")

# 3. Routes. A route may not cross a country we left out, so those cities take their next-nearest port.
world = countries()
blocked = prep(unary_union(world[world.ADMIN.isin(NO_ROUTES_THROUGH)].geometry.buffer(0)))


def crosses_blocked(encoded):
    return blocked.intersects(LineString([(lon, lat) for lat, lon in polyline.decode(encoded)]))


chosen_port, hours, km, encoded_routes = [], [], [], []
for i, city in cities.iterrows():
    for port_index in np.argsort(checked[i, :10]):
        port = PORT_NAMES[port_index]
        route = get_route(city, port)
        if not crosses_blocked(route["g"]):
            break
        print(f"{city['name']}: route to {port} crosses a left-out country, trying the next port")
    chosen_port.append(port)
    hours.append(route["t"] / 3600)
    km.append(route["d"] / 1000)
    encoded_routes.append(route["g"])
    if (i + 1) % 100 == 0:
        print(f"Routes: {i + 1} of {len(cities)}", flush=True)
cities["port"], cities["hours"], cities["km"] = chosen_port, hours, km
share = cities.groupby("port")["pop"].sum() / cities["pop"].sum()
print((share.sort_values(ascending=False) * 100).round(2).to_string())

# 4. Count people per road segment on a 1.5 km grid, so shared roads merge
transform = Transformer.from_crs(4326, 3035, always_xy=True)
GRID = 1500
load = collections.defaultdict(float)
by_port = collections.defaultdict(lambda: collections.defaultdict(float))
for encoded, population, port in zip(encoded_routes, cities["pop"], cities.port):
    points = np.array(polyline.decode(encoded))
    xs, ys = transform.transform(points[:, 1], points[:, 0])
    grid = np.round(np.c_[xs, ys] / GRID).astype(int)
    seen = set()
    for a, b in zip(map(tuple, grid[:-1]), map(tuple, grid[1:])):
        if a == b:
            continue
        key = (a, b) if a < b else (b, a)
        if key in seen:
            continue
        seen.add(key)
        load[key] += population
        by_port[key][port] += population

# 5. Draw
MAP_TOP = 258
frame = Frame(2254651, 6545349, 1380000, 5230000, 0, 1080, MAP_TOP)
HIGHLIGHT = {"Rotterdam": C["blue"], "Hamburg": C["apricot"]}


def line_width(population):
    return 0.7 + 7.2 * (population / 4e7) ** 0.5


quiet_land, data_land = land_paths(frame, LAND_WITH_DATA)
svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{quiet_land}" fill="{C["quiet_land"]}"/><path d="{data_land}" fill="{C["page"]}"/>',
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="70" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 50:.0f}" width="1080" height="50" fill="url(#fade-bottom)"/>',
]

# Group segments by colour and width to keep the SVG small
buckets = collections.defaultdict(list)
for key, population in load.items():
    main_port = max(by_port[key], key=by_port[key].get)
    colour = HIGHLIGHT.get(main_port, C["ctx"])
    width = round(line_width(population) * 4) / 4
    (ax, ay), (bx, by) = key
    start = frame.xy(ax * GRID, ay * GRID)
    end = frame.xy(bx * GRID, by * GRID)
    buckets[(colour, width)].append(f"M{start[0]:.1f} {start[1]:.1f}L{end[0]:.1f} {end[1]:.1f}")
for colour, width in sorted(buckets, key=lambda item: (item[0] != C["ctx"], item[1])):
    svg.append(f'<path d="{"".join(buckets[(colour, width)])}" fill="none" stroke="{colour}" stroke-width="{width}" stroke-linecap="round" stroke-linejoin="round"/>')
svg.append("</g>")

# Port dots and direct labels
LABELS = {
    "Rotterdam": (-14, -28, "end"), "Antwerp-Bruges": (-14, 34, "end"), "Hamburg": (16, -16, "start"),
    "Valencia": (14, 30, "start"), "Bremerhaven": (-55, -38, "start"), "Algeciras": (14, 28, "start"),
    "Piraeus": (14, 26, "start"), "Gioia Tauro": (16, 30, "start"), "Barcelona": (16, -8, "start"),
    "Felixstowe": (-14, 12, "end"),
}
for port, (lon, lat) in PORTS.items():
    x, y = frame.xy(*transform.transform(lon, lat))
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="6" fill="{HIGHLIGHT.get(port, C["ink2"])}" stroke="{C["page"]}" stroke-width="2"/>')
    dx, dy, anchor = LABELS[port]
    value = f"{share[port] * 100:.0f}%" if share[port] >= 0.01 else f"{share[port] * 100:.1f}%"
    highlighted = port in HIGHLIGHT
    svg.append(text(
        x + dx, y + dy, f"{port} {value}", 24 if highlighted else 21, 700 if highlighted else 500,
        C["blue"] if port == "Rotterdam" else C["ink"], anchor, halo=C["page"],
    ))

# Bar chart: each port's share of containers against its share of people
ports = pd.read_csv(HERE / "ports.csv").sort_values("teu_2025", ascending=False)
ports["teu_share"] = ports.teu_2025 / ports.teu_2025.sum()
ports["people_share"] = ports.port.map(share)
CHART_X, CHART_TOP, ROW_H, BAR_H = 800, 352, 45, 9
bar_scale = 188 / max(ports.teu_share.max(), ports.people_share.max())


def pct(value):
    return f"{value * 100:.0f}%" if value >= 0.01 else f"{value * 100:.1f}%"


svg.append(text(CHART_X, 288, "Containers vs people", 21, 700))
svg.append(text(CHART_X, 310, "Share across the top 10 ports", 15, 400, C["ink2"]))
svg.append(text(CHART_X, 330, "Upper bar: containers (TEU)", 15, 400, C["ink2"]))
svg.append(text(CHART_X, 349, "Lower bar: city dwellers nearest", 15, 400, C["ink2"]))
for row, port_row in enumerate(ports.itertuples()):
    y = CHART_TOP + 22 + row * ROW_H
    svg.append(text(CHART_X, y, port_row.port, 16, 600))
    teu_width = port_row.teu_share * bar_scale
    people_width = port_row.people_share * bar_scale
    colour = HIGHLIGHT.get(port_row.port, C["ctx"])
    svg.append(f'<rect x="{CHART_X}" y="{y + 5}" width="{teu_width:.1f}" height="{BAR_H}" rx="2" fill="{C["ink2"]}"/>')
    svg.append(text(CHART_X + teu_width + 6, y + 14, pct(port_row.teu_share), 14, 500, C["ink2"]))
    svg.append(f'<rect x="{CHART_X}" y="{y + 16}" width="{max(people_width, 1.5):.1f}" height="{BAR_H}" rx="2" fill="{colour}"/>')
    svg.append(text(CHART_X + people_width + 6, y + 25, pct(port_row.people_share), 14, 500, C["ink2"]))
ports[["port", "teu_2025", "teu_share", "people_share"]].round(4).to_csv(HERE / "port_summary.csv", index=False)

# Headline, dek and byline
svg.append(text(60, 90, "Europe's biggest port is the nearest", 54, 800))
svg.append(text(60, 148, "one for under 4% of city dwellers", 54, 800))
svg.append(text(60, 190, "Share of people in urban centres, by the top-10 container port they can drive to", 25, 400, C["ink2"]))
svg.append(text(60, 220, "fastest. Line width shows how many people's routes share each road.", 25, 400, C["ink2"]))
svg.append(byline(252))

# One handwritten note with a curved arrow
rx, ry = frame.xy(*transform.transform(*PORTS["Rotterdam"]))
note_x, note_y = 70, int(ry - 205)
svg.append(
    f'<text class="note" x="{note_x}" y="{note_y}" font-size="27" fill="{C["ink"]}">'
    f'<tspan x="{note_x}">Antwerp and Hamburg</tspan><tspan x="{note_x}" dy="33">box Rotterdam in</tspan></text>'
)
x0, y0 = note_x + 312, note_y - 6
x1, y1 = rx - 1, ry - 11
svg.append(f'<path d="M{x0} {y0} C {x0 + 70} {y0 + 6}, {x1 + 8} {y1 - 90}, {x1:.1f} {y1:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{x1 - 8:.1f} {y1 - 11:.1f} L{x1:.1f} {y1:.1f} L{x1 + 9:.1f} {y1 - 10:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# Source
svg.append(text(60, 1250, "Source: GHS-UCDB R2024A V1.2 (JRC), 2025. Car routes: OSRM, © OpenStreetMap contributors. Ports: top 10", 19, 400, C["muted"]))
svg.append(text(60, 1273, "by 2025 TEU (Wikipedia, from port authorities). Excludes Russia, Belarus, Ukraine and Atlantic", 19, 400, C["muted"]))
svg.append(text(60, 1296, "islands. Turkey and Cyprus are not in the dataset. Base: Natural Earth.", 19, 400, C["muted"]))

save_png(page("".join(svg)), HERE / "day02_lines.png")
cities[["name", "cnt", "pop", "lon", "lat", "port", "hours", "km"]].round(
    {"lon": 5, "lat": 5, "hours": 2, "km": 1}
).to_csv(HERE / "results.csv", index=False)
