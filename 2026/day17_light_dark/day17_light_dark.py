"""Day 17, Light & dark: the clock time of sunrise on the shortest day of 2026, 21 December.

Sunrise is worked out from the sun's position with the equations of NOAA's solar calculator, counting the sun as risen when its top
edge clears the horizon (90.833° from overhead, which allows for refraction). The clock time then depends on three
things: latitude, how far west a place sits inside its time zone, and which time zone its country keeps in winter.
"""
import base64
import io
import sys
from pathlib import Path

import numpy as np
import shapely
from PIL import Image
from affine import Affine
from pyproj import Transformer
from rasterio import features

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, Frame, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

JULIAN_DAY = 2461395.5  # 21 December 2026 at 0:00 UTC
WINTER_CLOCK = {  # hours ahead of UTC in winter, for every country that is coloured
    0: ["Iceland", "Ireland", "United Kingdom", "Portugal", "Faroe Islands", "Isle of Man", "Jersey", "Guernsey"],
    1: ["Spain", "France", "Belgium", "Netherlands", "Luxembourg", "Germany", "Denmark", "Norway", "Sweden", "Switzerland",
        "Liechtenstein", "Austria", "Italy", "Malta", "Monaco", "Andorra", "San Marino", "Vatican", "Poland", "Czechia",
        "Slovakia", "Hungary", "Slovenia", "Croatia", "Bosnia and Herzegovina", "Republic of Serbia", "Montenegro", "Kosovo",
        "Albania", "North Macedonia"],
    2: ["Finland", "Aland", "Estonia", "Latvia", "Lithuania", "Ukraine", "Moldova", "Romania", "Bulgaria", "Greece", "Cyprus",
        "Northern Cyprus"],
    3: ["Belarus", "Turkey"],
}
CITIES = {  # lon, lat, winter clock, label side, and a nudge up or down for labels that would collide
    "Reykjavik": (-21.94, 64.15, 0, "end"), "Tromsø": (18.96, 69.65, 1, "start"), "Helsinki": (24.94, 60.17, 2, "start"),
    "Stockholm": (18.07, 59.33, 1, "start"), "Oslo": (10.75, 59.91, 1, "end"), "Dublin": (-6.26, 53.35, 0, "end"),
    "London": (-0.13, 51.51, 0, "end"), "Amsterdam": (4.90, 52.37, 1, "end", -9), "Brest": (-4.49, 48.39, 1, "start"),
    "Paris": (2.35, 48.86, 1, "start"), "Berlin": (13.40, 52.52, 1, "start"), "Warsaw": (21.01, 52.23, 1, "start"),
    "Minsk": (27.57, 53.90, 3, "start"), "Vienna": (16.37, 48.21, 1, "start"), "Bucharest": (26.10, 44.43, 2, "start"),
    "Vigo": (-8.72, 42.24, 1, "end"), "Madrid": (-3.70, 40.42, 1, "start"), "Lisbon": (-9.14, 38.72, 0, "end"),
    "Rome": (12.50, 41.90, 1, "start"), "Athens": (23.73, 37.98, 2, "end"), "Istanbul": (28.98, 41.01, 3, "start"),
    "Nicosia": (33.36, 35.17, 2, "end"),
}
STRIP = ["Helsinki", "Vigo", "Brest", "Madrid", "Berlin", "Lisbon", "Warsaw"]
BANDS = [  # sunrise before this clock time (minutes after midnight), colour, legend label
    (450, "#FFE08A", "Before 7:30"), (480, "#F2C766", "7:30 to 8:00"), (510, "#D9AE6B", "8:00 to 8:30"), (540, "#A99A93", "8:30 to 9:00"),
    (570, "#6F7896", "9:00 to 9:30"), (600, "#4A557A", "9:30 to 10:00"), (9999, "#2F3A5C", "After 10:00"),
]
NO_SUNRISE = "#141826"


def sun(lat, hour):
    """Half-day hour angle in degrees and equation of time in minutes, for latitude(s), with the sun where it is at
    this hour (UTC) of the day. These are the equations behind NOAA's solar calculator, from Meeus."""
    t = (JULIAN_DAY + hour / 24 - 2451545) / 36525  # centuries since 2000
    rad, sin, cos = np.radians, lambda d: np.sin(np.radians(d)), lambda d: np.cos(np.radians(d))
    mean_long = (280.46646 + t * (36000.76983 + t * 0.0003032)) % 360
    anomaly = 357.52911 + t * (35999.05029 - 0.0001537 * t)
    ecc = 0.016708634 - t * (0.000042037 + 0.0000001267 * t)
    centre = sin(anomaly) * (1.914602 - t * (0.004817 + 0.000014 * t)) + sin(2 * anomaly) * (0.019993 - 0.000101 * t) + sin(3 * anomaly) * 0.000289
    apparent = mean_long + centre - 0.00569 - 0.00478 * sin(125.04 - 1934.136 * t)
    tilt = 23 + (26 + (21.448 - t * (46.815 + t * (0.00059 - t * 0.001813))) / 60) / 60 + 0.00256 * cos(125.04 - 1934.136 * t)
    decl = np.arcsin(sin(tilt) * sin(apparent))
    y = np.tan(rad(tilt / 2)) ** 2
    eqtime = 4 * np.degrees(y * sin(2 * mean_long) - 2 * ecc * sin(anomaly) + 4 * ecc * y * sin(anomaly) * cos(2 * mean_long)
                            - 0.5 * y * y * sin(4 * mean_long) - 1.25 * ecc * ecc * sin(2 * anomaly))
    la = rad(lat)
    cos_ha = np.cos(rad(90.833)) / (np.cos(la) * np.cos(decl)) - np.tan(la) * np.tan(decl)
    return np.degrees(np.arccos(np.clip(cos_ha, -1, 1))), eqtime  # an hour angle of 0 means the sun stays below the horizon


def clock(lon, lat, utc):
    """Sunrise and sunset in minutes after midnight, on the winter clock."""
    ha, eqtime = sun(lat, 7.5)  # mornings: around 7:30 UTC
    up = 720 - 4 * lon - eqtime + utc * 60 - 4 * ha
    ha, eqtime = sun(lat, 15.5)  # evenings: around 15:30 UTC
    return up, 720 - 4 * lon - eqtime + utc * 60 + 4 * ha


def hhmm(minutes):
    minutes = round(float(minutes))
    return f"{minutes // 60}:{minutes % 60:02d}"


# 1. The numbers on the chart
rise = {name: clock(*c[:3])[0] for name, c in CITIES.items()}
dark = {name: sun(c[1], 7.5)[0] == 0 for name, c in CITIES.items()}
print({k: "none" if dark[k] else hhmm(v) for k, v in rise.items()})
assert dark["Tromsø"]
gap = round(rise["Madrid"]) - round(rise["Warsaw"])  # the headline
north = round((CITIES["Warsaw"][1] - CITIES["Madrid"][1]) * 111.2, -2)  # km between the two latitudes
assert rise["Warsaw"] < rise["Madrid"] - 45 and rise["Lisbon"] < rise["Vigo"] - 60  # the dek and the note
polar = next(lat for lat in np.arange(60, 70, 0.01) if sun(lat, 10)[0] == 0)  # where the sun no longer rises

# 2. Map: every pixel of the coloured countries, by the clock time of its sunrise
MAP_TOP = 244
frame = Frame(1450000, 6950000, 1480000, 5420000, 0, 1080, MAP_TOP)
SCALE = 2
w, h = 1080 * SCALE, int(frame.ph * SCALE)
xs = frame.x0 + (np.arange(w) + 0.5) / SCALE / frame.k
ys = frame.y1 - (np.arange(h) + 0.5) / SCALE / frame.k
to4326 = Transformer.from_crs(3035, 4326, always_xy=True)
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
lon, lat = to4326.transform(*np.meshgrid(xs, ys))
# Clip in degrees first, so shapes that cross the date line can't wrap around in the projection
world = countries()
world["geometry"] = world.geometry.buffer(0).intersection(shapely.box(-45, 25, 75, 85))
# Natural Earth draws Crimea with Russia. It is Ukraine's by international law, so it joins Ukraine here, on Kyiv's clock.
crimea = shapely.box(32.3, 44.3, 36.65, 46.3)
ru, ua = world.index[world.ADMIN == "Russia"][0], world.index[world.ADMIN == "Ukraine"][0]
world.loc[ua, "geometry"] = world.geometry[ua].union(world.geometry[ru].intersection(crimea))
world.loc[ru, "geometry"] = world.geometry[ru].difference(crimea)
world = world[~world.is_empty].to_crs(3035)
world["geometry"] = world.geometry.intersection(frame.box().buffer(50000))
world = world[~world.is_empty]
zone = {name: utc for utc, names in WINTER_CLOCK.items() for name in names}
assert set(zone) <= set(world.ADMIN), set(zone) - set(world.ADMIN)
coloured = world[world.ADMIN.isin(zone)]
pixel = 1 / (SCALE * frame.k)  # metres per image pixel
grid = Affine(pixel, 0, frame.x0, 0, -pixel, frame.y1)
utc = features.rasterize([(g, zone[n] + 10) for g, n in zip(coloured.geometry, coloured.ADMIN)], out_shape=(h, w), transform=grid).astype(float)
inside = utc > 0
utc -= 10
ha, eqtime = sun(lat, 7.5)
sunrise = 720 - 4 * lon - eqtime + utc * 60 - 4 * ha
band = np.digitize(sunrise, [b[0] for b in BANDS[:-1]])
rgb = np.array([[int(c[i:i + 2], 16) for i in (1, 3, 5)] for c in [b[1] for b in BANDS] + [NO_SUNRISE]])
img = np.dstack([rgb[np.where(ha == 0, len(BANDS), band)], np.where(inside, 255, 0)])
buffer = io.BytesIO()
Image.fromarray(img.astype(np.uint8), "RGBA").save(buffer, "PNG", optimize=True)
uri = base64.b64encode(buffer.getvalue()).decode()
others = world[~world.ADMIN.isin(zone)].union_all()
borders = shapely.union_all([g.boundary for g in coloured.geometry]).intersection(frame.box())
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(others.intersection(frame.box()), frame)}" fill="{C["quiet_land"]}"/>',
       f'<image x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.1f}" href="data:image/png;base64,{uri}"/>']
border_d = "".join("M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in (frame.xy(*c) for c in g.coords))
                   for g in getattr(borders, "geoms", [borders]) if g.geom_type == "LineString")
svg.append(f'<path d="{border_d}" fill="none" stroke="#FFFFFF" stroke-opacity=".75" stroke-width=".7" stroke-linejoin="round"/>')

for name, (lo, la, _, side, *nudge) in CITIES.items():
    x, y = frame.xy(*to3035.transform(lo, la))
    ty = y + 5 + (nudge[0] if nudge else 0)
    dx = 8 if side == "start" else -8
    words = "no sunrise" if dark[name] else hhmm(rise[name])
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="3.5" fill="{C["ink"]}" stroke="#FFFFFF" stroke-width="1.2"/>')
    svg.append(f'<text x="{x + dx:.1f}" y="{ty:.1f}" font-size="14" font-weight="400" fill="{C["ink"]}" text-anchor="{side}" '
               f'stroke="{C["page"]}" stroke-width="3.5" paint-order="stroke">{name} <tspan font-weight="800">{words}</tspan></text>')
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic
LX, LY = 34, MAP_TOP + 170
svg.append(text(LX, LY, "Sunrise by the clock", 17, 700))
svg.append(text(LX, LY + 21, "on 21 December", 17, 700))
for i, (colour, label) in enumerate([(b[1], b[2]) for b in BANDS] + [(NO_SUNRISE, "No sunrise")]):
    y = LY + 36 + i * 23
    svg.append(f'<rect x="{LX}" y="{y}" width="18" height="16" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 27, y + 13, label, 15, 400, C["ink2"]))

# One note, over the Atlantic, pointing at Vigo
vx, vy = frame.xy(*to3035.transform(-8.72, 42.24))
late = round(rise["Vigo"] - rise["Lisbon"])
nx, ny = 34, vy - 124
svg.append(f'<text class="note" x="{nx}" y="{ny:.0f}" font-size="21" fill="{C["ink"]}"><tspan x="{nx}">Spain keeps Berlin\'s clock:</tspan>'
           f'<tspan x="{nx}" dy="26">sunrise in Vigo comes {late}</tspan><tspan x="{nx}" dy="26">minutes after Lisbon\'s</tspan></text>')
sx, sy, qx, qy = nx + 120, ny + 66, vx - 150, vy - 4
ex, ey = vx - 92, vy - 3
angle = np.arctan2(ey - qy, ex - qx)
head = " ".join(f"L{ex + 13 * np.cos(angle + np.pi + t):.1f} {ey + 13 * np.sin(angle + np.pi + t):.1f} M{ex:.1f} {ey:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy:.1f} Q {qx:.1f} {qy:.1f}, {ex:.1f} {ey:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round"/>')

# 3. Strip under the map: sunrise to sunset by the clock, on a dark day-long bar, latest sunrise first
TOP = MAP_TOP + frame.ph + 26
svg.append(text(60, TOP, "From sunrise to sunset by the clock, 21 December", 19, 700))
T0, T1 = 6 * 60, 19 * 60
ax = lambda m: 190 + 830 * (m - T0) / (T1 - T0)  # noqa: E731
rows = sorted(STRIP, key=lambda n: -rise[n])
for i, name in enumerate(rows):
    lo, la, off = CITIES[name][:3]
    up, down = clock(lo, la, off)
    y = TOP + 20 + i * 19
    svg.append(text(60, y + 12, name, 14, 600, C["ink"]))
    svg.append(f'<rect x="190" y="{y}" width="830" height="14" rx="3" fill="#1F2638"/>')
    svg.append(f'<rect x="{ax(up):.1f}" y="{y}" width="{ax(down) - ax(up):.1f}" height="14" rx="3" fill="#F3DFA8"/>')
    svg.append(text(ax(up) + 5, y + 11.5, hhmm(up), 12, 700, C["ink"]))
    svg.append(text(ax(down) - 5, y + 11.5, hhmm(down), 12, 700, C["ink"], "end"))
AY = TOP + 20 + len(rows) * 19 + 13
for m in range(T0, T1 + 1, 60):
    svg.append(text(ax(m), AY, f"{m // 60}:00", 12, 400, C["ink2"], "middle"))

# 4. Headline, dek, byline and footer
svg.append(text(60, 84, "On the shortest day, the sun rises", 46, 800))
svg.append(text(60, 134, f"{gap} minutes later in Madrid than in Warsaw", 46, 800))
svg.append(text(60, 174, "Clock time of sunrise on 21 December 2026. Spain and France sit at the western end of their time", 22, 400, C["ink2"]))
svg.append(text(60, 202, f"zone, so the sun comes up at {hhmm(rise['Madrid'])} in Madrid and at {hhmm(rise['Warsaw'])} in Warsaw, {north:,.0f} km further north.", 22, 400, C["ink2"]))
# The byline with the challenge day, one size smaller than usual so the theme's name fits on the line
svg.append(byline(234, "30DayMapChallenge #17: Light & dark").replace('font-size="20"', 'font-size="18"'))
svg += footer([
    ("Method:", "sunrise from NOAA's solar calculator equations, with the sun's top edge on a flat horizon, on each country's winter time."),
    ("Source:", "NOAA Global Monitoring Laboratory, solar calculation details. Borders from Natural Earth."),
    ("Comments:", f"north of {polar:.1f}°N the sun doesn't rise. Times can be a minute off. Russia, with several time zones, isn't coloured."),
], x=60, y=AY + 28, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day17_light_dark.png")
