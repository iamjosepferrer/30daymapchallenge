"""Day 28 data: tropical nights in each E-OBS cell, then and now.

A tropical night is one when the temperature never drops below 20°C: the daily minimum is above 20°C, as in the
standard climate index (TR in ECA&D's list). For each 0.1° cell (about 10 km) this counts them in every full year of
1985 to 1994 and of 2015 to 2024, and averages each decade. A year counts for a cell only when the cell has data on at
least 95% of its days, and a decade only when 8 of its 10 years count.

Writes tropical_nights.npz next to this script. It's in the repo, so day28_feeling.py runs without this step. Run it
to rebuild it (it downloads two E-OBS files, 1.9 GB in all, into the data folder):
python 2026/day28_feeling/count_nights.py
"""
import sys
from pathlib import Path

import numpy as np
import requests
import xarray as xr

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "common"))
from style import DATA_DIR  # noqa: E402

URL = "https://knmi-ecad-assets-prd.s3.amazonaws.com/ensembles/data/Grid_0.1deg_reg_ensemble/tn_ens_mean_0.1deg_reg_{}_v32.0e.nc"
DECADES = {"then": ("1980-1994", range(1985, 1995)), "now": ("2011-2025", range(2015, 2025))}
HOT = 20.0  # °C: a night that stays above this is a tropical night


def download(span):
    path = DATA_DIR / f"eobs_tn_0.1deg_{span}_v32.0e.nc"
    if not path.exists():
        print(f"Downloading E-OBS minimum temperatures, {span} (about 1 GB)", flush=True)
        with requests.get(URL.format(span), stream=True, timeout=3600) as response:
            response.raise_for_status()
            with open(f"{path}.part", "wb") as f:
                for chunk in response.iter_content(1 << 22):
                    f.write(chunk)
        Path(f"{path}.part").rename(path)
    return path


out = {}
for name, (span, years) in DECADES.items():
    ds = xr.open_dataset(download(span))
    counts, full = [], []
    for year in years:
        tn = ds.tn.sel(time=str(year)).values  # °C, (day, lat, lon)
        ok = np.isfinite(tn)
        counts.append(((tn > HOT) & ok).sum(0))
        full.append(ok.mean(0) >= 0.95)
        print(name, year, flush=True)
    counts, full = np.array(counts), np.array(full)
    good = full.sum(0)
    out[name] = np.where(good >= 8, (counts * full).sum(0) / np.maximum(good, 1), np.nan).astype(np.float32)
    out["lat"], out["lon"] = ds.latitude.values, ds.longitude.values
np.savez_compressed(HERE / "tropical_nights.npz", **out)
print("saved", HERE / "tropical_nights.npz")
