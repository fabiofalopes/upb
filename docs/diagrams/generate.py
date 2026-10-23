#!/usr/bin/env python3
"""Generate the upb registry / routing diagrams as Excalidraw JSON.

Run:  python3 docs/diagrams/generate.py
Writes one .excalidraw file per diagram into docs/diagrams/.

The .excalidraw files are hand-drawn-style and editable at excalidraw.com.
The same diagrams exist as mermaid inside the markdown docs, so they render
in Obsidian and GitHub without any tooling.
"""

import json
from pathlib import Path

OUT = Path(__file__).resolve().parent

# Palette (see the excalidraw skill's references/colors.md)
BLUE = "#a5d8ff"
GREEN = "#b2f2bb"
ORANGE = "#ffd8a8"
PURPLE = "#d0bfff"
RED = "#ffc9c9"
YELLOW = "#fff3bf"
TEAL = "#c3fae8"
PINK = "#eebefa"
ZONE_BLUE = "#dbe4ff"
ZONE_PURPLE = "#e5dbff"
ZONE_GREEN = "#d3f9d8"

INK = "#1e1e1e"
MUTED = "#757575"
STROKE_BLUE = "#4a9eed"
STROKE_RED = "#ef4444"
STROKE_GREEN = "#22c55e"
STROKE_PURPLE = "#8b5cf6"
STROKE_AMBER = "#f59e0b"
STROKE_CYAN = "#06b6d4"


_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial.ttf"
_font_cache = {}


def _measure(s, size):
    """Measured text width in px. PIL if available, else a close estimate."""
    try:
        from PIL import ImageFont
        key = int(size * 4)
        font = _font_cache.get(key)
        if font is None:
            try:
                font = ImageFont.truetype(_FONT_PATH, int(size))
            except Exception:
                font = ImageFont.load_default()
            _font_cache[key] = font
        return font.getlength(s)
    except Exception:
        return len(s) * size * 0.52


def _fit(s, max_w, size):
    """Largest size <= `size` at which `s` fits `max_w`."""
    out = size
    while out > 11 and _measure(s, out) > max_w:
        out -= 1
    return out


class Canvas:
    def __init__(self):
        self.elements = []
        self.n = 0

    def _id(self, stem):
        self.n += 1
        return f"{stem}_{self.n}"

    def zone(self, x, y, w, h, fill, label=None, stroke="#d0d0d0"):
        """A background layer band."""
        eid = self._id("zone")
        self.elements.append({
            "type": "rectangle", "id": eid, "x": x, "y": y, "width": w, "height": h,
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid",
            "roughness": 1, "strokeWidth": 1, "opacity": 100,
            "roundness": {"type": 3},
        })
        if label:
            self.elements.append({
                "type": "text", "id": self._id("zt"), "x": x + 14, "y": y + 10,
                "width": 300, "height": 24, "text": label, "fontSize": 16,
                "fontFamily": 1, "strokeColor": MUTED, "originalText": label,
                "autoResize": True,
            })
        return eid

    def shape(self, x, y, w, h, fill, lines, size=18, stroke=INK, radius=True):
        """A shape with bound (container) text. `lines` is a str or list.

        The text is shrunk to fit the box if it would overflow — measured, not
        guessed, so a long label degrades to a smaller font instead of
        spilling over the border.
        """
        eid = self._id("shape")
        body = lines if isinstance(lines, str) else "\n".join(lines)
        nlines = body.count("\n") + 1
        max_w = w - 16
        for ln in body.split("\n"):
            size = min(size, _fit(ln, max_w, size))
        # shrink further if the block is taller than the box
        while size > 11 and nlines * size * 1.25 > h - 8:
            size -= 1
        self.elements.append({
            "type": "rectangle", "id": eid, "x": x, "y": y, "width": w, "height": h,
            "strokeColor": stroke, "backgroundColor": fill, "fillStyle": "solid",
            "roughness": 1, "strokeWidth": 2, "opacity": 100,
            "roundness": {"type": 3} if radius else None,
            "boundElements": [{"id": eid + "_t", "type": "text"}],
        })
        self.elements.append({
            "type": "text", "id": eid + "_t", "x": x + 6, "y": y + 8,
            "width": w - 12, "height": h - 16, "text": body,
            "fontSize": size, "fontFamily": 1, "strokeColor": INK,
            "textAlign": "center", "verticalAlign": "middle",
            "containerId": eid, "originalText": body, "autoResize": True,
        })
        return eid

    def note(self, x, y, w, h, lines, fill=YELLOW, size=16, stroke=INK):
        """A free-standing note with a bound label."""
        return self.shape(x, y, w, h, fill, lines, size=size, stroke=stroke)

    def text(self, x, y, s, size=18, color=INK, align="left"):
        """Standalone text. x is the LEFT edge."""
        self.elements.append({
            "type": "text", "id": self._id("txt"), "x": x, "y": y,
            "width": max(60, len(s) * size * 0.55), "height": size * 1.3,
            "text": s, "fontSize": size, "fontFamily": 1, "strokeColor": color,
            "originalText": s, "autoResize": True, "textAlign": align,
        })

    def title(self, x, y, s, size=26):
        self.text(x, y, s, size=size, color=INK)

    def arrow(self, x1, y1, x2, y2, label=None, color=STROKE_BLUE, dashed=False,
              size=16, label_dx=None, label_dy=None):
        """An arrow between two points, with an optional bound label."""
        aid = self._id("arw")
        dx, dy = x2 - x1, y2 - y1
        el = {
            "type": "arrow", "id": aid, "x": x1, "y": y1,
            "width": abs(dx), "height": abs(dy),
            "points": [[0, 0], [dx, dy]],
            "strokeColor": color, "strokeWidth": 2, "roughness": 1,
            "endArrowhead": "arrow", "fillStyle": "solid",
        }
        if dashed:
            el["strokeStyle"] = "dashed"
        if label:
            el["boundElements"] = [{"id": aid + "_t", "type": "text"}]
            self.elements.append(el)
            cx = x1 + dx / 2
            cy = y1 + dy / 2
            lw = len(label) * size * 0.55
            lx = cx - lw / 2 + (label_dx or 0)
            ly = cy - size * 1.6 + (label_dy or 0)
            self.elements.append({
                "type": "text", "id": aid + "_t", "x": lx, "y": ly,
                "width": lw, "height": size * 1.3, "text": label,
                "fontSize": size, "fontFamily": 1, "strokeColor": color,
                "textAlign": "center", "verticalAlign": "middle",
                "containerId": aid, "originalText": label, "autoResize": True,
                "backgroundColor": "#ffffff",
            })
            return aid
        self.elements.append(el)
        return aid

    def save(self, name, bg="#ffffff"):
        path = OUT / name
        data = {
            "type": "excalidraw", "version": 2, "source": "hermes-agent",
            "elements": self.elements,
            "appState": {"viewBackgroundColor": bg},
            "files": {},
        }
        path.write_text(json.dumps(data, indent=1))
        return path


# ── 1. the three-layer registry ─────────────────────────────────────────

def registry_layers():
    c = Canvas()
    c.title(60, 36, "Canonical registry — three layers, so a rename touches one")

    x, w = 330, 760
    bands = [
        (120, "Intent — capability contracts", YELLOW,
         "primary.coding   primary.reasoning   cheap.scratch   vision",
         "asks for a CAPABILITY, never a model id"),
        (300, "Identity — canonical model", TEAL,
         "deepseek/deepseek-v4-pro   zhipuai/glm-5.2   minimax/MiniMax-M3",
         "provider-agnostic; survives renames. 85% of models.dev entries carry one"),
        (480, "Served at — provider binding", BLUE,
         "ollama-cloud/deepseek-v4-pro:0813   alibaba/glm-5.2   zai/glm-5.3",
         "THE CHURNY LAYER — status lives here: active / backup / deprecated"),
        (660, "Endpoint — provider", ORANGE,
         "ollama-cloud   alibaba   zai   mistral   zen   litellm   LM Studio",
         "keys, billing, trust zone. Key slots, never key values"),
    ]
    for y, label, fill, chips, note in bands:
        c.zone(x, y, w, 110, fill, label)
        c.text(x + 20, y + 46, chips, size=17)
        c.text(x + 20, y + 74, note, size=14, color=MUTED)

    for y in (230, 410, 590):
        c.arrow(710, y, 710, y + 66, color=STROKE_BLUE)

    c.text(60, 150, "1  INTENT", size=16, color=MUTED)
    c.text(60, 330, "2  IDENTITY", size=16, color=MUTED)
    c.text(60, 510, "3  BINDING", size=16, color=MUTED)
    c.text(60, 690, "4  ENDPOINT", size=16, color=MUTED)

    # the churn, confined to layer 3
    c.shape(1140, 470, 250, 130, RED,
            ["Provider renames it:", "deepseek-v4-pro", "→  deepseek-v4-pro:0813"],
            size=15, stroke=STROKE_RED)
    c.arrow(1140, 535, 1095, 535, color=STROKE_RED, dashed=True)
    c.text(1140, 610, "one line to fix", size=15, color=STROKE_RED)

    c.text(330, 810, "sources:  models.dev (facts)  ·  routes.yaml (declared)  ·  "
            "live /models (ground truth)", size=15, color=MUTED)
    c.text(330, 836, "manual decisions — status, slots, notes, key_slots — survive a rebuild",
           size=15, color=MUTED)
    return c.save("registry-three-layers.excalidraw")


# ── 2. the whole routing stack ──────────────────────────────────────────

def routing_stack():
    c = Canvas()
    c.title(60, 36, "Where everything sits — the router of routers")

    # ── three vertical zones ──
    c.zone(40, 100, 240, 460, ZONE_BLUE, "Harness (appliance)")
    c.zone(330, 100, 300, 460, ZONE_PURPLE, "upb — the spine")
    c.zone(680, 100, 300, 460, ZONE_GREEN, "Providers")

    # harnesses
    for i, (n, sub) in enumerate([("Claude Code", "Anthropic dialect"),
                                   ("OpenCode", "OpenAI dialect"),
                                   ("Hermes", "OpenAI dialect"),
                                   ("Pi / others", "whatever ships next")]):
        c.shape(60, 150 + i * 105, 200, 75, BLUE, [n, sub], size=16)

    # the spine
    c.shape(350, 150, 260, 120, PURPLE,
            ["upb router :8705", "translate · route · retry · log"], size=17)
    c.shape(350, 300, 260, 200, TEAL,
            ["REGISTRY", "", "models{}  identity", "bindings{} served at",
             "slots{}  intent"], size=15, stroke=STROKE_CYAN)

    # providers
    for i, (n, sub) in enumerate([("Subscription", "Claude Code · Codex · Gemini"),
                                   ("Metered API", "alibaba · zai · mistral"),
                                   ("Free tier", "zen · litellm"),
                                   ("Local", "LM Studio · Ollama · tailnet")]):
        c.shape(700, 150 + i * 105, 260, 75, GREEN, [n, sub], size=16)

    # ── harness bus → spine (no crossings) ──
    for i in range(4):
        c.arrow(262, 187 + i * 105, 300, 187 + i * 105, color=STROKE_BLUE)
    c.arrow(300, 187, 300, 502, color=STROKE_BLUE)
    c.arrow(300, 210, 350, 210, color=STROKE_BLUE)

    # ── spine bus → providers (no crossings) ──
    c.arrow(610, 210, 660, 210, color=STROKE_GREEN)
    c.arrow(660, 187, 660, 502, color=STROKE_GREEN)
    for i in range(4):
        c.arrow(660, 187 + i * 105, 700, 187 + i * 105, color=STROKE_GREEN)

    # ── models.dev feeds the registry, from directly below ──
    c.shape(360, 620, 260, 95, PINK,
            ["models.dev", "", "canonical ids · pricing · caps"], size=15)
    c.arrow(490, 620, 490, 500, color=STROKE_PURPLE, label="feeds", size=14,
            label_dx=-46, label_dy=-8)

    # ── observability and snapshots hang off the providers column ──
    c.shape(1050, 130, 300, 230, YELLOW,
            ["OBSERVABILITY", "", "ccusage — what you burned",
             "ClaudeBar / CodexBar", "  — what is LEFT", "",
             "LiteLLM — per-key spend"], size=15)
    c.arrow(962, 187, 1010, 187, color=STROKE_AMBER, dashed=True)
    c.arrow(1010, 187, 1010, 245, color=STROKE_AMBER, dashed=True)
    c.arrow(1010, 245, 1050, 245, color=STROKE_AMBER, dashed=True)

    c.shape(1050, 420, 300, 140, ORANGE,
            ["SNAPSHOTS", "", "upb snapshot — what was",
             "running at time T"], size=15)
    c.arrow(962, 502, 1010, 502, color=STROKE_AMBER, dashed=True)
    c.arrow(1010, 502, 1010, 490, color=STROKE_AMBER, dashed=True)
    c.arrow(1010, 490, 1050, 490, color=STROKE_AMBER, dashed=True)

    # ── footer ──
    c.text(40, 760, "One endpoint. One registry. Every harness points at the same spine; "
            "the provider becomes a config choice, not a rewrite.", size=17)
    c.text(40, 790, "Observability and snapshots read the providers' side; models.dev "
            "feeds the registry from below.", size=15, color=MUTED)
    return c.save("routing-stack.excalidraw")


# ── 3. slot resolution ─────────────────────────────────────────────────

def slot_resolution():
    c = Canvas()
    c.title(60, 36, "How a slot resolves — candidates, then filters, then a winner")

    # 1. the slot
    c.shape(420, 110, 620, 80, YELLOW,
            ["primary.coding", "intent slot — a capability, not a model id"], size=18)
    c.arrow(730, 190, 730, 240, color=STROKE_BLUE)

    # 2. candidates come from the slot's own tiers
    c.shape(300, 240, 860, 150, BLUE,
            ["CANDIDATES  —  the slot's own preference order", "",
             "prefer:   deepseek/deepseek-v4-pro · zhipuai/glm-5.2 · minimax/MiniMax-M3",
             "fallback: zhipuai/glm-5-turbo · moonshotai/kimi-k2.7-code"], size=16)
    c.arrow(730, 390, 730, 450, color=STROKE_BLUE)

    # 3. the filters — a funnel
    c.shape(300, 450, 860, 150, TEAL,
            ["FILTERS  —  a candidate must pass ALL of them", "",
             "1  capability contract     tools · context ≥ 100k · reasoning",
             "2  status                   not deprecated · provider routable",
             "3  price ceiling            input ≤ $3.00 / M  (output is separate)"],
            size=16, stroke=STROKE_CYAN)
    c.arrow(730, 600, 730, 650, color=STROKE_BLUE)

    # rejected branch
    c.shape(1200, 470, 300, 110, RED,
            ["rejected", "fails a filter", "— reported, not silent"], size=15,
            stroke=STROKE_RED)
    c.arrow(1160, 520, 1200, 520, color=STROKE_RED, dashed=True)

    # 4. the winner
    c.shape(300, 650, 520, 140, GREEN,
            ["WINNER  —  first survivor", "",
             "deepseek/deepseek-v4-pro", "the binding key — never a raw model id"], size=17)
    c.arrow(820, 720, 880, 720, color=STROKE_GREEN)

    # 5. the unresolved state
    c.shape(880, 650, 520, 140, RED,
            ["UNRESOLVED  —  and it says why", "",
             "no binding satisfies the slot", "requires: tools, ctx ≥ 100k"], size=16,
            stroke=STROKE_RED)
    c.text(880, 800, "reached only when no candidate survives every filter",
           size=15, color=MUTED)

    c.text(60, 880, "Every step is inspectable:  upb registry resolve primary.coding --json",
           size=17)
    c.text(60, 906, "reports the tier, the reference it matched, and every candidate it "
            "considered — and why the losers lost.", size=17, color=MUTED)
    return c.save("slot-resolution.excalidraw")


# ── 4. the observability split ─────────────────────────────────────────

def observability_split():
    c = Canvas()
    c.title(60, 36, "Two different questions — two different data sources")

    c.zone(60, 110, 660, 330, ZONE_BLUE, "API SPEND — dollars")
    c.shape(90, 160, 280, 120, BLUE,
            ["Proxy responses", "usage objects", "per token, per key"], size=16)
    c.shape(410, 160, 280, 120, BLUE,
            ["LiteLLM", "virtual keys · budgets", "per-key spend"], size=16)
    c.arrow(370, 220, 410, 220, color=STROKE_BLUE)
    c.shape(250, 320, 280, 90, GREEN, ["= a number"], size=17)

    c.zone(780, 110, 660, 330, ZONE_PURPLE, "SUBSCRIPTION QUOTA — what is LEFT")
    c.shape(810, 160, 280, 120, PURPLE,
            ["Provider rate-limit", "state (5h · weekly)", "NOT in responses"], size=16)
    c.shape(1130, 160, 280, 120, PURPLE,
            ["gpt-load", "parses Claude + Codex", "quota windows"], size=16)
    c.arrow(1090, 220, 1130, 220, color=STROKE_PURPLE)
    c.shape(970, 320, 280, 90, GREEN, ["= remaining %"], size=17)

    c.shape(60, 500, 620, 150, YELLOW,
            ["ccusage  ·  ClaudeBar  ·  CodexBar", "",
             "read LOCAL session JSONL (claude, codex, gemini, opencode)",
             "reconstructs what you burned — an estimate, not the truth"], size=16)
    c.arrow(800, 380, 500, 500, color=STROKE_AMBER, dashed=True,
            label="cross-check", size=14)

    c.shape(740, 500, 640, 150, ORANGE,
            ["Why both are needed", "",
             "no tool can see your Claude Max allowance from API payloads",
             "the remaining quota lives in Anthropic's / OpenAI's rate-limit state"], size=16)

    c.text(60, 700, "Rule of thumb: ccusage tells you how much you burned; "
            "ClaudeBar / CodexBar tell you how much is left.", size=17)
    return c.save("observability-split.excalidraw")


if __name__ == "__main__":
    for fn in (registry_layers, routing_stack, slot_resolution, observability_split):
        print("wrote", fn().name)
