#!/usr/bin/env python3
"""Render .excalidraw files to PNG/SVG so they can be eyeballed without a browser.

Usage:
  python3 docs/diagrams/render.py                    # all -> .png next to the source
  python3 docs/diagrams/render.py --svg              # also emit .svg
  python3 docs/diagrams/render.py file.excalidraw    # just one

Draws the subset of Excalidraw this repo uses: rectangles, ellipses, text and
straight/bent arrows with container-bound labels. Hand-drawn roughness is
approximated with a slight jitter on the stroke so the output still reads as
sketchy rather than clinical.
"""

import json
import math
import random
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Excalidraw's rough-line algorithm is complex; we approximate with a jittered
# polyline, which is visually close enough for review.
FONT = "Helvetica, Arial, sans-serif"


def esc(s):
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
             .replace('"', "&quot;"))


def jitter(p0, p1, rough=1.0, seed=0):
    """A slightly wobbly line from p0 to p1, as a list of points."""
    rnd = random.Random(seed)
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    dist = math.hypot(dx, dy)
    if dist < 1:
        return [p0, p1]
    steps = max(2, min(14, int(dist / 28)))
    nx, ny = -dy / dist, dx / dist  # normal
    pts = []
    for i in range(steps + 1):
        t = i / steps
        amp = 0.0 if i in (0, steps) else rough * 2.2
        off = rnd.uniform(-amp, amp)
        pts.append((p0[0] + dx * t + nx * off, p0[1] + dy * t + ny * off))
    return pts


def poly(pts):
    return " ".join(f"{x:.1f},{y:.1f}" for x, y in pts)


def render(path: Path, out_svg: bool = False) -> Path:
    data = json.loads(path.read_text())
    els = data.get("elements") or []
    bg = (data.get("appState") or {}).get("viewBackgroundColor", "#ffffff")

    xs, ys, xe, ye = [], [], [], []
    for e in els:
        w = e.get("width") or 0
        h = e.get("height") or 0
        if e.get("type") == "arrow":
            x = e.get("x", 0)
            y = e.get("y", 0)
            for pt in (e.get("points") or []):
                xs.append(x + pt[0])
                ys.append(y + pt[1])
        elif e.get("type") == "text":
            continue
        else:
            xs.append(e.get("x", 0))
            ys.append(e.get("y", 0))
            xe.append(e.get("x", 0) + w)
            ye.append(e.get("y", 0) + h)
    if not xs:
        xs, ys, xe, ye = [0], [0], [100], [100]
    pad = 40
    minx, miny = min(xs) - pad, min(ys) - pad
    maxx, maxy = max(xe + xs) + pad, max(ye + ys) + pad
    W, H = maxx - minx, maxy - miny

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W:.0f}" height="{H:.0f}" '
           f'viewBox="{minx:.0f} {miny:.0f} {W:.0f} {H:.0f}">',
           f'<rect x="{minx}" y="{miny}" width="{W}" height="{H}" fill="{bg}"/>',
           '<defs><marker id="arw" viewBox="0 0 10 10" refX="9" refY="5" '
           'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
           f'<path d="M 0 0 L 10 5 L 0 10 z" fill="context-stroke"/></marker></defs>']

    seed = 0
    for e in els:
        et = e.get("type")
        seed += 1
        if et == "rectangle":
            x, y = e.get("x", 0), e.get("y", 0)
            w, h = e.get("width", 0), e.get("height", 0)
            fill = e.get("backgroundColor", "transparent")
            stroke = e.get("strokeColor", "#1e1e1e")
            sw = e.get("strokeWidth", 2)
            op = (e.get("opacity", 100)) / 100
            rounded = e.get("roundness") is not None
            if rounded:
                r = 10
                out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
                           f'rx="{r}" ry="{r}" fill="{fill}" fill-opacity="{op:.2f}" '
                           f'stroke="{stroke}" stroke-width="{sw}"/>')
            else:
                out.append(f'<rect x="{x:.0f}" y="{y:.0f}" width="{w:.0f}" height="{h:.0f}" '
                           f'fill="{fill}" fill-opacity="{op:.2f}" '
                           f'stroke="{stroke}" stroke-width="{sw}"/>')
        elif et == "ellipse":
            cx = e.get("x", 0) + (e.get("width", 0) / 2)
            cy = e.get("y", 0) + (e.get("height", 0) / 2)
            out.append(f'<ellipse cx="{cx:.0f}" cy="{cy:.0f}" '
                       f'rx="{e.get("width",0)/2:.0f}" ry="{e.get("height",0)/2:.0f}" '
                       f'fill="{e.get("backgroundColor","transparent")}" '
                       f'stroke="{e.get("strokeColor","#1e1e1e")}" '
                       f'stroke-width="{e.get("strokeWidth",2)}"/>')
        elif et == "arrow":
            x, y = e.get("x", 0), e.get("y", 0)
            pts = [(x + p[0], y + p[1]) for p in (e.get("points") or [])]
            if len(pts) < 2:
                continue
            stroke = e.get("strokeColor", "#1e1e1e")
            dash = ' stroke-dasharray="8 6"' if e.get("strokeStyle") == "dashed" else ""
            out.append(f'<polyline points="{poly(jitter(pts[0], pts[-1], seed=seed))}" '
                       f'fill="none" stroke="{stroke}" stroke-width="2"{dash} '
                       f'marker-end="url(#arw)"/>')
        elif et == "text":
            s = e.get("text", "")
            size = e.get("fontSize", 18)
            color = e.get("strokeColor", "#1e1e1e")
            fam = FONT
            if e.get("fontFamily") == 1:
                # hand-drawn feel: slight per-line rotation
                pass
            lines = s.split("\n")
            tx, ty = e.get("x", 0), e.get("y", 0)
            cid = e.get("containerId")
            align = e.get("textAlign", "left")
            container = next((c for c in els if c.get("id") == cid), None)
            if container and align == "center":
                cx = container.get("x", 0) + container.get("width", 0) / 2
                cy = container.get("y", 0) + container.get("height", 0) / 2
                lh = size * 1.25
                ty = cy - (len(lines) - 1) * lh / 2 - size * 0.78
                for i, ln in enumerate(lines):
                    wpx = len(ln) * size * 0.52
                    out.append(f'<text x="{cx - wpx/2:.0f}" y="{ty + i*lh:.0f}" '
                               f'font-family="{fam}" font-size="{size}" fill="{color}" '
                               f'text-anchor="start">{esc(ln)}</text>')
            else:
                lh = size * 1.25
                for i, ln in enumerate(lines):
                    out.append(f'<text x="{tx:.0f}" y="{ty + size + i*lh:.0f}" '
                               f'font-family="{fam}" font-size="{size}" fill="{color}">'
                               f'{esc(ln)}</text>')
    out.append("</svg>")
    svg_path = path.with_suffix(".svg")
    svg_path.write_text("\n".join(out))
    return svg_path


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    want_svg = "--svg" in sys.argv
    files = ([Path(a) for a in args] if args
             else sorted(HERE.glob("*.excalidraw")))
    for f in files:
        svg = render(f, out_svg=want_svg)
        png = svg.with_suffix(".png")
        try:
            import subprocess
            subprocess.run(["rsvg-convert", "-w", "1600", "-f", "png",
                            "-o", str(png), str(svg)], check=True)
            print("rendered", png.name)
        except Exception as exc:
            print("png failed for", f.name, exc, "(svg written:", svg.name, ")")


if __name__ == "__main__":
    main()
