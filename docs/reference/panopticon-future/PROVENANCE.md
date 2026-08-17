# Provenance

Vendored from `panopticon` commit `c2ef3f3` (2026-08-17), directory `future/`.

These modules are the only surviving code from the archived `ai-model-router`
project (`~/projetos/ai-model-router/`, deleted after absorption in Jul 2026).
They are **reference material only** — not compiled, not imported, not wired
into upb. Ideas under consideration for upb:

- `TierAwareRouter` — provider cooldown/quarantine concept (adopted in
  modified form as upb's router cooldown, see MIGRATION_FROM_PANOPTICON.md G2)
- `BenchmarkLoader` — or-bench JSON consumer for benchmark-driven model
  selection (candidate for a future `upb bench`, G4 / P4)

Original integration notes: see `README.md` in this directory.
