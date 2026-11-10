"""Day 10, Prompting only: five AI chatbots drew Europe from memory, on top of the real one.

The answers in `answers/` are exactly what each chat replied to the same prompt, with web search off.
The only clean-up is reading past the ```json fence one of them wrapped its answer in.
This day breaks from the series look on purpose: white, all in a code font, laid out like a chat.
"""
import base64
import html
import json
import re
import sys
import textwrap
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
import shapely.ops
from pyproj import Transformer
from shapely.geometry import box, shape

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, FONT_DIR, Frame, _download, geom_path, page, save_png  # noqa: E402

NE = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
MONO_URL = "https://raw.githubusercontent.com/google/fonts/main/ofl/jetbrainsmono/JetBrainsMono%5Bwght%5D.ttf"
PROMPT = ('From memory, with no search or tools, draw these countries as GeoJSON polygons: the 27 EU countries, the UK, '
          'Iceland, Norway, Switzerland, the Western Balkans, Ukraine, Belarus and Moldova. Use longitude and latitude, '
          '15 to 60 points per country, and the properties "name" and "iso_a2". Reply only with the GeoJSON.')
MODELS = {  # file: (name on the chart, model and setting as used, colour)
    "chatgpt": ("ChatGPT", "GPT-6.1 Sol, highest reasoning", "#0E9F7E"),
    "claude": ("Claude", "Opus 5.5, highest effort", "#D9643A"),
    "gemini": ("Gemini", "3.1 Pro, thinking", "#2F6FDB"),
    "mistral": ("Mistral", "Medium 3.5, thinking", "#D9A21B"),
    "grok": ("Grok", "4.7, highest reasoning", "#1B1B1F"),
}
TARGET = ("AT BE BG HR CY CZ DK EE FI FR DE GR HU IE IT LV LT LU MT NL PL PT RO SK SI ES SE "
          "GB IS NO CH AL BA ME MK RS XK UA BY MD").split()
AREA = box(-24.6, 34, 45, 72)  # Europe without the Atlantic islands far offshore, for both maps

# The series background (Oat), with the map card in the series page colour
PAPER = C["page"]
INK, GREY, LIGHT, RULE = "#16181D", "#655F55", "#8F887C", "#CFC5B3"
LAND, LAND_EDGE = "#E4DACA", "#CDC2AE"
BUBBLE, SOFT = "#EAE2D3", "#EFE8DB"
to_laea = Transformer.from_crs(4326, 3035, always_xy=True)
def laea(g):
    return shapely.ops.transform(to_laea.transform, g)


# 1. The real countries (Natural Earth, with Crimea as part of Ukraine, as every AI drew it)
world = gpd.read_file(_download(NE + "ne_10m_admin_0_countries.geojson", DATA_DIR / "ne_10m_admin_0_countries.geojson"))
world = world[["ADMIN", "ISO_A2_EH", "geometry"]].copy()
world["geometry"] = shapely.make_valid(world.geometry.values)
russia, ukraine = (world.index[world.ADMIN == name][0] for name in ("Russia", "Ukraine"))
parts = list(world.at[russia, "geometry"].geoms)
crimea = [p for p in parts if box(32.4, 44.3, 36.6, 46.3).contains(p.centroid)]
world.at[russia, "geometry"] = shapely.MultiPolygon([p for p in parts if p not in crimea])
world.at[ukraine, "geometry"] = shapely.union_all([world.at[ukraine, "geometry"], *crimea])
world["iso"] = np.where(world.ADMIN == "Kosovo", "XK", world.ISO_A2_EH)
truth = {iso: laea(world[world.iso == iso].geometry.union_all().intersection(AREA)) for iso in TARGET}


# 2. Each AI's countries, and how much of each lands in the right country
def answer(file):
    text = re.sub(r"^```(json)?\s*|\s*```$", "", (HERE / "answers" / f"{file}.txt").read_text().strip())
    countries = {}
    for feature in json.loads(text)["features"]:
        iso = feature["properties"]["iso_a2"].upper()
        iso = {"UK": "GB", "EL": "GR"}.get(iso, iso)
        countries.setdefault(iso, []).append(shape(feature["geometry"]))
    return {iso: shapely.union_all([shapely.make_valid(g) for g in gs]) for iso, gs in countries.items()}


def polygons(g):
    return [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon"]


rows, drawn = [], {}
for file, (name, model, colour) in MODELS.items():
    ai = answer(file)
    drawn[file] = ai
    right = wrong = missed = 0
    gaps = []
    for iso in TARGET:
        real = truth[iso]
        mine = laea(ai[iso].intersection(AREA)) if iso in ai else shapely.Polygon()
        right += mine.intersection(real).area
        wrong += mine.difference(real).area
        missed += real.difference(mine).area
        for polygon in polygons(ai.get(iso, shapely.Polygon())):
            gaps += [shapely.Point(to_laea.transform(*xy)).distance(real.boundary) / 1000
                     for xy in polygon.exterior.coords[:-1] if AREA.contains(shapely.Point(xy))]
    total = right + wrong + missed
    rows.append({"ai": name, "model": model, "right": right / total, "wrong_place": wrong / total, "missed": missed / total,
                 "points": len(gaps), "median_miss_km": float(np.median(gaps)), "countries": len(set(ai) & set(TARGET))})
scores = pd.DataFrame(rows).sort_values("right", ascending=False).reset_index(drop=True)
print(scores.round(3).to_string(index=False))
scores.round(4).to_csv(HERE / "scores.csv", index=False)
best, worst = scores.iloc[0], scores.iloc[-1]
assert round(best["right"] * 100) == round(scores.iloc[1]["right"] * 100) == 91, "the headline says two AIs got 91% right"

# 3. Page, all in a code font (JetBrains Mono: every character is 0.6 em wide, which makes wrapping simple)
MONO_FILE = _download(MONO_URL, FONT_DIR / "JetBrainsMono.ttf")
MONO_CSS = ("@font-face{font-family:Mono;src:url(data:font/ttf;base64," + base64.b64encode(MONO_FILE.read_bytes()).decode()
            + ");font-weight:100 800} svg text{font-family:Mono,monospace}")
name_to_file = {v[0]: k for k, v in MODELS.items()}
ORDER = list(scores.sort_values("right").ai.map(name_to_file))  # worst first, so the closest ones end on top


def mono_text(x, y, words, size, weight=400, fill=INK, anchor="start", spacing=0, opacity=1):
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" letter-spacing="{spacing}" opacity="{opacity}">{html.escape(words)}</text>')


def wrap(words, size, width):
    return textwrap.wrap(words, int(width / (0.6 * size)))


def line_path(coords):
    return "M" + " L".join(f"{x:.1f} {y:.1f}" for x, y in coords)


# Layout
lines = wrap(PROMPT, 13, 620)
BW = max(len(line) for line in lines) * 0.6 * 13 + 40
BX, BY, BH = 1024 - BW, 214, 22 + 19 * len(lines)
CX0, CX1, CY0, CY1 = 56, 1024, BY + BH + 36, 1222
HEAD = 44
MAP_TOP, MAP_BOTTOM = CY0 + HEAD, CY1
y0, y1 = 1450000, 5450000
k = (MAP_BOTTOM - MAP_TOP) / (y1 - y0)
x0 = 4700000 - (CX1 - CX0) / 2 / k
frame = Frame(x0, x0 + (CX1 - CX0) / k, y0, y1, CX0, CX1, MAP_TOP)
view = frame.box().buffer(80000)

# Everything that never changes, drawn once
grat = []
for lat in range(30, 81, 10):
    xs, ys = to_laea.transform(np.linspace(-40, 70, 220), np.full(220, lat))
    grat.append(line_path(zip(*frame.xy(np.array(xs), np.array(ys)))))
for lon in range(-30, 71, 10):
    xs, ys = to_laea.transform(np.full(200, lon), np.linspace(25, 85, 200))
    grat.append(line_path(zip(*frame.xy(np.array(xs), np.array(ys)))))
land = world.clip(box(-40, 25, 70, 85)).to_crs(3035)
land = land[land.intersects(view)].geometry.intersection(view)
BASE_MAP = (f'<path d="{"".join(grat)}" fill="none" stroke="{RULE}" stroke-width=".9" stroke-dasharray="1 4" stroke-linecap="round"/>'
            f'<path d="{geom_path(land.union_all(), frame)}" fill="{LAND}"/>'
            f'<path d="{"".join(geom_path(g, frame) for g in land.simplify(1000))}" fill="none" stroke="{LAND_EDGE}" stroke-width=".8"/>')
# Each AI's outlines as separate rings, in the order the countries get drawn (west to east), so they can be traced
RINGS = {}
for file, ai in drawn.items():
    countries = sorted(ai.items(), key=lambda item: item[1].centroid.x)
    RINGS[file] = [[geom_path(laea(polygon), frame) for polygon in polygons(g)] for _, g in countries]


def callout(lon, lat, dx, dy, title, body):
    """A small label with a thin line to the spot it is about."""
    px, py = frame.xy(*to_laea.transform(lon, lat))
    tx, ty = px + dx, py + dy
    width = max(len(title), len(body)) * 0.6 * 12.5 + 26
    edge_x = tx if dx > 0 else tx + width
    return (f'<path d="M{px:.1f} {py:.1f} L{edge_x:.1f} {ty + 22:.1f}" stroke="{INK}" stroke-width="1"/>'
            f'<circle cx="{px:.1f}" cy="{py:.1f}" r="2.6" fill="{INK}"/>'
            f'<rect x="{tx:.1f}" y="{ty:.1f}" width="{width:.1f}" height="44" rx="10" fill="{PAPER}" stroke="{RULE}"/>'
            + mono_text(tx + 13, ty + 18, title, 12.5, 700) + mono_text(tx + 13, ty + 35, body, 12.5, 400, GREY))


FINAL = {"progress": {f: 1 for f in MODELS}, "current": None, "phase": None, "tick": 0, "done": set(MODELS), "callouts": True}


def chart(state=FINAL, embed_font=True):
    """The whole page as SVG. `state` says how far each AI has drawn, who is busy, and which scores show."""
    svg = [f"<style>{MONO_CSS}</style>"] if embed_font else []
    svg.append(mono_text(56, 80, "5 AIs drew Europe from memory.", 38, 500, INK, spacing=-1))
    top_two = " and ".join(scores.iloc[:2].ai)
    svg.append(mono_text(56, 128, f"{top_two}: {best['right']:.0%}. {worst['ai']}: {worst['right']:.0%}.", 38, 800, INK, spacing=-1))
    svg.append(mono_text(56, 166, "Map by Josep Ferrer using AI tools only and a final design layer · @iamjosepferrer · databites.tech",
                         13, 500, GREY))
    svg.append(mono_text(56, 187, "#30DayMapChallenge · Day 10 · Prompting only", 13, 500, LIGHT))

    # The prompt, as the user's message
    svg.append(f'<rect x="{BX:.1f}" y="{BY}" width="{BW:.1f}" height="{BH}" rx="18" fill="{BUBBLE}"/>')
    for i, line in enumerate(lines):
        svg.append(mono_text(BX + 20, BY + 27 + 19 * i, line, 13))
    svg.append(mono_text(1024, BY + BH + 18, "the same prompt, in 5 new chats", 12, 600, LIGHT, "end", spacing=0.5))

    # Who is answering right now, like a chat's status line
    if state["current"]:
        name, model, colour = MODELS[state["current"]]
        pulse = 5 + 1.6 * abs(np.sin(state["tick"] * 0.55))
        svg.append(f'<circle cx="62" cy="{BY + BH + 13}" r="{pulse:.1f}" fill="{colour}" opacity=".25"/><circle cx="62" cy="{BY + BH + 13}" r="4.5" fill="{colour}"/>')
        if state["phase"] == "thinking":
            words = f"{name} is thinking" + "." * (1 + state["tick"] // 3 % 3)
        elif state["phase"] == "drawing":
            drawn_now = sum(1 for i in range(40) if _country_progress(state["progress"][state["current"]], i, 40) > 0)
            words = f"{name} is drawing Europe · {drawn_now} of 40 countries"
        else:
            row = scores.set_index("ai").loc[name]
            words = f"{name} is done · {row['right']:.0%} in the right country"
        svg.append(mono_text(76, BY + BH + 18, words, 13, 600, INK))

    # The map card
    svg.append(f'<rect x="{CX0}" y="{CY0}" width="{CX1 - CX0}" height="{CY1 - CY0}" rx="22" fill="{PAPER}" stroke="{RULE}" stroke-width="1.2"/>')
    x = CX0 + 22
    for file, (name, _, colour) in MODELS.items():
        faded = state["current"] is not None and file != state["current"] and state["progress"][file] == 0
        svg.append(f'<circle cx="{x + 5}" cy="{CY0 + 22}" r="5" fill="{colour}" opacity="{0.35 if faded else 1}"/>')
        svg.append(mono_text(x + 16, CY0 + 27, name, 13, 600, INK, opacity=0.35 if faded else 1))
        x += 16 + len(name) * 7.8 + 26
    svg.append(f'<rect x="{CX1 - 176}" y="{CY0 + 16}" width="22" height="12" rx="3" fill="{LAND}" stroke="{LAND_EDGE}"/>')
    svg.append(mono_text(CX1 - 146, CY0 + 27, "real borders", 13, 600, GREY))
    svg.append(f'<path d="M{CX0} {CY0 + HEAD} H{CX1}" stroke="{RULE}"/>')
    svg.append(f'<clipPath id="card"><path d="M{CX0} {MAP_TOP} H{CX1} V{CY1 - 22} Q{CX1} {CY1} {CX1 - 22} {CY1} H{CX0 + 22} Q{CX0} {CY1} {CX0} {CY1 - 22} Z"/></clipPath>')
    svg.append('<g clip-path="url(#card)">' + BASE_MAP)
    for file in ORDER:
        p = state["progress"][file]
        if p <= 0:
            continue
        busy = state["current"] is not None
        opacity = 0.9 if (not busy or file == state["current"]) else 0.3
        colour = MODELS[file][2]
        if p >= 1:
            svg.append(f'<path d="{"".join(sum(RINGS[file], []))}" fill="none" stroke="{colour}" stroke-width="1.15" stroke-opacity="{opacity}" stroke-linejoin="round"/>')
            continue
        n = len(RINGS[file])
        for i, rings in enumerate(RINGS[file]):
            q = _country_progress(p, i, n)
            if q <= 0:
                continue
            for d in rings:  # trace each ring with a dash that grows from 0 to its full length
                svg.append(f'<path d="{d}" pathLength="1" stroke-dasharray="1 1" stroke-dashoffset="{1 - q:.3f}" fill="none" '
                           f'stroke="{colour}" stroke-width="1.15" stroke-opacity="{opacity}" stroke-linejoin="round"/>')
    svg.append("</g>")

    # The ranking: each row appears once that AI is done
    RX, RY, RW = CX0 + 20, frame.xy(0, 4760000)[1], 300
    svg.append(f'<rect x="{RX}" y="{RY}" width="{RW}" height="{40 + 22 * len(scores)}" rx="12" fill="{SOFT}" stroke="{RULE}"/>')
    svg.append(mono_text(RX + 16, RY + 24, "right country", 11, 600, LIGHT))
    svg.append(mono_text(RX + RW - 16, RY + 24, "median miss", 11, 600, LIGHT, "end"))
    for i, row in scores.iterrows():
        if name_to_file[row["ai"]] not in state["done"]:
            continue
        y = RY + 46 + 22 * i
        svg.append(f'<circle cx="{RX + 21}" cy="{y - 4}" r="4.5" fill="{MODELS[name_to_file[row["ai"]]][2]}"/>')
        svg.append(mono_text(RX + 34, y, row["ai"], 13, 600, INK))
        svg.append(mono_text(RX + 176, y, f"{row['right']:.0%}", 13, 700, INK, "end"))
        svg.append(mono_text(RX + RW - 16, y, f"{row['median_miss_km']:.0f} km", 13, 400, GREY, "end"))

    if state["callouts"]:
        svg.append(callout(-4.9, 58.0, -252, 22, "Mistral's Norway", "starts in Scotland"))  # its first point, over the North Sea
        svg.append(callout(25.6, 43.9, 150, -60, "Grok's Bulgaria", "is a thin strip"))  # label over the Black Sea

    footer = [
        ("method", "each AI's 40 countries compared with the real ones. Shares are of all land on either map, without far-off "
                   "islands. The median miss is how far each point the AI wrote sits from the real outline."),
        ("models", "each lab's top model on a standard paid plan, at its highest thinking setting, web search off, November 2026: "
                   + "; ".join(f"{n} {m}" for n, m, _ in MODELS.values()) + "."),
        ("source", "the five answers, unedited, in the repo. Natural Earth borders, with Crimea in Ukraine. Design added in code."),
    ]
    y = 1250
    for label, body in footer:
        for i, row in enumerate(wrap(f"{label}: {body}", 11.5, 968)):
            if i == 0:
                svg.append(f'<text x="56" y="{y}" font-size="11.5" fill="{GREY}"><tspan font-weight="700" fill="{INK}">{label}:</tspan>{html.escape(row[len(label) + 1:])}</text>')
            else:
                svg.append(mono_text(56, y, row, 11.5, 400, GREY))
            y += 15
    return page("".join(svg))


def _country_progress(p, i, n):
    """Countries start one after another, west to east, and each takes 40% of the drawing time to trace."""
    start = 0.6 * i / max(n - 1, 1)
    return float(np.clip((p - start) / 0.4, 0, 1))


if __name__ == "__main__":
    save_png(chart(), HERE / "day10_prompting.png")
