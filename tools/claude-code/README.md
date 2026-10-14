# tools/claude-code. The KDF Code Review Process tooling

The guard, the fresh reviewer launcher, the wiring checker and the installer for the
[KDF Code Review Process](../../kit/common/docs/agent/CODE_REVIEW_PROCESS.md), the one way a session asks Codex for a
second opinion, and the one way it runs a Linux pre-flight. They run on the owner's machine, in Claude Code sessions.
They are **not synced** to the other repos, the kit ships Markdown only (ADR D-028), so each machine installs them
from a clone of this repo.

| File | What it is |
| --- | --- |
| `kdf-guard.js` | A Claude Code PreToolUse hook. It lets a Bash command through only when it is plain and on the owner's approved list (D-068), asks the owner before a removal, and checks each Read, Grep and Glob, each file edit and each outward facing tool call. It exits 2 to refuse with the reason. No dependencies, one file, the list inside it |
| `guard-cases.json` | The table the guard is held to, one case per tool call with its role and whether it is allowed, refused or asked. Every rule change adds cases |
| `kdf-review.sh` | Starts one fresh Claude reviewer with the reviewer role in the repo folder itself, for at most four hours by default, or opens and closes the folder for Codex, checking first that the pin is pushed, the folder is at it and the brief's counts match it. Compares git before and after and fails the review if the reviewer changed anything but a new file under `docs/reviews`, the review archive. A Claude run's log is claude's stream, one JSON event a line as the run goes, so a detached run is watched by its log, and after a clean run the launcher writes Claude Code's own count of it beside the report, `<report stem>.usage.json`, from the stream's last result event. Brings a report Codex wrote in the cloud in from its branch, and warns when a report it did not start lacks its time or usage line |
| `kdf-brief.js` | Read only. The facts a brief states, measured at the pin, the commit line and the scope table's line counts, a check of a written brief's table, and every `file:line` cite of the living docs beside the lines it names |
| `kdf-retro.js` | Read only. The numbers a slice's retrospective starts from, counted from its answer key, the launcher's counts beside its reports or else their headers, and its Sol rounds, the escapes first |
| `kdf-ask-codex.sh` | Asks Codex for a read only review of a change, a plan or a decision, the one way every session does (D-052, D-053). Gives Codex a detached worktree of a commit, or a throwaway repo of a folder of patches with no secret file, link or token in it, sets the session's question in the standard frame, runs Codex with the verified flags and archives its answer in the workspace's `codex-archive`, never in a repo or in `temp` (D-069). Refuses a reviewer, and fails when Codex changed its folder or wrote no answer |
| `kdf-preflight.sh` | Runs a repo's CI lanes on Linux in a container, the one way a session runs a Linux pre-flight (D-072). Exports a commit as an LF tar, builds the image in `preflight/` with `docker build` alone and options on the guard's list, and reads each lane's result from marker lines a last step prints. Refuses a docker pointed at another machine, a dirty tree with no `--at`, a tracked secret file and an owner only lane |
| `preflight/` | The pre-flight's image, `Dockerfile`, Python 3.14.7 slim by digest with git, make, ShellCheck, Node and actionlint, and `lanes.sh`, which runs the lanes inside it |
| `check-wiring.js` | Read only. Says whether this machine's settings wire the guard as the process needs, and prints the block to add when they do not |
| `kdf-compact.js` | A Claude Code SessionStart hook for the work records (D-058). After a compaction or a resume it prints the paths of the open records the session wrote, read from its own transcript, and nothing for a reviewer or a subagent. It never blocks |
| `install.sh` | Stages the guard in `~/.claude/hooks/`, smoke tests the staged copy, then puts it in place and keeps the previous one, copies `kdf-compact.js`, and prints the settings block. It edits no settings and refuses to run inside a Claude Code session |

`../codex-cloud/kdf-codex-install.sh` and `../codex-cloud/kdf-codex-start-skill.md` are not run here. The owner pastes
them into a repo's Codex cloud environment as its Install script and Start skill, on trial for the kdf-sdk's S2 (ADRs
D-039 and D-048), and the process's section 11 says how.

## Set up a machine

Once per machine, by the owner, in a terminal. Git Bash on Windows.

1. Clone this repo, and `git pull` it whenever the guard changes.
2. `bash tools/claude-code/install.sh`. It stages `kdf-guard.js` in `~/.claude/hooks/`, proves the staged copy
   refuses a push to `main`, a reviewer's `git add`, a Read of `.env.kdf` and input that is not JSON and allows
   `git status`, then puts it in place and keeps the previous one as `kdf-guard.prev.js` when it differs. It copies
   `kdf-compact.js` beside it and prints a settings block, whose guard command ends with `|| exit 2`.
3. Merge the block into `~/.claude/settings.json` by hand. `defaultShell` and `hooks` are top level keys. The
   `permissions.deny` list merges with yours, so keep your existing rules and add the new entries beside them. The
   block sets Git Bash as the default shell, denies the PowerShell tool, hooks the guard on the tools it must see, and
   denies the Read tool the usual secret files. A machine set up before 2026-09-29 adds `Read|Grep|Glob` and
   `WebFetch|WebSearch` to its matcher first, and one set up before D-060 adds `Monitor`, which runs a shell
   command like Bash, to the matcher of every guard line, then swaps `Read(**/.env.local)` in its deny list for
   `Read(**/.env.kdf)`, `Read(**/.env.dev)` and `Read(**/.env.prod)`, in that order, so the guard's `.env.local` rule
   is in place before the old deny rule goes.
4. `bash tools/claude-code/install.sh --check`. Every line should pass, and a WARN is a step still to do, though the
   last line says all checks passed. A repo whose `.claude/settings.local.json` also runs the guard, with `reviewer`,
   ends that line with `|| exit 2` too, which the check does not read. Then restart every session and every
   `claude rc` server, a running session keeps the settings it started with.
5. In each repo the owner reviews, set the ruleset's bypass to "For pull requests only" and require the repo's CI gate
   as a status check. Without that GitHub cannot tell a session from the owner, both are the same login.

The hook command names the guard by absolute path, so the block differs per user. `check-wiring.js --print` fills in
this machine's path. Repeat the steps on every machine, the settings file is not shared between them.

The installer never edits `settings.json`, and the guard will not let a session do it either, settings, hooks, the MCP
list, git hooks and git's own config, a repo's `.git/config`, `~/.gitconfig`, `~/.config/git/config` and the system's
`etc/gitconfig`, are protected files, each path folded first so a `./` or `../` in it names the file it leads to. So
is what loads into a session, `~/.claude/skills`, `agents`, `commands` and `plugins`, Codex's `config.toml`, `rules`,
`hooks.json` and `AGENTS.md`, Claude Code's and Codex's managed folders and the owner's administrator folder (D-066),
and the shell's and PowerShell's profile files, which set the PATH, aliases and functions a command meets (D-068).
Only the owner edits them, by hand. `KDF_GUARD_ALLOW_SELF_EDIT` is gone (D-068).

## The approved list

The guard lets a Bash command through only when it is plain and every program in it is on the owner's list, `LIST`
in `kdf-guard.js`, with the subcommands and flags written there (D-068, the owner's word of 2026-10-12). Everything
else is refused, and the reason says to write the command another way or ask the owner, who runs it or adds it to the
list by pull request. The owner's rules below still hold for a listed program, so `git` is listed and a push to `main`
is still refused.

**Plain** means words, single quotes, double quotes holding no `$`, backtick or backslash, `&&`, `||`, `;`, `|`, a
newline and a `#` comment, and a redirect that writes only into a temp folder or `/dev/null`. So the guard reads a
command exactly as bash runs it. A `$`, a backtick, a heredoc, a loop, a function, a subshell, a brace, a background
`&`, `eval`, `source` and a variable set for a command, but for eight fixed pairs such as `PYTHONUTF8=1`, are
refused. A commit message goes in a file, `git commit -F`, or in single quotes, and a pull request's body in a file,
`gh pr create --body-file`. A program is a bare name, or a repo's venv interpreter, `<repo>/.venv/Scripts/python.exe`,
or a `.sh` script by its path. Inline code, `python -c`, `node -e` and `bash -c`, is refused, while a script file runs
as it is, the owner's word that scripts run unread. A `cd` is followed, down both outcomes of `&&` and `||`, so a
path after it is judged from every folder the shell could be in.

**The groups on the list.** Reading and searching, `cat`, `head`, `tail`, `grep` without `-r`, `rg` without
`--hidden`, `-u` or `--no-ignore`, `sed` and `awk` with scripts that neither write, read nor run anything, `find`
without `-delete` or `-exec`, and the like. Making files, `mkdir`, `touch`, `cp`, `mv`, and `tee` into a temp folder.
git's reading and writing subcommands, gh's reading verbs and `pr create` and `comment`, `make`, the venv python on a
file or a module, `node` on a file, `bash` on a script, `npx` of the repo's own tools, `npm` install, run, audit and
ls, docker's reading commands, `build`, `cp`, `start`, `stop` and `compose up`, `down`, `ps`, `logs` and `build` on
this machine's engine, `curl` to this machine alone on the reviewer's curl rules, the owner's choice of 2026-10-12,
`terraform fmt`, `validate` and `version`, and `claude --version` and `codex login status`. `timeout`, `xargs`, `env`,
`nohup`, `docker exec` and `run`, and `compose exec` and `run` are not on the first list, each to come back with a
check of its own. `taskkill` stays off, the owner's choice, since a broad one stops every `node`.

**A removal asks the owner.** A command that deletes a file or a folder, discards uncommitted work or writes over a
file, `rm`, `git clean`, `git reset --hard`, `git checkout -- <path>`, `git branch -D`, `npm ci`, a `make` target named
for cleaning, `docker volume rm`, and `cp` or `mv` onto a file that exists among them, answers with a permission
decision of ask, the command and what it removes in the prompt. Before one, a session says what each removal deletes
and why. A removal runs without asking when every path it names is written out and lies in a temp folder, the
session's scratchpad, the system's temp folder or `D:/KriegerDataForge/temp`, outside every git working tree, the
owner's word that temporary files may be deleted. A plain `git worktree remove` of a worktree there runs, since git
refuses one with work never committed. A reviewer removes nothing. In `claude -p`, where no one can answer, Claude Code
denies the call.

**The trial.** `node kdf-guard.js --log` decides every call as the guard would and lets it through, writing each
decision to `~/.claude/kdf-guard-trial.log`, so the owner runs it beside the installed guard for a week before it
refuses anything, and counts what it would refuse and ask. `KDF_GUARD_MODE=enforce`, set when the owner starts a
session, makes that session's trial copy enforce.

## The two roles

**Owner rules** apply to every session in every repo. Nothing merges, approves, marks ready, tags, releases,
dispatches a workflow, re-runs, cancels or deletes a workflow run, publishes a package, runs `terraform apply` or
`destroy`, runs `vercel`, or pushes to `main`. Since the approved list refuses every command it cannot read plainly,
a nested shell, a wrapper such as `env` or `timeout`, a variable and PowerShell among them, these rules meet each
command as bash runs it (D-068). A push names its branch and goes to `origin`, spelled exactly, and carries
only `-u` or `--set-upstream`, `-q` or `--quiet`, `-v` or `--verbose`, `-n` or `--dry-run`, `--porcelain`,
`--progress`, `--no-progress` or `--atomic`, each in full, since another option can take the next word as its value
and leave a URL where the remote should be, and git reads an abbreviation as the option it shortens. Force, delete,
tag, mirror and `--no-verify` pushes are refused, as are `git send-pack` and `git http-push` (D-062). The one push to
`main` it lets through
is a plain `git push origin main`, the whole call, in `kriegerdataforge-context`, judged by its fetch and push URLs,
with `main` checked out and every commit since `origin/main` changing `STATUS.md` alone, read after a fetch (D-046).
Any doubt, a GIT_ variable that moves git, a merge, an empty commit or a git error, refuses it. Git settings that run
commands or change
where code goes, aliases, hooks paths, credential helpers, protocols and remote URLs, are refused whether they are
written with `git config`, in its older options or its subcommands, or passed with `git -c`, every word of a `git
config` judged as a key, and a read of a protected config file through `git config --get` or `get` stays open. So
are `git config edit` and a moved or removed section, an abbreviation of either option included. The list then lets
`git config` only read, and refuses `git -c` and a variable set for a command, so no setting reaches git through a
call (D-068). And so are `gh gist`, deploy keys and account keys.

**Secret files are closed to every session**, by the owner's decision of 2026-09-29. No session reads, writes,
copies, sources or passes one to a command, in the shell or to Read, Grep, Edit and Write. `test`, `ls`, `stat` and
`git check-ignore` may name one, since they only show that it exists. A secret file is every `.env` file but an
example and `.env.local`, backups such as `.env.local.bak` included, a `*.tfvars` git does not track, `*.pem` and
`keys/`. Terraform's committed `common.auto.tfvars` stays readable. The words
checked are the program, its arguments, the value after an `=`, a curl style `@file`, and a redirect's target, whatever
the program, so `--env-file=.env.prod`, `-d @.env.kdf` and `ls >.env.kdf` count. A search pattern such as `'^\.env'`
that names no file on disk is not a path. A glob, a `*`, `?` or `[` outside quotes, `".e"nv*` included, is judged by
what it can match (D-060). The call is judged as written, then again for each path the glob matches in the folder it
runs in, whole and in the form bash gives it, and for the whole list, so a match meets every rule a named path or
word meets, a secret file, a reviewer's ignored or held path, a protected one, or git's branch, and these extra
judgments can only refuse. A bracket expression counts as any one character, which matches more than bash, never
less. One whose last part starts with a dot and could match a secret's name, `.env*` or `.e[n]v.kdf`, is refused
wherever it runs, since a `cd` earlier in the line can move it, and `cat *` refuses only where a secret file is
there. A glob quoted whole is a pattern. The owner's `.env.dev` and `.env.prod` get a message of their own. A stack or
a test starts through the repo's make target, which reads the file itself.

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
files under `docs/reviews`, never a tracked brief, plan, log or earlier report there, and no removal of any kind. A
reviewer reads the running stack and never changes it, docker running only `ps` and `logs`, their compose forms too,
against this machine's daemon. curl reaches `localhost`, `127.0.0.1` or `[::1]` over http or https alone, for every
session since the owner's choice of 2026-10-12. It takes an allow list of options, so nothing writes a file, reads
one with `@`, follows a redirect, goes through a proxy or a socket, or reaches port 2375, 2376 or 2019, the Docker
Engine and Caddy admin APIs, and the host is matched as text in one strict shape. `.curlrc` is a guardrail file.
A reviewer follows
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
bash <workspace>/kriegerdataforge-cicd/tools/claude-code/kdf-review.sh --repo . \
     --brief docs/reviews/2026-09-28-sdk/s1-foundation/step-2-review/SDK_REVIEW_S1_PROMPT.md \
     --report docs/reviews/2026-09-28-sdk/s1-foundation/step-2-review/SDK_REVIEW_S1_REPORT.md \
     --codex-report docs/reviews/2026-09-28-sdk/s1-foundation/step-2-review/SDK_REVIEW_S1_CODEX_REPORT.md \
     --pin <pin> --model <model> --effort max
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
# Codex in the cloud, which fetched the review branch and pushed its report on a branch of its own
bash kdf-review.sh --repo <repo> --codex-report <step>/<codex report> --pin <pin> \
     --collect-branch review/<pfx>-<slice>-codex
```

`--pin` checks that a branch of `origin` holds the pin, that the folder is at it with no tracked file changed, that the
brief is in it, and that the brief's scope table matches it, `kdf-brief.js check`. One review of a folder is open at a
time. A Claude run opens its review when claude starts and closes it when it ends.
`--prepare` opens the review, snapshots git, and prints the folder to open, the one line and the collect command.
`--collect` runs the same check, and since Codex has no guard, it is Codex's fence. A failed collect leaves the review
open, so the orchestrator puts right what the reviewer changed and collects again.

While a review is open, the other report of the scope waits in the repo's `.git/kdf-review/held` folder, out of the
working tree, and closing the review puts it back, never over a file. So does every other untracked file in the
brief's folder and below it, the scratch notes and probes a brief lets a reviewer keep beside its report, which
say what it found as plainly as the report does. Only under `docs/reviews`, and for a brief at the archive's own
root only the files that sit in that folder, the folders below it are other reviews. So Codex never sees Claude's
report or notes and Claude never sees Codex's, whichever goes first. A Claude run cut off before it closed its review leaves it open, and
`--collect` closes it with exit 6 and puts the held report back.

`--collect-branch` fetches the branch Codex in the cloud pushed its report to, checks that it is built on the pin and
adds nothing but new files under `docs/reviews`, and writes the report into the folder, never over one. It needs no
review open, since the cloud read GitHub and not the folder. Codex opens no pull request, ADR D-048. Every
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
node kdf-brief.js cites  --repo <repo> --pin HEAD --since <last clean commit>   # every cite that can have moved
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

`cites` lists every `file:line` cite of the docs it is given, or of every living doc, beside the first and last lines
it names at the pin (D-061). A living doc is a tracked Markdown file outside `docs/reviews/`, a dated record under
`docs/<kind>/<YYYY-MM-DD>-<slug>/` and a changelog or log, which keep the lines of their own day. A cite is a
backticked path, a colon and lines, `` `src/a.py:12` ``, `` `a.py:12-20` `` or `` `a.py:12, 40-41` ``, whose path
names a tracked file, holds a slash, or has an extension and names no host, so `localhost:5432` is no cite. A
code span may cross a line break within a paragraph or a quote, as Markdown's do, and a fenced code block holds no
cite. The path resolves against the whole repo, the exact path or else the one file whose path ends
with it, so a basename two files share is ambiguous and is printed with every candidate, and a longer path in the doc
settles it. `--only` keeps the cites into the files it names and `--since` the cites into a file changed since that
commit and every cite of a doc changed since. Both filter after the path resolves and never choose a file. It exits 1
on a missing file, a line out of range, a backwards range or an ambiguous basename, and lists another repository's
path and a line named with no file apart, for a hand read. It judges nothing, the orchestrator reads each cite against
its line before every pin, as the process's section 4 says.

## A slice's retrospective numbers

```bash
node kdf-retro.js docs/reviews/<YYYY-MM-DD>-<scope>/<slice folder>   # paste its output into the retrospective
```

It reads the slice's answer key, whose findings table must carry the answer key template's columns in their order, or
it exits 2 rather than guess. It prints the findings by source (raised, agreed, declined, the agreed ones in the step 2
pin's tree, and the escapes, the agreed findings in that tree that a later step found), the escape rate, every report's
reviewer, minutes and tokens from its header, and every Sol dispatch without its archived answer. The output is the
same every time for the same files, so a retrospective pastes it as printed, the process's section 14.

## Asking Codex

```bash
bash kdf-ask-codex.sh --repo <repo> --brief <question.md> --base origin/main   # a branch's change, read at HEAD
bash kdf-ask-codex.sh --repo <repo> --brief <question.md> --at <commit>        # a commit as it stands
bash kdf-ask-codex.sh --files <folder> --brief <question.md>                   # patches from several repos at once
bash kdf-ask-codex.sh --repo <repo> --brief <plan.md> --kind plan              # a plan, judged against the code
bash kdf-ask-codex.sh --repo <repo> --brief <choice.md> --kind decision        # a choice among options
bash kdf-ask-codex.sh --repo <repo> --brief <rules.md> --kind rules            # rules or process text itself
```

The brief holds the session's question alone, what to check and why. The tool sets it in the standard frame, read
only, files in the folder alone, PowerShell for Codex's commands since Git Bash cannot start in its sandbox, the
ecosystem's writing conventions, the owner's settled decisions from `kriegerdataforge-context/context/SETTLED.md`
when that clone sits beside this one, and a closing instruction. So no session writes those words again, or forgets
one. `--no-settled` leaves the settled decisions out, and `--dry-run` prints the frame and starts nothing. `--effort`
is `high` by default, or `xhigh` or `max`, the efforts a read is worth among those OpenAI's API takes for its GPT-6
models, and any other is refused before Codex starts. `--model` names the model, `gpt-6.1-sol` by default.

`--kind` sets the closing instruction, the one part of the frame that changes (D-053). `review`, the default, asks for
real problems in a change, each with its file, its line and what triggers it. `plan` tells Codex the question holds a
plan, not code, and asks first for Codex's own approach in a few lines, then whether the route is worth taking at all
and its simplest alternative, then what in the plan is wrong, missing or riskier than it says, each tied to the file
and line that shows it, with what Codex would do instead. `decision` asks Codex to choose among the options as if the
choice were its own, its pick first, which may be none of the options, doing nothing included, or a simpler
alternative, so it says whether the decision is worth taking at all, then why, then the strongest case against its
pick. A reader asked only what is wrong takes the route as given, so the question of worth is asked every time
(D-055). Each says plainly when nothing is wrong, since a model asked for problems tends to find some.

Each kind also asks its five of the review panel's fourteen questions (D-056), each answered in a line or two apart
from the findings, with the file and line or the probe it rests on, or not applicable, or unresolved and what would
settle it. The words live in the script alone, the array `questions`, so they cannot drift, and a question in no
kind's five stays in it for a reader to add.

| Kind | Questions |
| --- | --- |
| `plan` | 1 outcome, 2 assumptions, 3 blast radius, 6 failure, order and undo, 14 pre mortem |
| `decision` | 1 outcome, 2 assumptions, 9 evidence of success, 13 the doer and the cost, 14 pre mortem |
| `review` | 2 assumptions, 3 blast radius, 4 inputs and authority, 6 failure, order and undo, 9 evidence of success. `--fix` asks 10 the class in place of 3, `--security` asks 5 trust in place of 6, and a security fix passes both |
| `rules` | 3 blast radius, 7 time, 11 enforcement and wording, 12 contradiction and drift, 13 the doer and the cost |

The session declares more on top of the five, so every reader of one question gets the same list. `--fix` and
`--security` swap a review's 3 and 6 and add 10 or 5 as an extra to any other kind, and `--also <n>` adds any
question of the bank by its number, each once, such as `--also 8` for work where load or a failing dependency
matters, since question 8 is in no kind's five. Question 18, proportion, is on trial (D-070), in no kind's five and
asked only by `--also 18`. It kept its number from the candidates it was chosen from, so `--also` takes 1 to 14 or
18, and 15 to 17 are no questions. If its trial fails it comes out again. A reader of a review who thinks the change
is a fix or touches security says so. The answer's header names every question asked,
`Questions. plan, 1 2 3 6 14 8`, so a frame from a clone that was never pulled shows at once. The kind follows the
judgment asked, not the subject. A plan to change the rules is a `plan`, and `rules` is for rules, briefs and process
text alone, proposed or about to be pushed, with the plan's base three. A brief need not repeat its kind's questions,
and may sharpen one under its own number. A question's words change by a pull request here. A clone gets the
questions only once it is pulled, so after this change merges each machine pulls its cicd clone and checks one
`--dry-run` of each kind.

In repo mode Codex reads a detached worktree of the commit, `HEAD` when `--at` is not given. The worktree is made with
`--no-checkout`, since git runs the repo's post-checkout hook after any other worktree add, and is then filled with
`git reset --hard`, which runs no hook. A worktree holds tracked files alone, so a secret file git ignores is never in
its folder, and the worktree is removed when the run ends, failed or not, locked or not, even when the tool could not
read where git registered it. When git refuses to remove one it can no longer read, the tool removes that worktree's
registration by hand, and never runs `git worktree prune`, which would also drop another session's worktree that was
moved or sits on a drive that is not there. A commit that tracks a symbolic link is refused, since a link can lead
out of the folder, and none of the ecosystem's repos tracked one on 2026-10-05. `--base` names the branch or commit a
change is measured from, and the frame names the change from their merge base, what `git diff <base>...HEAD` shows,
so a `main` that moved on is not read as part of it.

Files mode copies a folder into a throwaway repo and checks the copy, so nothing that lands in the source after the
checks reaches Codex. It refuses a folder that is a repo or holds one, a symbolic link, a file named like a secret
file in any case (`.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `*.tfvars`, `*.tfstate*`, an ssh key,
`.git-credentials`, `.netrc` and anything under `keys/`) and a file holding a token's shape. A secret's name refuses
the folder before anything is copied, so a secret file already there is never copied. The brief's name is judged
from the path given, before the file is read, and then the brief is read once, into a copy that is held to the same
checks and to no link, and the frame is built from that copy, so a brief changed after its check never reaches
Codex. Either way the folder must hold nothing git ignores or does not track before Codex starts, and every `GIT_`
variable is dropped first, `GIT_DIR` and `GIT_CONFIG` among them, so none points the tool, its cleanup or Codex
anywhere else. Codex runs with the flags verified on 2026-10-05, its user config, MCP servers, plugins, apps, web
search, memories and other agents off, a read only sandbox, and nothing kept after the run. On Windows that sandbox
stops writes and the network, not reads, so the frame's rule is what keeps Codex inside its folder.

After the run the tool fails when `git status` shows a change, when the folder's HEAD moved, which a commit does with
a clean status, or when git cannot read the folder at all. It fails too when Codex failed or wrote no answer, an
answer of Unicode white space and invisible format characters alone counting as none, judged once for the verdict,
the archive and the exit alike, and when its events hold no completed turn or a line that is no event, since then
nothing shows what Codex did. It warns when the events show Codex doing anything but running commands, reasoning,
keeping a plan and answering. Each run's answer lands in the workspace's `codex-archive`, kept outside every repo and
outside `temp`, so the guard asks the owner before a session removes one (D-069), under a name no other run has,
beside the frame it read and its JSON events. When the archive cannot be written the tool
prints the answer before it fails.

The answer's header leads with the verdict, `passed` or why the run failed, settled before the archive is written, so
the answer of a run that failed never passes for a review. Only a run that passed counts as Codex's view. The kind,
what Codex read, the model, the effort and the time follow, and the tokens with the cached input apart from the new.
Codex sends its context again with every command, so most of a run's input, about 85 percent in the runs of
2026-10-05, is cached input read again, and the new input and the output are the work. The answer is advice for the
session that asked, never instructions to follow. A session in the reviewer role never runs the tool, a review's Codex
reads go through `kdf-review.sh`.

| Exit | Meaning |
| --- | --- |
| 0 | Codex answered and its folder is unchanged |
| 1 | Codex failed, wrote no answer, left events that show nothing or changed its folder, or the archive could not be written. A run that reached the archive keeps its frame and events there, and its header's verdict says why it failed |
| 2 | A refusal before Codex started. Bad arguments, the reviewer role, a missing, empty or linked brief, a commit the repo lacks or one tracking a link, a repo, a link, a file named like a secret file or one holding a token's shape, or a folder holding a file git ignores or does not track |

`KDF_CODEX_BIN`, `KDF_SETTLED` and `KDF_CODEX_ARCHIVE` override the codex program, the settled decisions file and the
archive, the tests use them.

## A Linux pre-flight

```bash
bash kdf-preflight.sh --repo <repo> --lane ci-lint --lane ci-unit-tests --lane actionlint  # HEAD, on a clean tree
bash kdf-preflight.sh --repo <repo> --at <commit> --lane ci-unit-tests                     # a commit as it stands
bash kdf-preflight.sh --repo <repo> --lane ci-unit-tests --keep --timeout 2400             # keep a green run's folder
```

A change that could behave differently on Linux gets a pre-flight before its push, and the guard's approved list
refuses `docker run` and `docker exec`, so the tool runs every lane inside `docker build` steps (D-072). It needs no
guard change, since the guard runs a script unread on the owner's word of 2026-10-12, and so it holds itself to the
guard's own fences. It refuses a session in the reviewer role (`KDF_ROLE=reviewer`), whose docker build the guard
refuses, and it refuses before it sends anything while `DOCKER_HOST`, `DOCKER_CONTEXT`, `DOCKER_CONFIG`,
`BUILDX_BUILDER` or `BUILDX_CONFIG` is set, while `~/.docker/config.json` names a current context other than
`default` or `desktop-linux`, read as the guard reads it, and while `~/.docker/buildx/current` chooses a builder other
than the engine's own. Every option it passes is on the guard's list for `docker build` and `docker rmi`, which a test
holds, and it never cleans the daemon as a whole, so it never stops another run.

**The commit.** `--at` names it, resolved to its full hash, or HEAD on a clean tree. A tree with changes or with
untracked files git does not ignore is refused with no `--at`, since a run of HEAD would leave them out unseen, so
commit first. Every `GIT_` variable is dropped first. The hash is printed at the start and the end of the run.

**What enters.** A tracked file named like a secret file, the names `kdf-ask-codex.sh` refuses but an `.env` example,
refuses the run before anything is exported, since a build's layers outlive the run. A token's shape in tracked
content is listed as a warning and not refused, since that text is already in git, and this repo's own tests hold
fake keys as fixtures. The run's folder, `<workspace>/temp/kdf-preflight/<run id>/`, holds `build.log` and
`context/`, which is the commit's tar from `git archive` with LF line ends beside `preflight/Dockerfile` and
`preflight/lanes.sh`, and nothing else, so a repo's own `.dockerignore` or `Dockerfile` never selects or replaces
anything. The tar is unpacked inside the image by `runner`, uid 1001, an unprivileged user as on GitHub's runner, so
modes, case and links land as a Linux checkout puts them, and made a repo of one commit.

**The lanes.** A lane is a `ci-*` target on its own line in the repo's `Makefile` at the commit, or `actionlint`,
the image's actionlint over the repo's workflows with ShellCheck, which actionlint runs over every `run:` script as on
GitHub's runner and would otherwise skip without a word, Debian 13's 0.10.0 where the runner has 0.9.0. It leaves
out the pyflakes that the official actionlint image adds, since the runner has none. A lane holding one of the
guard's owner only make words, such as deploy, release, publish or prod, or dev without local, is refused as a typed
`make` of it is, and so is `ci-version-check`, which compares against `origin/main`, a history an archive does not
have. Each lane runs with `ENVIRONMENT=local` and `GIT_TERMINAL_PROMPT=0`, without the base image's own
`PYTHON_VERSION`, which a runner never sets, and under its own `timeout`, so a red or a hung lane never stops the
lanes after it. A lane that needs a private package fails at setup, since no token enters the container, and is
reported in the pull request as a skipped pre-flight, and the tool says so when git's credential failure is in the
log. Today it serves this repo and any repo whose lanes install public packages alone.

**The image.** `preflight/Dockerfile` is Python 3.14.7 slim from AWS ECR Public's gallery by its index digest (D-064),
git, make and ShellCheck from the digest's own Debian release, unpinned since its mirror keeps only the current
package, Node 22, the major `ubuntu-latest` runs by default, from its official tarball, and actionlint at the version
and sha256 `ci.yml` pins, both checked by `ADD --checksum`. Node's version is a hand edit when the runner's major
moves, its comment naming where it was read. The base stage is built first and alone, tagged
`kdf-preflight-base:<the Dockerfile's hash>`, so a failure there is the tool's and the image shows in `docker images`.
The first run on a machine builds it, a few minutes. The lanes stage is tagged `kdf-preflight-run:<run id>` and
removed with `docker rmi` when the run ends, failed or not, under a timeout so a stalled daemon never holds the run,
and the tool warns when the image may be left behind, the lanes' result standing. The build cache is the owner's to
prune now and then. The image is never pushed to a registry.

**The result.** The run id is a build argument used in the step that runs the lanes, so that step is never taken from
the cache, and a last small step prints each lane's status after a marker holding the run id. The tool reads those
lines alone, never the build's status, so a broken build never reads as a red lane and BuildKit clipping a noisy
lane's log never hides a result. It finds that step by the line BuildKit itself opens it with, which no lane can
print, and counts only that step's lines that open with a marker, so neither a lane's output nor an excerpt passes for
a result even from a lane that learns the run id. The lane script writes the statuses only after every lane has run,
and the image keeps it and the tar as root's, so no lane rewrites a status or the script the last step runs. BuildKit
drops the rest of a step's stdout once it clips, measured at 200 KiB a
second and at 2 MiB a step, so a later lane's reason can be missing from the lanes step. Each lane's output goes to a
file of its own and is printed when the lane ends, with no pipe, so a process a lane leaves running never holds the
step open, and the last step prints, after the results and the end marker and on stderr, an excerpt of each failed
lane's own output, its last 50 lines of 300 bytes each, 64 KiB in all with a notice where it stops. The tool shows
that excerpt beside the failed lane. `--timeout`, 1800 seconds unless given, bounds the whole run, each build running
under what remains of it.

| Exit | Meaning |
| --- | --- |
| 0 | Every lane passed. The run's folder is removed unless `--keep` is given |
| 1 | A lane failed, each named with its exit status and the excerpt of its own output. The folder and its `build.log` are kept |
| 2 | A refusal before anything was built. Bad arguments, the reviewer role, a docker pointed elsewhere, a folder that is no repo, a commit it lacks, a dirty tree with no `--at`, a lane that is not the session's to run or not in the `Makefile`, `actionlint` with no workflows, or a tracked secret file. Nothing is kept |
| 3 | The run could not complete. A base that would not build, docker unreachable, the run past its timeout, or no whole set of marker lines, with the log's tail printed. The folder is kept |

`KDF_DOCKER_BIN` and `KDF_PREFLIGHT_DIR` override the docker program and the runs folder, the tests use them, and
`scripts/tests/test_kdf_preflight.py` plays docker with a stand in that records every call.

## The compaction hook

`kdf-compact.js` serves the work records of the kit's `DOCUMENTATION_STANDARD.md` (D-057, D-058). After a compaction
or a resume it reads the session's own transcript for the record files the session wrote with a file tool, a design
or bug `LOG.md`, a review's `README.md` and a brainstorm's `NOTES.md`, and prints each open one's path and status
word, the newest first, so the session reads its record before any task work. It prints paths, never a record's
words, since a hook's output reaches the context as Claude Code's own. With no record it points at the status page,
`KDF_STATUS_FILE` or the first `kriegerdataforge-context/STATUS.md` above the session's folder. It says nothing to a
reviewer the launcher started (`KDF_ROLE=reviewer`) or inside a subagent, and it never blocks or fails a session.

To wire it, once per machine, after any review campaign running there has closed, copy it beside the guard and add a
SessionStart entry to `~/.claude/settings.json`, then restart every session and `claude rc` server.

```json
"SessionStart": [
  {
    "matcher": "compact|resume",
    "hooks": [
      { "type": "command", "command": "node \"<home>/.claude/hooks/kdf-compact.js\" session-start", "timeout": 15 }
    ]
  }
]
```

It needs no wrapper, since it never refuses anything. Every compaction's summary is already in the session's
transcript, so how often a summary named its record is counted from the transcripts, with no other hook.

## What the guard cannot stop

The guard holds the commands a session types. A file a session runs runs what it says, a script, a test, a Python or
Node file and every `make` target, and no command reader sees inside it, the owner's word of 2026-10-12 that scripts
run unread, reviewed by the owner and by in depth reviews. That is why the launcher checks git afterward. The guard
is a fence against a session's mistakes, it is not a sandbox against a determined program. The permission deny rules
in `settings.json` stay as a second fence, and the rulesets on GitHub, with the admin bypass set to pull requests
only, are the last.

By design, `origin` is a name the guard checks, not a place. It is whatever URL the clone was made from, so a push to
the `origin` of a clone a session made from some other URL goes there. What the guard refuses is a change to where an
`origin` leads. A program's bare name is read as the program the PATH finds, and the profile files that set the PATH
are guardrail files. For an owner's session `mcp__ide__getDiagnostics` is the one MCP tool on the list. A hook that
times out lets the call through, by Claude Code's design, so the guard keeps a deadline of its own and refuses when it
runs out. Codex runs in its own sandbox and is not held by this guard yet.

A glob's extra judgments (D-060) only add refusals. A bracket counts as any one character, so two bracket globs that
bash narrows can be judged as other words, refusing more. `~` is Node's home folder, which on Windows is
`USERPROFILE`. And the globs of a call count against 200 matches, which can refuse a call bash would run.

Running a file in a protected folder counts as touching it, so `node ~/.claude/hooks/kdf-guard.js` is refused inside a
session. To try the installed guard, feed the same input to this folder's copy, which `check-wiring.js` confirms is
byte identical.

## Changing a rule

1. Add the cases to `guard-cases.json` first, one that must be refused and one that must still be allowed, and one
   that asks for a removal rule.
2. Change `kdf-guard.js`. A new program or form goes on `LIST` with its options written out, and an entry's comment
   never names a gap that is still open, since this repo is public.
3. `make test` runs every case, in parallel, and the launcher, checker and installer tests.
4. The owner merges, then installs by hand on each machine, as below.

**Installing the approved list (D-068), by the owner, one machine at a time.**

1. Drain. No Claude Code session runs on the machine.
2. Keep the whole previous state, a copy of `~/.claude/settings.json` and of the installed `kdf-guard.js`.
3. The trial. Copy this commit's `kdf-guard.js` to `~/.claude/hooks/kdf-guard-trial.js`, and add a second
   PreToolUse line beside the guard's, the same matcher, running `node "<home>/.claude/hooks/kdf-guard-trial.js"
   --log`, with no `|| exit 2`, since the trial refuses nothing. Restart the sessions and work for a week. Each
   decision lands in `~/.claude/kdf-guard-trial.log`, so the owner counts what it would refuse and ask.
4. The enforcement trial. Start a session with `KDF_GUARD_MODE=enforce`, and in it run a command the list allows, one
   it refuses, a removal that asks, in default, acceptEdits, auto and bypassPermissions mode and from the phone, a
   subagent's command, a full Round Table sitting and a review canary. A route where a refused command runs, or a
   failure lets a call through, stops the switch there.
5. The switch. `bash tools/claude-code/install.sh` puts the new guard in place and keeps the old one as
   `kdf-guard.prev.js`. Remove the trial's line, restart every session and `claude rc` server, and run
   `install.sh --check`.
6. Undo, for any failure or the owner's word. Put `kdf-guard.prev.js` back as `kdf-guard.js` and the kept
   `settings.json` back, restart, and run `install.sh --check` to see the previous wiring in place.

Input the guard cannot read, a call that names no tool, or an error while it checks refuses the call, every tool,
reads included, since an error before the secret checks once let a secret read through (D-059, the owner's choice of
2026-10-07 over the earlier "a bug here must never stall a session"). A guard that cannot start, a missing file or a
missing `node`, exits 1 or 127, which Claude Code lets through, so its settings line ends with `|| exit 2` and
`check-wiring.js` warns when it does not. A hook that times out still lets the call through, by Claude Code's design.
So a bug here stalls every session until it is fixed, and the way back is the owner's. Putting `kdf-guard.prev.js`
back in place works at once for every session, as long as `node` starts, since each call runs the file afresh.
Removing the hook means removing it from `~/.claude/settings.json` and from every repo's `.claude/settings.local.json`
that runs it, then restarting every session and every `claude rc` server, since a running session keeps the hooks it
started with. `KDF_GUARD_LOG=<file>` appends a line per refusal when the owner wants to see what a session tried.

## Notes

- The guard costs about 65 ms per guarded call, and only tools its matcher names pay it. Read, Grep and Glob pay it
  too since 2026-09-29, and a reviewer's read costs about 83 ms, since it also asks git whether the path is ignored.
- Line ends are pinned to LF for these files by `.gitattributes`. A carriage return breaks a shell script.
- Node is the runtime because it is present wherever Claude Code and the Next.js repos run. A Python guard would need
  an interpreter path on every machine.
