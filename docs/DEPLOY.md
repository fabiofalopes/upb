# Deploy — repo → live

The live router runs on **LXC 165 `gas-router-exp`** (narsil, `192.168.80.10`),
repo at `/opt/upb`, service `upb-router.service` (`node dist/index.js` from
`/opt/upb/router`). Deploying means: get the branch to the LXC, check it out,
build, restart.

## Remotes

| Remote | URL | Notes |
|---|---|---|
| `origin` | `git@github.com:fabiofalopes/upb.git` | **SSH only.** The https credential in the local store is denied write (403); GitHub SSH auth is verified working. |
| `lxc165` | `ssh://root@192.168.80.10/opt/upb` | Key-based (workstation key authorized 2026-09-17, comment `upb-deploy`). |

## Standard deploy

```bash
# 1. Local validation (must be green before anything moves)
cd router && npm test        # build + node --test (14 tests)

# 2. Push
git push origin <branch>
git push lxc165 <branch>

# 3. On the LXC: checkout + build + restart
ssh root@192.168.80.10 'git -C /opt/upb checkout <branch> && cd /opt/upb/router && npm run build && systemctl restart upb-router'
```

**Never push the branch that is currently checked out on the LXC** — git
refuses it (`receive.denyCurrentBranch`). Checkout explicitly, as above.
After any router change, verify `/health` shows `lanes` non-empty.

## Rules

- **Restart = brief fail-closed 503s.** Avoid restarting `upb-router` or
  `pf-screen` during working hours without warning.
- **Secrets never travel through context.** `router.env`
  (`/root/.config/upb/router.env`) and `secrets.env` are never `cat`ed. To wire
  a secret into new config, redirect between files on the box itself.
- **Any new port follows the iptables unit pattern.** `upb-router.service`
  allowlists `:8705` for `192.168.80.14` + `.8` via `ExecStartPre` rules; a new
  port with no equivalent unit pattern is LAN-open.
- **llm-prod (`192.168.80.2`) is production, local-only.** Experiments live on
  LXC 165. Never touch llm-prod config.

## Fallback: bundle transfer

If SSH to the LXC is unavailable, move history by bundle (no creds needed):

```bash
git bundle create /tmp/upb.bundle --all
scp /tmp/upb.bundle narsil:/tmp/
# then on narsil: pct push 165 /tmp/upb.bundle --dest /tmp/
# on LXC: git -C /opt/upb fetch /tmp/upb.bundle '<branch>:<branch>'
```
