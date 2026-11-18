"""Day 18, NULL: nul points, every Eurovision entry that ended a show with zero points.

The list is typed in from Wikipedia's "Voting at the Eurovision Song Contest" and checked against Aussievision's lists
of nul-point entries (read in November 2026), which give the same 38 entries up to 2015. Since 2016 the jury and the
public each give a score and the two are added, so a zero in total needs a zero from both: only the United Kingdom's
entry in the 2021 final got one. The semi-finals of 2023, 2024 and 2025 were decided by the public alone, and Romania
and San Marino got no points in the second semi-final of 2023 (results on Wikipedia's page for each contest).
"""
import sys
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, Frame, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

# Every entry with zero points in total: year, country (as Natural Earth names it), and the show
NUL = [
    (1962, "Belgium", "final"), (1962, "Spain", "final"), (1962, "Austria", "final"), (1962, "Netherlands", "final"),
    (1963, "Netherlands", "final"), (1963, "Norway", "final"), (1963, "Finland", "final"), (1963, "Sweden", "final"),
    (1964, "Germany", "final"), (1964, "Portugal", "final"), (1964, "Yugoslavia", "final"), (1964, "Switzerland", "final"),
    (1965, "Spain", "final"), (1965, "Germany", "final"), (1965, "Belgium", "final"), (1965, "Finland", "final"),
    (1966, "Monaco", "final"), (1966, "Italy", "final"), (1967, "Switzerland", "final"), (1970, "Luxembourg", "final"),
    (1978, "Norway", "final"), (1981, "Norway", "final"), (1982, "Finland", "final"), (1983, "Spain", "final"),
    (1983, "Turkey", "final"), (1987, "Turkey", "final"), (1988, "Austria", "final"), (1989, "Iceland", "final"),
    (1991, "Austria", "final"), (1994, "Lithuania", "final"), (1997, "Norway", "final"), (1997, "Portugal", "final"),
    (1998, "Switzerland", "final"), (2003, "United Kingdom", "final"), (2004, "Switzerland", "semi-final"),
    (2009, "Czechia", "semi-final"), (2015, "Austria", "final"), (2015, "Germany", "final"), (2021, "United Kingdom", "final"),
    (2023, "Romania", "semi-final"), (2023, "San Marino", "semi-final"),
]
COLOURS = {1: "#F0C9A8", 2: "#E08A5C", 3: "#B4472A", 4: "#5E2414"}
CODE = {"Austria": "AT", "Belgium": "BE", "Czechia": "CZ", "Finland": "FI", "Germany": "DE", "Iceland": "IS", "Italy": "IT",
        "Lithuania": "LT", "Luxembourg": "LU", "Monaco": "MC", "Netherlands": "NL", "Norway": "NO", "Portugal": "PT", "Romania": "RO",
        "San Marino": "SM", "Spain": "ES",
        "Sweden": "SE", "Switzerland": "CH", "Turkey": "TR", "United Kingdom": "UK", "Yugoslavia": "YU"}
GONE = C["ink2"]  # Yugoslavia, which no longer exists

nul = pd.DataFrame(NUL, columns=["year", "country", "show"])
times = Counter(nul.country)
finals = Counter(nul[nul.show == "final"].country)
assert len(nul) == 41 and len(times) == 21 and set(times) == set(CODE)
assert finals["Norway"] == finals["Austria"] == 4 and max(finals.values()) == 4  # the Guinness record, in finals
assert times["Switzerland"] == 4 and finals["Switzerland"] == 3
early = (nul.year <= 1970).sum()
assert early == 20 and 0.45 < early / len(nul) < 0.5  # "almost half", in the 15 contests from 1956 to 1970
print(sorted(times.items(), key=lambda kv: -kv[1]))

# 1. Map: every country that has ended a show with zero points, darker the more often
MAP_TOP = 250
frame = Frame(2150000, 7850000, 1560000, 5230000, 0, 1080, MAP_TOP)
view = frame.box().buffer(30000)
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(view)
world = world[~world.is_empty]
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{"".join(geom_path(g, frame) for g in world.geometry)}" fill="{C["page"]}" stroke="{C["ctxl"]}" '
       f'stroke-width=".7" stroke-linejoin="round"/>']
for n, colour in COLOURS.items():
    names = [c for c, k in times.items() if k == n]
    shapes = "".join(geom_path(g, frame) for g in world[world.ADMIN.isin(names)].geometry)  # one path per country keeps borders
    svg.append(f'<path d="{shapes}" fill="{colour}" stroke="#FFFFFF" stroke-width="1" stroke-linejoin="round"/>')
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# The number of zeros on each country, at a spot inside it
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
SPOT = {"Norway": (9.4, 61.0), "Austria": (14.3, 47.6), "Switzerland": (8.0, 46.75), "Finland": (26.0, 62.6),
        "Spain": (-3.7, 40.0), "Germany": (10.2, 51.0), "Netherlands": (5.7, 52.4), "Belgium": (4.6, 50.6),
        "Turkey": (33.0, 39.2), "Portugal": (-8.3, 39.6), "United Kingdom": (-1.8, 52.8), "Sweden": (15.6, 62.9),
        "Italy": (11.4, 43.3), "Luxembourg": (6.1, 49.7), "Iceland": (-18.6, 64.9), "Lithuania": (23.9, 55.3),
        "Czechia": (15.4, 49.8), "Romania": (25.0, 45.9)}
OUTSIDE = {"Luxembourg": (5.2, 49.35), "Monaco": (7.0, 42.9), "San Marino": (13.6, 44.5)}  # too small to hold the number: it sits beside them
for name, (lon, lat) in {**SPOT, **OUTSIDE}.items():
    x, y = frame.xy(*to3035.transform(lon, lat))
    inside = name in SPOT
    ink = "#FFFFFF" if inside and times[name] >= 3 else C["ink"]
    halo = "" if inside else f' stroke="{C["page"]}" stroke-width="3" paint-order="stroke"'
    svg.append(f'<text x="{x:.1f}" y="{y + (6 if inside else 5):.1f}" font-size="{17 if inside else 14}" font-weight="800" fill="{ink}" text-anchor="middle"{halo}>{times[name]}</text>')
# Monaco and San Marino are smaller than a pixel here, so each gets a dot
for name, lon, lat in (("Monaco", 7.42, 43.74), ("San Marino", 12.46, 43.94)):
    mx, my = frame.xy(*to3035.transform(lon, lat))
    svg.append(f'<circle cx="{mx:.1f}" cy="{my:.1f}" r="5" fill="{COLOURS[times[name]]}" stroke="{C["ink"]}" stroke-width="1"/>')

# Legend over Russia, which never scored zero
LX, LY = 800, MAP_TOP + 190
svg.append(text(LX, LY, "Times each country", 17, 700))
svg.append(text(LX, LY + 21, "finished on zero points", 17, 700))
for i, (n, colour) in enumerate(sorted(COLOURS.items(), reverse=True)):
    y = LY + 46 + i * 24
    svg.append(f'<rect x="{LX}" y="{y - 8}" width="18" height="16" rx="2" fill="{colour}"/>')
    svg.append(text(LX + 28, y + 5, f"{n} time{'s' if n > 1 else ''}", 15, 400, C["ink2"]))
svg.append(f'<rect x="{LX}" y="{LY + 144}" width="18" height="16" rx="2" fill="{GONE}"/>')
svg.append(text(LX + 28, LY + 157, "Yugoslavia, once (1964)", 15, 400, C["ink2"]))
svg.append(f'<circle cx="{LX + 9}" cy="{LY + 176}" r="5" fill="{COLOURS[1]}" stroke="{C["ink"]}" stroke-width="1"/>')
svg.append(text(LX + 28, LY + 181, "Monaco and San Marino", 15, 400, C["ink2"]))

# One note, over the North Sea, pointing at the UK
ux, uy = frame.xy(*to3035.transform(-5.9, 57.3))  # the west coast of Scotland, reached over open sea
nx, ny = 34, MAP_TOP + 150
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="21" fill="{C["ink"]}"><tspan x="{nx}">The UK in 2021: zero from</tspan>'
           f'<tspan x="{nx}" dy="26">the juries and</tspan><tspan x="{nx}" dy="26">the public</tspan></text>')
sx, sy, qx, qy = nx + 60, ny + 66, nx + 70, uy + 4
angle = np.arctan2(uy - qy, ux - qx)
head = " ".join(f"L{ux + 13 * np.cos(angle + np.pi + t):.1f} {uy + 13 * np.sin(angle + np.pi + t):.1f} M{ux:.1f} {uy:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx} {sy} Q {qx:.1f} {qy:.1f}, {ux:.1f} {uy:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round"/>')

# 2. Under the map: a timeline, one ball per entry stacked by year, labelled with its country and coloured like it on the map
TOP = MAP_TOP + frame.ph + 26
svg.append(text(60, TOP, "Every zero, year by year", 19, 700))
Y0, Y1 = 1961, 2026
ax = lambda year: 40 + 1000 * (year - Y0 + 0.5) / (Y1 - Y0 + 1)  # noqa: E731  one column per year, the balls just touch
R = 1000 / (Y1 - Y0 + 1) / 2 - 0.2
BASE = TOP + 112
svg.append(f'<path d="M40 {BASE + R + 4:.1f} L1040 {BASE + R + 4:.1f}" stroke="{C["ctxl"]}" stroke-width="1"/>')
for year, group in nul.groupby("year"):
    for i, row in enumerate(group.itertuples()):
        x, y = ax(year), BASE - i * (2 * R + 1)
        fill = GONE if row.country == "Yugoslavia" else COLOURS[times[row.country]]
        ink = "#FFFFFF" if fill in (GONE, COLOURS[3], COLOURS[4]) else C["ink"]
        stroke = f' stroke="{C["ink"]}" stroke-width="1.3" stroke-dasharray="2 1.6"' if row.show == "semi-final" else ""
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{R:.1f}"{stroke} fill="{fill}"/>')
        svg.append(text(x, y + 3, CODE[row.country], 8, 800, ink, "middle"))
for year in range(1970, 2021, 10):
    svg.append(text(ax(year), BASE + R + 24, str(year), 13, 400, C["ink2"], "middle"))
for year, label, anchor in ((1975, "1975: today's 12-point scoring starts", "start"), (2016, "2016: jury points and public points are added up", "end")):
    x = ax(year)
    svg.append(f'<path d="M{x:.1f} {BASE + R + 4:.1f} L{x:.1f} {TOP + 26}" stroke="{C["ink2"]}" stroke-width=".8" stroke-dasharray="3 3"/>')
    svg.append(text(x + (5 if anchor == "start" else -5), TOP + 36, label, 14, 600, C["ink2"], anchor))
# The codes, with each country's name
KY = BASE + R + 44
names = sorted(CODE.items(), key=lambda kv: kv[1])
for k, (name, code) in enumerate(names):
    x, y = 40 + (k % 7) * 146 + R, KY + (k // 7) * 23
    fill = GONE if name == "Yugoslavia" else COLOURS[times[name]]
    ink = "#FFFFFF" if fill in (GONE, COLOURS[3], COLOURS[4]) else C["ink"]
    svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{R:.1f}" fill="{fill}"/>')
    svg.append(text(x, y + 3, code, 8, 800, ink, "middle"))
    svg.append(text(x + R + 6, y + 5, name, 13.5, 400, C["ink2"]))
BASE = KY + ((len(names) - 1) // 7) * 23 + 28

# 3. Headline, dek, byline and footer
svg.append(text(60, 78, "The countries that scored zero points", 46, 800))
svg.append(text(60, 128, "at Eurovision", 46, 800))
svg.append(text(60, 168, f"Nul points: {len(nul)} songs from {len(times)} countries have finished a Eurovision show on zero points since 1956.", 22, 400, C["ink2"]))
svg.append(text(60, 196, "Norway, Austria and Switzerland did it four times each. Almost half came in the first 15 contests.", 22, 400, C["ink2"]))
svg.append(byline(230, "30DayMapChallenge #18: NULL"))
svg += footer([
    ("Method:", "songs that finished a final or a semi-final (dashed ring) with zero points in total. Only the public voted in the 2023 semi-finals."),
    ("Source:", "Wikipedia, voting history and yearly results, checked against Aussievision, November 2026. Borders: Natural Earth."),
    ("Comments:", "Norway and Austria share the Guinness record: four zeros each, all in finals. Switzerland's fourth was in a semi-final."),
], x=60, y=BASE + 28, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day18_null.png")
nul.to_csv(HERE / "nul_points.csv", index=False)
