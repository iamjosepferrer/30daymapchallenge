"""Day 27, New tool: 40 European economies drawn with popgrid, sized by GDP and not by land.

popgrid is a Python package that redraws a map as a grid of equal squares, handing each region as many squares as
its share of a number. Here 40 European countries share 1,000 squares by their 2025 GDP, so each square is 0.1% of
their combined GDP. Colour shows GDP per person: apricot below the average of the 40, blue above it. A small grid of
the same countries sized by land sits next to it.

All amounts are in euros, converted from the IMF's U.S. dollar figures at the ECB's average rate for 2025. The
figures are the snapshots in data.csv and imf_2025.csv, the same ones as in
https://github.com/iamjosepferrer/dataviz/tree/main/europe-economy-by-gdp, where make_map.py can download
them again. check_claims() recomputes every sentence on the chart and stops the script if one is no longer true.
"""
import html
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path

import geopandas as gpd
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import C, byline, flush, footer, page, save_png  # noqa: E402

DATA_CSV = HERE / "data.csv"
IMF_CSV = HERE / "imf_2025.csv"
USD_PER_EUR = 1.129983  # ECB reference rate, 2025 annual average: U.S. dollars per euro

# Natural Earth code -> (IMF code, name on the graphic).
# Editorial scope: Russia and Turkiye are out, because their land area would swamp the
# outline and most of it lies outside Europe. Microstates are out because the IMF does
# not cover them all.
COUNTRIES = {
    "ALB": ("ALB", "Albania"), "AUT": ("AUT", "Austria"), "BEL": ("BEL", "Belgium"),
    "BGR": ("BGR", "Bulgaria"), "BIH": ("BIH", "Bosnia"), "BLR": ("BLR", "Belarus"),
    "CHE": ("CHE", "Switzerland"), "CYP": ("CYP", "Cyprus"), "CZE": ("CZE", "Czechia"),
    "DEU": ("DEU", "Germany"), "DNK": ("DNK", "Denmark"), "ESP": ("ESP", "Spain"),
    "EST": ("EST", "Estonia"), "FIN": ("FIN", "Finland"), "FRA": ("FRA", "France"),
    "GBR": ("GBR", "U.K."), "GRC": ("GRC", "Greece"), "HRV": ("HRV", "Croatia"),
    "HUN": ("HUN", "Hungary"), "IRL": ("IRL", "Ireland"), "ISL": ("ISL", "Iceland"),
    "ITA": ("ITA", "Italy"), "KOS": ("UVK", "Kosovo"), "LTU": ("LTU", "Lithuania"),
    "LUX": ("LUX", "Luxembourg"), "LVA": ("LVA", "Latvia"), "MDA": ("MDA", "Moldova"),
    "MKD": ("MKD", "N. Macedonia"), "MLT": ("MLT", "Malta"), "MNE": ("MNE", "Montenegro"),
    "NLD": ("NLD", "Netherlands"), "NOR": ("NOR", "Norway"), "POL": ("POL", "Poland"),
    "PRT": ("PRT", "Portugal"), "ROU": ("ROU", "Romania"), "SRB": ("SRB", "Serbia"),
    "SVK": ("SVK", "Slovakia"), "SVN": ("SVN", "Slovenia"), "SWE": ("SWE", "Sweden"),
    "UKR": ("UKR", "Ukraine"),
}

# Natural Earth files these under another code, so they are moved to the country
# they belong to. Crimea and Sevastopol are internationally recognized as Ukraine.
REASSIGN_UNITS = {"Crimea": "UKR", "Sevastopol": "UKR"}
REASSIGN_CODES = {"ALD": "FIN", "CYN": "CYP", "WSB": "CYP", "ESB": "CYP"}

# Keeps Europe and its nearby islands, dropping overseas territories and Svalbard
BBOX = (-25, 34, 45, 72)



# DATA

def load_countries():
    """GDP in euros and population (IMF, 2025) and land area (World Bank) by country."""
    table = pd.read_csv(DATA_CSV, keep_default_na=False, na_values=[""])
    table["gdp"] = table.gdp_usd.astype(float) / USD_PER_EUR
    table["share"] = table.gdp / table.gdp.sum()
    table["per_person"] = table.gdp / table["pop"]
    return table.sort_values("gdp", ascending=False).reset_index(drop=True)


def load_imf(refresh=False):
    """2025 GDP by country in USD billions, from the snapshot in imf_2025.csv."""
    table = pd.read_csv(IMF_CSV, keep_default_na=False)
    return dict(zip(table.code, table.gdp_2025_usd_billions.astype(float)))


def load_shapes(countries):
    """Dissolve Natural Earth admin-1 units (popgrid's cached file) into countries."""
    from popgrid.data import _download_admin1

    units = gpd.read_file(_download_admin1(), columns=["adm0_a3", "name"])
    for unit, code in REASSIGN_UNITS.items():
        units.loc[units.name == unit, "adm0_a3"] = code
    units["adm0_a3"] = units.adm0_a3.replace(REASSIGN_CODES)
    units = units[units.adm0_a3.isin(countries.code)].clip(BBOX)
    shapes = units.dissolve(by="adm0_a3").reset_index()[["adm0_a3", "geometry"]]
    return shapes.merge(countries[["code", "gdp"]], left_on="adm0_a3", right_on="code")


def repair_quotas(gdp_landmasses, quotas):
    """
    popgrid 0.7.1 can give a very small region no square while its neighbor gets one
    too many (here Bosnia and North Macedonia). Hand the extra square to the region
    that is short, taking the one closest to it in the west of the donor.
    """
    cells = [cell for landmass in gdp_landmasses for cell in landmass]
    counts = Counter(cell[0] for cell in cells)
    short = [code for code, quota in quotas.items() if counts[code] < quota]
    extra = [code for code, quota in quotas.items() if counts[code] > quota]
    if len(short) != len(extra):
        raise SystemExit(f"Cannot repair squares: short {short}, extra {extra}")
    for needy, donor in zip(short, extra):
        square = min((cell for cell in cells if cell[0] == donor), key=lambda cell: cell[1])
        square[0] = needy
        print(f"Moved one square from {donor} to {needy}")


def build_grids(countries):
    """Run popgrid and return the squares, one [code, column, row] list per landmass."""
    from popgrid import AreaGrid, PopGrid

    shapes = load_shapes(countries)
    gdp_grid = PopGrid.from_geodataframe(shapes, region_col="adm0_a3", weight_col="gdp", n=1000).build()
    land_grid = AreaGrid.from_geodataframe(shapes, region_col="adm0_a3", n=1000).build()

    def squares(grid):
        out = []
        for landmass in grid._landmasses:
            cells = landmass["cells"]
            if cells is None or len(cells) == 0:
                continue
            bounds = cells.geometry.bounds
            size = grid._cell_size
            out.append([
                [code, round(x / size), round(y / size)]
                for code, x, y in zip(cells.region_name, bounds.minx, bounds.miny)
            ])
        return out

    grids = {"gdp": squares(gdp_grid), "land": squares(land_grid)}
    repair_quotas(grids["gdp"], gdp_grid.quotas)
    return grids


def check_claims(countries, grids, refresh=False):
    """Recompute every claim printed on the graphic."""
    c = countries.set_index("code")
    total = countries.gdp.sum()
    average = total / countries["pop"].sum()
    imf_table = load_imf(refresh)
    imf = lambda code: imf_table[code] * 1e9 / USD_PER_EUR  # euros, at the same rate
    squares = Counter(s[0] for landmass in grids["gdp"] for s in landmass)
    land = countries.land_km2.sum()
    top5 = countries.iloc[:5]
    rest = countries.iloc[1:]
    smallest = rest.sort_values("gdp").gdp.cumsum()
    n_beaten = int((smallest < c.gdp["DEU"]).sum())

    checks = {
        "40 countries": len(countries) == 40,
        "1,000 squares": sum(squares.values()) == 1000,
        "every country within one square of its share": all(
            abs(squares[r.code] - r.share * 1000) < 1 for r in countries.itertuples()
        ),
        "a square is 24.3 billion euros": round(total / 1000 / 1e9, 1) == 24.3,
        "combined GDP is 24.3 trillion euros": round(total / 1e12, 1) == 24.3,
        "top five are the named ones": set(top5.code) == {"DEU", "GBR", "FRA", "ITA", "ESP"},
        "top five are 62%": round(top5.share.sum() * 100) == 62,
        "Ukraine has eight squares": squares["UKR"] == 8,
        "Ukraine is the largest by land": countries.land_km2.idxmax() == countries.index[countries.code == "UKR"][0],
        "Ukraine is 10% of land": round(c.land_km2["UKR"] / land * 100) == 10,
        "Ukraine is 0.8% of GDP": round(c.share["UKR"] * 100, 1) == 0.8,
        "Germany beats 29 smallest": n_beaten == GERMANY_BEATS,
        "Germany printed as 4.5 trillion euros": 4.45e12 <= c.gdp["DEU"] < 4.55e12,
        "Germany above Japan": c.gdp["DEU"] > imf("JPN"),
        "U.K. above India": c.gdp["GBR"] > imf("IND"),
        "France above Russia and Canada": c.gdp["FRA"] > max(imf("RUS"), imf("CAN")),
        "Italy above Canada and Brazil": c.gdp["ITA"] > max(imf("CAN"), imf("BRA")),
        "Spain above Mexico and Australia": c.gdp["ESP"] > max(imf("MEX"), imf("AUS")),
        "Luxembourg is highest per person": c.per_person.idxmax() == "LUX",
        "Luxembourg is 131K euros per person": round(c.per_person["LUX"] / 1e3) == 131,
        "Luxembourg is about 3x the average": 2.9 < c.per_person["LUX"] / average < 3.3,
        "average is 41K euros": round(average / 1e3) == 41,
        "Kosovo and Montenegro get no square": squares["KOS"] == 0 and squares["MNE"] == 0,
        "Kosovo is 11B euros and Montenegro 8B": round(c.gdp["KOS"] / 1e9) == 11 and round(c.gdp["MNE"] / 1e9) == 8,
        "all others get a square": all(squares[code] > 0 for code in c.index if code not in ("KOS", "MNE")),
        "no country is below the color scale": countries.per_person.min() >= PC_LOW,
        "the scale's centre is the average": abs(PC_MID - average) < 1,
    }
    failed = [claim for claim, passed in checks.items() if not passed]
    print(f"Claims checked: {len(checks) - len(failed)} of {len(checks)} pass")
    if failed:
        raise SystemExit("These claims no longer hold:\n  " + "\n  ".join(failed))


# DESIGN

CELL = 17               # size of a square, in px
MAP_X, MAP_Y = 60, 216  # top-left corner of the main map
COL0, ROW0 = -38, 29    # first column and top row of the grid
INK, MUTED = C["ink"], C["ink2"]
# Apricot to pale to blue, with the average of the 40 countries at the middle stop
RAMP = ["#8A5312", "#B36F1E", "#DDB06E", "#F1EADC", "#8FA9CC", "#2E5A93", "#1B3A66"]
PC_LOW, PC_MID, PC_HIGH = 5_000, 40_785, 90_000
GERMANY_BEATS = 29


def X(col):
    return MAP_X + (col - COL0) * CELL


def Y(row):
    """Top edge of a row. Rows count upward, as in the projected map."""
    return MAP_Y + (ROW0 - row) * CELL


def side(at, col, row, nudge=9):
    """Leader that runs to a label starting at this column and row."""
    return dict(at=at, out=(X(col) + 4, Y(row) + nudge))


# Label settings per country.
#   at + out  draw a leader from that square to a label outside the country
#   anchor    "end" puts the label to the left of the leader
#   skip      no label here (Luxembourg has its magnifier)
#   rect      place the label in these cells: (col, row, width, height)
#   n         font size of the name
#   dx, dy    nudge
LABELS = {
    "LUX": dict(skip=True),
    "GBR": dict(rect=(-32, 6, 9, 6)),
    "ISL": side((-25, 27), -24, 27),
    "EST": side((11, 10), 13, 11),
    "LVA": side((11, 9), 13, 9, 12),
    "LTU": side((12, 8), 14, 8, 8),
    "BLR": side((14, 4), 16, 5),
    "UKR": side((15, 3), 16, 3),
    "MDA": side((14, 2), 16, 1),
    "BGR": side((10, -5), 12, -5),
    "MKD": side((9, -7), 12, -7),
    "ALB": side((9, -8), 12, -9),
    "CYP": side((13, -16), 15, -16),
    "MLT": dict(at=(-8, -16), out=(X(-9) + 4, Y(-16) + 9), anchor="end"),
    "SVN": dict(at=(5, -4), out=(X(6) - 4, Y(-5) + 9), anchor="end"),
    "HRV": dict(at=(7, -6), out=(X(6) - 4, Y(-6) + 13), anchor="end"),
    "BIH": dict(at=(8, -7), out=(X(7) - 8, Y(-8) + 12), anchor="end"),
    "SVK": side((10, 1), 16, 0),
    "HUN": dict(rect=(8, -3, 2, 2), n=9),
    "SRB": dict(n=9.5),
    "PRT": dict(n=9),
    "GRC": dict(n=9.5, rect=(7, -13, 2, 3)),
    "FIN": side((1, 24), 3, 25),
}

# The five largest economies get a larger label and a country comparison
HERO = {
    "DEU": dict(name=26, value=44, note=["Bigger than Japan"]),
    "GBR": dict(name=24, value=36, note=["Bigger than India"]),
    "FRA": dict(name=24, value=38, note=["Bigger than Russia or Canada"]),
    "ITA": dict(name=21, value=30, note=["Bigger than Canada", "or Brazil"]),
    "ESP": dict(name=21, value=30, note=["Bigger than Mexico", "or Australia"]),
}



# SVG HELPERS

def to_rgb(color):
    return [int(color[i:i + 2], 16) for i in (1, 3, 5)]


def mix(a, b, t):
    return "#%02x%02x%02x" % tuple(round(x + (y - x) * t) for x, y in zip(to_rgb(a), to_rgb(b)))


def scale_color(per_person):
    """Diverging scale: gold below the European average, blue above it."""
    if per_person <= PC_MID:
        position = 0.5 * max(0, per_person - PC_LOW) / (PC_MID - PC_LOW)
    else:
        position = 0.5 + 0.5 * min(1, (per_person - PC_MID) / (PC_HIGH - PC_MID))
    position *= len(RAMP) - 1
    i = min(int(position), len(RAMP) - 2)
    return mix(RAMP[i], RAMP[i + 1], position - i)


def luminance(color):
    channels = [v / 255 for v in to_rgb(color)]
    channels = [v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4 for v in channels]
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def text_color(background):
    """White or ink, whichever has more contrast against the background."""
    on_white = 1.05 / (luminance(background) + 0.05)
    on_ink = (luminance(background) + 0.05) / (luminance(INK) + 0.05)
    return "#ffffff" if on_white > on_ink else INK


def money(value):
    return f"\u20ac{value / 1e12:.2f}T" if value >= 1e12 else f"\u20ac{value / 1e9:.0f}B"



def text(x, y, content, size, weight=700, fill=INK, anchor="middle", extra="", halo=None, halo_width=3.5):
    """SVG text in Gabarito. A halo in the square's colour cuts the grid lines behind the label."""
    if halo:
        extra += f' paint-order="stroke" stroke="{halo}" stroke-width="{halo_width}" stroke-linejoin="round"'
    return (f'<text x="{x:.1f}" y="{y:.1f}" font-size="{size}" font-weight="{weight}" fill="{fill}" '
            f'text-anchor="{anchor}" {extra}>{html.escape(content)}</text>')


def lines(x, y, rows, size, height, weight=500, fill=INK, anchor="start"):
    return "".join(text(x, y + i * height, row, size, weight, fill, anchor) for i, row in enumerate(rows))


def leader(x1, y1, path_tail):
    """Thin line with a casing in the page colour and a dot on the country."""
    d = f"M{x1:.1f} {y1:.1f}{path_tail}"
    return (f'<path d="{d}" fill="none" stroke="{C["card"]}" stroke-width="2.6" stroke-opacity=".85"/>'
            f'<path d="{d}" fill="none" stroke="{INK}" stroke-width=".9"/>'
            f'<circle cx="{x1:.1f}" cy="{y1:.1f}" r="2.1" fill="{C["card"]}" stroke="{INK}" stroke-width=".9"/>')


def draw_squares(cells, size, origin_x, origin_y, fill_of, gap=0.6, radius=1.2, border=1.7, tint=0.30):
    """Draw {(col, row): state} as squares, with an outline around each state."""
    px = lambda col: origin_x + col * size
    py = lambda row: origin_y - (row + 1) * size
    out = []
    for (col, row), state in cells.items():
        fill = fill_of(state)
        out.append(
            f'<rect x="{px(col):.2f}" y="{py(row):.2f}" width="{size}" height="{size}" fill="{mix(fill, C["card"], tint)}"/>'
            f'<rect x="{px(col) + gap:.2f}" y="{py(row) + gap:.2f}" width="{size - 2 * gap:.2f}" '
            f'height="{size - 2 * gap:.2f}" rx="{radius}" fill="{fill}"/>'
        )
    edges = []
    for (col, row), state in cells.items():
        x, y = px(col), py(row)
        if cells.get((col - 1, row)) != state:
            edges.append(f"M{x:.2f} {y:.2f}V{y + size:.2f}")
        if cells.get((col + 1, row)) != state:
            edges.append(f"M{x + size:.2f} {y:.2f}V{y + size:.2f}")
        if cells.get((col, row + 1)) != state:
            edges.append(f"M{x:.2f} {y:.2f}H{x + size:.2f}")
        if cells.get((col, row - 1)) != state:
            edges.append(f"M{x:.2f} {y + size:.2f}H{x + size:.2f}")
    out.append(f'<path d="{"".join(edges)}" fill="none" stroke="{INK}" stroke-width="{border}" stroke-linecap="square"/>')
    return "".join(out)


def largest_rectangle(cells):
    """Largest, squarest rectangle inside a state: (col, row, width, height)."""
    best = (0, 0, 0, 0, 0)
    for col, row in sorted(cells):
        for height in range(1, 16):
            if (col, row + height - 1) not in cells:
                break
            width = 1
            while all((col + width, row + k) in cells for k in range(height)):
                width += 1
            score = width * height - abs(width - height) * 0.15
            if score > best[0]:
                best = (score, col, row, width, height)
    return best[1:]



# THE PAGE

def name_and_value(x, y, name, value, anchor):
    return (f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" fill="{INK}" font-size="12">'
            f'<tspan font-weight="500">{html.escape(name)}</tspan><tspan dx="5" font-weight="800">{html.escape(value)}</tspan></text>')


def labels(main, data, origin_x, origin_y):
    out = []
    px = lambda col: origin_x + col * CELL
    py = lambda row: origin_y - (row + 1) * CELL
    cells_of = defaultdict(set)
    for cell, code in main.items():
        cells_of[code].add(cell)
    for code, cells in cells_of.items():
        conf = LABELS.get(code, {})
        if conf.get("out") or conf.get("skip"):
            continue
        col, row, w, h = conf.get("rect") or largest_rectangle(cells)
        cx = px(col) + w * CELL / 2 + conf.get("dx", 0)
        cy = py(row + h - 1) + h * CELL / 2 + conf.get("dy", 0)
        fill = scale_color(data[code].per_person)
        ink = text_color(fill)
        value = money(data[code].gdp)
        if code in HERO:
            hero = HERO[code]
            size = hero["value"]
            out.append(text(cx, cy - size * 0.55, data[code].name, hero["name"], 700, ink, halo=fill, halo_width=5))
            out.append(text(cx, cy + size * 0.5, value, size, 800, ink, halo=fill, halo_width=6))
            for i, note in enumerate(hero["note"]):
                out.append(text(cx, cy + size * 0.5 + 16 + i * 14, note, 12, 500, ink, halo=fill, halo_width=4))
            continue
        out.append(text(cx, cy - 2.5, data[code].name, conf.get("n", 10.5) - 0.5, 500, ink, halo=fill))
        out.append(text(cx, cy + 9.5, value, 11.5 if "n" not in conf else 10.5, 800, ink, halo=fill))
    for code, conf in LABELS.items():
        if not conf.get("out"):
            continue
        x, y = conf["out"]
        col, row = conf["at"]
        out.append(leader(px(col) + CELL / 2, py(row) + CELL / 2, f"L{x:.1f} {y:.1f}"))
        out.append(name_and_value(x + (-4 if conf.get("anchor") == "end" else 4), y + 4.2, data[code].name, money(data[code].gdp),
                                  conf.get("anchor", "start")))
    return "".join(out)


def legend():
    """Colour key, on the left margin above Ireland."""
    x, y, width = round(flush("G", 15, 700), 1), 262, 130
    stops = "".join(f'<stop offset="{i / (len(RAMP) - 1)}" stop-color="{c}"/>' for i, c in enumerate(RAMP))
    middle = x + width / 2
    return "".join([
        f'<defs><linearGradient id="legend">{stops}</linearGradient></defs>',
        text(x, y - 10, "GDP per person", 15, 700, INK, "start"),
        f'<rect x="{x}" y="{y}" width="{width}" height="11" rx="2" fill="url(#legend)"/>',
        f'<path d="M{middle} {y - 2}V{y + 13}" stroke="{INK}" stroke-width="1.4"/>',
        text(x, y + 27, "\u20ac5K", 12.5, 600, INK, "start"), text(x + width, y + 27, "\u20ac90K+", 12.5, 600, INK, "end"),
        text(middle, y + 27, "\u20ac41K", 12.5, 600, INK), text(middle, y + 42, "average", 12, 400, MUTED),
    ])


def luxembourg_magnifier(main, data, fill_of):
    cx, cy, radius = 104, Y(0), 52
    start_x, start_y = X(-12) + CELL / 2, Y(3) + CELL / 2
    angle = math.atan2(cy - start_y, cx - start_x)
    end_x, end_y = cx - radius * math.cos(angle), cy - radius * math.sin(angle)
    out = [leader(start_x, start_y, f"L{end_x:.1f} {end_y:.1f}"),
           f'<circle cx="{cx}" cy="{cy}" r="{radius}" fill="{C["card"]}" stroke="{C["apricot"]}" stroke-width="3"/>']
    lux = {cell: code for cell, code in main.items() if code == "LUX"}
    cols, rows = [c for c, _ in lux], [r for _, r in lux]
    size = 12
    block_w, block_h = (max(cols) - min(cols) + 1) * size, (max(rows) - min(rows) + 1) * size
    out.append(draw_squares(lux, size, cx - block_w / 2 - min(cols) * size, cy - 3 + block_h / 2 + min(rows) * size,
                            fill_of, gap=0.5, border=1.2))
    out.append(text(cx, cy - 27, "Luxembourg", 12, 600))
    out.append(text(cx, cy + 36, money(data["LUX"].gdp), 18, 800))
    out.append(lines(cx, cy + radius + 19, ["Highest GDP per person:", "€131K, 3 times the average"], 12.5, 15.5, anchor="middle"))
    return "".join(out)


def land_inset(countries, fill_of):
    """The same countries on an ordinary map (equal-area, EPSG:3035), in a box, with an arrow to the grid."""
    shapes = load_shapes(countries).to_crs(3035)
    shapes["geometry"] = shapes.geometry.simplify(6000)
    x0, y0, x1, y1 = shapes.total_bounds
    left, top, width = 862, 262, 174
    k = width / (x1 - x0)
    height = (y1 - y0) * k

    def path(geom, **style):
        d = "".join("M" + "L".join(f"{left + (x - x0) * k:.1f} {top + (y1 - y) * k:.1f}" for x, y in ring.coords) + "Z"
                    for part in getattr(geom, "geoms", [geom]) for ring in [part.exterior, *part.interiors])
        return f'<path d="{d}" ' + " ".join(f'{key.replace("_", "-")}="{value}"' for key, value in style.items()) + "/>"

    out = [f'<rect x="{left - 16}" y="{top - 44}" width="{width + 32}" height="{height + 58:.0f}" rx="8" fill="{C["quiet_land"]}" stroke="{C["ctx"]}" stroke-width="1"/>',
           text(left - 4, top - 20, "The same 40 countries, by land", 13, 700, INK, "start")]
    out += [path(r.geometry, fill=fill_of(r.adm0_a3), stroke=INK, stroke_width=0.5, stroke_linejoin="round") for r in shapes.itertuples()]
    ukraine = shapes.geometry[shapes.adm0_a3 == "UKR"].iloc[0]
    out.append(path(ukraine, fill="none", stroke=INK, stroke_width=1.6, stroke_linejoin="round"))
    c = ukraine.representative_point()
    out.append(text(left + (c.x - x0) * k, top + (y1 - c.y) * k + 3, "Ukraine", 9.5, 700, "#ffffff", halo=fill_of("UKR"), halo_width=2.5))
    # An arrow runs from the box down to the grid
    sx, sy = left - 8, top + height + 14
    tx, ty = X(5) + CELL / 2, Y(10) - 8
    qx, qy = sx - 4, ty - 30
    angle = math.atan2(ty - qy, tx - qx)
    head = " ".join(f"L{tx + 11 * math.cos(angle + math.pi + t):.1f} {ty + 11 * math.sin(angle + math.pi + t):.1f} M{tx:.1f} {ty:.1f}" for t in (-0.5, 0.5))
    out.append(f'<path d="M{sx:.1f} {sy:.1f} Q {qx:.1f} {qy:.1f}, {tx:.1f} {ty:.1f} {head}" fill="none" stroke="{INK}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')
    return "".join(out)


def bars(countries, fill_of, top):
    """The seven largest economies, as a share of the 40 countries' GDP."""
    out = [text(flush("S", 19, 700), top, "Share of the 40 countries' GDP", 19, 700, INK, "start")]
    rows = countries.head(7)
    for i, r in enumerate(rows.itertuples()):
        y = top + 14 + i * 22
        out.append(text(flush(r.name, 14, 600), y + 12, r.name, 14, 600, INK, "start"))
        width = 640 * r.share / rows.share.max()
        out.append(f'<rect x="170" y="{y}" width="{width:.1f}" height="15" rx="2" fill="{fill_of(r.code)}" stroke="{INK}" stroke-width=".6"/>')
        out.append(text(170 + width + 8, y + 12, f"{r.share * 100:.0f}%", 13, 700, INK, "start"))
    return "".join(out), top + 14 + len(rows) * 22


def main():
    countries = load_countries()
    grids = build_grids(countries)
    check_claims(countries, grids)
    data = {r.code: r for r in countries.itertuples()}
    fill_of = lambda code: scale_color(data[code].per_person)
    grid = {(col, row): code for landmass in grids["gdp"] for code, col, row in landmass}
    origin_x, origin_y = MAP_X - COL0 * CELL, MAP_Y + (ROW0 + 1) * CELL
    bar_svg, base = bars(countries, fill_of, MAP_Y + 47 * CELL + 20)
    head = [(80, "If GDP drew the map of Europe...", 50, 800, INK),
            (120, "40 countries share 1,000 squares. Each square is 0.1% of their combined GDP in 2025, about", 21, 400, MUTED),
            (147, "\u20ac24.3 billion. Germany alone produces more than the 29 smallest economies combined.", 21, 400, MUTED)]
    svg = [text(flush(words, size, weight), y, words, size, weight, fill, "start") for y, words, size, weight, fill in head]
    svg.append(byline(180, "30DayMapChallenge #27: New tool").replace('font-size="20"', 'font-size="18"').replace('x="60.0"', f'x="{flush("M", 18, 600):.1f}"'))
    svg += [draw_squares(grid, CELL, origin_x, origin_y, fill_of, border=1.5), labels(grid, data, origin_x, origin_y), legend(),
            luxembourg_magnifier(grid, data, fill_of), land_inset(countries, fill_of), bar_svg]
    svg += footer([
        ("Method:", "each country's squares are its share of the combined GDP (\u20ac24.3T), rounded to whole squares with popgrid. Russia, T\u00fcrkiye and the "
                    f"microstates are left out. Kosovo ({money(data['KOS'].gdp)}) and Montenegro ({money(data['MNE'].gdp)}) are too small for a square. \u201cBigger than\u201d compares nominal GDP."),
        ("Source:", "IMF World Economic Outlook (2025 GDP and population), in euros at the ECB's 2025 average of $1.13. Land: World Bank. Borders: Natural Earth."),
    ], x=round(flush("M", 17, 700), 1), y=base + 30, width=960, size=17, line_height=20)
    save_png(page("".join(svg)), HERE / "day27_economy_by_gdp.png")


if __name__ == "__main__":
    main()
