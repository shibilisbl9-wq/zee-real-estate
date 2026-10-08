#!/usr/bin/env python3
"""Zee Real Estate - Shahrukhz Residences ad builder.

Builds 3 ad concepts x 2 formats (post 1080x1350, story 1080x1920):
  1. Pillow prepares hero backgrounds from the developer renders in assets/
  2. HTML is written to src/
  3. Headless Chromium screenshots each page into out/

Edit the constants below (PERMIT, CTA, etc.) and re-run:  python3 build.py
"""
import subprocess
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).parent.resolve()
SRC, OUT, ASSETS = ROOT / "src", ROOT / "out", ROOT / "assets"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"

# ---- editable bits ---------------------------------------------------------
BRAND = "ZEE REAL ESTATE"
PERMIT = ""  # e.g. "DLD Permit No. 12345 | ORN 1234" -- Dubai ads need this. Empty = not shown.
PROJECT = "Shahrukhz Residences"

POST = (1080, 1350)
STORY = (1080, 1920)


# ---- backgrounds -----------------------------------------------------------
def mono_gold(im):
    """Black/white look: desaturate everything except warm (gold/copper) tones."""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype("float32") / 255.0
    hsv = np.asarray(im.convert("HSV")).astype("float32") / 255.0
    h = hsv[..., 0] * 360.0
    # warm membership: 0-65deg and 340-360deg, soft edges
    sat = hsv[..., 1]
    w = np.clip((58 - h) / 18, 0, 1) * (h < 180) + np.clip((h - 335) / 15, 0, 1) * (h >= 180)
    w = w * np.clip((sat - 0.22) / 0.25, 0, 1)          # ignore low-sat noise
    w = np.asarray(Image.fromarray((np.clip(w, 0, 1) * 255).astype("uint8")).filter(ImageFilter.GaussianBlur(2.5))).astype("float32") / 255.0
    w = w[..., None]
    luma = (a * [0.299, 0.587, 0.114]).sum(-1, keepdims=True)
    luma = np.clip(luma, 0, 1) ** 1.35 * 1.05          # deeper, contrastier blacks
    gray = np.repeat(luma, 3, axis=-1)
    warm = a * (0.92 + 0.0)                             # keep gold as-is
    out = gray * (1 - w) + warm * w
    return Image.fromarray((np.clip(out, 0, 1) * 255).astype("uint8"))


def smooth(t):
    return t * t * (3 - 2 * t)


def build_bg(hero_box, src, W, H, scale, side, name):
    """Place a cropped render on one side and extend the scene to fill W x H."""
    hero = mono_gold(Image.open(ASSETS / src).convert("RGB").crop(hero_box))
    hw, hh = hero.size
    hero = hero.resize((round(hw * scale), round(hh * scale)), Image.LANCZOS)
    hw, hh = hero.size
    y0 = max(0, H - hh)  # bottom aligned; sky is extended upward

    # vertical extension (sky) above the hero
    col = Image.new("RGB", (hw, H))
    if y0:
        top = hero.crop((0, 0, hw, 6)).resize((1, 1), Image.BOX)
        # keep some horizontal variation: use per-column average of top rows
        strip = hero.crop((0, 0, hw, 6)).resize((hw, 1), Image.BOX)
        ext = strip.resize((hw, y0 + 100), Image.BILINEAR).filter(ImageFilter.GaussianBlur(40))
        col.paste(ext, (0, 0))
    mask = Image.new("L", (hw, hh), 255)
    if y0:
        fade = 90
        px = mask.load()
        for y in range(fade):
            v = int(255 * smooth(y / fade))
            for x in range(hw):
                px[x, y] = v
    col.paste(hero, (0, y0), mask)

    # backdrop from the inner edge column, stretched across the canvas
    ex = 0 if side == "right" else hw - 8
    edge = col.crop((ex, 0, ex + 8, H)).resize((1, H), Image.BOX)
    backdrop = edge.resize((W, H), Image.BILINEAR).filter(ImageFilter.GaussianBlur(28))

    # horizontal feather on the inner edge
    feather = 190
    m = Image.new("L", (hw, H), 255)
    mp = m.load()
    for x in range(feather):
        v = int(255 * smooth(x / feather))
        xx = x if side == "right" else hw - 1 - x
        for y in range(H):
            mp[xx, y] = v
    x_pos = W - hw if side == "right" else 0
    backdrop.paste(col, (x_pos, 0), m)
    out = ASSETS / f"bg_{name}.jpg"
    backdrop.save(out, quality=92)
    return out.name


def crop_asset(box, src, name, scale=1.0):
    im = mono_gold(Image.open(ASSETS / src).convert("RGB").crop(box))
    if scale != 1.0:
        im = im.resize((round(im.width * scale), round(im.height * scale)), Image.LANCZOS)
    p = ASSETS / f"{name}.jpg"
    im.save(p, quality=93)
    return p.name


# ---- shared HTML -----------------------------------------------------------
CSS = """
:root{
  --navy:#000; --navy2:#111;
  --g1:#f6e2a8; --g2:#d9aa4a; --g3:#9a6f1f;
  --gold:linear-gradient(135deg,#f6e2a8 0%,#d9aa4a 50%,#a77a24 100%);
}
*{box-sizing:border-box;margin:0;padding:0}
html,body{width:var(--W);height:var(--H);overflow:hidden}
body{position:relative;font-family:'Montserrat',sans-serif;color:#fff;-webkit-font-smoothing:antialiased}
.abs{position:absolute}
.serif{font-family:'Playfair Display',serif;font-variant-numeric:lining-nums;font-feature-settings:'lnum' 1}
.goldtxt{background:var(--gold);-webkit-background-clip:text;background-clip:text;color:transparent;text-shadow:none}
.brand{position:absolute;display:flex;align-items:center;gap:14px;font-weight:700;letter-spacing:.34em;font-size:21px}
.brand i{display:block;width:14px;height:14px;background:var(--gold);transform:rotate(45deg)}
.eyebrow{font-weight:600;letter-spacing:.26em;font-size:20px;text-transform:uppercase;color:#f6e2a8}
.cta{display:inline-flex;align-items:center;gap:16px;background:var(--gold);color:#0b0b0b;font-weight:700;
  letter-spacing:.14em;text-transform:uppercase;border-radius:999px;box-shadow:0 10px 30px rgba(0,0,0,.35)}
.fine{font-size:16px;line-height:1.45;color:rgba(255,255,255,.82)}
.glass{background:rgba(8,8,8,.58);backdrop-filter:blur(10px);-webkit-backdrop-filter:blur(10px);
  border:1.5px solid rgba(246,226,168,.55);border-radius:22px}
.hair{height:1.5px;background:linear-gradient(90deg,rgba(246,226,168,.9),rgba(246,226,168,0))}
.shadow{text-shadow:0 2px 18px rgba(0,0,0,.55)}
"""


def page(name, W, H, body, extra_css=""):
    html = f"""<!doctype html><html><head><meta charset="utf-8">
<link rel="stylesheet" href="fonts.css"><style>:root{{--W:{W}px;--H:{H}px}}{CSS}{extra_css}</style></head><body>{body}</body></html>"""
    (SRC / f"{name}.html").write_text(html)
    return name


def footer(disclaimer, bottom, left=60, width=960):
    permit = f" &nbsp;|&nbsp; {PERMIT}" if PERMIT else ""
    return f"""<div class="abs fine shadow" style="left:{left}px;bottom:{bottom}px;width:{width}px">
{disclaimer}<br><b style="letter-spacing:.12em">{BRAND}</b>{permit}</div>"""


# ---- Ad 1: Golden Visa -----------------------------------------------------
def ad1_post():
    bg = build_bg((730, 0, 1254, 1254), "1.webp", *POST, 1350 / 1254, "right", "a_post")
    body = f"""
<img class="abs" src="../assets/{bg}" style="inset:0;width:1080px;height:1350px">
<div class="abs" style="inset:0;background:linear-gradient(90deg,rgba(0,0,0,.78) 0%,rgba(0,0,0,.55) 42%,rgba(0,0,0,0) 66%)"></div>
<div class="brand shadow" style="left:60px;top:56px"><i></i>{BRAND}</div>
<div class="abs eyebrow shadow" style="left:60px;top:158px;font-size:17px;letter-spacing:.2em">{PROJECT} &middot; by Danube</div>
<h1 class="abs serif shadow" style="left:60px;top:204px;width:560px;font-size:76px;line-height:1.06;font-weight:700">
  Buy in Dubai.<br>Get a 10-year<br><span class="goldtxt" style="font-style:italic;font-weight:700">Golden Visa.*</span></h1>
<p class="abs shadow" style="left:60px;top:486px;width:470px;font-size:27px;line-height:1.4;font-weight:500">
  Fully furnished waterfront apartments in Dubai Maritime City, with sea views.</p>
<div class="abs" style="left:60px;top:640px;width:470px">
  <div class="hair"></div>
  <div style="display:flex;align-items:baseline;gap:20px;padding:22px 0"><b class="serif goldtxt" style="font-size:54px;min-width:210px">10%</b><span style="font-size:23px;font-weight:600;letter-spacing:.04em">DOWN PAYMENT</span></div>
  <div class="hair"></div>
  <div style="display:flex;align-items:baseline;gap:20px;padding:22px 0"><b class="serif goldtxt" style="font-size:54px;min-width:210px">30/70</b><span style="font-size:23px;font-weight:600;letter-spacing:.04em">PAYMENT PLAN</span></div>
  <div class="hair"></div>
  <div style="display:flex;align-items:baseline;gap:20px;padding:22px 0"><b class="serif goldtxt" style="font-size:40px;min-width:210px;white-space:nowrap">AED 2.3M</b><span style="font-size:23px;font-weight:600;letter-spacing:.04em">1 BHK FROM</span></div>
  <div class="hair"></div>
</div>
<div class="abs cta" style="left:60px;top:1070px;padding:26px 44px;font-size:24px">Get the price list <span style="font-size:30px">&rarr;</span></div>
{footer("*Golden Visa for units valued AED 2M+, subject to approval. Handover Dec 2029.", 40, width=480)}
"""
    return page("ad1_post", *POST, body)


def ad1_story():
    bg = build_bg((730, 0, 1254, 1254), "1.webp", *STORY, 1.08, "right", "a_story")
    body = f"""
<img class="abs" src="../assets/{bg}" style="inset:0;width:1080px;height:1920px">
<div class="abs" style="inset:0;background:linear-gradient(180deg,rgba(0,0,0,.55) 0%,rgba(0,0,0,0) 32%),linear-gradient(90deg,rgba(0,0,0,.72) 0%,rgba(0,0,0,.45) 40%,rgba(0,0,0,0) 62%)"></div>
<div class="brand shadow" style="left:60px;top:220px"><i></i>{BRAND}</div>
<div class="abs eyebrow shadow" style="left:60px;top:300px">{PROJECT} &middot; by Danube</div>
<h1 class="abs serif shadow" style="left:60px;top:346px;width:960px;font-size:88px;line-height:1.05;font-weight:700">
  Buy in Dubai.<br>Get a 10-year<br><span class="goldtxt" style="font-style:italic">Golden Visa.*</span></h1>
<p class="abs shadow" style="left:60px;top:790px;width:490px;font-size:29px;line-height:1.4;font-weight:500">
  Fully furnished waterfront apartments in Dubai Maritime City.</p>
<div class="abs" style="left:60px;top:960px;width:470px">
  <div class="hair"></div>
  <div style="padding:24px 0"><b class="serif goldtxt" style="font-size:70px;display:block;line-height:1;margin-bottom:10px">10%</b><span style="font-size:22px;font-weight:600;letter-spacing:.08em">DOWN PAYMENT</span></div>
  <div class="hair"></div>
  <div style="padding:24px 0"><b class="serif goldtxt" style="font-size:70px;display:block;line-height:1;margin-bottom:10px">30/70</b><span style="font-size:22px;font-weight:600;letter-spacing:.08em">PAYMENT PLAN</span></div>
  <div class="hair"></div>
  <div style="padding:24px 0"><b class="serif goldtxt" style="font-size:56px;display:block;line-height:1.1;margin-bottom:8px">AED 2.3M</b><span style="font-size:22px;font-weight:600;letter-spacing:.08em">1 BHK FROM</span></div>
  <div class="hair"></div>
</div>
<div class="abs cta" style="left:60px;top:1500px;padding:30px 50px;font-size:27px">Get the price list <span style="font-size:32px">&rarr;</span></div>
{footer("*Golden Visa for units valued AED 2M+, subject to approval. Handover Dec 2029.", 150, width=470)}
"""
    return page("ad1_story", *STORY, body)


# ---- Ad 2: 10% down + prices ----------------------------------------------
PRICES = [("Studio", "1.65M"), ("1 BHK", "2.3M"), ("2 BHK", "4.25M"), ("3 BHK", "6.5M")]


def ad2_post():
    bg = build_bg((0, 0, 405, 1254), "2.webp", *POST, 1350 / 1254, "left", "b_post")
    rows = "".join(
        f"""<div style="display:flex;justify-content:space-between;align-items:baseline;padding:15px 0;border-top:1.5px solid rgba(246,226,168,.35)">
        <span style="font-size:24px;font-weight:600;letter-spacing:.1em;text-transform:uppercase">{k}</span>
        <span class="serif goldtxt" style="font-size:40px;font-weight:700">AED {v}</span></div>"""
        for k, v in PRICES
    )
    body = f"""
<img class="abs" src="../assets/{bg}" style="inset:0;width:1080px;height:1350px">
<div class="abs" style="inset:0;background:linear-gradient(270deg,rgba(0,0,0,.6) 0%,rgba(0,0,0,.35) 55%,rgba(0,0,0,0) 80%)"></div>
<div class="brand shadow" style="left:480px;top:56px"><i></i>{BRAND}</div>
<div class="abs eyebrow shadow" style="left:480px;top:156px;font-size:17px;letter-spacing:.2em">Dubai Maritime City &middot; by Danube</div>
<h1 class="abs serif shadow" style="left:480px;top:196px;width:560px;font-size:68px;line-height:1.08;font-weight:700">
  Sea-view Dubai apartment.<br><span class="goldtxt" style="font-style:italic">10% down.</span></h1>
<div class="abs shadow" style="left:480px;top:476px;width:540px;display:flex;gap:28px;font-size:22px;line-height:1.35;font-weight:500">
  <div><b class="serif goldtxt" style="font-size:46px;display:block">30%</b>during construction</div>
  <div style="width:1.5px;background:rgba(246,226,168,.6)"></div>
  <div><b class="serif goldtxt" style="font-size:46px;display:block">70%</b>on handover<br>(Dec 2029)</div>
</div>
<div class="abs glass" style="left:480px;top:660px;width:540px;padding:22px 30px 14px">
  <div class="eyebrow" style="text-align:center;padding-bottom:12px">Starting prices</div>{rows}
</div>
<div class="abs shadow" style="left:480px;top:1085px;width:540px;font-size:22px;line-height:1.4;font-weight:500">
  <b>Fully furnished:</b> move in or rent out from handover.</div>
<div class="abs cta" style="left:480px;top:1170px;padding:22px 38px;font-size:22px">Get the full price list <span style="font-size:28px">&rarr;</span></div>
{footer("Starting prices, subject to availability. Handover Dec 2029.", 28, left=480, width=560)}
"""
    return page("ad2_post", *POST, body)


def ad2_story():
    bg = build_bg((0, 0, 405, 1254), "2.webp", *STORY, 1.0, "left", "b_story")
    rows = "".join(
        f"""<div style="display:flex;justify-content:space-between;align-items:baseline;padding:20px 0;border-top:1.5px solid rgba(246,226,168,.35)">
        <span style="font-size:28px;font-weight:600;letter-spacing:.1em;text-transform:uppercase">{k}</span>
        <span class="serif goldtxt" style="font-size:50px;font-weight:700">AED {v}</span></div>"""
        for k, v in PRICES
    )
    body = f"""
<img class="abs" src="../assets/{bg}" style="inset:0;width:1080px;height:1920px">
<div class="abs" style="inset:0;background:linear-gradient(180deg,rgba(0,0,0,.55) 0%,rgba(0,0,0,0) 30%),linear-gradient(270deg,rgba(0,0,0,.62) 0%,rgba(0,0,0,.35) 50%,rgba(0,0,0,0) 78%),linear-gradient(0deg,rgba(0,0,0,.92) 0%,rgba(0,0,0,.7) 12%,rgba(0,0,0,0) 24%)"></div>
<div class="brand shadow" style="left:60px;top:220px"><i></i>{BRAND}</div>
<div class="abs eyebrow shadow" style="left:60px;top:300px;font-size:19px">Dubai Maritime City &middot; by Danube</div>
<h1 class="abs serif shadow" style="left:60px;top:346px;width:960px;font-size:92px;line-height:1.05;font-weight:700">
  Sea-view Dubai<br>apartment.<br><span class="goldtxt" style="font-style:italic">10% down.</span></h1>
<div class="abs shadow" style="left:540px;top:820px;width:480px;display:flex;gap:26px;font-size:24px;line-height:1.35;font-weight:500">
  <div><b class="serif goldtxt" style="font-size:58px;display:block">30%</b>during construction</div>
  <div style="width:1.5px;background:rgba(246,226,168,.6)"></div>
  <div><b class="serif goldtxt" style="font-size:58px;display:block">70%</b>on handover<br>(Dec 2029)</div>
</div>
<div class="abs glass" style="left:540px;top:1030px;width:480px;padding:22px 26px 10px">
  <div class="eyebrow" style="text-align:center;padding-bottom:12px">Starting prices</div>{rows.replace('font-size:50px','font-size:40px').replace('font-size:28px','font-size:22px').replace('padding:20px 0','padding:18px 0')}
</div>
<div class="abs cta" style="left:540px;top:1500px;padding:26px 36px;font-size:23px">Get the price list <span style="font-size:28px">&rarr;</span></div>
{footer("Starting prices, subject to availability. Fully furnished: move in or rent out from handover (Dec 2029).", 150, left=60, width=960)}
"""
    return page("ad2_story", *STORY, body)


# ---- Ad 3: Live king style (dark / gold) ----------------------------------
FACTS = [
    ("Dec 2029", "Handover"),
    ("10 min", "to Burj Khalifa"),
    ("Italian", "kitchen & bath fittings"),
    ("Gauri Khan", "designed penthouses"),
]


def ad3_post():
    arch = crop_asset((730, 0, 1254, 1254), "1.webp", "arch_post", 0.84)
    facts = "".join(
        f"""<div style="padding:18px 0;border-top:1.5px solid rgba(246,226,168,.35)">
        <b class="serif goldtxt" style="font-size:38px;display:block;line-height:1.1">{a}</b>
        <span style="font-size:21px;font-weight:500;letter-spacing:.04em">{b}</span></div>"""
        for a, b in FACTS
    )
    css = """
body{background:radial-gradient(120% 80% at 80% 0%,#2a2a2a 0%,#0e0e0e 50%,#000 100%)}
.arch{position:absolute;overflow:hidden;border-radius:999px 999px 0 0;border:3px solid #d9aa4a;box-shadow:0 0 0 10px rgba(217,170,74,.12),0 30px 60px rgba(0,0,0,.45)}
.arch img{width:100%;height:100%;object-fit:cover;object-position:50% 20%}
"""
    body = f"""
<div class="brand" style="left:60px;top:56px"><i></i>{BRAND}</div>
<div class="arch" style="left:60px;top:170px;width:430px;height:900px"><img src="../assets/{arch}"></div>
<div class="abs eyebrow" style="left:550px;top:182px;font-size:16px;letter-spacing:.2em">{PROJECT} &middot; by Danube</div>
<h1 class="abs serif" style="left:550px;top:232px;width:480px;font-size:74px;line-height:1.05;font-weight:700">
  Live life,<br><span class="goldtxt" style="font-style:italic">king style.</span></h1>
<p class="abs" style="left:550px;top:430px;width:470px;font-size:23px;line-height:1.45;font-weight:500;color:rgba(255,255,255,.9)">
  Fully furnished waterfront apartments in Dubai Maritime City.</p>
<div class="abs" style="left:550px;top:560px;width:470px">{facts}<div style="border-top:1.5px solid rgba(246,226,168,.35)"></div></div>
<div class="abs cta" style="left:60px;top:1130px;padding:26px 46px;font-size:23px">Book a private briefing <span style="font-size:29px">&rarr;</span></div>
{footer("Fully furnished: move in or rent out from handover. Starting prices and availability on request.", 44)}
"""
    return page("ad3_post", *POST, body, css)


def ad3_story():
    arch = crop_asset((730, 0, 1254, 1254), "1.webp", "arch_story", 1.0)
    facts = "".join(
        f"""<div style="padding:34px 0;border-top:1.5px solid rgba(246,226,168,.35)">
        <b class="serif goldtxt" style="font-size:44px;display:block;line-height:1.1">{a}</b>
        <span style="font-size:22px;font-weight:500;letter-spacing:.04em">{b}</span></div>"""
        for a, b in FACTS
    )
    css = """
body{background:radial-gradient(120% 70% at 80% 0%,#2a2a2a 0%,#0e0e0e 50%,#000 100%)}
.arch{position:absolute;overflow:hidden;border-radius:999px 999px 0 0;border:3px solid #d9aa4a;box-shadow:0 0 0 10px rgba(217,170,74,.12),0 30px 60px rgba(0,0,0,.45)}
.arch img{width:100%;height:100%;object-fit:cover;object-position:50% 20%}
"""
    body = f"""
<div class="brand" style="left:60px;top:220px"><i></i>{BRAND}</div>
<div class="abs eyebrow" style="left:60px;top:300px">{PROJECT} &middot; by Danube</div>
<h1 class="abs serif" style="left:60px;top:346px;width:960px;font-size:100px;line-height:1.05;font-weight:700">
  Live life,<br><span class="goldtxt" style="font-style:italic">king style.</span></h1>
<div class="arch" style="left:60px;top:660px;width:520px;height:930px"><img src="../assets/{arch}"></div>
<div class="abs" style="left:620px;top:680px;width:400px">{facts}<div style="border-top:1.5px solid rgba(246,226,168,.35)"></div></div>
<div class="abs cta" style="left:620px;top:1500px;padding:24px 30px;font-size:20px;width:400px;justify-content:center">Book a briefing &rarr;</div>
{footer("Fully furnished: move in or rent out from handover. Starting prices and availability on request.", 150)}
"""
    return page("ad3_story", *STORY, body, css)


# ---- render ----------------------------------------------------------------
def render(name, size):
    w, h = size
    out = OUT / f"{name}.png"
    subprocess.check_call([
        CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--hide-scrollbars",
        "--force-device-scale-factor=1", f"--window-size={w},{h + 200}",
        "--virtual-time-budget=4000", f"--screenshot={out}", f"file://{SRC / (name + '.html')}",
    ], stderr=subprocess.DEVNULL)
    Image.open(out).crop((0, 0, w, h)).save(out)
    return out


if __name__ == "__main__":
    # fonts.css lives in src/, assets referenced relative to ROOT -> symlink-free via ../
    pages = [
        (ad1_post, POST), (ad1_story, STORY),
        (ad2_post, POST), (ad2_story, STORY),
        (ad3_post, POST), (ad3_story, STORY),
    ]
    for fn, size in pages:
        name = fn()
        print("rendered", render(name, size))
