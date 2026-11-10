"""Day 10 as an animation: each AI thinks, then traces its Europe, worst to best. Saves a GIF and an MP4.

Run day10_prompting.py first is not needed: this imports it and reuses its data and drawing.
Needs ffmpeg on the PATH.
"""
import asyncio
import shutil
import subprocess
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "common"))

import day10_prompting as d10  # noqa: E402
from style import H, W, _css  # noqa: E402

FPS = 12
THINK, DRAW, DONE, HOLD = 12, 30, 8, 54  # frames: 1 s thinking, 2.5 s drawing, a pause, 4.5 s on the final chart
FRAMES = HERE / "frames"


def states():
    """Every frame's state, one AI after another, worst score first."""
    progress = {f: 0.0 for f in d10.MODELS}
    done = set()
    tick = 0
    for file in d10.ORDER:
        for t in range(THINK):
            yield {"progress": dict(progress), "current": file, "phase": "thinking", "tick": tick, "done": set(done), "callouts": False}
            tick += 1
        for t in range(1, DRAW + 1):
            ease = 1 - (1 - t / DRAW) ** 2  # starts fast, settles at the end
            progress[file] = ease
            yield {"progress": dict(progress), "current": file, "phase": "drawing", "tick": tick, "done": set(done), "callouts": False}
            tick += 1
        done.add(file)
        for t in range(DONE):
            yield {"progress": dict(progress), "current": file, "phase": "done", "tick": tick, "done": set(done), "callouts": False}
            tick += 1
    for t in range(HOLD):
        yield d10.FINAL


async def render():
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir()
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        tab = await browser.new_page(viewport=dict(width=W, height=H), device_scale_factor=1)
        await tab.set_content(f"<!doctype html><meta charset=utf-8><style>{_css()}{d10.MONO_CSS}</style><div id=c></div>")
        last = None
        for i, state in enumerate(states()):
            svg = d10.chart(state, embed_font=False)
            if svg != last:
                await tab.evaluate("s => document.getElementById('c').innerHTML = s", svg)
                if last is None:
                    await tab.evaluate("document.fonts.ready")
                    await tab.wait_for_timeout(300)
                last = svg
            await tab.screenshot(path=str(FRAMES / f"{i:04d}.png"))
        await browser.close()
    print(f"{i + 1} frames")


asyncio.run(render())
pattern = str(FRAMES / "%04d.png")
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern, "-c:v", "libx264", "-preset", "veryfast",
                "-crf", "20", "-pix_fmt", "yuv420p", str(HERE / "day10_prompting.mp4")], check=True)
subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-framerate", str(FPS), "-i", pattern, "-vf",
                "scale=810:-1:flags=lanczos,split[a][b];[a]palettegen=max_colors=96:stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=4:diff_mode=rectangle",
                str(HERE / "day10_prompting.gif")], check=True)
shutil.rmtree(FRAMES)
for f in ("day10_prompting.mp4", "day10_prompting.gif"):
    print(f, f"{(HERE / f).stat().st_size / 1e6:.1f} MB")
