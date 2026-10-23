#!/usr/bin/env python3
"""What providers does Hermes actually have — and do they work?

Run:  python3 tools/providers.py [--json]

Answers the question `hermes status` cannot. `hermes status` reports whether a
KEY is present; this reports whether a provider can actually serve a request
with the credential you have, right now.

Three states are distinguished, because they are different problems:

  working   — a real call returned 200
  blocked   — the credential is fine but the plan/endpoint refuses this model
             (402 not in plan · 403 forbidden · 403 free-tier-only)
  stale     — the credential itself is dead (401 expired/revoked)

Exit 3 when any provider is not working.
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
from entitlement import (hermes_credentials, load_env_files,  # noqa: E402
                         probe)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

AUTH = Path.home() / ".hermes/auth.json"
HERMES_ENV = Path.home() / ".hermes/.env"
UPB_ENV = Path.home() / ".config/upb/secrets.env"
UPB_ROUTES = Path.home() / ".config/upb/routes.yaml"

# provider -> (probe model, dialect)
PROBE = {
    "commandcode": ("minimax/minimax-m3.1-flash", "chat"),
    "commandcode-anthropic": ("claude-sonnet-5-5", "anthropic"),
    "ollama-cloud": ("gemma4:31b", "chat"),
    "zai": ("glm-5.3", "chat"),
    "alibaba-coding-plan": ("qwen3.7-max", "chat"),
    "alibaba-coding-cn": ("qwen3.7-max", "chat"),
    "alibaba-coding-plan-cn": ("qwen3.7-max", "chat"),
    "alibaba-token-plan": ("qwen3.8-max", "chat"),
    "dashscope-coding-cn": ("qwen3.7-max", "chat"),
    "lmstudio": ("qwen/qwen3-30b-a3b-2507", "chat"),
    "opencode-zen": ("big-pickle", "chat"),
    "opencode-go": ("gpt-5.4", "chat"),
    "openai-api": ("gpt-5.4", "chat"),
    "openai-codex": ("gpt-5.4", "codex"),
    "copilot": ("gpt-5.4", "copilot"),
    "custom:modelos.ai.ulusofona.pt": ("amalia-9b", "chat"),
}

# Why a provider is in the state it is, when we know more than the code says.
NOTES = {
    "opencode-zen": "free tier is OpenCode-client-only (403 outside OpenCode)",
    "opencode-go": "requires x-opencode-session header; gpt-5.4 not on this plan",
    "copilot": "gh token works but the account has no Copilot licence",
    "openai-codex": "OAuth access_token expired — needs `hermes auth refresh`",
    "openai-api": "key points at the Lusofona gateway, not api.openai.com",
    "lmstudio": "server is up but has 0 models loaded",
    "alibaba-coding-plan": "token expired (401) across all alibaba-coding ids",
    "alibaba-token-plan": "token valid, but every model is plan-gated (403)",
    "custom:modelos.ai.ulusofona.pt": "gateway unreachable from this network",
}


def _env():
    return load_env_files(UPB_ENV, HERMES_ENV)


def _load_yaml_file(path):
    """Parse a YAML file with whatever interpreter has PyYAML.

    The system python3 on macOS has no PyYAML; the Hermes venv does. Returns
    a dict, or None if the file cannot be parsed.
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


def resolve_credential(pid, cred):
    """The actual key for a pooled entry: inline, env, or config."""
    tok = (cred.get("access_token") or cred.get("api_key") or "").strip()
    if tok:
        return tok
    src = cred.get("source", "?")
    env = _env()
    if src.startswith("env:"):
        var = src[4:]
        return env.get(var, "")
    if src.startswith("config:"):
        cfg = _load_yaml_file(Path.home() / ".hermes/config.yaml") or {}
        for e in (cfg.get("custom_providers") or []):
            if e.get("name") == src[7:]:
                return (e.get("api_key") or "").strip()
    return ""


def base_url_for(pid, cred):
    base = (cred.get("base_url") or "").strip()
    if base:
        return base
    routes = _load_yaml_file(UPB_ROUTES)
    if not routes:
        return ""
    name = {"zai": "zai", "alibaba-token-plan": "alibaba"}.get(pid, pid)
    return ((routes.get("providers") or {}).get(name) or {}).get("base_url", "")


def probe_special(pid, base, key, model):
    """Providers that need a non-standard request shape."""
    if pid == "copilot":
        import subprocess
        gh = subprocess.run(["gh", "auth", "token"], capture_output=True,
                            text=True).stdout.strip()
        if not gh:
            return False, None, "no-github-cli", "gh not installed or not logged in"
        h = {"Authorization": f"Bearer {gh}", "User-Agent": "GitHubCopilotChat/0.26.7",
             "Content-Type": "application/json", "Editor-Version": "vscode/1.96.0"}
        url = "https://api.githubcopilot.com/chat/completions"
        body = {"model": model, "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8}
    elif pid == "opencode-go":
        h = {"Authorization": f"Bearer {key}", "User-Agent": UA,
             "Content-Type": "application/json", "x-opencode-session": "probe-0001"}
        url = base.rstrip("/") + "/chat/completions"
        body = {"model": model, "messages": [{"role": "user", "content": "hi"}],
                "max_tokens": 8}
    elif pid == "openai-codex":
        try:
            d = json.loads(AUTH.read_text())
        except Exception:
            return False, None, "no-credentials", "auth.json unreadable"
        tok = ((d.get("providers") or {}).get("openai-codex") or {}) \
            .get("tokens", {}).get("access_token", "")
        if not tok:
            return False, None, "no-credentials", "no oauth token"
        h = {"Authorization": f"Bearer {tok}", "User-Agent": UA,
             "Content-Type": "application/json"}
        url = "https://chatgpt.com/backend-api/codex/responses"
        body = {"model": model, "input": "hi", "max_output_tokens": 16}
    else:
        return None, None, None, None

    try:
        urllib.request.urlopen(urllib.request.Request(
            url, data=json.dumps(body).encode(), headers=h, method="POST"),
            timeout=35)
        return True, 200, "working", ""
    except urllib.error.HTTPError as e:
        raw = e.read()[:220].decode(errors="replace")
        try:
            raw = json.loads(raw).get("error", {}).get("message", raw)
        except Exception:
            pass
        return False, e.code, classify(e.code), raw[:64].replace("\n", " ")
    except Exception as e:
        return False, -1, "unreachable", f"{type(e).__name__}"


def classify(code):
    if code == 401:
        return "stale-credential"
    if code == 402:
        return "plan-locked"
    if code == 403:
        return "blocked"
    if code == 404:
        return "not-served"
    if code == 429:
        return "upstream-busy"
    if code == 400:
        return "rejected"
    return "error"


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        d = json.loads(AUTH.read_text())
    except Exception as e:
        print(f"cannot read {AUTH}: {e}", file=sys.stderr)
        return 2
    pool = d.get("credential_pool") or {}

    def check(pid, cred):
        key = resolve_credential(pid, cred)
        base = base_url_for(pid, cred)
        model, dialect = PROBE.get(pid, ("?", "chat"))
        if dialect in ("codex", "copilot") or pid == "opencode-go":
            ok, code, kind, detail = probe_special(pid, base, key, model)
            if ok is None:
                ok, code, kind, detail = probe(base, key, model, "chat")
        else:
            dia = "anthropic_messages" if dialect == "anthropic" else "chat_completions"
            ok, code, kind, detail = probe(base, key, model, dia)
        if not key:
            # No credential at all — a different problem from a rejected one.
            kind, detail = "no-key", "no credential for this provider"
            ok, code = False, None
        return {"provider": pid, "model": model, "ok": ok, "code": code,
                "kind": kind, "detail": detail, "note": NOTES.get(pid, ""),
                "has_key": bool(key)}

    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = [ex.submit(check, pid, c) for pid, cs in pool.items() for c in cs]
        rows = [f.result() for f in futs]

    # Distinguish duplicate provider ids by their credential source.
    seen = {}
    for r in rows:
        n = seen.get(r["provider"], 0)
        seen[r["provider"]] = n + 1
        r["display"] = r["provider"] if n == 0 else f"{r['provider']} #{n+1}"
    rows.sort(key=lambda r: (not r["ok"], r["display"]))
    if args.json:
        print(json.dumps({"providers": rows,
                          "working": sum(1 for r in rows if r["ok"]),
                          "total": len(rows)}, indent=2))
        return 3 if any(not r["ok"] for r in rows) else 0

    print(f"{'PROVIDER':<32} {'STATE':<18} {'CODE':<6} DETAIL")
    print("-" * 108)
    for r in rows:
        state = "working" if r["ok"] else r["kind"]
        state = {"auth": "stale-credential", "bad-request": "rejected"}.get(state, state)
        # the live detail wins; the note explains the known cause
        detail = r["detail"] if (r["detail"] or r["ok"]) else r["note"]
        print(f"  {r['display']:<32} {state:<18} {str(r['code']):<6} {detail[:44]}")
    good = sum(1 for r in rows if r["ok"])
    print(f"\n{good}/{len(rows)} providers working")
    print("states: working · plan-locked (402) · blocked (403) · "
          "stale-credential (401) · rejected (400) · unreachable")
    return 3 if good != len(rows) else 0


if __name__ == "__main__":
    sys.exit(main())
