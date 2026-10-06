# Handoff — next session (Reference Atlas + corpus)

> **Written:** 2026-10-06 ~04:30 by session `4d64981b` (pane 4.3), closing.
> **Read first:** `CONVERGENCE.md` (in this dir) for the two-session reconciliation.
> **State:** cleaning phase STARTED. Corpus is indexed. Nothing pruned yet.

---

## 1. Where everything lives (ground truth, verified at close)

| Thing | Host | Path | What |
|---|---|---|---|
| **Reference Atlas** (index + UI) | orcrist | `~/projetos/reference-atlas/` | `atlas.db` + FastAPI **:8770** |
| **Agent-hub store** (bytes) | orcrist | `~/agent-hub/` | 317M, 11,057 real SKILL.md, no consumers of its own |
| **Cyber-foundry** (gate) | orcrist | `~/projetos/cyber-foundry/cyber-foundry-kit/` | 44 production skills + lifecycle registry |
| **Repo-catalog DB** | li | `~/agent-knowledge/projects/agent-hub/agent_hub.db` | 1,546 repos — atlas ETL source |
| **Twitter archive** | orcrist | `~/.myscripts/twitter-archive/archive.db` | 6k tweets / 8k links — atlas ETL source |
| **Role defs** | li | `~/.config/opencode/agents/` | 8 roles incl. kali-director/recon/exploit |
| **Skill-vault** (symlink farm) | li | `~/.config/opencode/skill-vault/` | 9,328 symlinks → `~/shared-local/hub/curated` |

Services (orcrist, `systemctl --user`, both enabled):
`reference-atlas.service` (uvicorn :8770, tailnet-only) · `reference-atlas-ingest.timer` (6h + boot).
URL: **http://orcrist.tail1d035f.ts.net:8770/** · manual: `bash launcher.sh start`

## 2. Current atlas state (14,445 entities / 26,006 provenance rows)

| kind | count | note |
|---|---|---|
| skill | 10,006 | from the store; 9,403 have multi-path provenance (symlink farm collapsed) |
| article | 2,594 | x_post / x_article from reposts |
| **repo** | **1,582** | ← the focus; 1,000+ merge across sources |
| paper | 173 | arxiv etc. |
| model | 74 | huggingface |
| agent-role | 16 | from `agent-hub/agents/` |

**Zero rows:** `edge=0` (graph not built), `tag=0`/`entity_tag=0` (tagging not built),
`technique=0` (ATT&CK not wired), `file_seen=0` (incremental skip not used yet).
Every entity is still `lifecycle='inbox'`, `curation='new'` — **nothing curated yet.**

## 3. WHAT THE USER WANTS NEXT (priority order, stated 2026-10-06)

1. **Focus on repos first.** All GitHub URLs from reposts are already scraped — repos are the
   most complete slice (1,582). Make them **navigable**: "what's around, what have we saved up."
   - 347 repos sit in `uncategorized` — real classification work needed.
   - Repos want: stars/language enrichment (needs GITHUB_TOKEN via Vaultwarden), better
     description extraction, and the graph.
2. **Also papers, posts, agentic-AI content** — same treatment, for "moments of looking back."
3. **Optimize the web UI** — the current treemap/table is Stage 0; user wants richer navigation.
4. **Cleaning phase (STARTED):** the corpus we moved needs dedup/prune. Order: **index → prune →
   re-index** (index is the proof of what exists). Prune list in `CONVERGENCE.md` §"Prune list".
5. **Roles** (later): pentester/red-teamer/etc. assembled from foundry-vetted skills — "not onesided".
6. **Tartarus** as the clean test target for red-team / RE / ghidra / fuzzing work.

## 4. Concrete next actions

### A. Repo navigation (do first)
- [ ] Classify the 347 uncategorized repos (improve `etl/etl_agenthub.py` classifier or add a
      pass over `description` via `reclassify.py`).
- [ ] GitHub enrichment: `enrich_github.py` (not written). Reads entities with
      `last_enriched_at IS NULL`, calls `api.github.com/repos/{o}/{r}`, writes stars/language/topics
      into `kind_meta_json`. Token from Vaultwarden; ~1,600 repos @1 req/s ≈ 30 min.
      **Verify `bw-inject-mcp` invocation first** (no installed binary/unit found).
- [ ] Build the **graph** (`edge` table): synthesize `co_domain`, `same_technique`, `part_of_pack`.
      `chains_with` in skill files is sparse — do NOT build the graph on it alone.
- [ ] UI: repo-centric view — filter by language/stars/domain/source, sort, and a "saved this"
      timeline. The treemap exists; add the graph + faceted repo browser.

### B. Dedup / clean (after repos usable)
- [ ] Confirm byte-identity between `canon/cyber-foundry/reference-repos/` and
      `skills/catalog/security-corpus/` (754 basename-overlap), then keep one.
- [ ] Remove `patterns/fabric/*` + `tools/diane-agent-kit/patterns/*` (49 dead `/root/…` links).
- [ ] Prune or heal the 53 broken symlinks under `skills/live/`.
- [ ] Fix `agent-hub/docs/{SOURCES,INDEX}.md` counts (20,384 → real distinct ~9,489; "0 broken" → 53).
- [ ] Re-run `etl/run_all.py` and confirm counts drop only by the pruned dupes.

### C. Roles (after corpus is clean)
- [ ] Define `roles/` specs: `role = {name, domain filter, skill set, permission posture}`.
- [ ] Seed from existing `~/.config/opencode/agents/kali-*.md` + foundry registry + atlas skills.
- [ ] Dry-run against tartarus.

## 5. Key commands

```bash
# atlas
ssh orcrist 'systemctl --user status reference-atlas reference-atlas-ingest.timer'
ssh orcrist 'cd ~/projetos/reference-atlas && python3 etl/run_all.py'      # idempotent
curl -s http://100.68.225.53:8770/api/overview | python3 -m json.tool

# inspect
ssh orcrist 'cd ~/projetos/reference-atlas && python3 -c "import sqlite3;c=sqlite3.connect(\"atlas.db\");print(c.execute(\"SELECT kind,COUNT(*) FROM entity GROUP BY kind\").fetchall())"'

# store census (read-only)
ssh orcrist 'find ~/agent-hub -name SKILL.md -type f | wc -l'   # real files only
ssh orcrist 'find ~/agent-hub -xtype l | wc -l'                 # broken symlinks
```

## 6. Traps / gotchas learned this session

- **NEVER count SKILL.md entries.** Count `-type f` and hash-dedupe. Naive counts are ~2x inflated
  (symlink farm + symlink target). Use **~9,489** as the real distinct skill count.
- **"agent-hub" is 4+ different things** — always use the resignated names from `CONVERGENCE.md`
  (`agent-hub-store`, `agent-hub-repos`).
- **A symlink is provenance, never an entity** — that's the modeling rule that fixed the inflation.
- orcrist has no `sqlite3` CLI — use `python3`. Disk constrained (~28G on /home).
- Port **8765** is taken (a2a-bus + agent-hub launchers share a PID file). Atlas is on **8770**.
- Two live Claude sessions can collide on this host. Check `tmux list-panes -a` and
  `~/.claude/projects/<proj>/*.jsonl` before assuming you're alone.

## 7. Files created this session

**orcrist `~/projetos/reference-atlas/`:** `db.py`, `server.py`, `launcher.sh`, `README.md`,
`static/index.html` (+ d3), `etl/{run_all,etl_twitter_archive,etl_agenthub,etl_agent_hub_store,reclassify}.py`,
`CONVERGENCE.md`, `HANDOFF-FROM-4.3.md`, this file.
**orcrist `~/agent-hub/`:** `CONVERGENCE.md`, `HANDOFF-FROM-4.3.md` (for the sibling session).
**systemd:** `~/.config/systemd/user/reference-atlas{,-ingest}.{service,timer}`.
**li:** `~/agent-knowledge/projects/agent-hub/harvest/{onetab_*,orcrist_ingest,reclassify}.py` + README;
`~/obsidian-vault/Research/OneTab Harvest — 2026-10-06.md`.