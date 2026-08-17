# Future — Planned Integrations

Code absorbed from the **ai-model-router** project (`~/projetos/ai-model-router/`, archived Jul 2026).
That project researched and designed a tier-aware routing layer for LiteLLM but was never deployed.
Panopticon superseded it as the deployed LLM control plane.

## custom_routing/

Two modules from ai-model-router's custom routing strategy. **Not yet integrated** into the
running LiteLLM stack — kept as reference for when we add intelligent model selection.

### tier_router.py — `TierAwareRouter`

Extends LiteLLM's `CustomRoutingStrategyBase`. Routing logic:

1. **Local-first**: Prefer Ollama for simple/haiku-tier tasks
2. **Free cloud**: Use `:free` OpenRouter models when available
3. **Paid fallback**: Only when explicitly requested or free exhausted
4. **Rate-limit cooldown**: Quarantines providers for 5min after 429s
5. **Speed/cost scoring**: Hardcoded rankings (`_speed_score`, `_cost_score`)

**To integrate**: Register via LiteLLM's `router_settings.routing_strategy` with a custom
strategy class. Requires the LiteLLM Python SDK (not just the Docker proxy).

### benchmark_loader.py — `BenchmarkLoader`

Reads `or-bench` results from `~/.cache/or-bench/*.json` and provides:

- Model rankings by TPS, TTFB, output tokens
- Filtering by parameter count, free/paid
- Auto-generated tier mappings (opus/sonnet/haiku) from benchmark data

**To integrate**: Feed benchmark results into routing decisions dynamically
instead of hardcoded speed rankings.

## Origin

| File | Source |
|------|--------|
| `tier_router.py` | `ai-model-router/custom_routing/tier_router.py` |
| `benchmark_loader.py` | `ai-model-router/custom_routing/benchmark_loader.py` |
| `__init__.py` | `ai-model-router/custom_routing/__init__.py` |

Full evolution story: see Obsidian vault `inference-stack/ai-model-router-to-panopticon.md`
