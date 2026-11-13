"""Day 13, Interactions: the 10 biggest Erasmus flows run between four countries.

Erasmus+ student stays of 90 days or more that started in 2023, between the countries taking part, from the
University of Helsinki's geolocated version of the official Erasmus+ mobility data (Väisänen et al., 2025).
Makes two images: a map of the ten biggest flows, and a chord diagram of the flows between the eight biggest hosts.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, footer, geom_path, page, save_png, text  # noqa: E402

FLOWS_URL = "https://zenodo.org/records/16737523/files/Erasmus_2014-2023_aggregate_NUTS.csv?download=1"
YEAR = 2023
NAMES = {"AL": "Albania", "AT": "Austria", "BE": "Belgium", "BG": "Bulgaria", "CH": "Switzerland", "CY": "Cyprus",
         "CZ": "Czechia", "DE": "Germany", "DK": "Denmark", "EE": "Estonia", "EL": "Greece", "ES": "Spain",
         "FI": "Finland", "FR": "France", "HR": "Croatia", "HU": "Hungary", "IE": "Ireland", "IS": "Iceland",
         "IT": "Italy", "LI": "Liechtenstein", "LT": "Lithuania", "LU": "Luxembourg", "LV": "Latvia",
         "ME": "Montenegro", "MK": "North Macedonia", "MT": "Malta", "NL": "Netherlands", "NO": "Norway",
         "PL": "Poland", "PT": "Portugal", "RO": "Romania", "RS": "Republic of Serbia", "SE": "Sweden",
         "SI": "Slovenia", "SK": "Slovakia", "TR": "Turkey", "UK": "United Kingdom"}
SPOT = {"AL": (20.0, 41.1), "AT": (14.6, 47.6), "BE": (4.6, 50.6), "BG": (25.3, 42.7), "CH": (8.2, 46.8),
        "CY": (33.1, 35.0), "CZ": (15.4, 49.8), "DE": (10.3, 51.1), "DK": (9.3, 56.1), "EE": (25.8, 58.7),
        "EL": (22.0, 39.6), "ES": (-3.7, 40.2), "FI": (26.0, 62.8), "FR": (2.5, 46.8), "HR": (16.2, 45.6),
        "HU": (19.4, 47.2), "IE": (-8.0, 53.2), "IS": (-18.6, 64.9), "IT": (12.6, 42.9), "LI": (9.55, 47.15),
        "LT": (23.9, 55.3), "LU": (6.1, 49.8), "LV": (25.2, 56.9), "ME": (19.3, 42.8), "MK": (21.7, 41.6),
        "MT": (14.4, 35.9), "NL": (5.6, 52.3), "NO": (9.5, 61.0), "PL": (19.3, 52.1), "PT": (-8.1, 39.6),
        "RO": (25.0, 45.9), "RS": (20.8, 44.0), "SE": (15.0, 61.5), "SI": (14.8, 46.1), "SK": (19.6, 48.7),
        "TR": (34.0, 39.0), "UK": (-1.8, 52.8)}

# 1. Flows between countries in 2023
raw = pd.read_csv(_download(FLOWS_URL, DATA_DIR / "Erasmus_2014-2023_aggregate_NUTS.csv"), sep=";")
raw = raw[raw.YEAR == YEAR]
raw["origin"], raw["dest"] = raw.ORIGIN.str[:2], raw.DESTINATION.str[:2]
abroad = raw[raw.origin != raw.dest]  # a few hundred stays within one country are left out
flows = abroad.groupby(["origin", "dest"]).COUNT.sum().rename("students").reset_index()
total = flows.students.sum()
sent = flows.groupby("origin").students.sum()
received = flows.groupby("dest").students.sum().sort_values(ascending=False)
# each country's first choice; Liechtenstein, with 20 students spread over ties, is left out
top = flows[flows.origin.map(sent) >= 100].sort_values("students").groupby("origin").tail(1).set_index("origin")
runner_up = flows.sort_values("students").groupby("origin").nth(-2).set_index("origin").students
top["margin"] = top.students - runner_up.reindex(top.index).fillna(0)
top["share"] = top.students / sent
spain_first = (top.dest == "ES").sum()
italy_to_spain = top.loc["IT", "share"]
print(f"{total:,} students; Spain receives {received['ES']:,} ({received['ES'] / total:.1%}); "
      f"first choice of {spain_first} of {len(top)} countries; Italy to Spain {top.loc['IT', 'students']:,} ({italy_to_spain:.0%})")
print(top.sort_values("students", ascending=False).to_string())
close = sorted(top[(top.dest == "ES") & (top.margin < 0.05 * top.students)].index.map(NAMES))
print("Spain wins by less than 5% in", close)
assert received.index[0] == "ES" and spain_first == 18 and len(top) == 35 and close == ["Austria", "Hungary", "Slovenia"]

# One colour per main host country, shared by the map, the columns and the flow chart; the rest in grey
PALETTE = {"ES": C["blue"], "IT": "#C4553A", "FR": "#D9A21B", "DE": "#3F7F6A", "PT": "#9C5B8F", "PL": "#E08A4F",
           "NL": "#6FA8A0", "BE": "#8C6D4F"}
REST = "#B8AE9C"


def tint(hex_colour, amount):
    """Mix a colour with the page colour; amount 0 is the page, 1 the colour."""
    a = np.array([int(hex_colour[i:i + 2], 16) for i in (1, 3, 5)])
    b = np.array([int(C["page"][i:i + 2], 16) for i in (1, 3, 5)])
    return "#" + "".join(f"{int(round(v)):02X}" for v in b + amount * (a - b))


# 2. Map: the countries taking part on the page colour, the four main ones tinted, an arrow for each of the ten biggest flows
MAP_TOP = 275
frame = Frame(2400000, 5200000, 1470000, 3520000, 0, 1080, MAP_TOP)  # zoomed to Spain, France, Germany and Italy
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(frame.box().buffer(50000))
in_erasmus = world.ADMIN.isin(NAMES.values())
assert in_erasmus.sum() == len(NAMES)
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(world[~in_erasmus].union_all(), frame)}" fill="{C["quiet_land"]}"/>',
       f'<path d="{geom_path(world[in_erasmus].union_all(), frame)}" fill="{C["page"]}" stroke="{C["ctxl"]}" stroke-width=".6"/>']
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
spot = {c: frame.xy(*to3035.transform(*SPOT[c])) for c in NAMES}


BEND = {("DE", "ES"): 0.36, ("FR", "ES"): 0.1}  # Germany's arrow to Spain swings wide of France's; the rest bend 0.2
LEAVE, APART = 20, 11  # arrows start and end a little away from the country's centre, each on its own side


def curve(origin, dest):
    """Start, control and end points of the arrow from origin to dest, which bends to one side of the straight line."""
    (x0, y0), (x1, y1) = spot[origin], spot[dest]
    length = np.hypot(x1 - x0, y1 - y0)
    ux, uy = (x1 - x0) / length, (y1 - y0) / length
    nx, ny = -uy, ux  # the side the arrow bends to; the return flow bends to the other side
    a = (x0 + ux * LEAVE + nx * APART, y0 + uy * LEAVE + ny * APART)
    b = (x1 - ux * LEAVE + nx * APART, y1 - uy * LEAVE + ny * APART)
    bend = BEND.get((origin, dest), 0.2) * length
    return a, ((a[0] + b[0]) / 2 + nx * bend, (a[1] + b[1]) / 2 + ny * bend), b


def along(origin, dest, t):
    """The point a share t of the way along the arrow from origin to dest."""
    (x0, y0), (cx, cy), (x1, y1) = curve(origin, dest)
    return ((1 - t) ** 2 * x0 + 2 * (1 - t) * t * cx + t ** 2 * x1, (1 - t) ** 2 * y0 + 2 * (1 - t) * t * cy + t ** 2 * y1)


def draw_arrow(a, c, b, width, colour):
    """A curved line from a to b through control point c, with an arrowhead at b."""
    tx, ty = b[0] - c[0], b[1] - c[1]
    norm = np.hypot(tx, ty)
    tx, ty = tx / norm, ty / norm
    head = 7 + width * 1.1
    hx, hy = b[0] - tx * head, b[1] - ty * head
    left, right = (hx - ty * head * 0.6, hy + tx * head * 0.6), (hx + ty * head * 0.6, hy - tx * head * 0.6)
    return (f'<path d="M{a[0]:.1f} {a[1]:.1f} Q{c[0]:.1f} {c[1]:.1f} {hx:.1f} {hy:.1f}" fill="none" stroke="{colour}" '
            f'stroke-width="{width:.1f}" stroke-opacity=".72"/>'
            f'<path d="M{left[0]:.1f} {left[1]:.1f} L{b[0]:.1f} {b[1]:.1f} L{right[0]:.1f} {right[1]:.1f}Z" fill="{colour}" fill-opacity=".9"/>')


def arrow_width(students):
    return 3 + 15 * students / 12464


# The ten biggest flows, each arrow in its host's colour
ten = flows.sort_values("students", ascending=False).head(10).reset_index(drop=True)
eleventh = flows.sort_values("students", ascending=False).iloc[10]
four = sorted(set(ten.origin) | set(ten.dest))
ten_share = ten.students.sum() / total
print(ten.to_string(), f"\n{ten_share:.1%} of all students; 11th: {eleventh.origin} to {eleventh.dest} {eleventh.students}")
assert four == ["DE", "ES", "FR", "IT"] and (eleventh.origin, eleventh.dest) == ("NL", "ES")
for c in four:
    svg.append(f'<path d="{geom_path(world[world.ADMIN == NAMES[c]].union_all(), frame)}" fill="{tint(PALETTE[c], .3)}" stroke="{C["page"]}" stroke-width="1"/>')
assert ten.students.max() == 12464  # the widest arrow, used in arrow_width
for _, f in ten.sort_values("students").iterrows():  # big arrows on top
    svg.append(draw_arrow(*curve(f.origin, f.dest), arrow_width(f.students), PALETTE[f.dest]))
LABEL_AT = {("IT", "ES"): 0.5, ("ES", "IT"): 0.5}  # share of the way along the arrow; the rest sit near the start
for _, f in ten.iterrows():
    lx, ly = along(f.origin, f.dest, LABEL_AT.get((f.origin, f.dest), 0.32))
    svg.append(f'<text x="{lx:.1f}" y="{ly + 6:.1f}" font-size="17" font-weight="700" fill="{C["ink"]}" text-anchor="middle" '
               f'stroke="{C["page"]}" stroke-width="4.5" paint-order="stroke" stroke-linejoin="round">{f.students:,}</text>')
NAME_AT = {"ES": (-5.2, 38.6), "FR": (2.3, 45.1), "DE": (11.6, 52.9), "IT": (15.9, 40.9)}
for c, (lon, lat) in NAME_AT.items():
    x, y = frame.xy(*to3035.transform(lon, lat))
    svg.append(text(x, y, NAMES[c], 22, 800, PALETTE[c], "middle"))
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

# Legend over the Atlantic, clear of any land: what an arrow means
LX, LY = 34, MAP_TOP + 112
svg.append(text(LX, LY, "How to read an arrow", 17, 700))
y = LY + 34
svg.append(draw_arrow((LX + 4, y), (LX + 60, y - 14), (LX + 116, y), 7, C["ink2"]))
svg.append(text(LX, y + 26, "Home", 15, 700, C["ink2"]))
svg.append(text(LX + 124, y + 26, "Host", 15, 700, C["ink2"], "end"))
svg.append(text(LX, y + 52, "From the students' home country", 15, 400, C["ink2"]))
svg.append(text(LX, y + 71, "to the country hosting them", 15, 400, C["ink2"]))
svg.append(text(LX, y + 96, "Colour: the host country", 15, 400, C["ink2"]))
svg.append(text(LX, y + 120, "Width: number of students", 15, 400, C["ink2"]))
for n, students in enumerate((4000, 12000)):
    yy = y + 144 + n * 26
    svg.append(f'<path d="M{LX} {yy} L{LX + 46} {yy}" stroke="{C["ink2"]}" stroke-width="{arrow_width(students):.1f}" stroke-opacity=".72"/>')
    svg.append(text(LX + 58, yy + 5, f"{students:,}", 15, 400, C["ink2"]))

# Note on the biggest flow, Italy to Spain, over the Atlantic north of Spain
note_x, note_y = 34, MAP_TOP + 364
svg.append(f'<text class="note" x="{note_x}" y="{note_y}" font-size="22" fill="{C["ink"]}"><tspan x="{note_x}">A third of Italy\'s Erasmus</tspan>'
           f'<tspan x="{note_x}" dy="27">students go to Spain</tspan></text>')
ax, ay = along("IT", "ES", 0.95)
ax, ay = ax - 30, ay  # just west of where the arrow lands in Spain
sx, sy = note_x + 120, note_y + 40
svg.append(f'<path d="M{sx} {sy} C {sx} {sy + 70}, {ax - 70} {ay - 10}, {ax:.1f} {ay:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{ax - 12:.1f} {ay - 7:.1f} L{ax:.1f} {ay:.1f} L{ax - 11:.1f} {ay + 8:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# Columns under the map: where the students went
dest_top = list(received.index[:6])
columns = [(received[c] / total, NAMES[c], PALETTE.get(c, REST)) for c in dest_top]
columns.append((1 - sum(v for v, _, _ in columns), f"{len(received) - len(dest_top)} others", REST))
TITLE_Y, BASE_Y, MAX_H = MAP_TOP + frame.ph + 34, MAP_TOP + frame.ph + 150, 76
svg.append(text(60, TITLE_Y, f"Where the {total / 1000:.0f}k Erasmus students who left in {YEAR} went", 21, 700))
step = 960 / len(columns)
tallest = max(v for v, _, _ in columns)
for i, (value, label, fill) in enumerate(columns):
    cx, h = 60 + step * (i + 0.5), MAX_H * value / tallest
    svg.append(f'<rect x="{cx - step * 0.36:.1f}" y="{BASE_Y - h:.1f}" width="{step * 0.72:.1f}" height="{h:.1f}" rx="3" fill="{fill}"/>')
    svg.append(text(cx, BASE_Y - h - 8, f"{value:.0%}", 20, 700, None, "middle"))
    svg.append(text(cx, BASE_Y + 20, label, 15, 400, C["ink2"], "middle"))

# Headline, dek, byline and footer
svg.append(text(60, 90, "The 10 biggest Erasmus flows", 50, 800))
svg.append(text(60, 146, "run between four countries", 50, 800))
svg.append(text(60, 190, f"Erasmus students who started a stay abroad of three months or more in {YEAR}.", 25, 400, C["ink2"]))
svg.append(text(60, 220, f"These ten flows carry {ten_share:.0%} of the {total / 1000:.0f}k students in the programme.", 25, 400, C["ink2"]))
svg.append(byline(252, "30DayMapChallenge #13: Interactions"))
FOOTER = [
    ("Method:", f"Erasmus+ students aged 18 or more who started a stay of at least 90 days abroad in {YEAR}. Switzerland sends none."),
    ("Source:", "Väisänen et al. (2025), University of Helsinki, from the European Commission's Erasmus+ data. Natural Earth."),
    ("Comments:", f"the 11th flow, the Netherlands to Spain ({eleventh.students:,} students), is only {ten.students.iloc[9] - eleventh.students} behind the 10th."),
]
svg += footer(FOOTER, x=60, y=1266, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day13_interactions.png")
top.assign(country=top.index.map(NAMES), first_choice=top.dest.map(NAMES), sent=sent.reindex(top.index)).rename(
    columns={"students": "students_to_first_choice"})[["country", "sent", "first_choice", "students_to_first_choice", "share"]] \
    .round(3).sort_values("sent", ascending=False).to_csv(HERE / "first_choice_by_country.csv")
ten.assign(home=ten.origin.map(NAMES), host=ten.dest.map(NAMES))[["home", "host", "students"]].to_csv(HERE / "top_flows.csv", index=False)

# 3. Second image: the flows between the eight biggest hosts and the rest, as a chord diagram
GROUPS = list(PALETTE) + ["XX"]  # XX: every other country
LABEL = {**NAMES, "XX": f"{len(set(flows.origin) | set(flows.dest)) - len(PALETTE)} other countries"}
COLOUR = {**PALETTE, "XX": REST}
grouped = flows.assign(origin=flows.origin.where(flows.origin.isin(PALETTE), "XX"), dest=flows.dest.where(flows.dest.isin(PALETTE), "XX"))
matrix = grouped.groupby(["origin", "dest"]).students.sum().unstack(fill_value=0).reindex(index=GROUPS, columns=GROUPS, fill_value=0)
matrix.loc["XX", "XX"] = 0  # flows between two smaller countries are left out, to keep the circle about the main hosts
out_total, in_total = matrix.sum(axis=1), matrix.sum(axis=0)
both = flows.assign(pair=[tuple(sorted(k)) for k in zip(flows.origin, flows.dest)]).groupby("pair").students.sum()
pairs = both.to_dict()  # every pair of countries, both directions added up
ranked = sorted(pairs.items(), key=lambda kv: -kv[1])
(best, best_n), (second, second_n) = ranked[0], ranked[1]
print("top pairs", ranked[:3])
assert set(best) == {"ES", "IT"} and set(second) == {"ES", "FR"} and 1.95 < best_n / second_n < 2.1

CX, CY, R = 540, 708, 328  # circle centre and inner radius of the ring
RING = 16
GAP, SPLIT = 0.045, 0.012  # radians between countries, and between each country's "sent" and "hosted" parts
free = 2 * np.pi - GAP * len(GROUPS) - SPLIT * len(GROUPS)
per_student = free / (out_total.sum() + in_total.sum())


def polar(angle, radius):
    return CX + radius * np.sin(angle), CY - radius * np.cos(angle)


def arc(a0, a1, radius):
    x, y = polar(a1, radius)
    return f"A{radius} {radius} 0 {int(a1 - a0 > np.pi)} 1 {x:.1f} {y:.1f}"


# Lay out each country: first the students it sent, then the ones it hosted, clockwise from the top
spans, angle = {}, GAP / 2
for g in GROUPS:
    sent_span = out_total[g] * per_student
    host_span = in_total[g] * per_student
    spans[g] = {"sent": (angle, angle + sent_span), "hosted": (angle + sent_span + SPLIT, angle + sent_span + SPLIT + host_span)}
    angle += sent_span + SPLIT + host_span + GAP

# Where each ribbon starts and ends: ribbons leave in clockwise order of their destination and arrive in order of origin
order = {g: i for i, g in enumerate(GROUPS)}
start, end = {}, {}
for g in GROUPS:
    a = spans[g]["sent"][0]
    for d in sorted(GROUPS, key=lambda d: (order[d] - order[g]) % len(GROUPS)):
        width = matrix.loc[g, d] * per_student
        start[(g, d)] = (a, a + width)
        a += width
    a = spans[g]["hosted"][0]
    for o in sorted(GROUPS, key=lambda o: (order[g] - order[o]) % len(GROUPS)):
        width = matrix.loc[o, g] * per_student
        end[(o, g)] = (a, a + width)
        a += width

chord = []
ribbons = sorted(((o, d) for o in GROUPS for d in GROUPS if matrix.loc[o, d] > 0), key=lambda k: matrix.loc[k])
for o, d in ribbons:  # small ribbons first, the big ones on top
    (a0, a1), (b0, b1) = start[(o, d)], end[(o, d)]
    p0, q0 = polar(a0, R), polar(b0, R)
    chord.append(f'<path d="M{p0[0]:.1f} {p0[1]:.1f} {arc(a0, a1, R)} Q{CX} {CY} {q0[0]:.1f} {q0[1]:.1f} {arc(b0, b1, R)} '
                 f'Q{CX} {CY} {p0[0]:.1f} {p0[1]:.1f}Z" fill="{COLOUR[d]}" fill-opacity=".72" stroke="{C["card"]}" stroke-width=".4"/>')

# The ring: a light band for the students each country sent, a solid one for those it hosted
for g in GROUPS:
    for part, shade in (("sent", .38), ("hosted", 1)):
        a0, a1 = spans[g][part]
        p0, p1 = polar(a0, R + 4), polar(a1, R + 4 + RING)
        q0 = polar(a0, R + 4 + RING)
        chord.append(f'<path d="M{p0[0]:.1f} {p0[1]:.1f} {arc(a0, a1, R + 4)} L{p1[0]:.1f} {p1[1]:.1f} '
                     f'A{R + 4 + RING} {R + 4 + RING} 0 {int(a1 - a0 > np.pi)} 0 {q0[0]:.1f} {q0[1]:.1f}Z" fill="{tint(COLOUR[g], shade)}"/>')
    mid = (spans[g]["sent"][0] + spans[g]["hosted"][1]) / 2
    lx, ly = polar(mid, R + RING + 26)
    anchor = "start" if np.sin(mid) > 0.15 else "end" if np.sin(mid) < -0.15 else "middle"
    dy = 6 if abs(np.cos(mid)) < 0.5 else (-4 if np.cos(mid) > 0 else 16)
    chord.append(text(lx, ly + dy, LABEL[g], 17, 700, C["ink"], anchor))
    detail = (f"sent {out_total[g] / 1000:.1f}k, hosted {in_total[g] / 1000:.1f}k" if g != "XX"
              else f"to and from the 8: sent {out_total[g] / 1000:.1f}k, hosted {in_total[g] / 1000:.1f}k")
    chord.append(text(lx, ly + dy + 19, detail, 14, 400, C["ink2"], anchor))

# Legend under the circle, and a note on the Italy and Spain ribbons
LY2 = CY + R + 100
chord.append(text(60, LY2, "How to read it", 17, 700))
chord.append(f'<rect x="60" y="{LY2 + 12}" width="34" height="12" rx="2" fill="{tint(C["blue"], .38)}"/><rect x="96" y="{LY2 + 12}" width="34" height="12" rx="2" fill="{C["blue"]}"/>')
chord.append(text(142, LY2 + 23, "Each country's ring: students it sent (light), then students it hosted (solid)", 15, 400, C["ink2"]))
chord.append(text(60, LY2 + 48, "Each ribbon runs from the home country to the host country, in the host's colour. Width shows students.", 15, 400, C["ink2"]))

it_es, es_it = matrix.loc["IT", "ES"], matrix.loc["ES", "IT"]
it_mid = (spans["IT"]["sent"][0] + spans["IT"]["hosted"][1]) / 2
nx, ny = 906, polar(it_mid, R + RING + 26)[1] + 96  # under the Italy label
chord.append(f'<text class="note" x="{nx}" y="{ny}" font-size="21" fill="{C["ink"]}"><tspan x="{nx}">{it_es:,} from</tspan>'
             f'<tspan x="{nx}" dy="26">Italy to Spain,</tspan><tspan x="{nx}" dy="26">{es_it:,} back</tspan></text>')
a0, a1 = start[("IT", "ES")]
tx, ty = polar((a0 + a1) / 2, R + RING + 8)
sx, sy = nx - 12, ny - 22  # from just above the note to the start of the Italy to Spain ribbon
chord.append(f'<path d="M{sx} {sy} C {sx - 4} {sy - 50}, {tx + 4} {ty + 40}, {tx:.1f} {ty:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
ux, uy = (tx - CX) / R, (ty - CY) / R  # pointing inwards at the ring
chord.append(f'<path d="M{tx + 12 * ux - 6 * uy:.1f} {ty + 12 * uy + 6 * ux:.1f} L{tx:.1f} {ty:.1f} L{tx + 12 * ux + 6 * uy:.1f} {ty + 12 * uy - 6 * ux:.1f}" '
             f'fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

chord.append(text(60, 90, "Italy and Spain swap more Erasmus", 50, 800))
chord.append(text(60, 146, "students than any other pair", 50, 800))
chord.append(text(60, 190, f"Erasmus students who started a stay abroad in {YEAR}, by home and host country.", 25, 400, C["ink2"]))
chord.append(text(60, 220, f"{best_n:,} went between Italy and Spain, twice as many as between France and Spain.", 25, 400, C["ink2"]))
chord.append(byline(252, "30DayMapChallenge #13: Interactions"))
CHORD_FOOTER = [FOOTER[0], ("Source:", "Väisänen et al. (2025), University of Helsinki, from the European Commission's Erasmus+ data."),
                ("Comments:", "students moving between two of the smaller countries are left out.")]
chord += footer(CHORD_FOOTER, x=60, y=1266, width=960, size=17, line_height=20)
save_png(page("".join(chord)), HERE / "day13_flows.png")
matrix.rename(index=LABEL, columns=LABEL).to_csv(HERE / "flows_between_hosts.csv")
