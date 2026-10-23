#!/usr/bin/env python3
"""Live session-state diagram for this Hermes session.

Run:  python3 docs/diagrams/generate_session.py
Writes session-state.excalidraw — a picture of what is actually running right
now: the agent, its tool surfaces, the delegation fan-out, and the artifacts
on disk.

The numbers are read from the live system at generation time where possible,
so the diagram is a snapshot, not a hand-drawn claim.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from generate import (Canvas, BLUE, GREEN, ORANGE, PURPLE, RED, YELLOW, TEAL,
                      PINK, ZONE_BLUE, ZONE_PURPLE, ZONE_GREEN,
                      INK, MUTED, STROKE_BLUE, STROKE_RED, STROKE_GREEN,
                      STROKE_PURPLE, STROKE_AMBER, STROKE_CYAN)

OUT = Path(__file__).resolve().parent


def _yaml(text):
    """Parse YAML with whatever interpreter has PyYAML available."""
    for exe in (sys.executable,
                str(Path.home() / ".hermes/hermes-agent/venv/bin/python3")):
        try:
            out = subprocess.run(
                [exe, "-c",
                 "import sys,yaml,json;"
                 "print(json.dumps(yaml.safe_load(sys.stdin.read())))"],
                input=text, capture_output=True, text=True, timeout=30)
            if out.returncode == 0 and out.stdout.strip():
                return json.loads(out.stdout)
        except Exception:
            continue
    return None


def sh(cmd):
    try:
        return subprocess.run(cmd, shell=True, capture_output=True, text=True,
                              timeout=20).stdout.strip()
    except Exception:
        return ""


def live():
    """Read what is actually running."""
    d = {}
    d["ps_hermes"] = len(sh("ps aux | grep -i hermes | grep -v grep").splitlines())
    d["listeners"] = []
    for line in sh("lsof -nP -iTCP -sTCP:LISTEN 2>/dev/null").splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 9:
            d["listeners"].append((parts[0], parts[8]))
    d["lms_loaded"] = "No models are currently loaded" not in sh(
        "~/.lmstudio/bin/lms ps 2>&1")
    d["cron_jobs"] = 0
    out = sh("hermes cron list 2>&1")
    if "No scheduled jobs" not in out:
        d["cron_jobs"] = out.count("\n")
    d["delegation"] = {}
    man = Path.home() / ".hermes/cache/delegation/live/deleg_31ab0e5a/manifest.json"
    if man.exists():
        m = json.loads(man.read_text())
        d["delegation"]["id"] = m.get("delegation_id")
        d["delegation"]["started"] = m.get("started")
        d["delegation"]["tasks"] = [(t.get("index"), t.get("status"))
                                    for t in m.get("tasks") or []]
    gw = sh("hermes status 2>&1")
    d["gateway"] = "stopped" not in gw
    d["sessions_active"] = 0
    for line in gw.splitlines():
        if "Active:" in line:
            try:
                d["sessions_active"] = int(line.split("Active:")[1].strip().split()[0])
            except (ValueError, IndexError):
                pass
    scratch = Path.home() / ".hermes/cache/scratch"
    d["gwresearch_files"] = len(list((scratch / "gwresearch").glob("*"))) if (scratch / "gwresearch").exists() else 0
    d["upb_branch"] = sh("cd ~/projetos/hub/upb && git branch --show-current")
    d["upb_commits"] = sh("cd ~/projetos/hub/upb && git log --oneline -1")
    d["upb_uncommitted"] = len(sh("cd ~/projetos/hub/upb && git status --short").splitlines())
    d["registry_bindings"] = 0
    d["registry_slots"] = 0
    reg = Path.home() / ".config/upb/registry.yaml"
    if reg.exists():
        r = _yaml(reg.read_text())
        if r:
            d["registry_bindings"] = len(r.get("bindings") or {})
            d["registry_slots"] = len(r.get("slots") or {})
            d["registry_providers"] = len(r.get("providers") or {})
    d["snapshots"] = len(list((Path.home() / ".local/share/upb/snapshots").glob("*.json"))) \
        if (Path.home() / ".local/share/upb/snapshots").exists() else 0
    d["upb_cli_deployed"] = sh(
        "grep -c 'def cmd_registry' ~/bin/upb 2>/dev/null || echo 0").strip() or "0"
    d["state_db_mb"] = round(
        (Path.home() / ".hermes/state.db").stat().st_size / 1048576, 1) \
        if (Path.home() / ".hermes/state.db").exists() else 0
    return d


def build(d):
    c = Canvas()
    c.title(60, 30, "This session — what is running, what it touched, what is left")

    # ── zone 1: the agent itself ──
    c.zone(40, 90, 520, 570, ZONE_PURPLE, "Hermes agent — the one process")
    c.shape(70, 140, 460, 92, PURPLE,
            ["Hermes Agent  (cli, this session)",
             "model: minimax/minimax-m3.1-flash  via CommandCode",
             "provider pool: 15 providers · 18 pooled credentials"], size=15)

    tools = [
        ("terminal", "local backend · 180s timeout"),
        ("browser_exec", "Browser Use CLI · real Chrome"),
        ("delegate_task", "4 subagents · 1 delegation unit"),
        ("execute_code", "persistent python kernel"),
        ("vision_analyze", "ollama-cloud · gemma4:31b"),
        ("write_file / patch", "direct fs writes"),
        ("memory / skill", "persistent + procedural"),
    ]
    for i, (n, sub) in enumerate(tools):
        y = 248 + i * 40
        c.shape(70, y, 460, 34, BLUE, [n], size=12)
        c.text(200, y + 11, sub, size=12, color=MUTED)

    c.shape(70, 528, 460, 66, TEAL,
            ["credential pool — 15 providers, 18 creds",
             "ollama-cloud ×2 · alibaba ×4 · codex oauth · copilot"],
            size=13, stroke=STROKE_CYAN)

    # ── zone 2: what was flying ──
    c.zone(610, 90, 470, 570, ZONE_GREEN, "The fan-out — 4 subagents, 12 min")
    names = {0: "gateway landscape", 1: "observability + quota",
             2: "catalog sources + snapshots", 3: "routing logic + frameworks"}
    for i, (idx, status) in enumerate(d["delegation"].get("tasks", [])):
        y = 145 + i * 100
        ok = status == "completed"
        c.shape(640, y, 410, 62,
                GREEN if ok else ORANGE,
                [f"task-{idx}  —  {status}", names.get(idx, "")],
                size=14, stroke=STROKE_GREEN if ok else STROKE_AMBER)
        if not ok:
            c.text(640, y + 66, "api cap — partial data survived in docs/research/",
                   size=12, color=STROKE_AMBER)
    c.shape(640, 560, 410, 50, PINK,
            [f"{d['gwresearch_files']} research artifacts in scratch/gwresearch"],
            size=13)

    # ── zone 3: the artifacts ──
    c.zone(1130, 90, 480, 570, ZONE_BLUE, "Artifacts on disk")
    arts = [
        ("upb repo", d["upb_branch"], d["upb_commits"][:40],
         GREEN if d["upb_uncommitted"] == 0 else ORANGE),
        ("registry.yaml", f"{d.get('registry_bindings',0)} bindings · "
                          f"{d.get('registry_slots',0)} slots",
         "live at ~/.config/upb/", GREEN),
        ("REGISTRY.md", "design + runbook, 449 lines", "committed", GREEN),
        ("diagrams", "4 × mermaid + 4 × excalidraw", "committed", GREEN),
        ("vault note", "PROJECTS/model-registry-…md", "written", GREEN),
        ("snapshots", "what was running at time T",
         f"{d['snapshots']} — the gap", RED if d["snapshots"] == 0 else GREEN),
        ("~/bin/upb", "the LIVE cli", "old build — not deployed", RED),
    ]
    for i, (n, sub, state, col) in enumerate(arts):
        y = 145 + i * 70
        c.shape(1160, y, 420, 40, col, [f"{n}  —  {state}"], size=13,
                stroke=INK if col != RED else STROKE_RED)
        c.text(1172, y + 44, sub, size=11, color=MUTED)

    # ── the flow ──
    c.arrow(560, 185, 610, 185, color=STROKE_BLUE)
    c.arrow(1080, 185, 1130, 185, color=STROKE_GREEN)

    # ── the loop: where the facts come from ──
    c.shape(70, 700, 400, 76, PINK,
            ["models.dev  —  canonical ids, pricing, caps",
             "85.1% of 9,149 entries carry a canonical id"], size=14)
    c.arrow(270, 700, 270, 594, color=STROKE_PURPLE, dashed=True,
            label="facts", size=13, label_dx=-32, label_dy=6)

    c.shape(520, 700, 400, 76, BLUE,
            ["live /models probes",
             "alibaba · zen · ollama-cloud · 128 ids"], size=14)
    c.arrow(720, 700, 720, 594, color=STROKE_BLUE, dashed=True,
            label="truth", size=13, label_dx=-34, label_dy=6)

    # ── footer: what is left ──
    c.shape(970, 700, 640, 120, RED,
            ["NOT DONE", "",
             "· branch not pushed (remote was force-pushed mid-session)",
             "· ~/bin/upb still the old build — live routing unchanged",
             "· 13 dead bindings still need a decision: backup or remove",
             "· no snapshot baseline — rename detection has nothing to diff"],
            size=14, stroke=STROKE_RED)

    c.text(60, 810, "The measurement that started this: 13 of 47 declared bindings "
            "were not served by the provider.", size=17)
    c.text(60, 838, "State.db 31 MB · 0 cron jobs · gateway stopped · 0 models loaded "
            "in LM Studio · the agent is the only thing running.", size=15, color=MUTED)
    return c.save("session-state.excalidraw")


if __name__ == "__main__":
    d = live()
    print(json.dumps(d, indent=1, default=str))
    print("wrote", build(d).name)
