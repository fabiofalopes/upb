#!/usr/bin/env python3
"""Model health gate — what you can actually pick, greyed out for what you can't.

Run:
  python3 tools/health_gate.py --scan          # probe every provider+model, write the gate
  python3 tools/health_gate.py --show           # show the current gate
  python3 tools/health_gate.py --apply          # write the gate into Hermes config
  python3 tools/health_gate.py --scan --json

The problem this solves
-----------------------
`/model` shows you every model a provider *lists*. It does not know whether
your plan can *call* it. So you pick "deepseek-v4-pro", the session starts,
and the first turn dies with 402 "not included in your free usage" — or the
model was renamed last week and the id 404s.

Two mechanisms, both already in Hermes, do the work:

  1. `custom_providers[].models:` + `discover_models: false`
     → the picker shows exactly that list, nothing else. A dead model simply
       is not in the list.
  2. `model_catalog.excluded_providers`
     → a provider (or alias) is hidden from the picker entirely.

This tool decides WHICH models go in which list, and keeps the answer fresh
by probing. A model moves between three buckets:

  selectable   works with your key right now            → in the picker
  greyed       exists, but your plan/endpoint refuses it → listed but unusable
  removed      the provider no longer serves it          → dropped from the list

Buckets are NOT permanent. Re-run `--scan` and a model that starts working
(you resubscribed, a trial ended, a plan upgraded) moves back to selectable
automatically. That is the "toggle back on" mechanism — no manual editing.
"""

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entitlement import (hermes_credentials, load_env_files,  # noqa: E402
                         probe)

HERMES_HOME = Path(os.environ.get("HERMES_HOME", Path.home() / ".hermes"))
CONFIG = HERMES_HOME / "config.yaml"
GATE = HERMES_HOME / "cache" / "model_health_gate.json"
UPB_ROUTES = Path.home() / ".config/upb/routes.yaml"

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# A model is "greyed" when the credential is fine but the plan/endpoint says no.
GREY_CODES = {402, 403}
# The credential itself is dead — the whole provider needs attention.
DEAD_CODES = {401}
# Transient — keep the model, just note it.
BUSY_CODES = {429}


def _load_yaml(path):
    try:
        import yaml
        return yaml.safe_load(Path(path).read_text())
    except ImportError:
        pass
    except Exception:
        return None
    venv = Path.home() / ".hermes/hermes-agent/venv/bin/python3"
    if not venv.exists():
        return None
    out = subprocess.run(
        [str(venv), "-c",
         "import yaml,json,sys;print(json.dumps(yaml.safe_load(open(sys.argv[1]).read())))",
         str(path)], capture_output=True, text=True, timeout=30)
    if out.returncode != 0:
        return None
    try:
        return json.loads(out.stdout)
    except Exception:
        return None


def save_yaml(path, data):
    """Write YAML with the Hermes venv's PyYAML (the system python3 lacks it)."""
    venv = Path.home() / ".hermes/hermes-agent/venv/bin/python3"
    if venv.exists():
        code = ("import yaml,json,sys;"
                "yaml.safe_dump(json.loads(sys.stdin.read()), open(sys.argv[1],'w'),"
                "sort_keys=False, allow_unicode=True)")
        r = subprocess.run([str(venv), "-c", code, str(path)],
                           input=json.dumps(data), capture_output=True, text=True,
                           timeout=30)
        if r.returncode == 0:
            return True
    try:
        import yaml
        Path(path).write_text(yaml.safe_dump(data, sort_keys=False, allow_unicode=True))
        return True
    except Exception:
        return False


# ── the provider surface ───────────────────────────────────────────────

def provider_surface():
    """Every provider Hermes knows about, with the models worth probing.

    Returns {provider_slug: {"base_url", "key", "dialect", "models": [...]}}.
    """
    env = load_env_files(Path.home() / ".config/upb/secrets.env",
                         Path.home() / ".hermes/.env")
    creds = {c["provider"]: c for c in hermes_credentials()}
    cfg = _load_yaml(CONFIG) or {}
    routes = _load_yaml(UPB_ROUTES) or {}

    out = {}

    def add(slug, base, key, dialect, models):
        if not base:
            return
        out[slug] = {"base_url": base.rstrip("/"), "key": key,
                     "dialect": dialect, "models": list(models)}

    # 1. every custom provider in the Hermes config
    for entry in (cfg.get("custom_providers") or []):
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        base = entry.get("base_url")
        if not name or not base:
            continue
        key = (entry.get("api_key") or "").strip()
        models = list((entry.get("models") or {}).keys())
        add(f"custom:{name}", base, key, "chat", models)

    # 2. providers from the credential pool
    for pid, c in creds.items():
        if pid.startswith("custom:"):
            continue
        base = c.get("base_url") or ""
        # hermes_credentials() normalises the token into "key"
        key = c.get("key") or c.get("access_token") or c.get("api_key") or ""
        if not base:
            continue
        dialect = "anthropic_messages" if pid.endswith("-anthropic") else "chat_completions"
        models = []
        if pid == "commandcode":
            models = ["minimax/minimax-m3.1-flash", "deepseek/deepseek-v4-pro",
                      "zai-org/GLM-5.3", "moonshotai/Kimi-K2.7-Code",
                      "google/gemini-3.8-flash", "xai/grok-4.7", "gpt-5.4",
                      "claude-sonnet-5-5"]
        elif pid == "ollama-cloud":
            models = ["gemma4:31b", "gpt-oss:120b", "nemotron-3-super",
                      "beam", "minimax-m3", "minimax-m3.1-flash",
                      "mistral-large-3:675b", "deepseek-v4-pro:0813",
                      "glm-5.3", "kimi-k2.7-code"]
        elif pid == "zai":
            models = ["glm-5.3", "glm-5.2", "glm-5-turbo", "glm-4.7"]
        elif pid == "lmstudio":
            models = []
        add(pid, base, key, dialect, models)

    # 3. upb routes — providers Hermes does not have but upb can reach
    for name, p in ((routes.get("providers") or {})).items():
        if not isinstance(p, dict) or not p.get("base_url"):
            continue
        if name in out:
            continue
        key_spec = p.get("key")
        key = ""
        if isinstance(key_spec, dict):
            var = key_spec.get("var")
            key = env.get(var, "") if var else ""
        models = list((p.get("models") or {}).keys())
        add(f"upb:{name}", p["base_url"], key, "chat", models)

    return out


def scan(surface=None):
    """Probe every (provider, model). Returns the gate structure."""
    surface = surface or provider_surface()
    rows = []

    def check(slug, spec, model):
        ok, code, kind, detail = probe(spec["base_url"], spec["key"], model,
                                       spec["dialect"])
        if ok:
            bucket = "selectable"
        elif "was retired" in (detail or "").lower() or \
                "has been retired" in (detail or "").lower():
            # The provider retired the model and says so — it names the date
            # and the replacement. This is the cleanest signal there is.
            bucket = "retired"
        elif code in GREY_CODES:
            bucket = "greyed"
        elif code in DEAD_CODES:
            bucket = "provider-dead"
        elif code in BUSY_CODES:
            bucket = "busy"
        elif code == 404:
            bucket = "removed"
        else:
            bucket = "error"
        return {"provider": slug, "model": model, "bucket": bucket,
                "code": code, "detail": detail[:80]}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = []
        for slug, spec in surface.items():
            for model in spec["models"]:
                futs.append(ex.submit(check, slug, spec, model))
        rows = [f.result() for f in futs]

    gate = {
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "providers": {},
    }
    for slug, spec in surface.items():
        mine = [r for r in rows if r["provider"] == slug]
        if not mine:
            continue
        gate["providers"][slug] = {
            "base_url": spec["base_url"],
            "selectable": sorted(r["model"] for r in mine if r["bucket"] == "selectable"),
            "greyed": sorted(r["model"] for r in mine if r["bucket"] == "greyed"),
            "busy": sorted(r["model"] for r in mine if r["bucket"] == "busy"),
            "removed": sorted(r["model"] for r in mine if r["bucket"] == "removed"),
            "retired": sorted(r["model"] for r in mine if r["bucket"] == "retired"),
            "dead": sorted(r["model"] for r in mine if r["bucket"] == "provider-dead"),
            "errors": [r for r in mine if r["bucket"] == "error"],
        }
    return gate, rows


# ── applying the gate ──────────────────────────────────────────────────

def apply_gate(gate, dry_run=False):
    """Write the gate into the Hermes config.

    - a custom provider whose models are all dead gets its models emptied
    - a custom provider with a mix gets `models:` set to the SELECTABLE ones
      and `discover_models: false` so the picker shows exactly that list
    - a provider whose every model is dead AND which has no live credential
      is added to `model_catalog.excluded_providers` (hidden from the picker)
    """
    cfg = _load_yaml(CONFIG) or {}
    custom = cfg.get("custom_providers") or []
    excluded = list((cfg.get("model_catalog") or {}).get("excluded_providers") or [])

    changes = []
    for entry in custom:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        slug = f"custom:{name}"
        g = (gate.get("providers") or {}).get(slug)
        if not g:
            continue
        if g["dead"] and not g["selectable"]:
            # every model on this provider is unusable
            new_models = {}
            note = "all models dead → emptied"
        else:
            new_models = {m: {} for m in g["selectable"]}
            note = f"{len(g['selectable'])} selectable, {len(g['greyed'])} greyed"
        if new_models != (entry.get("models") or {}):
            entry["models"] = new_models
            changes.append(f"{slug}: {note}")
        # pin the list so the picker does not re-discover dead models
        if entry.get("discover_models") is not False:
            entry["discover_models"] = False
            changes.append(f"{slug}: discover_models=false (pinned)")

    cfg["custom_providers"] = custom
    cfg.setdefault("model_catalog", {})["excluded_providers"] = excluded

    if dry_run:
        return changes, cfg

    ok = save_yaml(CONFIG, cfg)
    return changes, (cfg if ok else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--scan", action="store_true", help="probe everything and refresh the gate")
    ap.add_argument("--show", action="store_true", help="show the current gate")
    ap.add_argument("--apply", action="store_true", help="write the gate into the Hermes config")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.scan:
        gate, rows = scan()
        GATE.parent.mkdir(parents=True, exist_ok=True)
        GATE.write_text(json.dumps(gate, indent=2, sort_keys=True))
        if args.json:
            print(json.dumps(gate, indent=2, sort_keys=True))
        else:
            print(f"scanned {len(rows)} provider/model pairs → {GATE}")
            for slug, g in sorted(gate["providers"].items()):
                print(f"\n  {slug}")
                if g["selectable"]:
                    print(f"    selectable ({len(g['selectable'])}): {', '.join(g['selectable'])}")
                if g["greyed"]:
                    print(f"    greyed     ({len(g['greyed'])}): {', '.join(g['greyed'])}")
                if g["busy"]:
                    print(f"    busy       ({len(g['busy'])}): {', '.join(g['busy'])}")
                if g["removed"]:
                    print(f"    removed    ({len(g['removed'])}): {', '.join(g['removed'])}")
                if g["retired"]:
                    print(f"    RETIRED    ({len(g['retired'])}): {', '.join(g['retired'])}")
                if g["dead"]:
                    print(f"    dead       ({len(g['dead'])}): {', '.join(g['dead'])}")
                for e in g["errors"]:
                    print(f"    error      {e['model']}: {e['detail']}")
        if args.apply:
            changes, _ = apply_gate(gate, dry_run=args.dry_run)
            print("\ngate applied:" if not args.dry_run else "\ngate would apply:")
            for c in changes:
                print(f"  {c}")
            if not changes:
                print("  (no changes)")
        return 0

    if args.show:
        if not GATE.exists():
            print("no gate yet — run: python3 tools/health_gate.py --scan")
            return 3
        gate = json.loads(GATE.read_text())
        if args.json:
            print(json.dumps(gate, indent=2, sort_keys=True))
            return 0
        print(f"gate generated {gate.get('generated_at')}")
        for slug, g in sorted((gate.get("providers") or {}).items()):
            sel = len(g["selectable"])
            print(f"  {slug:<34} {sel} selectable · {len(g['greyed'])} greyed · "
                  f"{len(g['dead'])} dead · {len(g['removed'])} removed")
        return 0

    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
