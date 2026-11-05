#!/usr/bin/env python3
"""Pre-flight: is the CURRENT Hermes config actually usable?

Run:  python3 tools/preflight.py [--json] [--fix-suggest]

Answers the question that `hermes status` cannot: not "is the key set?" but
"if you started a session right now, would it work?"

It checks:
  1. the primary model + provider — does a real 1-token call succeed?
  2. every auxiliary task (vision, compression, mcp, …) — same question
  3. the fallback chain — is each entry reachable?
  4. the local model server — is anything loaded?

Exit 0 = everything works. Exit 3 = something is configured but broken.
This is the check that would have caught the default model being plan-locked.
"""

import argparse
import json
import subprocess
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from entitlement import (credentials_for, load_env_files,  # noqa: E402
                         probe)

CONFIG = Path.home() / ".hermes/config.yaml"


def _yaml():
    """Import PyYAML from whichever interpreter has it.

    The system python3 on macOS has no PyYAML; the Hermes venv does. This
    tool must run from a bare `python3 tools/preflight.py`, so it falls back
    to the venv rather than failing with a bare ModuleNotFoundError.
    """
    try:
        import yaml
        return yaml
    except ImportError:
        import subprocess
        venv = Path.home() / ".hermes/hermes-agent/venv/bin/python3"
        if venv.exists():
            code = (
                "import yaml,sys,json;"
                "print(json.dumps(yaml.safe_load(open(sys.argv[1]).read())))"
            )
            out = subprocess.run([str(venv), "-c", code, str(CONFIG)],
                                 capture_output=True, text=True, timeout=30)
            if out.returncode == 0:
                return _RemoteYaml(out.stdout)
        raise SystemExit(
            "preflight: PyYAML not available. Install it (pip install pyyaml) "
            "or run with ~/.hermes/hermes-agent/venv/bin/python3")


class _RemoteYaml:
    """Minimal YAML facade backed by the Hermes venv interpreter."""

    def __init__(self, payload):
        import json
        self._data = json.loads(payload)

    def safe_load(self, _text):
        return self._data

    class YAMLError(Exception):
        pass


def _load_yaml_file(path):
    """Parse a YAML file with whatever interpreter has PyYAML."""
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


def load_cfg():
    """Parse ~/.hermes/config.yaml. A parse failure is fatal, not silent —
    a swallowed exception here turns "the config is broken" into "nothing is
    configured", which is a much harder failure to diagnose."""
    yaml = _yaml()
    try:
        return yaml.safe_load(CONFIG.read_text()) or {}
    except Exception as e:
        print(f"preflight: config is not valid YAML: {e}", file=sys.stderr)
        raise SystemExit(2)


def tls_for(provider):
    """(ca_cert, verify) for a provider, from its config entry."""
    cfg = _load_yaml_file(Path.home() / ".hermes/config.yaml") or {}
    entry = None
    for slug, e in (cfg.get("providers") or {}).items():
        if slug == provider and isinstance(e, dict):
            entry = e
    if entry is None:
        for e in (cfg.get("custom_providers") or []):
            if isinstance(e, dict) and (provider.endswith(e.get("name", ""))):
                entry = e
    if not entry:
        return None, True
    ca = entry.get("ssl_ca_cert")
    verify = entry.get("ssl_verify", True)
    if isinstance(verify, str):
        verify = verify.strip().lower() not in ("false", "no", "0")
    return (ca or None), bool(verify)


def _dialect_for(provider):
    if provider.endswith("-anthropic"):
        return "anthropic_messages"
    if provider == "openai-codex":
        return "codex_responses"
    return "chat_completions"


def cred_candidates(provider):
    """Every (base_url, key, label) the runtime could use, best first.

    Ordering matters: a provider can hold several credentials for the same
    endpoint (a stale manual key and a live env key), and probing only the
    first reports a working provider as 401. Try them in the order the runtime
    would, and stop at the first that answers.
    """
    out = []
    for c in credentials_for(provider):
        out.append((c["base_url"], c["key"], f"{c['source']} ({c['label']})"))
    env = load_env_files(Path.home() / ".config/upb/secrets.env",
                         Path.home() / ".hermes/.env")
    static = {
        "ollama-cloud": ("https://ollama.com/v1", env.get("OLLAMA_API_KEY", "")),
        "zai": ("https://api.z.ai/api/coding/paas/v4", env.get("ZAI_API_KEY", "")),
        "alibaba": ("https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
                    env.get("ALIBABA_TOKEN_PLAN_KEY", "")),
        "lmstudio": ("http://127.0.0.1:1234/v1", env.get("LM_API_KEY", "")),
    }
    if not out and provider in static:
        base, key = static[provider]
        if key:
            out.append((base, key, "env"))
    return out


def cred_for(provider):
    """Resolve (base_url, key, dialect) for a configured provider name.

    The dialect matters more than it looks: probing openai-codex with a
    Chat Completions body reports a working model as broken.
    """
    cands = cred_candidates(provider)
    if cands:
        return cands[0][0], cands[0][1], _dialect_for(provider)
    return None, None, "chat_completions"


def check_one(label, provider, model, cfg=None, api_mode=None):
    ca_cert, verify = tls_for(provider)
    dialect = _dialect_for(provider)
    if api_mode:
        dialect = {"anthropic_messages": "anthropic_messages",
                   "codex_responses": "codex_responses",
                   "openai_chat": "chat_completions",
                   "chat_completions": "chat_completions"}.get(
                       str(api_mode), dialect)
    cands = cred_candidates(provider)
    if not cands:
        return {"label": label, "provider": provider, "model": model,
                "ok": False, "code": None, "kind": "no-credentials",
                "detail": f"no base_url/key known for '{provider}'",
                "credential": None}
    # Try each credential the runtime could pick, in order. The first that
    # answers is the one a session would actually use — so a stale manual key
    # at a lower priority cannot make a working provider look dead.
    last = None
    for base, key, via in cands:
        ok, code, kind, detail = probe(base, key, model, dialect,
                                       ca_cert=ca_cert, verify=verify)
        last = {"label": label, "provider": provider, "model": model,
                "ok": ok, "code": code, "kind": kind, "detail": detail,
                "credential": via}
        if ok:
            return last
    return last


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--fix-suggest", action="store_true",
                    help="print config commands that would repair what is broken")
    args = ap.parse_args()

    cfg = load_cfg()
    checks = []

    # 1. primary
    m = cfg.get("model") or {}
    checks.append(check_one("PRIMARY", m.get("provider", "?"),
                            m.get("default", "?"), cfg,
                            api_mode=m.get("api_mode")))

    # 2. auxiliary tasks
    for name, entry in sorted((cfg.get("auxiliary") or {}).items()):
        if not isinstance(entry, dict):
            continue
        checks.append(check_one(f"aux:{name}", entry.get("provider", "?"),
                                entry.get("model", "?"), cfg))

    # 3. fallback chain
    for i, entry in enumerate(cfg.get("fallback_providers") or []):
        if not isinstance(entry, dict):
            continue
        checks.append(check_one(f"fallback:{i+1}", entry.get("provider", "?"),
                                entry.get("model", "?"), cfg))

    # 4. local server — LM Studio requires its API token even on /models.
    #    Use the OpenAI-compatible path: it lists the models actually being
    #    SERVED, which is the question. The native /api/v1/models can answer
    #    "0 models" while the port is up, and a listening port with nothing
    #    loaded is not a working fallback.
    lm_key = load_env_files(Path.home() / ".hermes/.env").get("LM_API_KEY", "")
    try:
        hdrs = {"User-Agent": "preflight/1.0"}
        if lm_key:
            hdrs["Authorization"] = f"Bearer {lm_key}"
        req = urllib.request.Request("http://127.0.0.1:1234/v1/models",
                                     headers=hdrs)
        with urllib.request.urlopen(req, timeout=6) as r:
            models = [m.get("id") for m in json.loads(r.read()).get("data", [])]
        if models:
            checks.append({"label": "lmstudio", "provider": "lmstudio",
                           "model": ", ".join(models)[:40],
                           "ok": True, "code": 200, "kind": "ok",
                           "detail": "", "credential": None})
        else:
            checks.append({"label": "lmstudio", "provider": "lmstudio",
                           "model": "127.0.0.1:1234", "ok": False, "code": 200,
                           "kind": "no-model-loaded",
                           "detail": "server up but no model loaded",
                           "credential": None})
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = json.loads(e.read()).get("error", {}).get("message", "")[:60]
        except Exception:
            pass
        checks.append({"label": "lmstudio", "provider": "lmstudio",
                       "model": "127.0.0.1:1234", "ok": False, "code": e.code,
                       "kind": "auth" if e.code in (401, 403) else "unreachable",
                       "detail": body or f"HTTP {e.code}", "credential": None})
    except Exception as e:
        checks.append({"label": "lmstudio", "provider": "lmstudio",
                       "model": "127.0.0.1:1234", "ok": False, "code": None,
                       "kind": "unreachable",
                       "detail": f"{type(e).__name__} — no local model server",
                       "credential": None})

    bad = [c for c in checks if not c["ok"]]
    if args.json:
        print(json.dumps({"checks": checks, "ok": not bad}, indent=2))
        return 3 if bad else 0

    print("HERMES PRE-FLIGHT")
    print("=" * 60)
    for c in checks:
        mark = "✓" if c["ok"] else "✗"
        line = f"  {mark} {c['label']:<22} {c['provider']}/{c['model']}"
        if c.get("credential"):
            line += f"  [via {c['credential']}]"
        if not c["ok"]:
            line += f"\n      [{c['kind']}] {c['detail']}"
        print(line)
    print("=" * 60)
    print(f"  {len(checks)-len(bad)}/{len(checks)} working")
    if bad and args.fix_suggest:
        print("\nSuggested repairs:")
        for c in bad:
            print(f"  hermes config set {c['label'].replace('aux:', 'auxiliary.').replace('fallback:', '')}"
                  f"...")
        print("  (run `python3 tools/entitlement.py` to find a working model first)")
    return 3 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
