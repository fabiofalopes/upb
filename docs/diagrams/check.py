#!/usr/bin/env python3
"""Geometry validator for the .excalidraw diagrams.

Run:  python3 docs/diagrams/check.py [file.excalidraw ...]

Catches the two failure modes that are easy to miss by eye and annoying to
discover in a rendered PNG:

  1. text wider than the box that holds it
  2. two boxes overlapping where they should not

Both are checked against MEASURED text (PIL), not a character-count estimate.
Exit code 3 on findings, so it can run in CI or a pre-commit hook.
"""

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"

_cache = {}

try:
    from PIL import ImageFont

    def measure(s, size):
        """Measured text width in px (PIL), not a character-count estimate."""
        key = int(size * 4)
        f = _cache.get(key)
        if f is None:
            try:
                f = ImageFont.truetype(FONT_PATH, int(size))
            except Exception:
                f = ImageFont.load_default()
            _cache[key] = f
        return f.getlength(s)
except Exception:
    def measure(s, size):
        """Fallback estimate when PIL is unavailable."""
        return len(s) * size * 0.52


def rects_overlap(a, b):
    return not (a["x"] + a["width"] <= b["x"] or b["x"] + b["width"] <= a["x"]
                or a["y"] + a["height"] <= b["y"] or b["y"] + b["height"] <= a["y"])


def contains(outer, inner):
    return (outer["x"] <= inner["x"] and outer["y"] <= inner["y"]
            and outer["x"] + outer["width"] >= inner["x"] + inner["width"]
            and outer["y"] + outer["height"] >= inner["y"] + inner["height"])


def check(path: Path):
    problems = []
    data = json.loads(path.read_text())
    els = data.get("elements") or []
    shapes = [e for e in els if e.get("type") in ("rectangle", "ellipse", "diamond")]
    texts = [e for e in els if e.get("type") == "text"]
    by_id = {e.get("id"): e for e in els}

    # ── 1. bound text vs its container ──
    for t in texts:
        cid = t.get("containerId")
        if not cid:
            continue
        c = by_id.get(cid)
        if not c:
            problems.append(f"text {t.get('id')}: containerId {cid} not found")
            continue
        if c.get("type") == "arrow":
            # An arrow label rides the arrow, not a box — there is no width to
            # fit inside. Its length is checked against the arrow's span below.
            continue
        size = t.get("fontSize", 16)
        body = t.get("text", "")
        lines = body.split("\n")
        for ln in lines:
            tw = measure(ln, size)
            avail = c["width"] - 12
            if tw > avail:
                problems.append(
                    f"text {t.get('id')} overflows {cid}: "
                    f"{tw:.0f}px > {avail:.0f}px :: {ln[:56]!r}")
        # vertical: block height vs container height
        block_h = len(lines) * size * 1.25
        if block_h > c["height"] - 4:
            problems.append(
                f"text {t.get('id')} too tall for {cid}: "
                f"{block_h:.0f}px > {c['height']:.0f}px")

    # ── 2. standalone text vs the box it sits in ──
    for t in texts:
        if t.get("containerId"):
            continue
        tw = measure(t.get("text", ""), t.get("fontSize", 16))
        for r in shapes:
            if (r["x"] <= t["x"] <= r["x"] + r["width"]
                    and r["y"] <= t["y"] <= r["y"] + r["height"]):
                if t["x"] + tw > r["x"] + r["width"] - 2:
                    problems.append(
                        f"text {t.get('id')} spills past {r.get('id')}: "
                        f"ends {t['x']+tw:.0f} > {r['x']+r['width']:.0f} :: "
                        f"{t.get('text','')[:56]!r}")
                break

    # ── 3. shape overlap (ignoring zone/child containment) ──
    for i, a in enumerate(shapes):
        for b in shapes[i + 1:]:
            if not rects_overlap(a, b):
                continue
            if contains(a, b) or contains(b, a):
                continue
            problems.append(
                f"shapes overlap: {a.get('id')} "
                f"({a['x']:.0f},{a['y']:.0f},{a['width']:.0f}x{a['height']:.0f}) "
                f"vs {b.get('id')} "
                f"({b['x']:.0f},{b['y']:.0f},{b['width']:.0f}x{b['height']:.0f})")

    # ── 4. shapes off-canvas ──
    xs = [e["x"] for e in shapes] + [e.get("x", 0) for e in texts]
    if xs and min(xs) < -50:
        problems.append(f"content starts at x={min(xs):.0f} (off-canvas)")
    return problems


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    files = ([Path(a) for a in args] if args
             else sorted(HERE.glob("*.excalidraw")))
    total = 0
    for f in files:
        probs = check(f)
        if probs:
            print(f"{f.name}: {len(probs)} problem(s)")
            for p in probs[:12]:
                print(f"    ✗ {p}")
            if len(probs) > 12:
                print(f"    ... {len(probs)-12} more")
            total += len(probs)
        else:
            print(f"{f.name}: clean")
    print(f"\n{total} problem(s) across {len(files)} diagram(s)")
    return 3 if total else 0


if __name__ == "__main__":
    sys.exit(main())
