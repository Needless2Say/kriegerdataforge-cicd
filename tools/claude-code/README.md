# tools/claude-code. The KDF Code Review Process tooling

The guard, the fresh reviewer launcher, the wiring checker and the installer for the
[KDF Code Review Process](../../kit/common/docs/agent/CODE_REVIEW_PROCESS.md). They run on the owner's machine, in
Claude Code sessions. They are **not synced** to the other repos, the kit ships Markdown only (ADR D-028), so each
machine installs them from a clone of this repo.

| File | What it is |
| --- | --- |
| `kdf-guard.js` | A Claude Code PreToolUse hook. It reads each Bash and PowerShell command the way a shell does, each Read, Grep and Glob, and each file edit and outward facing tool call, and exits 2 to refuse with the reason. No dependencies, one file |
| `guard-cases.json` | The table the guard is held to, one case per tool call with its role and whether it is allowed or refused. Every rule change adds cases |
| `kdf-review.sh` | Starts one fresh Claude reviewer with the reviewer role in the repo folder itself, or opens and closes the folder for Codex, checking first that the pin is pushed, the folder is at it and the brief's counts match it. Compares git before and after and fails the review if the reviewer changed anything but a new file under `docs/reviews`, the review archive. Brings a report Codex wrote in the cloud in from its branch |
| `kdf-brief.js` | Read only. The facts a brief states, measured at the pin, the commit line and the scope table's line counts, and a check of a written brief's table |
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
   denies the Read tool the usual secret files. A machine set up before 2026-09-29 adds `Read|Grep|Glob` and
   `WebFetch|WebSearch` to its matcher first, then swaps `Read(**/.env.local)` in its deny list for
   `Read(**/.env.kdf)`, `Read(**/.env.dev)` and `Read(**/.env.prod)`, in that order, so the guard's `.env.local` rule
   is in place before the old deny rule goes.
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

**Secret files are closed to every session**, by the owner's decision of 2026-09-29. No session reads, writes,
copies, sources or passes one to a command, in the shell or to Read, Grep, Edit and Write. `test`, `[`, `ls`, `stat`
and `git check-ignore` may name one, since they only show that it exists. A secret file is every `.env` file but an
example and `.env.local`, backups such as `.env.local.bak` included, a `*.tfvars` git does not track, `*.pem` and
`keys/`. Terraform's committed `common.auto.tfvars` stays readable. The words
checked are the program, its arguments, the value after an `=`, a curl style `@file`, and a redirect's target, whatever
the program, so `--env-file=.env.prod`, `-d @.env.kdf` and `ls >.env.kdf` count. A search pattern such as `'^\.env'`
that names no file on disk is not a path. The owner's `.env.dev` and `.env.prod` get a message of their own. A stack or a test starts
through the repo's make target, which reads the file itself.

**`.env.local` opens to every session once its repo has adopted the env standard**, the owner's decision too, since
the standard (`skills.md`, ADR D-030) keeps only values that work on this machine there and every credential in
`.env.kdf`. It fails closed. A `.env.local` is open only where git tracks a `.env.kdf.example` beside it, and only
while it holds none of the credentials named there, on an active or a commented line, or built in, a non empty `GH_PACKAGES_PAT`, `GH_NPM_TOKEN`,
`KDF_OIDC_CLIENT_SECRET`, `KDF_SERVICE_KEY`, `AUTH_RESEND_API_KEY`, `AUTH_TWILIO_AUTH_TOKEN` or
`AUTH_ADMIN_EMAIL_PASSWORD`. Anywhere else it stays closed, since it may hold anything. The hub's
`vercel_api/.env.local`, which `vercel env pull` wrote, holds Vercel and database credentials no built in name covers.
The guard reads the file itself and never shows a value.

**Make targets that reach DEV or PROD are the owner's.** A target whose name holds `prod`, `production`, `deploy`,
`apply`, `destroy`, `publish`, `release`, `promote` or `rollout` is refused, and so is one that holds `dev` unless it
also holds `local`. The ecosystem's Makefiles name the remote environments `dev` and `prod` and the developer's own
machine `local`, so `make seed-dev-admins` and `make apply-prod` are refused while `make seed-local-dev-client`,
`make reseed-local` and `make ci` run. `ENVIRONMENT` or `HUB_ENV` set to `dev`, `prod` or `production` on a make
command is refused too. A new local target is named for `local`, never for `dev`. A package script run with `npm`,
`pnpm`, `yarn` or `bun` is held to the same words, so `npm run deploy`, `yarn release:prod` and `bun run promote` are
refused while `npm run dev`, `npm run build` and `npm test` run.

**cicd's ops scripts run in their read only mode only.** `rotate_secret.py --mode check`,
`distribute_app_secrets.py check` or `targets`, `distribute_kit.py check`, `distribute_scripts.py check` and
`provision_projects.py check` run. Every other mode is refused, and so is `trigger_triage.py`, which has no read only
mode. The owner runs the rest through the ops issue forms.

**Reviewer rules** apply on top when `KDF_ROLE=reviewer` is set, or the guard is started with `reviewer`. Read only
git, no GitHub CLI, no shell command that writes, deletes, installs or downloads, no redirect into a file,
no connector, artifact, message, schedule, notification, web fetch or web search tool, and file edits only for new
files under `docs/reviews`, never a tracked brief, plan, log or earlier report there. A reviewer reads the running
stack and never changes it. docker runs only `ps` and `logs`, their compose forms too, against this machine's daemon,
and curl reaches `localhost`, `127.0.0.1` or `[::1]` over http or https alone. curl takes an allow list of options,
so nothing writes a file, reads one with `@`, follows a redirect, goes through a proxy or a socket, or reaches port
2375, 2376 or 2019, the Docker Engine and Caddy admin APIs. The host is matched as text in one strict shape, so no
URL parser has to agree with curl's own, and a URL in any other shape is refused. Neither takes an environment
assignment such as `https_proxy=`. A reviewer follows
`.gitignore`, so Read, Grep, Glob and every shell program that prints a file are refused a path git ignores,
`.env.local` aside, and the reports the launcher holds in
`.git/kdf-review`. A recursive `grep`, `rg -u` or `--no-ignore`, and `git grep` or `git diff` with `--no-index` are
refused too, `git grep` and `rg` honour `.gitignore`. Glob still lists ignored names, which hold no value.

**The same rules for every other model.** The kit's `docs/agent/AGENT_ROLES.md` writes these roles and rules for any
model or tool, and it reaches them through `AGENTS.md`, `WORKFLOW.md`, which opens with it, and every review brief,
which states the reviewer's role in its own text. The guard is what makes the rules binding for Claude. For Codex the
launcher's prepare and collect, its own sandbox and GitHub's rulesets are, and nothing but that page keeps it from
reading a file in the folder. A new rule here is a new line there, in the same pull request.

The role comes from the environment the session was started in, so it works in any repo with no settings file in it.

```bash
cd <workspace>/<repo>
KDF_ROLE=reviewer claude rc --spawn=same-dir      # sessions opened from a phone
step=docs/reviews/2026-09-28-sdk/s1-foundation/step-2-review
bash <workspace>/kriegerdataforge-cicd/tools/claude-code/kdf-review.sh --repo . \
     --brief "$step/SDK_REVIEW_S1_PROMPT.md" --report "$step/SDK_REVIEW_S1_REPORT.md" \
     --codex-report "$step/SDK_REVIEW_S1_CODEX_REPORT.md" --pin <pin> --model <model> --effort max
```

Every review is archived in its own dated folder, `docs/reviews/<YYYY-MM-DD>-<scope>/`, with a folder per slice and
per step inside, as the process's section 3 lays out. `<step>` below is such a step folder, where the brief sits and
both reports land beside it. A report path is refused unless it is under `docs/reviews`, at any depth, and
`docs/security` holds posture docs no reviewer writes.

Whether a `claude rc` server passes the variable on to the sessions it spawns is not documented, so run the permission
test from the process, section 10, in the first session it opens.

## The launcher

`kdf-review.sh` checks its arguments, refuses to start a Claude reviewer unless `check-wiring.js` passes and the
installed guard passes two canary calls, snapshots git, runs `claude -p` with `KDF_ROLE=reviewer` and without the
owner's self edit switch, and snapshots again. The snapshot holds HEAD, the branch, every local ref, the stash count,
the index and the hash of every modified or untracked file. Remote tracking refs are left out, an editor's background
fetch moves them.

Every reviewer reads the repo folder itself, with no copy and no second environment, and runs the tests with the
repo's own environment. At a pinned commit, the way the process runs every review.

```bash
# Claude
bash kdf-review.sh --repo <repo> --brief <step>/<brief> --report <step>/<report> \
     --codex-report <step>/<codex report> --pin <pin> --model <model> --effort max
# Codex, the owner starts it by hand in the same folder
bash kdf-review.sh --repo <repo> --brief <step>/<brief> --report <step>/<report> \
     --codex-report <step>/<codex report> --pin <pin> --prepare
bash kdf-review.sh --repo <repo> --collect
# Codex in the cloud, which read the review branch on GitHub and handed its report back on a pull request's branch
bash kdf-review.sh --repo <repo> --codex-report <step>/<codex report> --pin <pin> --collect-branch <branch>
```

`--pin` checks that a branch of `origin` holds the pin, that the folder is at it with no tracked file changed, that the
brief is in it, and that the brief's scope table matches it, `kdf-brief.js check`. One review of a folder is open at a
time. A Claude run opens its review when claude starts and closes it when it ends.
`--prepare` opens the review, snapshots git, and prints the folder to open, the one line and the collect command.
`--collect` runs the same check, and since Codex has no guard, it is Codex's fence. A failed collect leaves the review
open, so the orchestrator puts right what the reviewer changed and collects again.

While a review is open, the other report of the scope waits in the repo's `.git/kdf-review/held` folder, out of the
working tree, and closing the review puts it back, never over a file. So Codex never sees Claude's report and Claude
never sees Codex's, whichever goes first. A Claude run cut off before it closed its review leaves it open, and
`--collect` closes it with exit 6 and puts the held report back.

`--collect-branch` fetches the branch of the pull request Codex in the cloud opened, checks that it is built on the pin
and adds nothing but new files under `docs/reviews`, and writes the report into the folder, never over one. It needs
no review open, since the cloud read GitHub and not the folder. The owner closes that pull request unmerged. Every
collect, and every Claude run, warns when a report's header does not name the pin or list what the reviewer read
first.

| Exit | Meaning |
| --- | --- |
| 0 | Clean. Only the report, and any new file under `docs/reviews`, changed |
| 2 | Bad arguments, a report path outside `docs/reviews`, a pin no branch of `origin` holds, a folder not at the pin, a brief the pin lacks or whose counts differ from it, a report that already exists, a cloud branch not built on the pin, or another review of the folder open |
| 3 | Contamination. The reviewer changed something it must not, every path is listed, nothing is reverted |
| 4 | The reviewer wrote no report |
| 5 | The guard is not wired, the installed guard failed its canary, or node, which a pinned review needs for the brief check, is missing |
| 6 | `claude` itself failed, or a Claude run was cut off before it closed its review |

`--dry-run` prints the one line prompt for Claude and for Codex, and the pin, and starts nothing. Without `--pin` a
Claude reviewer reads the folder as it stands. `KDF_CLAUDE_BIN` and `KDF_HOME` override the claude program and the
home directory, the tests use them.

## The brief's facts

```bash
node kdf-brief.js facts  --repo <repo> --pin HEAD                     # the state, its branch, the tip of main
node kdf-brief.js counts --repo <repo> --pin HEAD Code=src/pkg/auth "Tests=tests/unit/auth/*.py"
node kdf-brief.js check  --repo <repo> --pin HEAD <step>/<brief>
```

`facts` runs on the slice's state commit, before the brief's own commit, and prints the brief's "The commit" line. The
brief sits alone in the commit on top of the state, and that commit is the pin, so the line names the state and says
the pin is the commit that adds the brief, since no commit holds its own hash.

`counts` prints one scope table row per argument, every file it names at the pin with its line count, in the order a
row states them, ``| Code, `a.py`, `b.py` | 120, 1,203 |``. A path may be a directory or a glob. A line count is the
number of lines an editor shows, so a last line without a newline counts. `check` reads the brief at the pin, finds its
`| Files | Lines |` table, and compares each row, one count per path or one total for the row. A directory's files are
summed, and a row with a line range or a placeholder is skipped. It exits 1 on a count that differs or a path missing
at the pin, and the launcher runs it before every pinned review.

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

- The guard costs about 65 ms per guarded call, and only tools its matcher names pay it. Read, Grep and Glob pay it
  too since 2026-09-29, and a reviewer's read costs about 83 ms, since it also asks git whether the path is ignored.
- Line ends are pinned to LF for these files by `.gitattributes`. A carriage return breaks a shell script.
- Node is the runtime because it is present wherever Claude Code and the Next.js repos run. A Python guard would need
  an interpreter path on every machine.
