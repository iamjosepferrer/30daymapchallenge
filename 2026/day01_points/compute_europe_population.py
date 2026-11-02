"""Total Europe's 2025 population from the GHS-POP grid.

day01_points.py reads the saved europe_population.csv, so you only need to run this
to check that number. It downloads about 475 MB the first time.

Boundaries come from Natural Earth at 1:10m, and every grid cell touching them counts.
Coarser boundaries cut off coastal cells and undercount the total by about 10 million.
"""
import io
import sys
import zipfile
from pathlib import Path

import geopandas as gpd
import pandas as pd
import rasterio
import requests
from rasterio.mask import mask
from shapely.geometry import box
from shapely.ops import unary_union

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))

from style import DATA_DIR  # noqa: E402

NAME = "GHS_POP_E2025_GLOBE_R2023A_4326_30ss_V1_0"
POP_URL = (
    "https://jeodpp.jrc.ec.europa.eu/ftp/jrc-opendata/GHSL/GHS_POP_GLOBE_R2023A/"
    f"GHS_POP_E2025_GLOBE_R2023A_4326_30ss/V1-0/{NAME}.zip"
)
BOUNDARIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_10m_admin_0_countries.geojson"
)
# Countries in the GHS-UCDB Europe region, with Natural Earth names
SCOPE = {
    "United Kingdom", "Ireland", "France", "Spain", "Portugal", "Germany", "Netherlands",
    "Belgium", "Luxembourg", "Switzerland", "Austria", "Italy", "Denmark", "Norway", "Sweden",
    "Finland", "Iceland", "Estonia", "Latvia", "Lithuania", "Poland", "Czechia", "Slovakia",
    "Hungary", "Slovenia", "Croatia", "Bosnia and Herzegovina", "Republic of Serbia",
    "Montenegro", "Kosovo", "North Macedonia", "Albania", "Greece", "Bulgaria", "Romania",
    "Moldova", "Ukraine", "Belarus", "Russia", "Malta", "Jersey", "Andorra", "Liechtenstein",
    "Monaco", "San Marino", "Vatican", "Guernsey", "Isle of Man", "Faroe Islands", "Aland",
    "Gibraltar",
}
# West of 60°E, which also leaves out France's overseas territories
EUROPE_BOX = box(-32, 27, 60, 82)

raster = DATA_DIR / f"{NAME}.tif"
if not raster.exists():
    print("Downloading GHS-POP (461 MB)")
    response = requests.get(POP_URL, timeout=1800)
    response.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        archive.extract(raster.name, DATA_DIR)

boundaries = DATA_DIR / "ne_10m_admin_0_countries.geojson"
if not boundaries.exists():
    print("Downloading Natural Earth 1:10m boundaries")
    response = requests.get(BOUNDARIES_URL, timeout=300)
    response.raise_for_status()
    boundaries.write_bytes(response.content)

world = gpd.read_file(boundaries)
europe = unary_union(world[world.ADMIN.isin(SCOPE)].geometry.buffer(0)).intersection(EUROPE_BOX)

with rasterio.open(raster) as source:
    cells, _ = mask(source, [europe], crop=True, nodata=0, filled=True, all_touched=True)
total = round(float(cells[cells > 0].sum()))

pd.DataFrame({"scope": ["Europe"], "population_2025": [total]}).to_csv(HERE / "europe_population.csv", index=False)
print(f"Total: {total / 1e6:.1f} million")
