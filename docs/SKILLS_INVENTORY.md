# Skills & Tools Inventory — All Local Harnesses

> Consolidated map of every skill/tool/plugin/agent directory across the
> workstation fleet. Compiled 2026-10-06.
> Scope: Claude Code, OpenCode, pi, Hermes, Codex, Tartarus, and the
> open-format `~/.agents` tree — plus project-local and vault copies.

## Hosts

| Host | Address | Status | Notes |
|---|---|---|---|
| **kali** (this machine) | local | reachable | primary workstation |
| **orcrist** | `Host fabio` / `Host orcrist` (tailnet) | reachable | `Host fabio` == orcrist (same box) |
| **eu** | `100.95.148.46` (user `fabiofalopes`) | reachable | eu-2.local |
| **mac-studio** | `100.94.171.75` (user `csi`) | **AUTH FAIL** | `Permission denied (publickey)` — bridge key rejected |

---

## 1. kali (local) — by harness

### 1.1 Claude Code — `~/.claude/`
- `skills/` — **30 skills**
  - Obsidian suite: `broken-link-healer`, `fleeting-processor`, `glossary-builder`, `interactive-quiz`, `json-canvas`, `markdown-linter`, `moc-builder`, `obsidian-bases`, `obsidian-cli`, `obsidian-markdown`, `obsidian-stats`, `orphan-connector`, `serendipity-engine`, `smart-tagger`, `smart-web-clipper`, `toc-generator`, `zettel-atomizer`
  - Transcription: `ig-transcribe-yandex`, `instagram-transcribe`, `youtube-transcribe`, `todoist-integration`
  - TUI/harness driving: `hermes-tui`, `freebuff-tui`, `tmux-pane-interaction`, `teamwork`
  - Infra: `gpu-deploy`, `swarm-deploy`, `orchestration`, `code-review-expert`, `defuddle`
- `plugins/` — marketplaces: `claude-plugins-official` (anthropics/claude-plugins-official), `zai-coding-plugins` (local npm dir)
- `downloads/obsidian-skills-stage/tpitsunov/` — **staging** (upstream of installed obsidian set): 17 skills
- Root files: `settings.json`, `settings.local.json`, `settings-ollama.json`, `settings.json.lusofona`

### 1.2 Open-format shared — `~/.agents/`
- `AGENTS.md` — machine root agent instructions (principal, standing rules, sovereignty doctrine)
- `skills/` — **24 skills**: `archivist`, `browser-master`, `code-review-expert`, `connector`, `context-keeper`, `documentarian`, `inference-engineer`, `live-tidal-jam`, `orchestration`, `pi-harness-ops`, `structuralist`, `task-planner`, `tor-gateway`, `twitter-integration`, `vaultwarden-secret-management`, `wave-conductor`, `web-dj`, `archive` + bitgpt-lab ports (`bitnet-native-quant`, `llm-scratch-lab`, `model-diff-probe`, `nl2cmd-corpus`, `paper-deep-research`, `voice-ramble-to-plan`)
- Format: `SKILL.md` with YAML frontmatter (`name`, `description`)

### 1.3 OpenCode — `~/.config/opencode/`
- `skills/` — **48 skills**
  - Network/infra ops: `fortinet`, `fortigate-agentic`, `linux`, `network-monitoring`, `network-troubleshooting`, `network-self-healing`, `network-safety`, `osi-model`, `tcp-ip`, `narsil-proxmox-lxc`, `proxmox-lab-management`, `pop-cluster-management`, `pop06-stt-stability`, `self-hosted-vpn-mesh`, `ssh-helper-ops`, `sshx`, `server-inventory`, `endpoint-scout`, `mac-llm`, `mac-256-glm`
  - Harness/agent eng: `session-distillation`, `distill-to-harness`, `agent-failure-recovery`, `optimizer-loop`, `run-fleet-sessions`, `session-audit`, `agent-prompt-composer`, `skill-chain-composer`, `skill-judge`, `context-engineer-init`, `deepwork`, `verification-planning`
  - Prompt/style: `prompt-clarifier`, `prompt-creator`, `prompt-judge`, `clarity-engine-style`, `problem-reframer-style`, `extract-recommendations-style`, `deep-search-optimizer-style-v2`, `dimensional-extractor`, `dimension-graph-planner`, `iterative-brief-builder`, `frontmatter-gen`, `ai-deslop`
  - Transcription pipeline: `transcript-transform`, `transcription-quality-analyzer`, `transcription-refiner`, `transcription-pipeline`, `image-transcriber`, `groq-voice`
  - Misc: `repo-auditor`, `workspace-mapper`, `art-director`, `dimension-graph-planner`, `mcp-installer-validator`, `tartarus-dev`, `obsidian-gatekeeper`, `task-manager`, `valid-models-reference`, `diane-dashboard`, `artifact-triage`, `unlazy`, `project-tracker`, `reflect`, `simplify`, `worktrees`, `quick-commands`, `hermes-telegram`, `openmemory-rag-integration`, `z800-*` (context-awareness/certificate-mgmt)
- `skill-vault/harness-engineering/` — **15 curated harness-eng skills** ← *the most directly on-topic collection*: `agentic-loop`, `context-governance`, `control-plane-design`, `delegation-verification-state`, `error-recovery`, `harness-checklists`, `harness-introduction`, `harness-philosophies`, `harness-principles`, `multi-agent-verification`, `query-loop-design`, `rpi-bridge`, `skills-hooks-governance`, `team-adoption`, `tool-permissions-interrupts`
- `agent-loops/` — `fleet-optimizer`
- `agents/` — subagent defs: `diane.md`, `hermes.md`, `inference_engineer.md`, `kali-director.md`, `kali-exploit.md`, `kali-recon.md`, `mirror.md`, `vault_keeper.md`
- `commands/` — `browser-live.md`
- Config: `opencode.json(c)`, `oh-my-opencode-slim.json`, `playwright-mcp{,-tor}.json`, `tui.json`, `themes/`, `workspace/`

### 1.4 pi — `~/.pi/agent/`
- `skills/` — `gated-ops`, `orchestration` (**2**)
- `AGENTS.md`, `extensions/`, `bin/`, `sessions/`, models/settings + many `.bak`
- Not a git repo.

### 1.5 Hermes — `~/.hermes/`
- `hermes-agent/` — git clone of `github.com/NousResearch/hermes-agent.git`
  - `optional-skills/` — **19 categories**, nested SKILL.md: `autonomous-ai-agents` (antigravity-cli, blackbox, grok, honcho, openhands), `blockchain` (evm, hyperliquid, solana), `communication`, `creative` (baoyu-*, blender-mcp, concept-diagrams, hyperframes, kanban-video-orchestrator, meme-generation, pixel-art), `devops` (cli, docker-management, hermes-s6-container-supervision, pinggy-tunnel, watchers), `dogfood`, `email` (agentmail), `finance` (3-statement-model, comps-analysis, dcf-model, excel-author, lbo-model, merger-model, pptx-author, stocks), `gaming`, `health`, `mcp` (fastmcp, mcporter), `migration` (openclaw-migration), `mlops` (accelerate, chroma, clip, faiss, flash-attention, guidance, huggingface-tokenizers, instructor, lambda-labs, llava, modal, nemo-curator, …)
  - `skills/` — **18 categories** (apple, autonomous-ai-agents, computer-use, creative, data-science, dogfood, email, github, index-cache, media, mlops, note-taking, productivity, research, smart-home, social-media, software-development, yuanbao)
  - Runtime: `plugin bundles`, `hooks/`, `cron/`, `kanban.db`, `memories/`, `sandboxes/`, `state.db`, `SOUL.md`, `config.yaml`

### 1.6 Codex — `~/.codex/` — **exists but empty**

### 1.7 Tartarus — `~/.config/tartarus/skills/` — `godmode` (**1**)
- Repo: `git@github.com:fabiofalopes/tartarus.git` (`~/projects/tartarus`)

### 1.8 Shell — `~/.bashrc.d/`
- `skills/agent-browser` (1); `agent/AGENTS.md`

---

## 2. kali (local) — project-local skills

| Project | Skills |
|---|---|
| `~/projects/bitgpt-lab/skills/` | `bitnet-native-quant`, `llm-scratch-lab`, `model-diff-probe`, `nl2cmd-corpus`, `paper-deep-research`, `voice-ramble-to-plan` (6) |
| `~/.config/tartarus/skills/` | `godmode` |

## 3. kali (local) — shared hub & vault copies

| Location | Contents |
|---|---|
| `~/shared-local/skills/native/` | `aws-iam-privilege-escalation`, `c2-infrastructure-setup`, `llm-prompt-injection-testing` |
| `~/shared-local/hub/curated/_native/` | same three (mirror) |
| `~/shared-local/hub/curated/tools/` | `rtbt-agent-fabric` |
| `~/agent-knowledge/skills/` | 8: `critical-thinking`, `fortinet`, `linux`, `network-monitoring`, `network-troubleshooting`, `osi-model`, `tcp-ip`, `_template` |
| `~/agent-knowledge/projects/{agent-credential-manager,harmonic-army,proxmox-homelab-ecosystem,pop-win}/skills/` | project skills |
| `~/obsidian-vault/Knowledge/Skills/` | curated copies + `mac-inference` |
| `~/obsidian-vault/Projects/*/skills/` | vault mirrors of project skills |
| `~/obsidian-vault/kali-import/{skills,.forge/skills}/` | `inference-engineering-apple-silicon`, `tailnet-lab-ops`, `tailscale`, `cron-agent-swarm` |
| `~/breaking-claude/` | `AGENTS.md`, `vault/AGENTS.md` (no-git) |

## 4. kali (local) — harness-related repos

| Repo | Remote | Role |
|---|---|---|
| `~/projects/upb` | `git@github.com:fabiofalopes/upb.git` | **gateway / harness control plane** — `cli/`, `router/`, `config/` |
| `~/.hermes/hermes-agent` | `github.com/NousResearch/hermes-agent.git` | Hermes agent framework |
| `~/projects/tartarus` | `git@github.com:fabiofalopes/tartarus.git` | Tartarus harness (DESIGN.md, eval/, flake.nix) |
| `~/breaking-claude` | no-git | research |
| `~/agent-knowledge/{projects/agentic-harness, projects/harness-research, lost-treasures/harness-research}` | no-git | harness research notes + `AGENTS.md` |

---

## 5. orcrist (`Host fabio` — same box)

| Location | Count | Notes |
|---|---|---|
| `~/.config/opencode/skills/` | **~65** | **superset of local**: adds `run-fleet-sessions`, `optimizer-loop`, `endpoint-scout`, `sshx`, `session-audit`, `mac-llm`, `mac-256-glm`, `valid-models-reference`, full prompt-* suite, `skill-judge`/`frontmatter-gen` |
| `~/.config/opencode/skills-archive/` | z800-* | also mirrored locally |
| `~/.agents/skills/` | **20** | **unique**: `runpod`, `runpodctl`, `runpod-mcp`, `runpod-migrate`, `runpod-templates`, `runpod-usage`, `orca-cli`, `companion-clis`, `flash`, `sharepoint-m365`, `prime-intellect` |
| `~/.claude/skills/` | **14** | runpod suite + `obliteratus`, `hermes-tui`, `code-review-expert`, `orchestration` |
| `~/.pi/agent/skills/` | **13** | runpod suite, `sleepy-agent`, `prime-intellect`, `flash`, `companion-clis`, `orca-cli` |
| `~/.hermes/skills/` | categorized | `agent-hub`, `agent-thought-log`, `agent_thought_log`, `apple`, `automation`, `autonomous-ai-agents`, `cloud-gpu-providers`, `companion-clis`, `creative`, `data-science`, `devops`, `diagramming`, `domain`, `email`, `external-model-lanes`, `feeds`, `flash`, `freebuff`, `freebuff-tui`, `gaming`, `gates`, `gateway-detached-restart`, `gifs`, `github`, `hermes-agent`, `hermes-tui`, `inference-sh`, `mcp`, `media`, `mlops`, … |
| `~/projetos/{agentic-workspace,breaking-claude,proxmox-homelab-ecosystem,agent-credential-manager,pop-win,harmonic-army}/skills/` | project | incl. `hermes-claude-{code,providers,routing}`, `secure-secret-handling`, `llama-cpp-skills` |
| `~/.claude/plugins/` | `task-manager` | |

## 6. eu (`eu-2.local`)

| Location | Notes |
|---|---|
| `~/.config/opencode/skills/ptpt-filter/` | |
| `~/.codex/skills/` | `workplace-account-editor`; `.system/`: `skill-creator`, `plugin-creator`, `skill-installer`, `openai-docs`, `imagegen`, `review-agent` |
| `~/.hermes/skills/` | `software-development/` (test-driven-development, systematic-debugging, plan, codebase-inspection, spike, requesting-code-review, simplify-code, python-debugpy, node-inspect-debugger, dogfood, github, hermes-agent-skill-authoring, inspecting-hermes-desktop-dom), `research/` (grounded-citations, blogwatcher, competitor-news-monitor, polymarket, llm-wiki, research-paper-writing), `apple/`, `devops/sdlc-review`, `data-science/jupyter-live-kernel`, `social-media/xurl`, `.archive/` |
| `~/projetos/hub/skills/` | `session-distillation`, `distill-to-harness` |
| `~/mac-llm/remote/SKILL.md` | |
| `~/.obsidian-vault-backups/*/.opencode/AGENTS.md` | vault backups |

## 7. mac-studio — **UNREACHABLE**

`csi@100.94.171.75: Permission denied (publickey,keyboard-interactive)`.
Key `~/.ssh/id_ed25519_bridge_100.94.171.75` present but rejected.
Content unknown until auth fixed.

---

## 8. Cross-host observations (for the "how to use" phase)

1. **Split-brain**: same skills live in different sets across `~/.claude/skills`, `~/.agents/skills`, `~/.config/opencode/skills`, `~/.pi/agent/skills`. orcrist has a superset of OpenCode skills and unique `.agents` runpod tooling not synced back to kali.
2. **`~/.agents/skills` is the de-facto open-format home** — harness-agnostic, works everywhere; kali and orcrist have drifted in both directions.
3. **Only explicitly harness-focused collection**: `~/.config/opencode/skill-vault/harness-engineering/` (15).
4. **Operational tooling** lives in orcrist `~/.hermes/skills/` (`gates`, `external-model-lanes`, `inference-sh`).
5. **Duplicated 3–4×**: `orchestration`, `code-review-expert`, `session-distillation`/`distill-to-harness`, entire runpod suite.
6. **Staging not yet promoted**: `~/.claude/downloads/obsidian-skills-stage/tpitsunov/` (17) supersets the installed obsidian set.

## 9. Open questions / next steps

- [ ] Fix mac-studio auth and complete its inventory.
- [ ] Decide canonical source of truth (proposal: `~/.agents/skills` open format, symlinked/exported per harness).
- [ ] Dedup + reconcile kali ↔ orcrist drift; promote staging set.
- [ ] Then: "how do we use them" — routing/loading design across the fleet.