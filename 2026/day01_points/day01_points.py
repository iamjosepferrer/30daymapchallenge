"""Day 1, Points: half of Europe's city dwellers live in just 80 urban areas."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

import pandas as pd  # noqa: E402

from style import C, Frame, byline, fade_defs, footer, land_paths, load_urban_centres, page, save_png, text  # noqa: E402

LAND_WITH_DATA = {
    "United Kingdom", "Ireland", "France", "Spain", "Portugal", "Germany", "Netherlands",
    "Belgium", "Luxembourg", "Switzerland", "Austria", "Italy", "Denmark", "Norway", "Sweden",
    "Finland", "Iceland", "Estonia", "Latvia", "Lithuania", "Poland", "Czechia", "Slovakia",
    "Hungary", "Slovenia", "Croatia", "Bosnia and Herzegovina", "Republic of Serbia",
    "Montenegro", "Kosovo", "North Macedonia", "Albania", "Greece", "Bulgaria", "Romania",
    "Moldova", "Ukraine", "Belarus", "Russia", "Malta", "Jersey", "Andorra", "Liechtenstein",
    "Monaco", "San Marino", "Vatican", "Guernsey", "Isle of Man", "Faroe Islands", "Aland",
}
# City label positions: top, bottom, left or right of the circle
LABELS = {
    "Moscow": "b", "London": "l", "Paris": "l", "Madrid": "t",
    "Saint Petersburg": "t", "Barcelona": "r", "Berlin": "t", "Athens": "r",
}


def radius(population):
    """Circle area is proportional to population."""
    return 37 * (population / 14.4e6) ** 0.5


# Data: rank centres and find the smallest group that reaches half of the total
cities = load_urban_centres()
cities = cities[cities.lon <= 60].sort_values("pop", ascending=False).reset_index(drop=True)
total = cities["pop"].sum()
cities["rank"] = cities.index + 1
cities["cum_share"] = cities["pop"].cumsum() / total
n_top = int((cities.cum_share < 0.5).sum() + 1)
cities["top"] = cities.index < n_top
# Everyone in Europe, from compute_europe_population.py
europe_total = pd.read_csv(HERE / "europe_population.csv").population_2025.sum()
top_pop = cities["pop"][cities.top].sum()
other_pop = total - top_pop
rest_pop = europe_total - total
print(f"Europe {europe_total / 1e6:.1f}M: top {top_pop / 1e6:.1f}M {top_pop / europe_total:.1%}, other centres {other_pop / 1e6:.1f}M {other_pop / europe_total:.1%}, everyone else {rest_pop / 1e6:.1f}M {rest_pop / europe_total:.1%}")
print(f"{n_top} of {len(cities):,} centres hold {cities.cum_share.iloc[n_top - 1]:.2%} of {total / 1e6:.1f} million people")

# Map frame
MAP_TOP = 410
frame = Frame(2441860, 7308140, 1320000, 5036800, 0, 1080, MAP_TOP)
cities["px"], cities["py"] = frame.xy(cities.X, cities.Y)
on_map = cities[cities.px.between(0, 1080) & cities.py.between(MAP_TOP, MAP_TOP + frame.ph)]

quiet_land, data_land = land_paths(frame, LAND_WITH_DATA)
svg = [
    f'<clipPath id="map"><rect x="0" y="{MAP_TOP}" width="1080" height="{frame.ph:.0f}"/></clipPath>',
    f'<g clip-path="url(#map)"><path d="{quiet_land}" fill="{C["quiet_land"]}"/><path d="{data_land}" fill="{C["page"]}"/>',
    fade_defs(),
    f'<rect x="0" y="{MAP_TOP}" width="1080" height="90" fill="url(#fade-top)"/>',
    f'<rect x="0" y="{MAP_TOP + frame.ph - 60:.0f}" width="1080" height="60" fill="url(#fade-bottom)"/>',
    f'<rect x="1024" y="{MAP_TOP}" width="56" height="{frame.ph:.0f}" fill="url(#fade-right)"/>',
]

# Circles: grey first, then the blue group on top
for _, city in on_map[~on_map.top].iterrows():
    svg.append(f'<circle cx="{city.px:.1f}" cy="{city.py:.1f}" r="{radius(city["pop"]):.2f}" fill="{C["ctx"]}" fill-opacity=".8" stroke="{C["page"]}" stroke-width=".6"/>')
for _, city in on_map[on_map.top].iterrows():
    svg.append(f'<circle cx="{city.px:.1f}" cy="{city.py:.1f}" r="{radius(city["pop"]):.2f}" fill="{C["blue"]}" stroke="{C["page"]}" stroke-width="1"/>')
svg.append("</g>")

# Direct labels with values, and a dark outline on each labelled circle
for name, side in LABELS.items():
    city = cities[cities.name == name].iloc[0]
    r = radius(city["pop"])
    svg.append(f'<circle cx="{city.px:.1f}" cy="{city.py:.1f}" r="{r:.2f}" fill="none" stroke="{C["ink"]}" stroke-width="2"/>')
    x, y, anchor = {
        "t": (city.px, city.py - r - 8, "middle"),
        "b": (city.px, city.py + r + 24, "middle"),
        "l": (city.px - r - 7, city.py + 8, "end"),
        "r": (city.px + r + 7, city.py + 8, "start"),
    }[side]
    svg.append(text(x, y, f'{name} {city["pop"] / 1e6:.1f}M', 23, 600, C["ink"], anchor, halo=C["page"]))

# Headline, dek and byline
svg.append(text(60, 96, "Half of Europe's city dwellers", 58, 800))
svg.append(text(60, 158, f"live in just {n_top} urban areas", 58, 800))
svg.append(text(60, 204, f"People living in urban centres, 2025. Blue marks the {n_top} largest, which hold", 26, 400, C["ink2"]))
svg.append(text(60, 236, f"as many people as the other {len(cities) - n_top:,} centres combined.", 26, 400, C["ink2"]))
svg.append(byline(272))

# Bar: where everyone in Europe lives
BAR_X, BAR_W, BAR_Y, BAR_H, GAP = 60, 960, 324, 30, 3
svg.append(text(BAR_X, 314, f"Where Europe's roughly {round(europe_total / 1e8) * 100} million people live", 21, 700))
segments = [
    (top_pop, C["blue"], f"{n_top} largest urban areas"),
    (other_pop, C["ctx"], f"Other {len(cities) - n_top:,} urban centres"),
    (rest_pop, C["page"], "Everyone else: smaller towns, suburbs and villages"),
]
x = BAR_X
for population, colour, label in segments:
    width = BAR_W * population / europe_total
    svg.append(f'<rect x="{x:.1f}" y="{BAR_Y}" width="{width - GAP:.1f}" height="{BAR_H}" rx="3" fill="{colour}"/>')
    svg.append(text(x, BAR_Y + BAR_H + 23, f"About {round(population / europe_total * 20) * 5}%", 22, 700))
    svg.append(text(x, BAR_Y + BAR_H + 44, label, 17, 400, C["ink2"]))
    x += width

# Size key
for key_x, population, label in [(92, 10e6, "10M"), (158, 1e6, "1M"), (204, 1e5, "100k")]:
    r = radius(population)
    svg.append(f'<circle cx="{key_x}" cy="{606 - r:.1f}" r="{r:.1f}" fill="none" stroke="{C["ink2"]}" stroke-width="1.3"/>')
    svg.append(text(key_x, 634, label, 20, 500, C["ink2"], "middle"))

# One handwritten note, in the open space above the British Isles
paris = cities[cities.name == "Paris"].iloc[0]
note_x, note_y = 148, 488
svg.append(
    f'<text class="note" x="{note_x}" y="{note_y}" font-size="27" fill="{C["ink"]}">'
    f'<tspan x="{note_x}">Paris here means its whole dense area,</tspan>'
    f'<tspan x="{note_x}" dy="33">{paris["pop"] / 1e6:.1f}M people, not the city\'s 2.1M</tspan></text>'
)
# Arrow through the open North Sea, landing on the top of the Paris circle
x0, y0 = note_x + 185, note_y + 46
x1, y1 = paris.px + 1, paris.py - radius(paris["pop"]) - 4
svg.append(f'<path d="M{x0} {y0} C {x0} {y0 + 160}, {x1 + 6} {y1 - 110}, {x1:.1f} {y1:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round"/>')
svg.append(f'<path d="M{x1 - 7:.1f} {y1 - 11:.1f} L{x1:.1f} {y1:.1f} L{x1 + 7:.1f} {y1 - 11:.1f}" fill="none" stroke="{C["ink"]}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>')

# Footer: method, source and comments
FOOTER = [
    ("Method:", f"rank Europe's {len(cities):,} urban centres by population and add them up from the top: the first {n_top} hold half of their people. An urban centre is a dense area of 50,000+ people, whatever the municipal borders."),
    ("Source:", "GHS-UCDB R2024A V1.2 and GHS-POP R2023A (European Commission, JRC), 2025 estimates. Base: Natural Earth."),
    ("Comments:", "the bar compares with all of Europe's roughly 700 million people. Europe means west of 60°E, without Turkey or Cyprus, which are not in the dataset. The Canaries, Madeira and Russia's outer edges are counted but off the map."),
]
svg += footer(FOOTER, x=60, y=1251, width=960, size=17, line_height=20)

save_png(page("".join(svg)), HERE / "day01_points.png")
cities[["rank", "name", "cnt", "pop", "lon", "lat", "cum_share", "top"]].to_csv(HERE / "results.csv", index=False)
