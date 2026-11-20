"""Day 19, Senses: Smell. An atlas of the EU's protected cheeses: one dot per cheese, where it is made.

The list comes from eAmbrosia, the EU register of geographical indications, through its public API: every registered,
not removed name whose customs code is 0406 (cheese and curd) from an EU country. That leaves out a few
cheese-like products the EU registers in its class for other animal products, under the plain code 04: ricotta,
requeijão, Cancoillotte, Obazda and Estonia's Sõir. PDO means every step happens in the
named area; PGI means at least one does. The register has no coordinates, so cheese_places.csv places each cheese by
hand near the centre of its production area. Dots that would overlap are nudged apart, without leaving their country.
"""
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import shapely
import shapely.affinity
import shapely.ops
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, DATA_DIR, Frame, _download, byline, countries, fade_defs, flush, footer, geom_path, page, save_png, text  # noqa: E402

API = "https://webgate.ec.europa.eu/eambrosia-api/api/geographical-indications?page={}&size=2000"
EU = {"at": "Austria", "be": "Belgium", "bg": "Bulgaria", "cy": "Cyprus", "cz": "Czechia", "de": "Germany", "dk": "Denmark",
      "ee": "Estonia", "es": "Spain", "fi": "Finland", "fr": "France", "gr": "Greece", "hr": "Croatia", "hu": "Hungary",
      "ie": "Ireland", "it": "Italy", "lt": "Lithuania", "lu": "Luxembourg", "lv": "Latvia", "mt": "Malta", "nl": "Netherlands",
      "pl": "Poland", "pt": "Portugal", "ro": "Romania", "se": "Sweden", "si": "Slovenia", "sk": "Slovakia"}
PDO, PGI = "#C98A0E", "#F2D58C"
# The cheeses named on the map: register name, label, and where the label goes from its dot (dx, dy, anchor)
NAMED = {"Roquefort": ("Roquefort", -9, 16, "end"), "Camembert de Normandie": ("Camembert", -9, 12, "end"),
         "Comté": ("Comté", 12, -12, "start"), "Époisses": ("Époisses", -9, -6, "end"), "Munster": ("Munster", 9, -6, "start"),
         "Maroilles": ("Maroilles", -9, -4, "end"), "Brie de Meaux": ("Brie de Meaux", 0, -12, "middle"),
         "Parmigiano Reggiano": ("Parmigiano", 10, 14, "start"), "Gorgonzola": ("Gorgonzola", -12, 6, "end"),
         "Mozzarella di Bufala Campana": ("Mozzarella di Bufala", -9, 10, "end"), "Pecorino Sardo": ("Pecorino Sardo", -9, 12, "end"),
         "Queso Manchego": ("Manchego", 9, 4, "start"), "Cabrales": ("Cabrales", 0, -30, "middle"),
         "Torta del Casar": ("Torta del Casar", -9, 14, "end"), "Idiazabal": ("Idiazabal", 6, -22, "start"),
         "Mahón-Menorca": ("Mahón", 9, 4, "start"), "Queijo Serra da Estrela": ("Serra da Estrela", -9, -2, "end"),
         "Φέτα": ("Feta", 14, -4, "start"), "Χαλλούμι": ("Halloumi", 0, 18, "middle"), "Gouda Holland": ("Gouda", -12, 0, "end"),
         "Fromage de Herve": ("Herve", 9, 4, "start"), "Havarti": ("Havarti", 9, 12, "start"), "Oscypek": ("Oscypek", 14, 12, "start"),
         "Olomoucké tvarůžky": ("Olomoucké tvarůžky", 9, -5, "start"),
         "Paški sir": ("Paški sir", 9, 12, "start"), "Telemea de Sibiu": ("Telemea de Sibiu", 9, 10, "start"),
         "Kaffeost": ("Kaffeost", 9, 4, "start"), "Svecia": ("Svecia", 9, 4, "start"), "Džiugas": ("Džiugas", 9, 4, "start"),
         "Imokilly Regato": ("Imokilly Regato", 0, -10, "middle"), "Γραβιέρα Κρήτης": ("Graviera Kritis", 0, 20, "middle")}

# 1. The register: every registered cheese of an EU country, with the place it comes from
pages = [json.loads(_download(API.format(p), DATA_DIR / f"eambrosia_gi_page{p}.json").read_text()) for p in (0, 1)]
gi = pd.DataFrame([g for p in pages for g in p["content"]])
assert len(gi) == pages[0]["totalElements"]
gi["status"] = gi.registration.map(lambda r: (r or {}).get("status"))
gi["cheese"] = gi.cnClassification.map(lambda cn: any(c["cnText"].startswith("0406") for c in (cn or [])))
cheese = gi[gi.cheese & (gi.status == "REGISTERED") & ~gi.removedFlag & ~gi.thirdCountry].copy()
cheese["name"] = cheese.protectedNames.str[0].str.strip().str.replace(r" \(Queijo de Castelo Branco.*", "", regex=True)
cheese["country"] = cheese.countries.str[0]  # one cheese is shared by Croatia and Slovenia; it counts for Croatia, listed first
cheese = cheese.merge(pd.read_csv(HERE / "cheese_places.csv"), on="name", how="left")
assert len(cheese) == 255 and cheese.lon.notna().all() and cheese.country.isin(EU).all() and set(NAMED) <= set(cheese.name)
count = cheese.groupby(["country", "giType"]).size().unstack(fill_value=0)
count["total"] = count.sum(axis=1)
count = count.sort_values(["total", "PDO"], ascending=False)
print(count.to_string())
assert list(count.index[:2]) == ["fr", "it"]
assert 0.66 < count.total[["fr", "it", "es", "gr"]].sum() / len(cheese) < 0.69  # "two in every three"
assert count.total["be"] == 1  # the note: Herve is Belgium's only one


def spread(xy, gap, keep=None, rounds=600):
    """Nudge points apart until none are closer than `gap`, keeping each as near its true place as it can be.
    `keep` holds, for each point, the shape it must stay inside (its own country), or None."""
    xy, home = xy.copy(), xy.copy()
    rng = np.random.default_rng(0)
    for _ in range(rounds):
        delta = xy[:, None, :] - xy[None, :, :]
        dist = np.hypot(*np.moveaxis(delta, 2, 0)) + np.eye(len(xy)) * 1e9
        close = dist < gap
        if not close.any():
            break
        push = np.where(close[..., None], delta / np.maximum(dist, 0.01)[..., None] * (gap - dist)[..., None] / 2, 0).sum(axis=1)
        same = (dist < 0.01).any(axis=1)  # two cheeses on the very same spot need a first shove
        push[same] += rng.normal(0, 1, (same.sum(), 2))
        xy += push + (home - xy) * 0.02
        for k, shape in enumerate(keep if keep is not None else []):
            if shape is not None and not shape.contains(shapely.Point(xy[k])):
                xy[k] = shapely.ops.nearest_points(shape, shapely.Point(xy[k]))[0].coords[0]
    return xy


# 2. Map: the EU, and every cheese as a dot where it is made
MAP_TOP = 244
frame = Frame(1880000, 6800000, 1330000, 5080000, 0, 1080, MAP_TOP)
view = frame.box().buffer(30000)
world = countries().to_crs(3035)
world["geometry"] = world.geometry.buffer(0).intersection(view)
world = world[~world.is_empty]
in_eu = world.ADMIN.isin(EU.values())
svg = [f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath><g clip-path="url(#map)">',
       f'<path d="{geom_path(world[~in_eu].union_all(), frame)}" fill="{C["quiet_land"]}"/>',
       f'<path d="{"".join(geom_path(g, frame) for g in world[in_eu].geometry)}" fill="{C["page"]}" stroke="{C["ctxl"]}" '
       f'stroke-width=".7" stroke-linejoin="round"/>']
svg += [fade_defs(), f'<rect x="0" y="{MAP_TOP}" width="1080" height="24" fill="url(#fade-top)"/>',
        f'<rect x="0" y="{MAP_TOP + frame.ph - 30:.0f}" width="1080" height="30" fill="url(#fade-bottom)"/>', "</g>"]

R = 4.6
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
islands = cheese.lon < -12  # the Azores and the Canaries, drawn in boxes
main = cheese[~islands].copy()
px = np.array([frame.xy(x, y) for x, y in zip(*to3035.transform(main.lon.values, main.lat.values))])
# A dot may move to make room, but never out of its own country or into the sea
k = frame.k
to_pixels = [k, 0, 0, -k, frame.xy(0, 0)[0], frame.xy(0, 0)[1]]
shapes = {code: shapely.affinity.affine_transform(world[world.ADMIN == name].union_all(), to_pixels) for code, name in EU.items()}
inner = {code: shape.buffer(-1.5) for code, shape in shapes.items()}
keep = []
for (x, y), code in zip(px, main.country):
    point = shapely.Point(x, y)
    # A place right on a border can fall just outside the simplified outline, so 6 px of slack. Dots on small islands
    # (or on islets missing from the base map) stay free: there is no room on the island to move them apart.
    part = min(getattr(inner[code], "geoms", [inner[code]]), key=lambda g: g.distance(point))
    keep.append(inner[code] if part.distance(point) < 6 and part.area > 600 else None)
px = spread(px, 2 * R + 0.8, keep)
main["x"], main["y"] = px[:, 0], px[:, 1]
for row in main.sort_values("giType", ascending=False).itertuples():
    svg.append(f'<circle cx="{row.x:.1f}" cy="{row.y:.1f}" r="{R}" fill="{PDO if row.giType == "PDO" else PGI}" '
               f'stroke="{C["ink"]}" stroke-opacity=".55" stroke-width=".6"/>')
for row in main[main.name.isin(NAMED)].itertuples():
    label, dx, dy, anchor = NAMED[row.name]
    svg.append(f'<path d="M{row.x:.1f} {row.y:.1f} L{row.x + dx * 0.75:.1f} {row.y + dy * 0.75 - (4 if dy else 0):.1f}" stroke="{C["ink"]}" '
               f'stroke-width=".7"/>')
    svg.append(f'<circle cx="{row.x:.1f}" cy="{row.y:.1f}" r="{R}" fill="{PDO if row.giType == "PDO" else PGI}" '
               f'stroke="{C["ink"]}" stroke-width="1.3"/>')
    svg.append(text(row.x + dx, row.y + dy, label, 13, 700, C["ink"], anchor, halo=C["page"]))

# The Azores and the Canaries, in boxes over the Atlantic, at the same scale
for title, box, bx, by in (("Azores", (-29.0, 38.2, -27.0, 39.0), 60, MAP_TOP + 630), ("Canary Islands", (-18.3, 27.5, -13.3, 29.5), 60, MAP_TOP + 732)):
    lon0, lat0, lon1, lat1 = box
    crs = f"+proj=laea +lat_0={(lat0 + lat1) / 2} +lon_0={(lon0 + lon1) / 2}"
    to_local = Transformer.from_crs(4326, crs, always_xy=True)
    (x0, y0), (x1, y1) = to_local.transform(lon0, lat0), to_local.transform(lon1, lat1)
    f = Frame(x0, x1, y0, y1, bx, bx + (x1 - x0) * frame.k, by)
    land = countries().geometry.buffer(0).intersection(shapely.box(*box)).to_crs(crs)
    svg.append(f'<rect x="{bx}" y="{by}" width="{f.pw:.1f}" height="{f.ph:.1f}" fill="{C["card"]}" stroke="{C["ctxl"]}" stroke-width=".8"/>')
    svg.append(f'<path d="{geom_path(land[~land.is_empty].union_all(), f)}" fill="{C["page"]}" stroke="{C["ctxl"]}" stroke-width=".6"/>')
    here = cheese[islands & cheese.lon.between(lon0, lon1)]
    pts = spread(np.array([f.xy(*to_local.transform(lo, la)) for lo, la in zip(here.lon, here.lat)]), 2 * R + 0.8)
    for (x, y), kind in zip(pts, here.giType):
        svg.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{R}" fill="{PDO if kind == "PDO" else PGI}" stroke="{C["ink"]}" '
                   f'stroke-opacity=".55" stroke-width=".6"/>')
    svg.append(text(flush(title, 13, 600, bx), by - 7, title, 13, 600, C["ink2"]))

# Legend over the Atlantic, on the same left margin as the title
LX, LY = 60, MAP_TOP + 82
for i, words in enumerate(("One dot per protected cheese,", "where it is made")):
    svg.append(text(flush(words, 17, 700, LX), LY + i * 21, words, 17, 700))
for i, (colour, label, sub) in enumerate([(PDO, "PDO, protected designation of origin", "every step happens in the named area"),
                                          (PGI, "PGI, protected geographical indication", "at least one step happens there")]):
    y = LY + 50 + i * 44
    svg.append(f'<circle cx="{LX + 7.3}" cy="{y - 4}" r="7" fill="{colour}" stroke="{C["ink"]}" stroke-opacity=".55" stroke-width=".6"/>')
    svg.append(text(LX + 22, y + 1, label, 15, 600, C["ink"]))
    svg.append(text(LX + 22, y + 19, sub, 14, 400, C["ink2"]))

# One note, over the North Sea and Scotland (not part of the map's subject), pointing at Herve
herve = main[main.name == "Fromage de Herve"].iloc[0]
NOTE = ["Herve is Belgium's only", "PDO cheese and it is", "famous for its smell"]
nx, ny, step = 214, MAP_TOP + 241, 26
svg.append(f'<text class="note" x="{nx}" y="{ny}" font-size="21" fill="{C["ink"]}">'
           + "".join(f'<tspan x="{nx}"' + (f' dy="{step}"' if i else "") + f'>{line}</tspan>' for i, line in enumerate(NOTE)) + "</text>")
# The note must not sit on the continent: check its box against every country but the United Kingdom, in pixels
note_box = shapely.box(nx - 2, ny - 19, nx + 11.2 * max(map(len, NOTE)), ny + step * (len(NOTE) - 1) + 5)
continent = shapely.affinity.affine_transform(world[~world.ADMIN.isin(["United Kingdom", "Isle of Man"])].union_all(), to_pixels)
assert not note_box.intersects(continent)
sx, sy = nx + 11.2 * len(NOTE[-1]) - 8, ny + step * (len(NOTE) - 1) + 12
ex, ey = herve.x - 5, herve.y - 11
qx, qy = sx + 6, (sy + ey) / 2 + 20
angle = np.arctan2(ey - qy, ex - qx)
head = " ".join(f"L{ex + 12 * np.cos(angle + np.pi + t):.1f} {ey + 12 * np.sin(angle + np.pi + t):.1f} M{ex:.1f} {ey:.1f}" for t in (-0.5, 0.5))
svg.append(f'<path d="M{sx:.1f} {sy} Q {qx:.1f} {qy:.1f}, {ex:.1f} {ey:.1f} {head}" fill="none" stroke="{C["ink"]}" stroke-width="2" '
           f'stroke-linecap="round" stroke-linejoin="round"/>')

# 3. Columns under the map: protected cheeses per country
TOP = MAP_TOP + frame.ph + 22
svg.append(text(flush("P", 19, 700), TOP, "Protected cheeses by country", 19, 700))
col, SCALE = 960 / len(count), 0.72
wide = col * 0.68
BASE = TOP + 26 + count.total.max() * SCALE
for i, (code, row) in enumerate(count.iterrows()):
    left = 60 + col * i  # the first column starts on the left margin, in line with the title and the footer
    pdo, pgi = row.get("PDO", 0) * SCALE, row.get("PGI", 0) * SCALE
    svg.append(f'<rect x="{left:.1f}" y="{BASE - pdo:.1f}" width="{wide:.1f}" height="{pdo:.1f}" fill="{PDO}"/>')
    svg.append(f'<rect x="{left:.1f}" y="{BASE - pdo - pgi:.1f}" width="{wide:.1f}" height="{pgi:.1f}" fill="{PGI}"/>')
    svg.append(text(left + wide / 2, BASE - pdo - pgi - 5, str(row.total), 12, 700, C["ink"], "middle"))
    svg.append(f'<text x="{left:.1f}" y="{BASE + 15:.1f}" font-size="12.5" font-weight="600" fill="{C["ink2"]}" '
               f'transform="rotate(38 {left:.1f} {BASE + 15:.1f})">{EU[code]}</text>')
svg.append(f'<path d="M60 {BASE:.1f} L1020 {BASE:.1f}" stroke="{C["ctxl"]}" stroke-width="1"/>')

# 4. Headline, dek, byline and footer
HEAD = [(78, f"Where the EU's {len(cheese)} protected", 46, 800, C["ink"]), (128, "cheeses are made", 46, 800, C["ink"]),
        (168, f"France has {count.total['fr']}, Italy {count.total['it']}, Spain {count.total['es']} and Greece {count.total['gr']}. "
              "That is two in every three.", 22, 400, C["ink2"]),
        (196, "The dots crowd the Alps, the Massif Central and Spain's north coast.", 22, 400, C["ink2"])]
for y, words, size, weight, colour in HEAD:  # every line starts with its first letter exactly on the left margin
    svg.append(text(flush(words, size, weight), y, words, size, weight, colour))
svg.append(byline(230, "30DayMapChallenge #19: Smell").replace('x="60.0"', f'x="{flush("M", 20, 600):.1f}"'))
svg += footer([
    ("Method:", "cheese names registered by EU countries (customs code 0406), placed by hand near the centre of each area."),
    ("Source:", "eAmbrosia, the EU register of geographical indications, European Commission, November 2026. Borders: Natural Earth."),
    ("Comments:", "places are approximate, and dots are nudged apart inside their own country. The EU files ricotta, requeijão, Cancoillotte and Estonia's Sõir as other dairy products, so they aren't here."),
], x=round(flush("M", 17, 700), 1), y=BASE + 80, width=960, size=17, line_height=20)
save_png(page("".join(svg)), HERE / "day19_smell.png")
(cheese[["name", "giType", "country", "lon", "lat", "giIdentifier"]].assign(country=lambda d: d.country.map(EU))
 .sort_values(["country", "name"]).to_csv(HERE / "protected_cheeses.csv", index=False))
