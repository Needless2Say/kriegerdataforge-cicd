# tools/claude-code. The KDF Code Review Process tooling

The guard, the fresh reviewer launcher, the wiring checker and the installer for the
[KDF Code Review Process](../../kit/common/docs/agent/CODE_REVIEW_PROCESS.md). They run on the owner's machine, in
Claude Code sessions. They are **not synced** to the other repos, the kit ships Markdown only (ADR D-028), so each
machine installs them from a clone of this repo.

| File | What it is |
| --- | --- |
| `kdf-guard.js` | A Claude Code PreToolUse hook. It reads each Bash and PowerShell command the way a shell does, and each file edit and outward facing tool call, and exits 2 to refuse with the reason. No dependencies, one file |
| `guard-cases.json` | The table the guard is held to, one case per tool call with its role and whether it is allowed or refused. Every rule change adds cases |
| `kdf-review.sh` | Starts one fresh Claude reviewer in a repo with the reviewer role, then compares git before and after and fails the run if the reviewer changed anything but a new file under `docs/security` |
| `check-wiring.js` | Read only. Says whether this machine's settings wire the guard as the process needs, and prints the block to add when they do not |
| `install.sh` | Copies the guard to `~/.claude/hooks/`, smoke tests it, and prints the settings block. It edits no settings and refuses to run inside a Claude Code session |

## Set up a machine

Once per machine, by the owner, in a terminal. Git Bash on Windows.

1. Clone this repo, and `git pull` it whenever the guard changes.
2. `bash tools/claude-code/install.sh`. It copies `kdf-guard.js` to `~/.claude/hooks/`, proves it refuses a push to
   `main` and a reviewer's `git add` and allows `git status`, and prints a settings block.
3. Merge the block into `~/.claude/settings.json` by hand. `defaultShell` and `hooks` are top level keys. The
   `permissions.deny` list merges with yours, so keep your existing rules and add the new entries beside them. The
   block sets Git Bash as the default shell, denies the PowerShell tool, hooks the guard on the tools it must see, and
   denies the Read tool the usual secret files.
4. `bash tools/claude-code/install.sh --check`. Every line should pass. Then restart every session and every
   `claude rc` server, a running session keeps the settings it started with.
5. In each repo the owner reviews, set the ruleset's bypass to "For pull requests only" and require the repo's CI gate
   as a status check. Without that GitHub cannot tell a session from the owner, both are the same login.

The hook command names the guard by absolute path, so the block differs per user. `check-wiring.js --print` fills in
this machine's path. Repeat the steps on every machine, the settings file is not shared between them.

The installer never edits `settings.json`, and the guard will not let a session do it either, settings, hooks, the MCP
list and git hooks are protected files. When the owner wants a session to edit one, the owner starts that session with
`KDF_GUARD_ALLOW_SELF_EDIT=1`, a session cannot set it for itself.

## The two roles

**Owner rules** apply to every session in every repo. Nothing merges, approves, marks ready, tags, releases,
dispatches a workflow, re-runs, cancels or deletes a workflow run, publishes a package, runs `terraform apply` or
`destroy`, runs `vercel`, or pushes to `main`. The guard reads every spelling of those, including `git -C`, a nested
`bash -c`, an `env` prefix quoted or not, a command after a shell keyword such as `do`, `then` or `!`, `cmd //c`,
`env -S` and PowerShell. A push names its branch and goes to `origin`, and force, delete, tag, mirror and
`--no-verify` pushes are refused, as are `git send-pack` and `git http-push`. Git settings that run commands or change
where code goes, aliases, hooks paths, credential helpers, protocols and remote URLs, are refused whether they are
written with `git config` or passed with `git -c`, and so are `gh gist`, deploy keys and account keys.

**Make targets that reach DEV or PROD are the owner's.** A target whose name holds `prod`, `production`, `deploy`,
`apply`, `destroy`, `publish`, `release`, `promote` or `rollout` is refused, and so is one that holds `dev` unless it
also holds `local`. The ecosystem's Makefiles name the remote environments `dev` and `prod` and the developer's own
machine `local`, so `make seed-dev-admins` and `make apply-prod` are refused while `make seed-local-dev-client`,
`make reseed-local` and `make ci` run. `ENVIRONMENT` or `HUB_ENV` set to `dev`, `prod` or `production` on a make
command is refused too. A new local target is named for `local`, never for `dev`.

**cicd's ops scripts run in their read only mode only.** `rotate_secret.py --mode check`,
`distribute_app_secrets.py check` or `targets`, `distribute_kit.py check`, `distribute_scripts.py check` and
`provision_projects.py check` run. Every other mode is refused, and so is `trigger_triage.py`, which has no read only
mode. The owner runs the rest through the ops issue forms.

**Reviewer rules** apply on top when `KDF_ROLE=reviewer` is set, or the guard is started with `reviewer`. Read only
git, no GitHub CLI, no shell command that writes, deletes, installs or downloads, no redirect into a file, no secret
file, no connector, artifact, message, schedule or notification tool, and file edits only under `docs/security`.

The role comes from the environment the session was started in, so it works in any repo with no settings file in it.

```bash
cd <workspace>/<repo>
KDF_ROLE=reviewer claude rc --spawn=same-dir      # sessions opened from a phone
bash <workspace>/kriegerdataforge-cicd/tools/claude-code/kdf-review.sh --repo . \
     --brief docs/security/SDK_REVIEW_S1_PROMPT.md --report docs/security/SDK_REVIEW_S1_REPORT.md \
     --model <model> --effort max --codex-report docs/security/SDK_REVIEW_S1_CODEX_REPORT.md
```

Whether a `claude rc` server passes the variable on to the sessions it spawns is not documented, so run the permission
test from the process, section 10, in the first session it opens.

## The launcher

`kdf-review.sh` checks its arguments, refuses to start unless `check-wiring.js` passes and the installed guard passes
two canary calls, snapshots git, runs `claude -p` in the repo with `KDF_ROLE=reviewer` and without the owner's self
edit switch, and snapshots again. The snapshot holds HEAD, the branch, every ref, the stash count, the index and the
hash of every modified or untracked file.

| Exit | Meaning |
| --- | --- |
| 0 | Clean. Only the report, and any new file under `docs/security`, changed |
| 2 | Bad arguments. The report must be a new file under `docs/security`, the brief must exist inside the repo |
| 3 | Contamination. The reviewer changed something it must not, every path is listed, nothing is reverted |
| 4 | The reviewer wrote no report |
| 5 | The guard is not wired, or the installed guard failed its canary |
| 6 | `claude` itself failed |

`--dry-run` prints the one line prompt for Claude and for Codex and starts nothing. `KDF_CLAUDE_BIN` and `KDF_HOME`
override the claude program and the home directory, the tests use them.

## What the guard cannot stop

A one line Python or Node script can still write anywhere, and no command reader sees inside it. That is why the
launcher checks git afterward. The guard is a fence against a session's mistakes and against text that leads it
astray, it is not a sandbox against a determined program. The permission deny rules in `settings.json` stay as a
second fence, and the rulesets on GitHub, with the admin bypass set to pull requests only, are the last.

What it cannot read, by design. A program named through a variable (`c=gh; $c pr merge`) or built by a command
substitution, a letter escaped with a backslash, what a script it runs does inside itself (`bash script.sh`,
`python -c`), and a direct call to a repo's seed or migration code with the environment pointed at DEV or PROD by
hand. Each of those is a deliberate way around a rule, and a session that writes one has stopped following the
process.

Running a file in a protected folder counts as touching it, so `node ~/.claude/hooks/kdf-guard.js` is refused inside a
session. To try the installed guard, feed the same input to this folder's copy, which `check-wiring.js` confirms is
byte identical.

## Changing a rule

1. Add the cases to `guard-cases.json` first, one that must be refused and one that must still be allowed.
2. Change `kdf-guard.js`.
3. `make test` runs every case, in parallel, and the launcher, checker and installer tests.
4. Run `bash tools/claude-code/install.sh` on each machine, then `install.sh --check`.

A crash in the guard exits 1, which Claude Code treats as a non blocking error. That is deliberate, a bug here must
never stall a session. `KDF_GUARD_LOG=<file>` appends a line per refusal when the owner wants to see what a session
tried. To switch the guard off, remove its hook from `settings.json`.

## Notes

- The guard costs about 65 ms per guarded call, and only tools its matcher names pay it.
- Line ends are pinned to LF for these files by `.gitattributes`. A carriage return breaks a shell script.
- Node is the runtime because it is present wherever Claude Code and the Next.js repos run. A Python guard would need
  an interpreter path on every machine.
