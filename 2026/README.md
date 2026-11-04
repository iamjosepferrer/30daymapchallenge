# 30DayMapChallenge 2026

One map a day about Europe, each built around a clear finding.

- [Day 1, Points: half of Europe's city dwellers live in just 80 urban areas](#day-1-points)
- [Day 2, Lines: Europe's biggest port is the nearest one for under 4% of city dwellers](#day-2-lines)
- [Day 3, Polygons: half of Europe's tourist nights happen in just 102 of its 1,247 regions](#day-3-polygons)
- [Day 4, Clusters: a third of the land in the EU, Norway and Switzerland is just three empty patches](#day-4-clusters)
- [Data sources and licenses](#data-sources-and-licenses)
- [How to recreate the maps](#how-to-recreate-the-maps)

**How these maps are made:** each map uses public data and is built in Python, then drawn as SVG and exported to PNG with a headless browser. I direct the analysis and the editing, and Claude helps build the code and maps. Day 10 is made entirely by prompting, as that day's theme requires.

---

## Day 1: Points

![Half of Europe's city dwellers live in just 80 urban areas](day01_points/day01_points.png)

### What it shows

Europe has 1,100 urban centres with 50,000 or more people, home to 288 million people in 2025. Half of them live in the largest 80. The bar adds the wider picture: most Europeans live outside these urban centres altogether.

| Group | People in 2025 | Share of Europe |
| --- | --- | --- |
| 80 largest urban centres | 144.3 million | 20.5% |
| Other 1,020 urban centres | 144.2 million | 20.5% |
| Everyone else | 415.0 million | 59.0% |
| **Europe** | **703.5 million** | **100%** |

The map rounds these to "about 20%" and "about 60%", because the total depends on how coastal grid cells are handled. See the limitations below.

### What counts as a city here

The map uses urban centres as defined by the European Commission's Joint Research Centre (JRC): contiguous 1 km grid cells with at least 1,500 inhabitants per km² and at least 50,000 people in total. This follows where people actually live, not municipal borders. For example, Essen, Duisburg, Bochum and seven neighbouring Ruhr towns count as one urban centre of 2.7 million. In the same way, Paris on the map is its whole dense area of 9.3 million people, while the city of Paris itself has about 2.1 million.

### How it was made

1. **Load the urban centres** from GHS-UCDB R2024A V1.2, using the Europe region file and its 2025 population estimates.
2. **Limit the area** to centres west of 60°E, which removes 65 centres in Russia and leaves 1,100.
3. **Rank by population** and add up the shares. The largest 79 centres hold 49.78% of the total and the largest 80 hold 50.01%, so the blue group is 80.
4. **Calculate Europe's total** from the GHS-POP R2023A grid (30 arcsecond resolution, 2025) for the same countries west of 60°E, using Natural Earth 1:10m boundaries.
5. **Draw one circle per centre** in the ETRS89-LAEA projection (EPSG:3035), with circle area proportional to population.

### Limitations

- Turkey and Cyprus are not in this Europe dataset, so Istanbul is not on the map.
- Urban centres are split at national borders, so a cross-border urban area can appear as two centres.
- The Canaries, Madeira and centres at the far edges of Russia are counted but fall outside the map frame.
- Europe's total ranges from about 699 to 710 million depending on how coastal grid cells are treated. The published figure counts every cell that touches a 1:10m boundary. The shares barely move across that range.
- Population figures for 2025 are modelled estimates, not census counts.

**Files:** [`day01_points.py`](day01_points/day01_points.py) draws the map, [`compute_europe_population.py`](day01_points/compute_europe_population.py) calculates the total, [`europe_population.csv`](day01_points/europe_population.csv) stores it, and [`results.csv`](day01_points/results.csv) lists every centre with its rank.

---

## Day 2: Lines

![Europe's biggest port is the nearest one for under 4% of city dwellers](day02_lines/day02_lines.png)

### What it shows

Rotterdam handles 21% of the containers across Europe's top 10 container ports, but it is the fastest to reach for only 3.4% of the 211 million people living in the urban centres covered here. Hamburg is the fastest to reach for 23%, and Antwerp-Bruges and Felixstowe for 20% each.

| Port | Containers, 2025 (TEU) | Share of containers | Share of people nearest |
| --- | ---: | ---: | ---: |
| Rotterdam | 14,244,954 | 21.0% | 3.4% |
| Antwerp-Bruges | 13,630,000 | 20.1% | 20.1% |
| Hamburg | 8,300,000 | 12.2% | 23.2% |
| Valencia | 5,662,661 | 8.3% | 5.4% |
| Bremerhaven | 4,900,000 | 7.2% | 0.7% |
| Algeciras | 4,738,146 | 7.0% | 3.6% |
| Piraeus | 4,641,295 | 6.8% | 8.4% |
| Gioia Tauro | 4,490,566 | 6.6% | 6.6% |
| Barcelona | 3,726,624 | 5.5% | 8.8% |
| Felixstowe | 3,510,413 | 5.2% | 19.8% |

TEU means twenty-foot equivalent unit, the standard measure of container volume. Both share columns are out of the top 10 ports only.

**The main caveat:** this measures geography, not trade. Real cargo also follows rivers, rail and shipping contracts, and that gap is the point of the map. Geography alone doesn't explain why Rotterdam is the biggest.

### How it was made

1. **Choose the ports:** the top 10 European container ports by 2025 TEU, saved in [`ports.csv`](day02_lines/ports.csv).
2. **Choose the cities:** 815 urban centres from GHS-UCDB R2024A V1.2, holding 211 million people.
3. **Find each city's nearest port:** the OSRM table service returns car driving times from every city to all 10 ports, and the shortest time wins.
4. **Download the routes:** the OSRM route service returns the full road geometry from each city to its port.
5. **Check the routes:** four cities in Romania and Moldova (Bălți, Rybnitsa, Suceava and Botoșani) had routes crossing Ukraine, which is left out of the analysis, so they go to their next-nearest port with a route that avoids it. All four end up at Piraeus.
6. **Merge shared roads:** routes are snapped to a 1.5 km grid in EPSG:3035, and each road segment adds up the population of every city routed through it.
7. **Draw the lines:** width grows with the square root of population, and colour follows the port that most of those people route to.

### Limitations

- **Cars, not trucks:** driving times come from OSRM's car profile, and routes can include ferries. They ignore traffic, border checks and truck rules.
- **Left out:** Russia, Belarus and Ukraine, because road freight there is disrupted, and Iceland, the Canaries, Madeira and the Azores. Turkey and Cyprus are not in this dataset.
- **Ceuta and Melilla:** OSRM starts these two routes on the Spanish mainland instead of in the city, so their lines and times are approximate. Together they are under 0.1% of the people covered.
- **Port locations:** each port is a single approximate point at a major container terminal. Measuring from Rotterdam's Waalhaven instead of Maasvlakte raises its share from 3.4% to 3.7%, so "under 4%" holds either way.
- **Port figures:** they come from Wikipedia's list, compiled from port authorities and other published sources, not from one official dataset. Bremerhaven uses the figure for the Ports of Bremen, which also covers Bremen.
- **Road data changes:** the routes reflect OpenStreetMap as served by OSRM in November 2026, so a new download can shift the numbers slightly.

**Files:** [`day02_lines.py`](day02_lines/day02_lines.py) does everything, [`results.csv`](day02_lines/results.csv) lists each city's port, driving time and distance, and [`port_summary.csv`](day02_lines/port_summary.csv) holds the shares above.

---

## Day 3: Polygons

![Half of Europe's tourist nights happen in just 102 of its 1,247 regions](day03_polygons/day03_polygons.png)

### What it shows

Europe's registered tourist accommodation recorded 3.28 billion nights in 2025. Half of them happened in just 102 of 1,247 regions, which are home to 24% of residents. A quarter happened in only 28 regions. Tourism pressure is not a European problem but a very local one, and the map shows where.

| Rank | Region | Nights in 2025 (million) |
| ---: | --- | ---: |
| 1 | Rome | 56.0 |
| 2 | Mallorca | 55.0 |
| 3 | Paris | 47.3 |
| 4 | Barcelona | 41.3 |
| 5 | Venice | 38.6 |
| 6 | South Tyrol (Bolzano) | 38.2 |
| 7 | Tenerife | 35.3 |
| 8 | Alicante | 34.0 |
| 9 | Madrid | 33.0 |
| 10 | Málaga | 30.6 |

Paris alone hosts more nights than the whole of Ireland (42 million), and Mallorca more than all of Belgium (46 million). Of the 28 regions that host a quarter of all nights, 9 are in Spain and 6 in Italy.

### How it was made

1. **Get nights spent** from Eurostat's `tour_occ_nin3` table for 2025: all guests in hotels, holiday and short-stay accommodation and campsites, for NUTS 3 regions.
2. **Rank the regions** by nights and add up their shares until they reach a quarter and then half of the total.
3. **Join to boundaries** from GISCO's NUTS 2024 file at 1:10 million. All 1,247 regions matched.
4. **Draw the map** in EPSG:3035 at the same scale as Day 2, with the 28 quarter regions in blue (18.4 million nights or more), the next 74 in light blue (7.2 to 18.1 million), and every other region unfilled (under 7.2 million). Five regions are outlined and labelled with their nights: Rome, Mallorca, Paris, Barcelona and Venice. The city of Paris is only a few pixels wide at this scale, so it is also shown in a magnifying lens. The Canary Islands and Madeira are in insets at the same scale, because Tenerife and Gran Canaria rank in the top 28 and Madeira 71st. No other overseas region makes the top 102: the Azores rank 273rd and France's overseas regions 445th or lower.

### Limitations

- **Registered accommodation only:** unregistered rentals, and stays with friends and family, are missing, so real tourist numbers are higher in some places.
- **All overnight guests count:** "tourists" includes domestic guests and business travellers, which is part of why Paris, Madrid and Berlin rank high.
- **Regions differ in size:** NUTS 3 regions range from German districts to large Nordic areas. A big region can reach the top half with moderate pressure, and a small one needs intense pressure, so this map shows where nights concentrate, not how crowded a place feels. The earlier version of this map, in the repo's history, showed nights per resident instead.
- **No data:** the UK, Turkey, Bosnia and Herzegovina, Kosovo, North Macedonia, Moldova, Ukraine, Belarus and Russia are not covered for 2025.
- **Svalbard left out:** Svalbard and Jan Mayen (0.2 million nights) have no boundaries in the NUTS 2024 file, so the 1,247 regions exclude them. This changes no figure on the map.
- **Not drawn:** the Azores, France's overseas regions, Madeira's uninhabited Savage Islands, Iceland and the far north are counted but not drawn.
- **Region names:** NUTS 3 regions are provinces, islands or districts, so the labels say "province" where it matters: Barcelona, Rome and Venice mean their provinces, while Paris is the city itself.

**Files:** [`day03_polygons.py`](day03_polygons/day03_polygons.py) does everything, and [`results.csv`](day03_polygons/results.csv) lists all 1,247 regions with their rank, share and group.

---

## Day 4: Clusters

![A third of the land in the EU, Norway and Switzerland is just three empty patches](day04_clusters/day04_clusters.png)

### What it shows

The 2021 census counted nobody in 57% of the land in the EU, Norway and Switzerland, measured in 1 km squares. That empty land is not scattered: most of it joins up into three huge patches, which together cover 34% of all land.

| Patch | Land (km²) | Main countries |
| --- | ---: | --- |
| Nordic | 658,000 | Sweden, Norway, Finland |
| South-east | 410,000 | Romania, Bulgaria, Greece, Hungary, Slovakia |
| Iberian | 409,000 | Spain, Portugal, France |

The Iberian patch covers 72% of Spain and reaches from Portugal into France, so you could cross the peninsula without entering a single square kilometre where anyone lives. The fourth largest patch, in the Alps, is only 75,000 km².

### How it was made

1. **Load the grid:** Eurostat's Census 2021 population grid, version 3, which flags every 1 km square as populated or not, by usual residents.
2. **Join empty squares:** squares with nobody in them form one patch when they share a side.
3. **Measure each patch** by its land area, since coastal squares are only partly land.
4. **Draw the map** from the grid itself, with the three largest patches in blue.

### Limitations

- **Empty is not unused:** it means nobody lives there. The land can still be farmland, forest or mountain.
- **Countries differ:** each national statistics office places residents on the grid in its own way, which partly explains sharp edges at some borders, such as the Pyrenees.
- **Joining rule:** counting squares that only touch at a corner makes the patches bigger (the south-east one reaches about 670,000 km²), but the same three stay on top.
- **Residents not on the grid:** censuses could not place about 435,000 residents (0.1%) on a square, mostly in France, Italy, Finland and Bulgaria. Spain and Portugal have none, so the Iberian crossing holds. Every square in the three patches has zero residents.
- **Coverage:** the grid covers the EU, Norway, Switzerland and Liechtenstein, so the UK, Iceland and the Balkans outside the EU are left out. The Canary Islands and other far-off islands are counted but off the map.

**Files:** [`day04_clusters.py`](day04_clusters/day04_clusters.py) does everything, and [`results.csv`](day04_clusters/results.csv) lists the three patches.

---

## Data sources and licenses

| Dataset | Used for | Where it comes from | License |
| --- | --- | --- | --- |
| [GHS-UCDB R2024A V1.2](https://human-settlement.emergency.copernicus.eu/ghs_ucdb_2024.php) | Urban centres and population (Days 1, 2) | Downloaded from the JRC's open data site | CC BY 4.0 |
| [GHS-POP R2023A](https://human-settlement.emergency.copernicus.eu/download.php) | Europe's total population (Day 1) | Downloaded from the JRC's open data site | CC BY 4.0 |
| [Natural Earth](https://www.naturalearthdata.com/) | Land, country boundaries (Days 1 to 4) | GitHub mirror of Natural Earth | Public domain |
| [OSRM](https://project-osrm.org/) on [OpenStreetMap](https://www.openstreetmap.org/copyright) | Driving times and routes (Day 2) | OSRM's free demo server | Data: ODbL, © OpenStreetMap contributors |
| [List of busiest ports in Europe](https://en.wikipedia.org/wiki/List_of_busiest_ports_in_Europe) | Top 10 ports and TEU (Day 2) | Wikipedia, read in November 2026 | CC BY-SA |
| [Eurostat](https://ec.europa.eu/eurostat/data/database) `tour_occ_nin3`, `demo_r_pjanaggr3` | Nights spent and residents (Day 3) | Eurostat's statistics API | Free reuse with credit to Eurostat |
| [GISCO NUTS 2024](https://ec.europa.eu/eurostat/web/gisco/geodata/statistical-units/territorial-units-statistics) | Regional boundaries (Day 3) | Eurostat's GISCO service | © EuroGeographics for the administrative boundaries. Free for non-commercial use |
| [Eurostat Census 2021 population grid](https://ec.europa.eu/eurostat/web/gisco/geodata/population-distribution/population-grids) | 1 km population grid (Day 4) | Eurostat's GISCO service | © European Union, free reuse with credit |

**Citations**

- Mari Rivero, I. et al. (2024). GHS-UCDB R2024A, GHS Urban Centre Database 2025. European Commission, JRC. doi: [10.2905/1a338be6-7eaf-480c-9664-3a8ade88cbcd](https://doi.org/10.2905/1a338be6-7eaf-480c-9664-3a8ade88cbcd)
- Schiavina, M., Freire, S., Carioli, A., MacManus, K. (2023). GHS-POP R2023A, GHS population grid multitemporal (1975-2030). European Commission, JRC. doi: [10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE](https://doi.org/10.2905/2FF68A52-5B5B-4A22-8F40-C41DA8332CFE)

The maps use the Gabarito and Shantell Sans fonts, both under the SIL Open Font License.

## How to recreate the maps

Follow the setup in the [main README](../README.md), then run:

```bash
python 2026/day01_points/day01_points.py
python 2026/day02_lines/day02_lines.py
```

- **Day 1** takes about a minute and downloads about 50 MB. Recalculating Europe's total with `compute_europe_population.py` is optional and downloads about 475 MB.
- **Day 2** sends about 830 requests to the OSRM demo server the first time, at no more than one per second, so it takes around 25 minutes. Results are saved in `cache/`, so you can stop and resume it. The demo server is for reasonable, non-commercial use, so client work needs its own OSRM instance.

## License

The code is MIT licensed. The maps are CC BY 4.0. Each dataset keeps the license listed above, and anything derived from OpenStreetMap stays under ODbL.
