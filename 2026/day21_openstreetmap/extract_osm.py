"""Day 21 data: every cycle path in Overture Maps' copy of OpenStreetMap, summed in 1 km cells.

OpenStreetMap has two common ways to tag a path for bicycles: highway=cycleway, and a path, footway, pedestrian street
or bridleway tagged bicycle=designated. Both are read here from Overture's transportation theme (release 2026-11-18.0),
which keeps OpenStreetMap's highway classes and its access tags. Overture's bucket is public, so no account is needed.

The download is large, so it runs in 10° tiles (only those that touch the map) and keeps each tile on disk: if it
stops, run it again and it picks up where it left off. Then each path is cut into pieces of at most 200 m, and every
piece adds its length, measured on the WGS84 ellipsoid, to the 1 km cell of the EU's grid (EPSG:3035) that holds
its middle.

Writes cycleways_1km.parquet and shared_paths_1km.parquet next to this script (columns cx, cy: the cell, in km;
m: metres of path). Both are in the repo, so day21_cycleways.py runs without this step. Run it to rebuild them:
python 2026/day21_openstreetmap/extract_osm.py   (needs duckdb; about 15 minutes, keeps about 300 MB of tiles in data/)
"""
import glob
import os
import sys
import time
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
import pyarrow.parquet as pq
import shapely
from pyproj import Geod, Transformer

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from style import DATA_DIR  # noqa: E402

RELEASE = "s3://overturemaps-us-west-2/release/2026-11-18.0"
FRAME = shapely.box(2300000, 1480000, 6900000, 5140000)  # the map's extent in EPSG:3035, as in day21_cycleways.py
KINDS = {
    "cycleways": "class = 'cycleway'",
    "shared_paths": "class IN ('path', 'footway', 'pedestrian', 'bridleway') AND list_contains(list_transform("
                    "list_filter(access_restrictions, lambda x: list_contains(x.\"when\".mode, 'bicycle')), "
                    "lambda x: x.access_type), 'designated')",
}
to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
to4326 = Transformer.from_crs(3035, 4326, always_xy=True)
WGS84 = Geod(ellps="WGS84")
frame_lonlat = shapely.transform(shapely.segmentize(FRAME, 20000), lambda c: np.column_stack(
    to4326.transform(c[:, 0], c[:, 1])))
TILES = [(lon, lat) for lon in range(-25, 65, 10) for lat in range(23, 72, 10)
         if shapely.box(lon, lat, lon + 10, min(lat + 10, 72)).intersects(frame_lonlat)]


def download(kind, where, folder):
    con = duckdb.connect()
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL spatial; LOAD spatial;")
    con.sql("CREATE OR REPLACE SECRET overture (TYPE s3, PROVIDER config, KEY_ID '', SECRET '', REGION 'us-west-2');")
    con.sql("SET memory_limit='3GB'; SET threads=4; SET preserve_insertion_order=false;")
    folder.mkdir(parents=True, exist_ok=True)
    start = time.time()
    for lon, lat in TILES:
        out = folder / f"{lon}_{lat}.parquet"
        if out.exists():
            continue
        # a segment belongs to the tile that holds the lower left corner of its bounding box, so none is counted twice
        con.sql(f"""COPY (
          SELECT id, ST_AsWKB(geometry) wkb
          FROM read_parquet('{RELEASE}/theme=transportation/type=segment/*', hive_partitioning=1)
          WHERE bbox.xmin >= {lon} AND bbox.xmin < {lon + 10} AND bbox.ymin >= {lat} AND bbox.ymin < {min(lat + 10, 72)}
            AND subtype = 'road' AND {where}
        ) TO '{out}.part' (FORMAT parquet, COMPRESSION zstd)""")
        os.rename(f"{out}.part", out)
        print(kind, out.name, con.sql(f"SELECT count(*) FROM '{out}'").fetchall()[0][0], "segments,",
              round(time.time() - start), "s", flush=True)


def grid(folder):
    parts = []
    for f in sorted(glob.glob(str(folder / "*.parquet"))):
        for batch in pq.ParquetFile(f).iter_batches(batch_size=200_000, columns=["wkb"]):
            lines = shapely.from_wkb(batch.column("wkb").to_numpy(zero_copy_only=False))
            lines = shapely.transform(lines, lambda c: np.column_stack(to3035.transform(c[:, 0], c[:, 1])))
            lines = shapely.segmentize(lines, 200)  # every piece at most 200 m, so each lands in the right 1 km cell
            xy, which = shapely.get_coordinates(lines, return_index=True)
            same = which[1:] == which[:-1]
            a, b = xy[:-1][same], xy[1:][same]
            mid = (a + b) / 2
            # length on the WGS84 ellipsoid: the grid's projection keeps areas true and stretches distances a little
            (lon_a, lat_a), (lon_b, lat_b) = to4326.transform(*a.T), to4326.transform(*b.T)
            metres = WGS84.inv(lon_a, lat_a, lon_b, lat_b)[2]
            parts.append(pd.DataFrame({"cx": (mid[:, 0] // 1000).astype(np.int32), "cy": (mid[:, 1] // 1000).astype(np.int32),
                                       "m": metres}).groupby(["cx", "cy"], as_index=False).m.sum())
    cells = pd.concat(parts).groupby(["cx", "cy"], as_index=False).m.sum()
    cells["m"] = cells.m.round().astype(np.int32)
    return cells


if __name__ == "__main__":
    for kind, where in KINDS.items():
        folder = DATA_DIR / f"osm_{kind}_tiles"
        download(kind, where, folder)
        cells = grid(folder)
        cells.to_parquet(HERE / f"{kind}_1km.parquet", index=False)
        print(f"{kind}: {cells.m.sum() / 1000:,.0f} km in {len(cells):,} cells", flush=True)
