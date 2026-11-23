"""Day 24 data: Europe's high-voltage power lines and cables, from Overture Maps' copy of OpenStreetMap.

Overture's infrastructure theme (release 2026-11-18.0) keeps OpenStreetMap's power=line and power=cable ways, with
their original tags. This keeps those with a voltage of at least 110 kV (the highest one, when a line carries several),
plus the tags that say how many circuits a line has and whether it carries direct current. The read runs in 10° tiles
(only those that touch the map) and keeps each tile on disk, so if it stops, run it again and it picks up where it
left off.

Then each line is cut to the map, its length measured on the WGS84 ellipsoid (km), and its shape simplified to 30 m,
which keeps the file small enough for GitHub without changing what the map shows. Writes power_lines.parquet next to
this script (columns kind, kv, circuits, dc, location, km, wkb in lon/lat). It's in the repo, so day24_network.py runs
without this step. Run it to rebuild it:
python 2026/day24_network/extract_grid.py   (needs duckdb; a few minutes)
"""
import os
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import shapely
from pyproj import Geod, Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from style import DATA_DIR  # noqa: E402

RELEASE = "s3://overturemaps-us-west-2/release/2026-11-18.0"
FRAME = shapely.box(2300000, 1480000, 6900000, 5140000)  # the map's extent in EPSG:3035, as in day24_network.py
to4326 = Transformer.from_crs(3035, 4326, always_xy=True)
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
frame_lonlat = shapely.transform(shapely.segmentize(FRAME, 20000), lambda c: np.column_stack(to4326.transform(c[:, 0], c[:, 1])))
TILES = [(lon, lat) for lon in range(-25, 65, 10) for lat in range(23, 72, 10)
         if shapely.box(lon, lat, lon + 10, min(lat + 10, 72)).intersects(frame_lonlat)]
# the highest number in a voltage tag such as "400000;220000", in kV
KV = "list_max(list_transform(regexp_extract_all(source_tags['voltage'], '[0-9]+'), lambda v: TRY_CAST(v AS DOUBLE))) / 1000"


def main():
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    con.sql("CREATE OR REPLACE SECRET overture (TYPE s3, PROVIDER config, KEY_ID '', SECRET '', REGION 'us-west-2');")
    con.sql("SET memory_limit='3GB'; SET threads=4;")
    folder = DATA_DIR / "overture_power_lines_tiles"
    folder.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for lon, lat in TILES:
        out = folder / f"{lon}_{lat}.parquet"
        if out.exists():
            continue
        # a line belongs to the tile that holds the lower left corner of its bounding box, so none is counted twice
        con.sql(f"""COPY (
          SELECT id, class AS kind, {KV} AS kv, source_tags['circuits'] AS circuits,
                 (source_tags['frequency'] = '0' OR source_tags['current'] = 'dc') AS dc, source_tags['location'] AS location,
                 ST_AsWKB(geometry) AS wkb
          FROM read_parquet('{RELEASE}/theme=base/type=infrastructure/*', hive_partitioning=1)
          WHERE bbox.xmin >= {lon} AND bbox.xmin < {lon + 10} AND bbox.ymin >= {lat} AND bbox.ymin < {min(lat + 10, 72)}
            AND subtype = 'power' AND class IN ('power_line', 'cable') AND {KV} >= 110
        ) TO '{out}.part' (FORMAT parquet)""")
        os.rename(f"{out}.part", out)
        print(out.name, con.sql(f"SELECT count(*) FROM '{out}'").fetchall()[0][0], "lines,", round(time.time() - start), "s", flush=True)
    lines = pd.concat([pd.read_parquet(f) for f in sorted(folder.glob("*.parquet"))], ignore_index=True)
    project = lambda geoms, t: shapely.transform(geoms, lambda c: np.column_stack(t.transform(c[:, 0], c[:, 1])))
    clipped = shapely.intersection(project(shapely.from_wkb(lines.wkb.values), to3035), FRAME)
    keep = ~shapely.is_empty(clipped)
    lines, clipped = lines[keep].drop(columns=["id", "wkb"]).reset_index(drop=True), clipped[keep]
    lonlat = project(clipped, to4326)
    lines["km"] = [Geod(ellps="WGS84").geometry_length(g) / 1000 for g in lonlat]  # measured before simplifying
    small = project(shapely.simplify(clipped, 30), to4326)
    lines["wkb"] = shapely.to_wkb(shapely.set_precision(small, 0.00001))  # about 1 m
    lines.to_parquet(HERE / "power_lines.parquet", index=False, compression="zstd")
    print(len(lines), "lines;", lines.kind.value_counts().to_dict(), flush=True)


if __name__ == "__main__":
    main()
