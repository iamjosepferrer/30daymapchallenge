# 30DayMapChallenge

My maps for [#30DayMapChallenge](https://30daymapchallenge.com/), organised by year.

By Josep Ferrer (@iamjosepferrer on LinkedIn and X, [databites.tech](https://databites.tech)).

| Year | Theme | Maps, data and methods |
| --- | --- | --- |
| 2026 | Europe, with one clear finding per map | [Go to 2026](2026/README.md) |

## Run the maps

You need Python 3.10 or newer.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium

python 2026/day01_points/day01_points.py
python 2026/day02_lines/day02_lines.py
```

Each script downloads what it needs and saves its PNG and results in its own folder.

## License

The code is MIT licensed. The maps are CC BY 4.0. Data keeps its original license, as listed in each year's README.
