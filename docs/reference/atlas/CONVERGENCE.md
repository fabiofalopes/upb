# CONVERGENCE — two sessions, one corpus

> **Written:** 2026-10-06 by session `4d64981b` (pane 4.3).
> **For:** session `668276ca` (pane 4.2, "agent skills folders across harnesses") and any later session.
> **Status:** coordination doc. Read before writing to `~/agent-hub` or the atlas.

Two Claude sessions worked the same goal on orcrist today without seeing each other.
Neither overwrote the other — **verified**. But the result is two halves of one system
and a name collision. This doc is the hand-off.

## What each session built (ground truth)

| | Built | Path | Size | Truth |
|---|---|---|---|---|
| **4.2** | physical **byte store** | `orcrist:~/agent-hub/` | 317M | 21,400 real files, 9,490 symlinks, 11,057 real SKILL.md. **No DB, no index, no consumers, not git.** |
| **4.3** | **entity catalog** + service | `orcrist:~/projetos/reference-atlas/` | 4.2M DB | 4,423 entities, 54 domains, FastAPI :8770. **`kind='skill'` = 0 rows** — the skill ETL was never wired. |

They are complements. **4.2 has the bytes, 4.3 has the index + taxonomy + service.** Neither
references the other. The merge is: 4.2 supplies payload, 4.3 supplies the schema/service.

Comprehension check: no session touched the other's paths. `~/agent-hub` did not exist before
02:10 today; `~/projetos/agent-hub` (the older dashboard) is a *different* path and is intact.

## The count was inflated ~2x — this is the headline

`docs/INDEX.md` advertises **"20,384 SKILL.md artifacts"**. Verified breakdown:

| | Count |
|---|---|
| entries named SKILL.md | 20,385 |
| — of which **symlinks** | −9,328 |
| **real files** | **11,057** |
| distinct by resolved path (all sources, li+orcrist) | 9,606 |
| **distinct by content hash (sha1)** | **≈9,489** |

The 9,328 symlinks in `skills/live/li/opencode-skill-vault` point **into** the 9,455 real
files in `skills/catalog/security-corpus`. Pointer + target = the same bytes counted twice.

The same inflation exists on li: `~/.config/opencode/skill-vault` (9,343 entries) is
**9,328 symlinks + 15 real files**, and 9,327 of those symlinks resolve into
`~/shared-local/hub/curated` (9,455 real). ~99.8% the same files reached two ways.

> **Use 9,489 as the real distinct-skill count.** Anything treating "20k" as corpus size
> overstates by ~9k of the same bytes.

## Collisions / divergences, most severe first

| # | Sev | Problem | Fix |
|---|---|---|---|
| 1 | HIGH | **Double-count via symlink farm** (above). | Model as one entity + N provenance rows keyed by content hash. **A symlink is provenance, never an entity.** |
| 2 | HIGH | **`canon/` duplicates `skills/catalog/`.** `canon/cyber-foundry/reference-repos/Anthropic-Cybersecurity-Skills` (818) overlaps catalog's `anthropic-cyber-skills` (754) **754-for-754 by basename**; CyberStrikeAI (24) also overlaps. Violates the store's own README principle 1. | Collapse in the catalog (extra provenance rows). In the store: confirm byte-identity, then keep one, drop the other — **owner's decision, see prune list**. |
| 3 | HIGH | **`~/agent-hub` vs `~/projetos/agent-hub` ambiguity.** Four things now share the name (see table below). | Resolve at the DB level: atlas `source.key='agent-hub-store'` ≠ `'agent-hub'` (repo db). Dir rename deferred to owner. |
| 4 | HIGH | **`patterns/fabric` is non-functional.** 49 symlinks → `/root/.myscripts/fabric-custom-patterns/*`, **permission-denied**; 0 real files. Docs present it as populated. Escapes `find -xtype l` (EACCES ≠ ENOENT). Also duplicated in `tools/diane-agent-kit/patterns/`. | Prune or re-source from a host where `/root` is readable. Do not count as skills. |
| 5 | MED | **`SOURCES.md` "0 broken links remain" is false store-wide** — 53 broken symlinks under `skills/live/` (verbatim-copied macOS/other-host targets that were never retargeted). | Heal or prune the 53; correct the doc. |
| 6 | MED | **`canon/` holds 1,089 SKILL.md** though README describes it as "durable human knowledge (docs, not skills)" — 43% of all real skills are hiding there. | Reclassify: reference-repos are a second corpus, not canon. |
| 7 | MED | **Store claims "canonical source of truth" but has zero consumers.** Live inputs still flow to li `~/shared-local/hub/curated` and orcrist `~/projetos/agent-hub`. | Wire consumers (the atlas ETL) or downgrade the claim. |

### The four "agent-hub"s

| Path | What | Live? |
|---|---|---|
| `li:~/agent-knowledge/projects/agent-hub/` | repo-catalog dashboard DB (1,546 repos) — atlas ETL source | **yes** |
| `orcrist:~/projetos/agent-hub/` | same dashboard, older copy (324 repos) | stale |
| `orcrist:~/agent-hub/` | **the new 317M byte store** | inert (no consumers yet) |
| `orcrist:~/breakinc-claude/li-sync/.../agent-hub/` | synced snapshot (216 repos, Jul 20) | dead |
| `orcrist:~/.hermes/skills/agent-hub/` | hermes SKILL.md for the dashboard | live |

Both launchers share `~/.hermes/agent-hub.pid` and port **8765** — a latent clash.

## Agreed naming (adopt these)

- **`agent-hub-repos`** — the repo-catalog dashboard DB (li). Formerly `agent-hub`.
- **`agent-hub-store`** — the 317M skill byte store (orcrist `~/agent-hub`). Display name **"the Armory"**.
- **`reference-atlas`** — the entity catalog + service (:8770). The **index**.
- **`cyber-foundry`** — the curation gate (`~/projetos/cyber-foundry/cyber-foundry-kit/`). The **gate**.
- **roles** — the output layer (`roles/`), assembled from gate-approved skills + domain filters.

Pipeline: **sources → store (bytes) → foundry (curate) → atlas (index) → roles (agents).**

## Prune list (owner executes — 4.3 is read-only on the store)

1. `patterns/fabric/*` — 49 dead symlinks to `/root/…` (permission-denied). Remove.
2. `tools/diane-agent-kit/patterns/*` — same dead set. Remove.
3. 53 broken symlinks under `skills/live/` — prune or heal.
4. After byte-identity check: drop the duplicated tree between `canon/cyber-foundry/reference-repos/` and `skills/catalog/` (~754 trees).
5. Fix `docs/SOURCES.md` ("0 broken links") and `docs/INDEX.md` (20,384 → distinct count).

**Do NOT** delete anything until the atlas has indexed the store — the index is the proof of
what exists. Chain: index first, then prune, re-index to confirm counts.

## Tartarus (next target — separately)

`tartarus` is clean/empty and being tested for red-team + RE work (ghidra, fuzzing,
exploit/vuln research). It should draw from the **store + foundry**, not re-harvest.
Wiring plan in `docs/TARTARUS.md` (4.3 owns).
