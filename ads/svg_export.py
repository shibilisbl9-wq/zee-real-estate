#!/usr/bin/env python3
"""Export the ad HTML pages (src/*.html) to SVG.

Chromium lays each page out; a small script dumps every box, gradient, image and
line of text (with exact positions) as JSON; this script turns that into SVG.

  svg/<name>.svg           text converted to outlines  -> identical everywhere
  svg/editable/<name>.svg  live <text> with subset fonts embedded -> editable

Run after build.py:  python3 svg_export.py
"""
import base64
import html as htmlmod
import io
import json
import re
import subprocess
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.subset import Options, Subsetter
from fontTools.ttLib import TTFont

ROOT = Path(__file__).parent.resolve()
SRC, FONTS = ROOT / "src", ROOT / "fonts"
OUT, OUT_EDIT = ROOT / "svg", ROOT / "svg" / "editable"
CHROME = "/opt/pw-browsers/chromium-1194/chrome-linux/chrome"
NAMES = ["ad1_post", "ad1_story", "ad2_post", "ad2_story", "ad3_post", "ad3_story"]

# ---------------------------------------------------------------- measuring JS
EXTRACT_JS = r"""
<script>
document.fonts.ready.then(() => {
  const ops = [];
  const num = v => parseFloat(v) || 0;
  const rect = el => { const r = el.getBoundingClientRect(); return {x:r.left, y:r.top, w:r.width, h:r.height}; };
  function radii(cs, r){
    let v = ['borderTopLeftRadius','borderTopRightRadius','borderBottomRightRadius','borderBottomLeftRadius'].map(k => num(cs[k]));
    const f = Math.min(1,
      r.w / Math.max(1, v[0]+v[1]), r.h / Math.max(1, v[1]+v[2]),
      r.w / Math.max(1, v[2]+v[3]), r.h / Math.max(1, v[3]+v[0]));
    return v.map(x => x*f);
  }
  function textOps(node, el){
    const cs = getComputedStyle(el);
    const txt = node.nodeValue; if(!txt.trim()) return;
    const range = document.createRange();
    const lines = []; let cur = null;
    for(let i=0;i<txt.length;i++){
      range.setStart(node,i); range.setEnd(node,i+1);
      const rs = range.getClientRects(); if(!rs.length) continue;
      const r = rs[0];
      if(/\s/.test(txt[i]) && txt[i] !== '\u00a0' && r.width < 0.01) continue;
      if(!cur || Math.abs(r.top-cur.top) > num(cs.fontSize)*0.5){ cur = {s:'', x:r.left, top:r.top}; lines.push(cur); }
      cur.s += txt[i];
    }
    const clip = cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text';
    ops.push({t:'text', lines: lines.map(l => ({s:l.s.replace(/\s+$/,''), x:l.x, top:l.top})).filter(l => l.s.trim()),
      family: cs.fontFamily.split(',')[0].replace(/["']/g,'').trim(), weight: cs.fontWeight, style: cs.fontStyle,
      size: num(cs.fontSize), ls: cs.letterSpacing === 'normal' ? 0 : num(cs.letterSpacing),
      upper: cs.textTransform === 'uppercase', color: cs.color,
      grad: clip ? cs.backgroundImage : null, box: rect(el), shadow: cs.textShadow, feat: cs.fontFeatureSettings});
  }
  function walk(el){
    const cs = getComputedStyle(el);
    if(cs.display === 'none') return;
    const r = rect(el), rd = radii(cs, r);
    const clipText = cs.webkitBackgroundClip === 'text' || cs.backgroundClip === 'text';
    const isInline = cs.display === 'inline';
    if(el.tagName === 'IMG'){
      ops.push({t:'img', src: el.getAttribute('src'), box:r, fit: cs.objectFit, pos: cs.objectPosition, nw: el.naturalWidth, nh: el.naturalHeight});
      return;
    }
    if(el.tagName === 'SCRIPT' || el.tagName === 'STYLE' || el.tagName === 'LINK' || el.tagName === 'PRE') return;
    const rotated = cs.transform !== 'none';
    if(!isInline && !clipText){
      const bw = ['Top','Right','Bottom','Left'].map(s => ({w:num(cs['border'+s+'Width']), c:cs['border'+s+'Color'], st:cs['border'+s+'Style']}));
      ops.push({t:'box', box:r, rd, rotated, bgc: cs.backgroundColor, bgi: cs.backgroundImage, bw,
        shadow: cs.boxShadow, tag: el.tagName});
    }
    const clips = cs.overflow !== 'visible';
    if(clips) ops.push({t:'clip', box:r, rd});
    for(const n of el.childNodes){
      if(n.nodeType === 3) textOps(n, el);
      else if(n.nodeType === 1) walk(n);
    }
    if(clips) ops.push({t:'endclip'});
  }
  walk(document.body);
  const body = getComputedStyle(document.body);
  const pre = document.createElement('pre'); pre.id = '__out';
  pre.textContent = JSON.stringify({w: document.body.clientWidth, h: document.body.clientHeight, bg: body.backgroundColor, bgi: body.backgroundImage, ops});
  document.body.appendChild(pre);
});
</script>
"""


def measure(name):
    page = (SRC / f"{name}.html").read_text()
    tmp = SRC / f"__measure_{name}.html"
    tmp.write_text(page.replace("</body>", EXTRACT_JS + "</body>"))
    try:
        dom = subprocess.check_output(
            [CHROME, "--headless=new", "--no-sandbox", "--disable-gpu", "--force-device-scale-factor=1",
             "--window-size=1080,2200", "--virtual-time-budget=6000", "--dump-dom", f"file://{tmp}"],
            stderr=subprocess.DEVNULL).decode()
    finally:
        tmp.unlink(missing_ok=True)
    m = re.search(r'<pre id="__out">(.*?)</pre>', dom, re.S)
    return json.loads(htmlmod.unescape(m.group(1)))


# ---------------------------------------------------------------- fonts
_fonts = {}


def font_path(family, weight, style):
    fam = family.replace(" ", "")
    st = "italic" if style == "italic" else "normal"
    wanted = int(weight) if str(weight).isdigit() else (700 if weight == "bold" else 400)
    avail = sorted(int(re.search(r"-(\d+)\.ttf", p.name).group(1)) for p in FONTS.glob(f"{fam}-{st}-*.ttf"))
    w = min(avail, key=lambda a: abs(a - wanted))
    return FONTS / f"{fam}-{st}-{w}.ttf"


def load(path):
    if path not in _fonts:
        tt = TTFont(path)
        blob = hb.Blob.from_file_path(str(path))
        _fonts[path] = (tt, hb.Font(hb.Face(blob)), tt["head"].unitsPerEm)
    return _fonts[path]


def outline(text, path, size, ls, features):
    """Shape text and return (svg path data in px, advance width)."""
    tt, hbfont, upm = load(path)
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    feats = dict(features)
    if ls:
        feats["liga"] = False
    hb.shape(hbfont, buf, feats)
    gs = tt.getGlyphSet()
    order = tt.getGlyphOrder()
    s = size / upm
    pen = SVGPathPen(gs, ntos=lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
    x = 0.0
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        gname = order[info.codepoint]
        tp = TransformPen(pen, (s, 0, 0, -s, x + pos.x_offset * s, -pos.y_offset * s))
        gs[gname].draw(tp)
        x += pos.x_advance * s + ls
    return pen.getCommands(), x


def asc_px(path, size):
    tt, _, upm = load(path)
    return round(tt["hhea"].ascent * size / upm)


# ---------------------------------------------------------------- css helpers
def split_top(s, sep=","):
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == sep and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


def parse_color(c):
    m = re.match(r"rgba?\(([^)]+)\)", c.strip())
    if not m:
        return "#000000", 0.0
    p = [float(v) for v in re.split(r"[ ,/]+", m.group(1).strip()) if v]
    a = p[3] if len(p) > 3 else 1.0
    return "#%02x%02x%02x" % tuple(int(round(v)) for v in p[:3]), a


class Defs:
    def __init__(self):
        self.items, self.n = [], 0

    def add(self, s):
        self.items.append(s)

    def uid(self, p):
        self.n += 1
        return f"{p}{self.n}"


def gradient_layers(bgi):
    return [l for l in split_top(bgi) if "gradient(" in l]


def gradient_def(layer, box, defs):
    """CSS gradient string -> SVG paint url, in userSpaceOnUse on `box`."""
    kind, inner = re.match(r"([\w-]+)\((.*)\)$", layer, re.S).groups()
    args = split_top(inner)
    gid = defs.uid("g")
    x, y, w, h = box["x"], box["y"], box["w"], box["h"]
    if kind == "linear-gradient":
        import math
        ang = 180.0
        if re.match(r"-?[\d.]+deg", args[0]):
            ang = float(args[0][:-3])
            args = args[1:]
        t = math.radians(ang)
        L = abs(w * math.sin(t)) + abs(h * math.cos(t))
        dx, dy = math.sin(t), -math.cos(t)
        cx, cy = x + w / 2, y + h / 2
        head = (f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{cx - dx * L / 2:.2f}" '
                f'y1="{cy - dy * L / 2:.2f}" x2="{cx + dx * L / 2:.2f}" y2="{cy + dy * L / 2:.2f}">')
        tail = "</linearGradient>"
    else:  # radial: "<w>% <h>% at <x>% <y>%"
        m = re.match(r"([\d.]+)%\s+([\d.]+)%\s+at\s+([\d.]+)%\s+([\d.]+)%", args[0])
        rx, ry = float(m.group(1)) / 100 * w, float(m.group(2)) / 100 * h
        cx, cy = x + float(m.group(3)) / 100 * w, y + float(m.group(4)) / 100 * h
        args = args[1:]
        head = (f'<radialGradient id="{gid}" gradientUnits="userSpaceOnUse" cx="0" cy="0" r="1" '
                f'gradientTransform="translate({cx:.2f} {cy:.2f}) scale({rx:.2f} {ry:.2f})">')
        tail = "</radialGradient>"
    parsed = []
    for st in args:
        m = re.match(r"(rgba?\([^)]+\))\s*(?:([\d.]+)%)?", st)
        parsed.append([m.group(1), float(m.group(2)) if m.group(2) else None])
    n = len(parsed)
    for i, p in enumerate(parsed):  # CSS: unpositioned stops are spread evenly
        if p[1] is None:
            p[1] = 0.0 if i == 0 else 100.0 if i == n - 1 else i * 100.0 / (n - 1)
    stops = ""
    for color, pos in parsed:
        col, a = parse_color(color)
        stops += f'<stop offset="{pos / 100:.4f}" stop-color="{col}" stop-opacity="{a:.3f}"/>'
    defs.add(head + stops + tail)
    return f"url(#{gid})"


def rrect_path(x, y, w, h, r):
    tl, tr, br, bl = r
    return (f"M{x + tl:.2f} {y:.2f}H{x + w - tr:.2f}" + (f"A{tr:.2f} {tr:.2f} 0 0 1 {x + w:.2f} {y + tr:.2f}" if tr else "")
            + f"V{y + h - br:.2f}" + (f"A{br:.2f} {br:.2f} 0 0 1 {x + w - br:.2f} {y + h:.2f}" if br else "")
            + f"H{x + bl:.2f}" + (f"A{bl:.2f} {bl:.2f} 0 0 1 {x:.2f} {y + h - bl:.2f}" if bl else "")
            + f"V{y + tl:.2f}" + (f"A{tl:.2f} {tl:.2f} 0 0 1 {x + tl:.2f} {y:.2f}" if tl else "") + "Z")


def shadows(s):
    """computed box/text shadow string -> [(color, a, dx, dy, blur, spread)]"""
    if not s or s == "none":
        return []
    out = []
    for part in split_top(s):
        m = re.match(r"(rgba?\([^)]+\))\s+(-?[\d.]+)px\s+(-?[\d.]+)px(?:\s+(-?[\d.]+)px)?(?:\s+(-?[\d.]+)px)?", part)
        if not m:
            continue
        col, a = parse_color(m.group(1))
        out.append((col, a, float(m.group(2)), float(m.group(3)), float(m.group(4) or 0), float(m.group(5) or 0)))
    return out


# ---------------------------------------------------------------- SVG build
def build(name, data, editable):
    W, H = data["w"], data["h"]
    defs, body = Defs(), []
    used = {}  # font file -> set(chars) for subsetting
    blur_ids = {}

    def blur_filter(std):
        key = round(std, 2)
        if key not in blur_ids:
            fid = f"b{len(blur_ids)}"
            blur_ids[key] = fid
            defs.add(f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="-200" y="-200" width="{W + 400}" '
                     f'height="{H + 400}"><feGaussianBlur stdDeviation="{key}"/></filter>')
        return blur_ids[key]

    # page background
    body.append(f'<rect width="{W}" height="{H}" fill="#000"/>')
    for layer in reversed(gradient_layers(data["bgi"])):
        body.append(f'<rect width="{W}" height="{H}" fill="{gradient_def(layer, dict(x=0, y=0, w=W, h=H), defs)}"/>')

    clip_depth = 0
    for op in data["ops"]:
        t = op["t"]
        if t == "clip":
            b, cid = op["box"], defs.uid("c")
            defs.add(f'<clipPath id="{cid}"><path d="{rrect_path(b["x"], b["y"], b["w"], b["h"], op["rd"])}"/></clipPath>')
            body.append(f'<g clip-path="url(#{cid})">')
            clip_depth += 1
        elif t == "endclip":
            body.append("</g>")
            clip_depth -= 1
        elif t == "img":
            b = op["box"]
            data_uri = "data:image/jpeg;base64," + base64.b64encode((SRC / op["src"]).resolve().read_bytes()).decode()
            if op["fit"] == "cover":
                s = max(b["w"] / op["nw"], b["h"] / op["nh"])
                px, py = [float(v) / 100 for v in re.findall(r"([\d.]+)%", op["pos"])]
                iw, ih = op["nw"] * s, op["nh"] * s
                ix, iy = b["x"] + (b["w"] - iw) * px, b["y"] + (b["h"] - ih) * py
            else:
                ix, iy, iw, ih = b["x"], b["y"], b["w"], b["h"]
            body.append(f'<image x="{ix:.2f}" y="{iy:.2f}" width="{iw:.2f}" height="{ih:.2f}" '
                        f'preserveAspectRatio="none" href="{data_uri}"/>')
        elif t == "box":
            b, rd = op["box"], op["rd"]
            if op["rotated"]:  # the 45deg diamond: bbox is the rotated square
                cx, cy, hh = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2, b["w"] / 2
                fill = "#d9aa4a"
                if "gradient(" in op["bgi"]:
                    fill = gradient_def(gradient_layers(op["bgi"])[0], b, defs)
                body.append(f'<path d="M{cx:.2f} {cy - hh:.2f}L{cx + hh:.2f} {cy:.2f}L{cx:.2f} {cy + hh:.2f}L{cx - hh:.2f} {cy:.2f}Z" fill="{fill}"/>')
                continue
            d = rrect_path(b["x"], b["y"], b["w"], b["h"], rd)
            for col, a, dx, dy, blur, spread in shadows(op["shadow"]):
                if blur:
                    body.append(f'<path d="{d}" transform="translate({dx} {dy})" fill="{col}" fill-opacity="{a:.3f}" '
                                f'filter="url(#{blur_filter(blur / 2)})"/>')
                elif spread:
                    sd = rrect_path(b["x"] - spread, b["y"] - spread, b["w"] + 2 * spread, b["h"] + 2 * spread,
                                    [r + spread if r else 0 for r in rd])
                    body.append(f'<path d="{sd}" fill="{col}" fill-opacity="{a:.3f}"/>')
            col, a = parse_color(op["bgc"])
            if a > 0:
                body.append(f'<path d="{d}" fill="{col}" fill-opacity="{a:.3f}"/>')
            for layer in reversed(gradient_layers(op["bgi"])):
                body.append(f'<path d="{d}" fill="{gradient_def(layer, b, defs)}"/>')
            bw = op["bw"]
            if all(s["w"] > 0 and s["st"] != "none" for s in bw) and len({(s["w"], s["c"]) for s in bw}) == 1:
                bc, ba = parse_color(bw[0]["c"])
                sw = bw[0]["w"]
                inner = rrect_path(b["x"] + sw / 2, b["y"] + sw / 2, b["w"] - sw, b["h"] - sw,
                                   [max(0, r - sw / 2) for r in rd])
                body.append(f'<path d="{inner}" fill="none" stroke="{bc}" stroke-opacity="{ba:.3f}" stroke-width="{sw}"/>')
            else:
                for side, s in zip("trbl", bw):
                    if s["w"] > 0 and s["st"] != "none":
                        bc, ba = parse_color(s["c"])
                        r = {"t": (b["x"], b["y"], b["w"], s["w"]), "b": (b["x"], b["y"] + b["h"] - s["w"], b["w"], s["w"]),
                             "l": (b["x"], b["y"], s["w"], b["h"]), "r": (b["x"] + b["w"] - s["w"], b["y"], s["w"], b["h"])}[side]
                        body.append(f'<rect x="{r[0]:.2f}" y="{r[1]:.2f}" width="{r[2]:.2f}" height="{r[3]:.2f}" '
                                    f'fill="{bc}" fill-opacity="{ba:.3f}"/>')
        elif t == "text":
            fpath = font_path(op["family"], op["weight"], op["style"])
            feats = {"kern": True, "liga": True}
            if "lnum" in (op["feat"] or ""):
                feats["lnum"] = True
            if op["grad"] and "gradient(" in op["grad"]:
                fill, fop = gradient_def(gradient_layers(op["grad"])[0], op["box"], defs), 1.0
            else:
                fill, fop = parse_color(op["color"])
            shs = shadows(op["shadow"])
            asc = asc_px(fpath, op["size"])
            for ln in op["lines"]:
                s = ln["s"].upper() if op["upper"] else ln["s"]
                s = s.replace(" ", " ")
                base = ln["top"] + asc
                if editable:
                    used.setdefault(fpath, set()).update(s)
                    esc = htmlmod.escape(s)
                    attrs = (f'x="{ln["x"]:.2f}" y="{base:.2f}" font-family="{op["family"]}" font-size="{op["size"]}" '
                             f'font-weight="{fpath.stem.split("-")[-1]}" font-style="{"italic" if op["style"] == "italic" else "normal"}" '
                             f'letter-spacing="{op["ls"]:.3f}" xml:space="preserve" '
                             f'style="font-feature-settings:{htmlmod.escape(op["feat"], quote=True)}"')
                    mk = lambda extra="": f'<text {attrs} {extra}>{esc}</text>'
                else:
                    d, _ = outline(s, fpath, op["size"], op["ls"], feats)
                    mk = lambda extra="", d=d, x=ln["x"], y=base: f'<path transform="translate({x:.2f} {y:.2f})" d="{d}" {extra}/>'
                for col, a, dx, dy, blur, _ in shs:
                    body.append(_shadow_copy(mk, dx, dy, col, a, blur_filter(blur / 2), editable))
                body.append(mk(f'fill="{fill}"' + (f' fill-opacity="{fop:.3f}"' if fop < 1 else "")))
    assert clip_depth == 0

    style = ""
    if editable:
        faces = []
        for fpath, chars in used.items():
            tt = TTFont(fpath)
            opt = Options()
            opt.layout_features = ["*"]
            sub = Subsetter(opt)
            sub.populate(text="".join(sorted(chars)) + " ")
            sub.subset(tt)
            buf = io.BytesIO()
            tt.save(buf)
            fam = "Playfair Display" if "Playfair" in fpath.name else "Montserrat"
            wgt = fpath.stem.split("-")[-1]
            sty = "italic" if "italic" in fpath.name else "normal"
            faces.append(f"@font-face{{font-family:'{fam}';font-weight:{wgt};font-style:{sty};"
                         f"src:url(data:font/ttf;base64,{base64.b64encode(buf.getvalue()).decode()}) format('truetype')}}")
        style = "<style>" + "".join(faces) + "</style>"
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">'
            f"{style}<defs>{''.join(defs.items)}</defs>\n" + "\n".join(body) + "\n</svg>\n")


def _shadow_copy(mk, dx, dy, col, a, fid, editable):
    el = mk(f'fill="{col}" fill-opacity="{a:.3f}" filter="url(#{fid})"')
    return f'<g transform="translate({dx} {dy})">{el}</g>'


if __name__ == "__main__":
    OUT.mkdir(exist_ok=True)
    OUT_EDIT.mkdir(exist_ok=True)
    for n in NAMES:
        d = measure(n)
        (OUT / f"{n}.svg").write_text(build(n, d, editable=False))
        (OUT_EDIT / f"{n}.svg").write_text(build(n, d, editable=True))
        print("svg", n, (OUT / f"{n}.svg").stat().st_size // 1024, "KB /", (OUT_EDIT / f"{n}.svg").stat().st_size // 1024, "KB")
