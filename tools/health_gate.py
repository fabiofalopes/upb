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
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entitlement import (_ssl_context, hermes_credentials,  # noqa: E402
                         load_env_files, probe)

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

def _load_yaml(path):
    """Parse a YAML file with whatever interpreter has PyYAML.

    The system python3 on macOS has no PyYAML; the Hermes venv does. This
    tool must run from a bare `python3 tools/health_gate.py`, so it falls back
    to the venv rather than failing with a bare ModuleNotFoundError.
    """
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


def _verify_flag(value):
    """ssl_verify may be a bool or the string forms Hermes accepts."""
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "no", "0", "")
    return True if value is None else bool(value)


def provider_surface():
    """Every provider Hermes knows about, with the models worth probing.

    Returns {provider_slug: {"base_url", "key", "dialect", "models": [...]}}.
    """
    env = load_env_files(Path.home() / ".config/upb/secrets.env",
                         Path.home() / ".hermes/.env")
    # Best credential per provider, not whichever the pool happened to list
    # last — a stale manual key must not shadow a live env key.
    from entitlement import credentials_for
    creds = {}
    for pid in {c["provider"] for c in hermes_credentials(env)}:
        best = credentials_for(pid, env)
        if best:
            creds[pid] = best[0]
    cfg = _load_yaml(CONFIG) or {}
    routes = _load_yaml(UPB_ROUTES) or {}

    out = {}

    def add(slug, base, key, dialect, models, ca_cert=None, verify=True):
        if not base:
            return
        out[slug] = {"base_url": base.rstrip("/"), "key": key,
                     "dialect": dialect, "models": list(models),
                     "ca_cert": ca_cert, "verify": verify}

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
        add(f"custom:{name}", base, key, "chat", models,
            ca_cert=entry.get("ssl_ca_cert"),
            verify=_verify_flag(entry.get("ssl_verify")))

    # 1b. the NEW-STYLE `providers:` block. Hermes converts these to the same
    # internal custom-provider shape, so the picker treats them identically —
    # which means the gate must too. A config that migrated from
    # `custom_providers:` to `providers:` must not silently stop being gated.
    #
    # The `providers:` block often carries NO api_key — the credential lives in
    # a `custom_providers:` entry or the credential pool for the same base_url.
    # Resolve it by base_url, or the probe 401s on a perfectly good provider.
    def _norm(u):
        """Compare base_urls ignoring a trailing /v1 — the same endpoint is
        spelled both ways across the two config blocks."""
        u = (u or "").rstrip("/").lower()
        if u.endswith("/v1"):
            u = u[:-3]
        return u

    def _key_for_base(base):
        want = _norm(base)
        for e in (cfg.get("custom_providers") or []):
            if not isinstance(e, dict):
                continue
            if _norm(e.get("base_url")) != want:
                continue
            k = (e.get("api_key") or "").strip()
            if k:
                return k
        for c in creds.values():
            if _norm(c.get("base_url")) == want and c.get("key"):
                return c["key"]
        return ""

    for slug, entry in (cfg.get("providers") or {}).items():
        if not isinstance(entry, dict):
            continue
        base = entry.get("api") or entry.get("base_url") or entry.get("url") or ""
        if not base:
            continue
        key = (entry.get("api_key") or "").strip() or _key_for_base(base)
        models = list((entry.get("models") or {}).keys())
        add(slug, base, key, "chat", models,
            ca_cert=entry.get("ssl_ca_cert"),
            verify=_verify_flag(entry.get("ssl_verify")))

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
                                       spec["dialect"],
                                       ca_cert=spec.get("ca_cert"),
                                       verify=spec.get("verify", True))
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


# ── discovery: what upstream serves that the config does not declare ───
#
# The gate could grey a model out but never say "the provider moved and here is
# its new name". That is why a catalogue rotation left an empty provider
# instead of a one-line suggestion: `discover_models: false` pins the picker to
# a list that was correct 13 days ago, and nothing compares that list to what
# the gateway now serves.
#
# Discovery answers the second half of the question. It fetches each provider's
# `GET /models`, diffs it against the declared list, and — only where something
# is actually broken — probes the candidates and proposes the ones that answer.

def _writable_slugs():
    """Provider slugs whose model list this tool can actually rewrite.

    Only a configured provider (`providers:` / `custom_providers:`) has a
    model list to write. A curated or pool-served provider gets its catalogue
    from Hermes itself, so proposing an edit there would be a lie.
    """
    cfg = _load_yaml(CONFIG) or {}
    slugs = set((cfg.get("providers") or {}).keys())
    for e in (cfg.get("custom_providers") or []):
        if isinstance(e, dict) and e.get("name"):
            slugs.add(f"custom:{e['name']}")
    return slugs


def fetch_catalogue(spec, timeout=25):
    """GET /models for one provider. Returns (ids, error).

    A provider that exposes no catalogue is not a fault to shout about — it is
    simply not discoverable this way, and the row says so.
    """
    url = spec["base_url"].rstrip("/") + "/models"
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {spec['key']}", "User-Agent": UA,
        "Accept": "application/json"})
    try:
        ctx = None
        if spec.get("ca_cert") or not spec.get("verify", True):
            ctx = _ssl_context(spec.get("ca_cert"), spec.get("verify", True))
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            body = json.loads(r.read())
    except urllib.error.HTTPError as e:
        return [], f"HTTP {e.code} on /models"
    except urllib.error.URLError as e:
        return [], f"transport: {e.reason}"
    except Exception as e:
        return [], f"{type(e).__name__}: {e}"
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return [], "no `data` array in /models"
    ids = [str(m["id"]) for m in data
           if isinstance(m, dict) and m.get("id")]
    return ids, None


def discover(surface=None, probe_new=True, max_probe=24):
    """Diff each provider's declared models against what it actually serves."""
    surface = surface or provider_surface()
    writable = _writable_slugs()
    rows = []

    for slug, spec in sorted(surface.items()):
        declared = list(spec["models"])
        row = {"provider": slug, "base_url": spec["base_url"],
               "declared": declared, "live": [], "new": [], "missing": [],
               "catalogue_error": None, "writable": slug in writable,
               "proposed": [], "not_usable": []}
        live, err = fetch_catalogue(spec)
        if err:
            row["catalogue_error"] = err
            rows.append(row)
            continue
        live_set, declared_set = set(live), set(declared)
        row["live"] = live
        row["new"] = [m for m in live if m not in declared_set]
        row["missing"] = [m for m in declared if m not in live_set]
        rows.append(row)

    if not probe_new:
        return rows

    # Probe the candidates ONLY where something we declare has disappeared from
    # the catalogue. A provider whose declared list is intact does not need a
    # proposal: "83 new models available" is noise, "your 14 are gone and these
    # 4 work" is a decision.
    for row in rows:
        if not row["new"] or not row["missing"]:
            continue
        spec = surface[row["provider"]]
        candidates = row["new"][:max_probe]

        def check(m):
            ok, code, kind, detail = probe(
                spec["base_url"], spec["key"], m, spec["dialect"],
                ca_cert=spec.get("ca_cert"), verify=spec.get("verify", True))
            return {"model": m, "ok": ok, "code": code, "kind": kind,
                    "detail": (detail or "")[:80]}

        with ThreadPoolExecutor(max_workers=8) as ex:
            results = list(ex.map(check, candidates))
        row["proposed"] = [r for r in results if r["ok"]]
        row["not_usable"] = [r for r in results if not r["ok"]]
    return rows


def _entry_for(cfg, slug):
    """The config entry a slug writes to, or None."""
    if slug.startswith("custom:"):
        for e in (cfg.get("custom_providers") or []):
            if isinstance(e, dict) and e.get("name") == slug[7:]:
                return e
        return None
    e = (cfg.get("providers") or {}).get(slug)
    return e if isinstance(e, dict) else None


def adopt_discovery(rows, dry_run=False):
    """Append the proposed models to their provider's entry.

    Also repoints `default_model` when the configured one is among the models
    the provider no longer serves — otherwise adopting the new catalogue still
    leaves the provider selecting a dead default.
    """
    cfg = _load_yaml(CONFIG) or {}
    changes = []

    for row in rows:
        if not row.get("writable"):
            continue
        proposed = [p["model"] for p in (row.get("proposed") or [])]
        served = set(row["live"])
        declared = set(row["declared"])
        unusable = {r["model"] for r in (row.get("not_usable") or [])}
        # a replacement we can actually stand behind: probed OK, else one the
        # provider still serves that we already declare and have not seen fail
        replacement = proposed[0] if proposed else next(
            (m for m in row["live"]
             if m in declared and m not in unusable), None)

        entry = _entry_for(cfg, row["provider"])
        if entry is None:
            if proposed:
                changes.append(f"{row['provider']}: configured but not found — skipped")
            continue

        models = entry.get("models") or {}
        added = [m for m in proposed if m not in models]
        if added:
            for m in added:
                models[m] = {}
            entry["models"] = models
            changes.append(f"{row['provider']}: +{len(added)} model(s) → "
                           f"{', '.join(added)}")

        # Repoint the selected model when the provider no longer serves it. The
        # two config blocks name the field differently: `custom_providers:`
        # uses `model`, `providers:` uses `default_model`.
        #
        # The test is against the LIVE catalogue, not `missing`. A selected
        # model can name something that was never in the declared list at all
        # (the Lusofona entry pointed at qwopus3.5-9b-coder while declaring 14
        # other ids), so a declared-vs-served diff cannot see it.
        #
        # Guarded on a non-empty catalogue: if /models could not be read, every
        # id would look dead and this would repoint a healthy provider.
        live = set(row["live"])
        for field in ("default_model", "model"):
            current = entry.get(field)
            if not current or not live or current in live:
                continue
            if replacement:
                entry[field] = replacement
                changes.append(f"{row['provider']}: {field} "
                               f"{current} → {replacement} (not served)")
            else:
                changes.append(f"{row['provider']}: {field} {current} is not "
                               f"served and no working replacement was found")

    if dry_run:
        return changes, cfg
    if changes:
        ok = save_yaml(CONFIG, cfg)
        if not ok:
            return changes + ["config write FAILED"], None
    return changes, cfg


def print_discovery(rows):
    """Human-readable diff: declared vs served, per provider."""
    proposed_any = False
    for row in sorted(rows, key=lambda r: r["provider"]):
        if row["catalogue_error"]:
            continue
        if not row["new"] and not row["missing"]:
            continue
        print(f"\n  {row['provider']}")
        print(f"    served {len(row['live'])}, declared {len(row['declared'])}")
        if row["missing"]:
            shown = ", ".join(row["missing"][:6])
            more = f" (+{len(row['missing'])-6})" if len(row["missing"]) > 6 else ""
            print(f"    no longer served ({len(row['missing'])}): {shown}{more}")
        if row["new"]:
            shown = ", ".join(row["new"][:8])
            more = f" (+{len(row['new'])-8})" if len(row["new"]) > 8 else ""
            print(f"    served but undeclared ({len(row['new'])}): {shown}{more}")
        if row["proposed"]:
            proposed_any = True
            print(f"    → usable now ({len(row['proposed'])}): "
                  f"{', '.join(p['model'] for p in row['proposed'])}")
        elif row["missing"] and row["new"]:
            print("    → none of the new ids answered a probe")
        if not row["writable"]:
            print("    (not a config-configured provider — report only)")
    if not proposed_any:
        print("\n  no provider needs a catalogue update")


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

    def _gate_for(slug):
        return (gate.get("providers") or {}).get(slug)

    def _apply_to(entry, slug):
        g = _gate_for(slug)
        if not g:
            return
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

    # the new-style providers: block
    for slug, entry in (cfg.get("providers") or {}).items():
        if isinstance(entry, dict):
            _apply_to(entry, slug)

    for entry in custom:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name")
        slug = f"custom:{name}"
        g = _gate_for(slug)
        if not g:
            continue
        _apply_to(entry, slug)

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
    ap.add_argument("--discover", action="store_true",
                    help="diff declared models against the provider's live /models and "
                         "propose the ones that work")
    ap.add_argument("--adopt", action="store_true",
                    help="with --discover: write the proposed models into the config")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.discover:
        rows = discover()
        if args.json:
            print(json.dumps({"discovery": rows}, indent=2, sort_keys=True))
        else:
            print("DISCOVERY — declared models vs what each provider serves")
            print_discovery(rows)
            unreachable = [r for r in rows if r["catalogue_error"]]
            if unreachable:
                print("\n  no catalogue endpoint (skipped):")
                for r in unreachable:
                    print(f"    {r['provider']}: {r['catalogue_error']}")
        if args.adopt:
            changes, _ = adopt_discovery(rows, dry_run=args.dry_run)
            print("\nmodels adopted:" if not args.dry_run else "\nmodels would be adopted:")
            for c in changes:
                print(f"  {c}")
            if not changes:
                print("  (nothing to adopt)")
        return 0

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
