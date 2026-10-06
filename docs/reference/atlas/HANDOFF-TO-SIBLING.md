# HANDOFF → session `668276ca` (pane 4.2)

From session `4d64981b` (pane 4.3), 2026-10-06.

**Both our sessions worked the same goal on orcrist today.** Neither overwrote the other —
verified — but we built two halves of one system and left a naming collision. I've written
`~/agent-hub/CONVERGENCE.md` with the full findings. This is the short version.

## TL;DR

| You built | I built |
|---|---|
| `orcrist:~/agent-hub/` — 317M byte store, 11,057 real SKILL.md | `orcrist:~/projetos/reference-atlas/` — entity catalog, FastAPI :8770 |

They're complements: **you have the bytes, I have the index + taxonomy + service.** I've now
wired my ETL to index your store **read-only** — I have not moved, renamed, or deleted anything.

## The one number that matters

Your `docs/INDEX.md` says **20,384 SKILL.md**. That double-counts: 9,328 are symlinks in
`skills/live/li/opencode-skill-vault` pointing *into* the 9,455 real files in
`skills/catalog/security-corpus` — the same bytes twice. **Real distinct ≈ 9,489 by content hash.**

I modelled this correctly rather than just reporting it: symlinks are now **provenance rows**,
not entities. Result: 10,006 skill entities where 9,403 carry multiple provenance paths
(the farm collapsed, no double-count).

## What I did (read-only on your store)

- Added `reference-atlas/etl/etl_agent_hub_store.py` — walks `~/agent-hub`, hashes artifacts,
  indexes each physical file **once**, records every symlink path as provenance.
- Ran it: **11,076 artifacts indexed, 9,197 symlinks → provenance, 199 duplicate paths collapsed.**
- Atlas is now **14,445 entities** (10,006 skills, 16 agent-roles, + the earlier 4,423).
- Live at http://orcrist.tail1d035f.ts.net:8770/ — the skills are now browsable/treemappable.

## Things in your store you'll want to fix (I didn't touch them)

1. **`patterns/fabric/` is non-functional** — 49 symlinks to `/root/.myscripts/fabric-custom-patterns/*`,
   permission-denied on orcrist, 0 real files. Also duplicated in `tools/diane-agent-kit/patterns/`.
   `docs/INDEX.md` presents them as populated.
2. **`canon/` duplicates `skills/catalog/`** — `canon/.../Anthropic-Cybersecurity-Skills` (818)
   overlaps catalog's `anthropic-cyber-skills` (754) 754-for-754 by basename.
3. **`SOURCES.md` "0 broken links remain"** — actually 53 broken symlinks under `skills/live/`
   (verbatim-copied macOS/other-host paths never retargeted). I counted 151 broken my run
   (includes the fabric set's permission-denied targets).
4. **`canon/` holds 1,089 SKILL.md** while the README calls it "docs, not skills".

## Naming (please adopt)

- `agent-hub-repos` = the repo-catalog dashboard DB (li). Was ambiguously "agent-hub".
- `agent-hub-store` = your 317M store (orcrist `~/agent-hub`). Suggested display name: **the Armory**.
- `reference-atlas` = the index (:8770); `cyber-foundry` = the curation gate; `roles/` = the output.

**Before you prune anything:** let the atlas index first — it's the proof of what exists.
Chain: index → prune → re-index to confirm counts. Full prune list is in `CONVERGENCE.md`.

## Onward

Owner wants: roles assembled from the corpus (pentester/red-teamer, not onesided), one
browsable catalog, foundry as the curation gate, and tartarus as the clean test target for
red-team/RE/ghidra/fuzzing work. Details in `CONVERGENCE.md`. Coordinate before writing to
`~/agent-hub` again — I'll re-index after any change.