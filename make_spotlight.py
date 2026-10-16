"""Render a Local Flyer Ads "CT Business Spotlight" ad (1080x1350 PNG).

Usage: python make_spotlight.py spotlight.json out.png

spotlight.json:
{
  "business": "Frank Pepe Pizzeria Napoletana",
  "town": "New Haven",
  "category": "Pizzeria",
  "headline": "Coal fired since 1925",
  "highlights": ["Famous White Clam Pizza", "Wooster Street icon", "Dine in and takeout"],
  "address": "157 Wooster St, New Haven, CT",
  "accent": "#3bdfef"            (optional; brand cyan by default)
}
"""

import asyncio
import html
import json
import sys
from pathlib import Path

from playwright.async_api import async_playwright

HERE = Path(__file__).resolve().parent
PIN = (
    '<svg viewBox="0 0 120 150" width="{w}" height="{h}"><path d="M60 4 C30 4 8 27 8 56 C8 92 60 146 60 146 '
    'C60 146 112 92 112 56 C112 27 90 4 60 4 Z" fill="{c}"/><path d="M28 58 L90 32 L58 68 Z" fill="#06090f"/>'
    '<path d="M58 68 L90 32 L72 86 Z" fill="#ac52fa"/><path d="M58 68 L61 84 L67 75 Z" fill="#5B2A8C"/></svg>'
)


def page(d: dict) -> str:
    e = lambda s: html.escape(str(s))
    accent = d.get("accent", "#3bdfef")
    name = d["business"]
    size = 112 if len(name) <= 16 else 92 if len(name) <= 24 else 76 if len(name) <= 34 else 64
    chips = "".join(f'<div class="chip"><span class="dot"></span>{e(h)}</div>' for h in d["highlights"][:3])
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{box-sizing:border-box;margin:0;padding:0}}
body{{width:1080px;height:1350px;background:#06090f;font-family:Poppins,Inter,sans-serif;color:#f4f7fb;overflow:hidden;position:relative}}
.blob1{{position:absolute;width:760px;height:760px;border-radius:50%;background:{accent};opacity:.13;top:-260px;right:-260px}}
.blob2{{position:absolute;width:520px;height:520px;border-radius:50%;background:#ac52fa;opacity:.16;bottom:120px;left:-260px}}
.stripe{{position:absolute;left:0;right:0;top:0;height:14px;background:linear-gradient(90deg,{accent},#ac52fa)}}
.wrap{{position:absolute;inset:0;padding:84px 84px 0}}
.top{{display:flex;align-items:center;gap:20px}}
.brand{{font-weight:700;font-size:34px;letter-spacing:.5px}}
.brand small{{display:block;font-weight:500;font-size:20px;color:#8fa3b8;letter-spacing:3px}}
.kicker{{margin-top:92px;display:inline-flex;gap:14px;align-items:center;background:rgba(59,223,239,.12);border:2px solid {accent};
  color:{accent};font-weight:700;font-size:26px;letter-spacing:4px;padding:14px 26px;border-radius:999px;text-transform:uppercase}}
.cat{{margin-top:44px;font-size:30px;font-weight:500;color:#ac52fa;letter-spacing:2px;text-transform:uppercase}}
h1{{margin-top:12px;font-size:{size}px;line-height:1.02;font-weight:700;letter-spacing:-1.5px;max-width:920px}}
.head{{margin-top:28px;font-size:42px;font-weight:500;color:#c9d6e3;max-width:900px;line-height:1.25}}
.chips{{margin-top:48px;display:flex;flex-direction:column;gap:18px}}
.chip{{display:flex;align-items:center;gap:20px;font-size:34px;font-weight:500}}
.dot{{width:22px;height:22px;border-radius:50%;background:{accent};flex:none;box-shadow:0 0 0 6px rgba(59,223,239,.18)}}
.addr{{position:absolute;left:84px;right:84px;bottom:236px;display:flex;align-items:center;gap:22px;font-size:32px;font-weight:500;color:#e8eef5}}
.foot{{position:absolute;left:0;right:0;bottom:0;height:190px;background:{accent};color:#06090f;display:flex;align-items:center;
  justify-content:space-between;padding:0 84px}}
.foot b{{display:block;font-size:38px;font-weight:700;line-height:1.15}}
.foot span{{font-size:26px;font-weight:600}}
.cta{{background:#06090f;color:#f4f7fb;font-weight:700;font-size:28px;padding:22px 34px;border-radius:18px;white-space:nowrap}}
</style></head><body>
<div class="blob1"></div><div class="blob2"></div><div class="stripe"></div>
<div class="wrap">
  <div class="top">{PIN.format(w=64, h=80, c=accent)}<div class="brand">Local Flyer Ads<small>CONNECTICUT</small></div></div>
  <div class="kicker">CT Business Spotlight · {e(d["town"])}</div>
  <div class="cat">{e(d["category"])}</div>
  <h1>{e(name)}</h1>
  <div class="head">{e(d["headline"])}</div>
  <div class="chips">{chips}</div>
</div>
<div class="addr">{PIN.format(w=34, h=42, c="#ac52fa")}{e(d["address"])}</div>
<div class="foot"><div><b>Want your business featured?</b><span>Screens + social ads across CT</span></div>
<div class="cta">Reserve your spot ▸</div></div>
</body></html>"""


async def render(spec: Path, out: Path) -> None:
    d = json.loads(spec.read_text())
    async with async_playwright() as p:
        b = await p.chromium.launch()
        pg = await b.new_page(viewport={"width": 1080, "height": 1350})
        await pg.set_content(page(d))
        await pg.wait_for_timeout(300)
        await pg.screenshot(path=str(out), type="png")
        await b.close()


if __name__ == "__main__":
    asyncio.run(render(Path(sys.argv[1]), Path(sys.argv[2])))
