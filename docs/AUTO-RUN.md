# Auto-run: making Hermes stop asking "can I run this?"

**Status:** implemented 2026-10-23. See `docs/AUTO-RUN.md` for the full guide.

## The problem

Hermes classifies a command as *dangerous* and prompts. The prompt has four
answers — `once` / `session` / `always` / `deny` — and the friction is
repeating the same decision for the same shape of command.

Three levers, in increasing order of how much they buy you:

| Lever | Where | Scope | Safety |
|---|---|---|---|
| **smart mode** (default) | `approvals.mode: smart` | an auxiliary LLM judges each command | catches real danger; can still escalate |
| **command_allowlist** | `config.yaml` → `command_allowlist` | exact command text / patterns you approve once | only what you list |
| **yolo** | `--yolo` flag, `/yolo`, or `approvals.mode: off` | everything, this process/session | only `approvals.deny` still blocks |

## The recommended setting for this machine

`approvals.mode: smart` is already the default and already what this session
runs. That is the right default — it is the only mode that reduces prompts
*without* removing the safety net.

For the commands that still prompt, `hermes approvals suggest` mines the
session database for what you have already approved and proposes allowlist
entries:

```console
$ hermes approvals suggest --days 30
Proposed command_allowlist additions (from approval history, last 30 days):

  1. package manager uninstall    — approved 1x (class key)

Nothing has been changed. Apply selected entries with:
  hermes approvals suggest --apply 1,3
```

Destructive classes (recursive delete, sudo, disk writes, credential edits) are
**never** proposed — the miner skips them by design.

## The escape hatches

```console
hermes --yolo                    # this process only
/yolo                             # this session, from inside a chat
hermes config set approvals.mode off   # persistent, all sessions
```

`approvals.mode: off` is equivalent to `HERMES_YOLO_MODE=true`. It disables
approval checks for terminal commands entirely.

**The floor that survives all of it:** `approvals.deny` is a list of fnmatch
globs that block matching commands **unconditionally** — even under `--yolo`,
`/yolo`, or `mode: off`. It is the one thing that cannot be bypassed.

```yaml
approvals:
  deny:
    - "git push --force*"
    - "rm -rf /*"
```

Set this BEFORE turning approvals off. It is what makes `mode: off` a
reasonable choice on a machine with real work on it.

## Non-terminal surfaces

Terminal commands are the loud part, but three other surfaces prompt too, and
they have their own switches:

- `approvals.mcp_reload_confirm` — `/reload-mcp` before rebuilding the tool set
- `approvals.destructive_slash_confirm` — `/clear`, `/new`, `/reset`, `/undo`
- `approvals.single_query_mode` — one-shot (`-q`) sessions, where no human is
  watching. Default `deny`; set `approve` to auto-approve there.
- `approvals.cron_mode` — scheduled jobs. Default `deny`.
- `approvals.unattended_mode` — messaging platforms with no one watching.

For a self-hosted personal agent, `single_query_mode: approve` is usually
right — a `-q` session is one you deliberately fired off.

## Why "smart" beats "off" here

Smart mode spends one auxiliary LLM call per flagged command and auto-approves
the safe ones. That call is cheaper than the interruption. It also survives
because it does not need a human in the loop at all — which is what makes it
work from cron, from a messaging gateway, and from a delegated subagent.

`mode: off` treats every command as trusted. On a laptop that also holds your
SSH keys, your vault, and your provider credentials, that is a bigger bet than
it looks — especially with a model that can be steered by content it reads.

## The middle path worth knowing about

`approvals.smart_policy` appends your own rules to the smart-approval
guardian's system prompt (the trusted channel, never alongside the untrusted
command text):

```yaml
approvals:
  smart_policy: |
    Always ESCALATE commands that modify anything under /etc.
    APPROVE docker compose restarts in ~/deploys — they are routine here.
```

That gets you "never stop asking me about `docker compose restart`" without
giving up the guard on anything else. It is the most surgical lever of the
four.
