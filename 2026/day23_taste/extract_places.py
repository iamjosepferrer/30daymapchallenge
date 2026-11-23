"""Day 23 data: every winery and brewery in Overture Maps' places (release 2026-11-18.0).

Overture's places come from business listings: here, about half from Meta and most of the rest from BrightQuery.
Each place has a main category: 'winery' and 'brewery' are the two used here. Places marked permanently closed are
left out. The read runs in 10° tiles (only those that touch the map) and keeps each tile on disk, so if it stops,
run it again and it picks up where it left off.

Writes wineries_breweries.parquet next to this script (columns id, name, kind, lon, lat, confidence, country).
It's in the repo, so day23_taste.py runs without this step. Run it to rebuild it:
python 2026/day23_taste/extract_places.py   (needs duckdb; a few minutes)
"""
import os
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import shapely
from pyproj import Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from style import DATA_DIR  # noqa: E402

RELEASE = "s3://overturemaps-us-west-2/release/2026-11-18.0"
FRAME = shapely.box(2300000, 1480000, 6900000, 5140000)  # the map's extent in EPSG:3035, as in day23_taste.py
to4326 = Transformer.from_crs(3035, 4326, always_xy=True)
frame_lonlat = shapely.transform(shapely.segmentize(FRAME, 20000), lambda c: np.column_stack(to4326.transform(c[:, 0], c[:, 1])))
TILES = [(lon, lat) for lon in range(-25, 65, 10) for lat in range(23, 72, 10)
         if shapely.box(lon, lat, lon + 10, min(lat + 10, 72)).intersects(frame_lonlat)]


def main():
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    con.sql("CREATE OR REPLACE SECRET overture (TYPE s3, PROVIDER config, KEY_ID '', SECRET '', REGION 'us-west-2');")
    con.sql("SET memory_limit='3GB'; SET threads=4;")
    folder = DATA_DIR / "overture_wineries_breweries_tiles"
    folder.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for lon, lat in TILES:
        out = folder / f"{lon}_{lat}.parquet"
        if out.exists():
            continue
        # a place belongs to the tile that holds it, so none is counted twice
        con.sql(f"""COPY (
          SELECT id, names.primary AS name, taxonomy.primary AS kind, ST_X(geometry) AS lon, ST_Y(geometry) AS lat,
                 confidence, addresses[1].country AS country
          FROM read_parquet('{RELEASE}/theme=places/type=place/*', hive_partitioning=1)
          WHERE bbox.xmin >= {lon} AND bbox.xmin < {lon + 10} AND bbox.ymin >= {lat} AND bbox.ymin < {min(lat + 10, 72)}
            AND taxonomy.primary IN ('winery', 'brewery')
            AND coalesce(operating_status, 'open') <> 'permanently_closed'
        ) TO '{out}.part' (FORMAT parquet)""")
        os.rename(f"{out}.part", out)
        print(out.name, con.sql(f"SELECT count(*) FROM '{out}'").fetchall()[0][0], "places,", round(time.time() - start), "s", flush=True)
    places = pd.concat([pd.read_parquet(f) for f in sorted(folder.glob("*.parquet"))], ignore_index=True)
    places.to_parquet(HERE / "wineries_breweries.parquet", index=False)
    print(places.kind.value_counts().to_dict(), flush=True)


if __name__ == "__main__":
    main()
