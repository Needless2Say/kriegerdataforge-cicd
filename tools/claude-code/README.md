# tools/claude-code. The KDF Code Review Process tooling

The guard, the fresh reviewer launcher, the wiring checker and the installer for the
[KDF Code Review Process](../../kit/common/docs/agent/CODE_REVIEW_PROCESS.md), and the one way a session asks Codex
for a second opinion. They run on the owner's machine, in Claude Code sessions. They are **not synced** to the other
repos, the kit ships Markdown only (ADR D-028), so each machine installs them from a clone of this repo.

| File | What it is |
| --- | --- |
| `kdf-guard.js` | A Claude Code PreToolUse hook. It reads each Bash and PowerShell command the way a shell does, each Read, Grep and Glob, and each file edit and outward facing tool call, and exits 2 to refuse with the reason. No dependencies, one file |
| `guard-cases.json` | The table the guard is held to, one case per tool call with its role and whether it is allowed or refused. Every rule change adds cases |
| `kdf-review.sh` | Starts one fresh Claude reviewer with the reviewer role in the repo folder itself, for at most four hours by default, or opens and closes the folder for Codex, checking first that the pin is pushed, the folder is at it and the brief's counts match it. Compares git before and after and fails the review if the reviewer changed anything but a new file under `docs/reviews`, the review archive. A Claude run's log is claude's stream, one JSON event a line as the run goes, so a detached run is watched by its log, and after a clean run the launcher writes Claude Code's own count of it beside the report, `<report stem>.usage.json`, from the stream's last result event. Brings a report Codex wrote in the cloud in from its branch, and warns when a report it did not start lacks its time or usage line |
| `kdf-brief.js` | Read only. The facts a brief states, measured at the pin, the commit line and the scope table's line counts, and a check of a written brief's table |
| `kdf-retro.js` | Read only. The numbers a slice's retrospective starts from, counted from its answer key, the launcher's counts beside its reports or else their headers, and its Sol rounds, the escapes first |
| `kdf-ask-codex.sh` | Asks Codex for a read only review of a change, a plan or a decision, the one way every session does (D-052, D-053). Gives Codex a detached worktree of a commit, or a throwaway repo of a folder of patches with no secret file, link or token in it, sets the session's question in the standard frame, runs Codex with the verified flags and archives its answer in the workspace's `temp/codex`, never in a repo. Refuses a reviewer, and fails when Codex changed its folder or wrote no answer |
| `check-wiring.js` | Read only. Says whether this machine's settings wire the guard as the process needs, and prints the block to add when they do not |
| `kdf-compact.js` | A Claude Code SessionStart hook for the work records (D-058). After a compaction or a resume it prints the paths of the open records the session wrote, read from its own transcript, and nothing for a reviewer or a subagent. It never blocks |
| `install.sh` | Copies the guard to `~/.claude/hooks/`, smoke tests it, and prints the settings block. It edits no settings and refuses to run inside a Claude Code session |

`../codex-cloud/kdf-codex-install.sh` and `../codex-cloud/kdf-codex-start-skill.md` are not run here. The owner pastes
them into a repo's Codex cloud environment as its Install script and Start skill, on trial for the kdf-sdk's S2 (ADRs
D-039 and D-048), and the process's section 11 says how.

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
`--no-verify` pushes are refused, as are `git send-pack` and `git http-push`. The one push to `main` it lets through
is a plain `git push origin main`, the whole call, in `kriegerdataforge-context`, judged by its fetch and push URLs,
with `main` checked out and every commit since `origin/main` changing `STATUS.md` alone, read after a fetch (D-046).
Any doubt, a GIT_ variable that moves git, a merge, an empty commit or a git error, refuses it. Git settings that run
commands or change
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
one. `--no-settled` leaves the settled decisions out, and `--dry-run` prints the frame and starts nothing.

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
matters, since question 8 is in no kind's five. A reader of a review who thinks the change is a fix or touches
security says so. The answer's header names every question asked, `Questions. plan, 1 2 3 6 14 8`, so a frame from a
clone that was never pulled shows at once. The kind follows the
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
a clean status, or when git cannot read the folder at all. It fails too when Codex failed or wrote no answer, and when
its events hold no completed turn or a line that is no event, since then nothing shows what Codex did. It warns when
the events show Codex doing anything but running commands, reasoning, keeping a plan and answering. Each run's answer
lands in the workspace's `temp/codex`, the owner's scratch, under a name no other run has, beside the frame it read
and its JSON events. When the archive cannot be written the tool prints the answer before it fails.

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
