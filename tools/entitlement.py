#!/usr/bin/env python3
"""Entitlement probe — is a model actually usable with YOUR key right now?

Run:  python3 tools/entitlement.py [--all] [--provider P] [--json]

The gap this closes: `/v1/models` tells you a provider *serves* a model. It
does not tell you whether *your* plan can *call* it. A model can be listed and
still return 402 (not in free usage), 403 (not in plan), 404 (rolling out) or
429 (upstream down).

Only a real call answers that. This probe sends a 1-token chat completion and
classifies the response. It is deliberately tiny (max_tokens=1) but it IS
billable on metered models — run it deliberately, not in a hot loop.

Exit codes: 0 all probed models usable · 3 some unusable.
"""

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36")

# How to read each failure mode.
CLASSIFY = [
    (402, "plan-locked", "model exists but is NOT in your plan's included usage"),
    (403, "plan-locked", "forbidden — often 'available in Pro and above'"),
    (401, "auth", "the key itself was rejected"),
    (404, "not-served", "model id not found on this endpoint"),
    (429, "upstream-busy", "rate limited or upstream provider temporarily down"),
    (400, "bad-request", "rejected — often a wrong dialect or an unsupported model id"),
]


def load_env_files(*paths):
    out = {}
    for p in paths:
        try:
            for line in Path(p).expanduser().read_text().splitlines():
                if "=" in line and not line.strip().startswith("#"):
                    k, _, v = line.partition("=")
                    out[k.strip()] = v.strip().strip("'\"")
        except OSError:
            pass
    return out


def hermes_credentials():
    """Providers from ~/.hermes/auth.json credential pool — the real keys."""
    try:
        d = json.loads((Path.home() / ".hermes/auth.json").read_text())
    except Exception:
        return []
    out = []
    for pid, creds in (d.get("credential_pool") or {}).items():
        for c in creds:
            key = (c.get("access_token") or c.get("api_key") or "").strip()
            base = c.get("base_url") or ""
            # A pooled entry with an EMPTY token is a placeholder, not a
            # credential — it would shadow a working .env key. Skip it.
            if not key or not base:
                continue
            out.append({"provider": pid, "base_url": base.rstrip("/"),
                        "key": key, "source": c.get("source", "?")})
    return out


def classify(code, body):
    for want, kind, why in CLASSIFY:
        if code == want:
            return kind, why
    return "error", (body or "")[:70]


def _ssl_context(ca_cert=None, verify=True):
    """An SSL context honouring a provider's pinned CA.

    A gateway whose issuer chain is not in the local trust store fails
    verification even though the cert is perfectly valid (this machine's
    Lusofona gateway is issued by a Greek research CA that neither macOS's
    keychain nor Python's certifi carries). Pinning the intermediate as the
    trust anchor fixes it WITHOUT disabling verification.
    """
    import ssl
    ctx = ssl.create_default_context()
    if not verify:
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    elif ca_cert:
        try:
            ctx.load_verify_locations(ca_cert)
        except Exception:
            pass
    return ctx


def probe(base, key, model, dialect="chat_completions", ca_cert=None, verify=True):
    """One 1-token call. Returns (ok, code, kind, detail).

    Three wire dialects, because the providers do not agree:
      chat_completions   — OpenAI Chat Completions
      anthropic_messages — Anthropic Messages
      codex_responses    — OpenAI Responses, but ONLY with a LIST-shaped
                           `input` and `stream: true`. A scalar input is
                           rejected with "Input must be a list" and a
                           non-streaming request with "Stream must be set to
                           true" — both of which look like a broken model
                           when they are really a wrong probe.
    """
    headers = {"Content-Type": "application/json", "User-Agent": UA,
               "Accept": "application/json"}
    if dialect == "anthropic_messages":
        headers["x-api-key"] = key
        headers["anthropic-version"] = "2023-06-01"
        url, body = base + "/messages", {
            "model": model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}]}
    elif dialect == "codex_responses":
        headers["Authorization"] = f"Bearer {key}"
        headers["Accept"] = "text/event-stream"
        url, body = base + "/responses", {
            "model": model, "store": False, "stream": True,
            "input": [{"role": "user",
                       "content": [{"type": "input_text", "text": "hi"}]}],
            "max_output_tokens": 16}
    else:
        headers["Authorization"] = f"Bearer {key}"
        url, body = base + "/chat/completions", {
            "model": model, "max_tokens": 1,
            "messages": [{"role": "user", "content": "hi"}]}
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers=headers, method="POST")
    try:
        if ca_cert or not verify:
            # a pinned CA needs its own context; urlopen's default cannot
            # take per-request TLS options.
            ctx = _ssl_context(ca_cert, verify)
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                resp.read(1)
            return True, 200, "usable", ""
        urllib.request.urlopen(req, timeout=30)
        return True, 200, "usable", ""
    except urllib.error.HTTPError as e:
        raw = e.read()[:300].decode(errors="replace")
        try:
            raw = json.loads(raw).get("error", {}).get("message", raw)
        except Exception:
            pass
        kind, why = classify(e.code, raw)
        return False, e.code, kind, why
    except Exception as e:
        return False, -1, "transport", f"{type(e).__name__}: {e}"[:60]


def candidates(args):
    """(provider, base_url, key, model, dialect) tuples to probe."""
    out = []
    creds = hermes_credentials()
    # Hermes .env is authoritative for Hermes credentials; upb's secrets.env
    # is a separate copy that can drift (it already had a stale OLLAMA_API_KEY
    # that 401s while the .env one works). Load upb's FIRST so .env wins.
    env = load_env_files(Path.home() / ".config/upb/secrets.env",
                         Path.home() / ".hermes/.env")

    # Pooled credentials first.
    endpoints = []
    for c in creds:
        endpoints.append((c["provider"], c["base_url"], c["key"]))

    # Then env-sourced endpoints, which override a pooled entry with the SAME
    # provider id: the pool may hold a stale or partial token while .env has
    # the working key (ollama-cloud is exactly this case).
    env_names = {
        "ollama-cloud": "OLLAMA_API_KEY",
        "openai-api": "OPENAI_API_KEY",
        "opencode-zen": "OPENCODE_ZEN_API_KEY",
        "opencode-go": "OPENCODE_GO_API_KEY",
        "lmstudio": "LM_API_KEY",
    }

    # static probes for the providers we know how to reach
    static = [
        ("ollama-cloud", "https://ollama.com/v1", env.get("OLLAMA_API_KEY", "")),
        ("zai", "https://api.z.ai/api/coding/paas/v4", env.get("ZAI_API_KEY", "")),
        ("alibaba", "https://token-plan.ap-southeast-1.maas.aliyuncs.com/compatible-mode/v1",
         env.get("ALIBABA_TOKEN_PLAN_KEY", "")),
        ("lmstudio", "http://127.0.0.1:1234/v1", env.get("LM_API_KEY", "")),
    ]
    for n, b, k in static:
        if k:
            endpoints = [e for e in endpoints if e[0] != n]
            endpoints.append((n, b, k))
    # de-duplicate by provider id, keeping the last (env wins over pool)
    seen = {}
    for pid, base, key in endpoints:
        seen[pid] = (pid, base, key)
    endpoints = list(seen.values())

    for pid, var in env_names.items():
        if env.get(var):
            endpoints = [e for e in endpoints if e[0] != pid]
            base = next((b for n, b, _ in static if n == pid), None)
            if base:
                endpoints.append((pid, base, env[var]))

    models_by_provider = {
        "ollama-cloud": ["gemma4:31b", "gpt-oss:120b", "nemotron-3-super",
                         "minimax-m3", "minimax-m3.1-flash", "mistral-large-3:675b",
                         "deepseek-v4-pro:0813", "glm-5.3", "kimi-k2.7-code"],
        "zai": ["glm-5.3", "glm-5.2", "glm-5-turbo", "glm-4.7"],
        "alibaba": ["qwen3.8-max", "qwen3.7-max", "qwen3.7-plus", "qwen3.6-flash",
                    "deepseek-v4-pro", "glm-5.2"],
        "lmstudio": [],
        "commandcode": ["minimax/minimax-m3.1-flash", "deepseek/deepseek-v4-pro",
                        "zai-org/GLM-5.3", "moonshotai/Kimi-K2.7-Code",
                        "google/gemini-3.8-flash", "xai/grok-4.7", "gpt-5.4"],
    }

    for pid, base, key in endpoints:
        if args.provider and pid != args.provider:
            continue
        models = models_by_provider.get(pid)
        if models is None:
            # unknown provider: probe its catalogue head only
            models = ["__catalogue__"]
        for m in models:
            dialect = "anthropic_messages" if pid.endswith("-anthropic") else "chat_completions"
            out.append((pid, base, key, m, dialect))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", help="only this provider")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--catalogue-only", action="store_true",
                    help="skip the 1-token calls; only list what each provider serves")
    args = ap.parse_args()

    rows = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(probe, b, k, m, d): (p, m) for p, b, k, m, d in candidates(args)}
        for fut, (p, m) in futs.items():
            ok, code, kind, detail = fut.result()
            rows.append({"provider": p, "model": m, "usable": ok, "code": code,
                         "kind": kind, "detail": detail})

    rows.sort(key=lambda r: (r["provider"], not r["usable"], r["model"]))
    if args.json:
        print(json.dumps(rows, indent=2))
    else:
        by_prov = {}
        for r in rows:
            by_prov.setdefault(r["provider"], []).append(r)
        for prov, rs in by_prov.items():
            print(f"\n{prov}")
            for r in rs:
                mark = "✓" if r["usable"] else "✗"
                extra = "" if r["usable"] else f"  [{r['kind']}] {r['detail']}"
                print(f"  {mark} {r['model']:<34} {r['code']}{extra}")
        bad = [r for r in rows if not r["usable"]]
        print(f"\n{len(rows)-len(bad)}/{len(rows)} usable, {len(bad)} not usable")
    return 3 if any(not r["usable"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
