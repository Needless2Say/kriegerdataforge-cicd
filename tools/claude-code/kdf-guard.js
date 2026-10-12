#!/usr/bin/env node
'use strict';
/*
 * kdf-guard.js, the KDF Code Review Process guard. A Claude Code PreToolUse hook.
 *
 *   node kdf-guard.js                   owner rules, for every session the owner starts
 *   node kdf-guard.js reviewer          reviewer rules, on top of the owner rules
 *   KDF_ROLE=reviewer node kdf-guard.js the same reviewer rules, chosen when the session is launched
 *   node kdf-guard.js --log             the trial, which logs what it would decide and lets every call through
 *
 * The approved list (D-068). A shell command runs only when it is plain and every program in it is on the owner's
 * list, LIST below, with the subcommands and flags written there. Everything else is refused, and the reason tells the
 * session to write the command another way or ask the owner. A removal, a command that deletes a file or a folder,
 * discards uncommitted work or writes over a file, asks the owner with the command in the prompt, unless every path
 * it names is a temporary file. The owner changes the list by pull request and installs it by hand.
 *
 * Owner rules, every session and every repo. Only the owner merges, approves, tags, releases, deploys or pushes
 * to main. A push names its branch and goes to origin, and force, delete, tag and mirror pushes are refused. The one
 * push to main a session makes is a plain git push origin main in kriegerdataforge-context whose every commit
 * changes STATUS.md alone, the owner's live status (D-046).
 * Guardrails are the owner's to change, so a session cannot edit its own settings, hooks, MCP list or git hooks.
 * Git settings that run commands or change where code goes are refused. So is a make target that reaches DEV or
 * PROD or applies, deploys or publishes, one of cicd's ops scripts outside its read only mode, and re-running,
 * cancelling or deleting a workflow run, which can redeploy. Secret files are closed to every session, no read,
 * write, copy, source or pass to a command, only a check that one exists. .env.local is open, by the owner's decision,
 * unless it still holds a credential that works beyond this machine, which the env standard keeps in .env.kdf.
 *
 * Reviewer rules, on top of those. Read only git, no GitHub CLI, no shell command that writes, installs or
 * downloads, no redirect into a file, no secret file, no connector, artifact, message, schedule or notification
 * tool, and file edits only under docs/reviews. A reviewer follows .gitignore, so it opens no path git ignores
 * but .env.local, no report the launcher holds, and runs no recursive grep.
 *
 * Exit 0 allows the call, or with a permission decision of ask on stdout asks the owner. Exit 2 blocks it and stderr
 * tells the model why. Input it cannot read, a call with no tool name, or an error while it checks refuses the call
 * with exit 2, every tool, since an error before a check would let that check's call through (D-059). The guard keeps
 * a deadline of its own well inside the hook's timeout and refuses when it runs out. A guard that cannot start exits
 * 1 or 127, which Claude Code lets through, so its settings line runs node ... || exit 2. To switch it off, remove the
 * hook from the settings file.
 *
 * Environment. KDF_ROLE=reviewer picks the reviewer rules. KDF_GUARD_MODE=log or enforce picks the trial or the guard,
 * over --log, so the owner can start a session that enforces during the trial. KDF_GUARD_LOG=<file> appends one line
 * per refusal, and KDF_GUARD_TRIAL_LOG=<file> is where the trial writes. KDF_GUARD_TEMP_ROOTS lists the temp folders,
 * separated by ;.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROLE = String(process.argv.slice(2).find((a) => a !== '--log') || process.env.KDF_ROLE || '').toLowerCase();
const MODE = ROLE === 'reviewer' ? 'reviewer' : 'orchestrator';
const LOG_ONLY = (process.env.KDF_GUARD_MODE || (process.argv.includes('--log') ? 'log' : 'enforce')) === 'log';
const TRIAL_LOG = process.env.KDF_GUARD_TRIAL_LOG || path.join(os.homedir(), '.claude', 'kdf-guard-trial.log');
// The guard's own deadline, well inside the hook's timeout, since a hook that times out lets the call through.
const STARTED = Date.now();
const BUDGET_MS = 20000;
function timeLeft() {
  const left = STARTED + BUDGET_MS - Date.now();
  if (left < 500) throw new Error('its own time ran out');
  return left;
}
const FILE_TOOLS = /^(Edit|Write|MultiEdit|NotebookEdit)$/;
// Tools that reach outside the repo, or run code the guard cannot read. A reviewer uses none of them. The IDE
// diagnostics tool alone stays allowed, its code runner is refused like any other (D-060).
const OUTWARD_TOOLS = /^(mcp__(?!ide__getDiagnostics$)|Artifact|SendUserFile$|SendMessage$|PushNotification$|RemoteTrigger$|Cron|DesignSync$|EnterWorktree$|Workflow$|WebFetch$|WebSearch$)/;
// The MCP tools any session may call, each by its whole name. A tool not on the list is refused, so a server or
// connector added later is refused until the owner adds its tools here by pull request (D-066).
const MCP_ALLOWED = new Set(['mcp__ide__getDiagnostics']);
const MCP_WHY = 'A session calls only the MCP tools on the guard\'s list, MCP_ALLOWED in kdf-guard.js, which the owner '
  + 'changes by pull request. ';

// Files that hold the guardrails. A session never edits them, the owner does. Git's global and system config are
// among them, since a remote's push URL or a pushInsteadOf there sends every repo's origin somewhere else (D-062).
// What loads into a session is the owner's too, the skills, agents, commands and plugins folders, Codex's config,
// Claude Code's managed settings and the owner's administrator folder (D-066), and so are the shell's and
// PowerShell's profile files, which set the PATH, the aliases and the functions a command meets (D-068).
const PROTECTED = [
  /(^|\/)\.claude\/(settings(\.local)?\.json|hooks(\/|$))/,
  /(^|\/)\.claude\.json$/,
  /(^|\/)\.mcp\.json$/,
  /(^|\/)\.git\/(hooks(\/|$)|config$)/,
  /(^|\/)\.gitconfig$/,
  /(^|\/)\.config\/git\/config$/,
  /(^|\/)etc\/gitconfig$/,
  /(^|\/)\.claude\/(skills|agents|commands|plugins)(\/|$)/,
  /(^|\/)\.codex\/(config\.toml|hooks\.json|rules(\/|$)|agents\.md$)/,
  /(^|\/)program files\/(claudecode|kriegerdataforge)(\/|$)/,
  /(^|\/)programdata\/openai(\/|$)/,
  /(^|\/)\.(bashrc|bash_profile|bash_login|profile|inputrc)$/,
  /(^|\/)[._]curlrc$/,
  /(^|\/)(windows)?powershell\/[^/]*profile[^/]*\.ps1$/
];
const GUARDRAIL_WHY = 'Guardrails are the owner\'s to change. Settings, hooks, the MCP list, git hooks, git\'s own '
  + 'config files, what loads into a session and the shell\'s profile files are edited by hand.';
// Files that hold secrets, closed to every session. Every .env file is one, .env.kdf, .env.test, the admin files
// .env.dev and .env.prod, and backups such as .env.local.bak, but an example is not, and .env.local is open unless it
// still holds a credential. *.pem and keys/ are secrets too, and so is a *.tfvars git does not track. A tracked one,
// terraform's common.auto.tfvars, holds no secret, since git shows it to everyone who reads the repo.
const ENV_FILE = /(^|[\\/])\.env(\.[^\\/]*)?$/i;
const TFVARS_FILE = /\.tfvars(\.json)?$/i;
const KEY_FILE = /\.pem$|(^|[\\/])keys[\\/]/i;
const LOCAL_ENV = /(^|[\\/])\.env\.local$/i;
const ADMIN_ENV = /(^|[\\/])\.env\.(dev|prod)[^\\/]*$/i;
function isSecretFile(p) {
  const s = String(p);
  if (ENV_FILE.test(s)) return !/\.example$/i.test(s) && !LOCAL_ENV.test(s);
  if (TFVARS_FILE.test(s)) return !trackedByGit(s);
  return KEY_FILE.test(s);
}
// Credentials that work beyond this machine. The env standard keeps them in .env.kdf, and a repo's .env.kdf.example
// names its own on top of these.
const KDF_CREDENTIALS = [
  'GH_PACKAGES_PAT', 'GH_NPM_TOKEN', 'KDF_OIDC_CLIENT_SECRET', 'KDF_SERVICE_KEY', 'AUTH_RESEND_API_KEY',
  'AUTH_TWILIO_AUTH_TOKEN', 'AUTH_ADMIN_EMAIL_PASSWORD'
];
const ENV_LINE = /^[ \t]*(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=[ \t]*(.*)$/gm;
// A name a .env.kdf.example lists, active or commented out, since every line of the standard's example starts commented
// so a copy overrides nothing. A prose comment that looks like one only adds a name, which keeps more closed.
const EXAMPLE_NAME = /^[ \t]*(?:#[ \t]*)?(?:export[ \t]+)?([A-Za-z_][A-Za-z0-9_]*)[ \t]*=/gm;
const SECRET_WHY = 'Secret files are the owner\'s. No session reads, writes, copies, sources or passes one to a '
  + 'command, it only checks that one exists. A stack or a test starts through the repo\'s make target, which reads the '
  + 'file itself. Otherwise ask the owner.';
const ADMIN_WHY = '.env.dev and .env.prod are the owner\'s admin files for the DEV and PROD databases. No session '
  + 'touches them.';
const CREDENTIAL_WHY = 'This .env.local is closed. It opens once its repo has adopted the env standard, a tracked '
  + '.env.kdf.example beside it, and it holds none of the credentials that work beyond this machine, which the '
  + 'standard keeps in .env.kdf. Ask the owner.';
// Programs that only check that a file exists, the one thing a session may do with a secret file.
const EXISTENCE_ONLY = new Set(['test', '[', '[[', 'ls', 'dir', 'stat']);
// Programs that print what a file holds. A reviewer never points one at a path git ignores.
const CONTENT_READERS = new Set([
  'cat', 'less', 'more', 'head', 'tail', 'grep', 'egrep', 'fgrep', 'rg', 'sed', 'awk', 'gawk', 'bat', 'strings',
  'xxd', 'od', 'hexdump', 'base64', 'nl', 'tac', 'sort', 'uniq', 'cut', 'diff', 'cmp', 'jq', 'yq', 'type',
  'get-content', 'gc', 'select-string', 'sls'
]);
const IGNORED_WHY = 'Reviewers follow .gitignore, a path git ignores is not part of the review. Search with git grep '
  + 'or rg, which skip ignored paths.';
const HELD_WHY = 'The launcher holds the other reviewer\'s report of the scope there while a review is open. Never open it.';
// Programs that only read, so naming a protected file to them is fine.
const READ_ONLY_PROGRAMS = new Set([
  'cat', 'less', 'more', 'head', 'tail', 'grep', 'egrep', 'fgrep', 'rg', 'ls', 'dir', 'wc', 'diff', 'cmp', 'stat',
  'file', 'tree', 'du', 'type', 'realpath', 'readlink', 'basename', 'dirname', 'test', '[', '[[', 'echo', 'printf',
  'export', 'local', 'declare', 'readonly', 'typeset', 'unset'
]);
const GIT_READ = new Set(['status', 'diff', 'log', 'show', 'blame', 'ls-files', 'check-ignore', 'cat-file', 'rev-parse', 'ls-tree', 'grep']);

let PROJECT = process.cwd();
// The shell's directory for this call, which a relative path in a command or a tool input is read against.
let CWD = process.cwd();

function deny(why, detail) {
  const line = 'kdf-guard (' + MODE + ') refused this call. ' + why;
  if (process.env.KDF_GUARD_LOG) {
    try {
      fs.appendFileSync(process.env.KDF_GUARD_LOG, new Date().toISOString() + ' ' + MODE + ' ' + String(detail || '').replace(/\s+/g, ' ').slice(0, 160) + ' | ' + why + '\n');
    } catch (err) {
      // A log that cannot be written must not change the answer.
    }
  }
  if (LOG_ONLY) trial('refuse', detail, why);
  process.stderr.write(line + '\n');
  process.exit(2);
}

let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  raw += chunk;
});
// A call the guard cannot check could be any call, and an error before a check once let a secret read through, so it
// is refused, every tool, reads included (D-059).
const CANNOT_CHECK = 'The guard could not check this call, so it refuses it. The way back is the owner\'s, put ' +
  'kdf-guard.prev.js back, or remove its hook from ~/.claude/settings.json and any repo\'s ' +
  '.claude/settings.local.json and restart the sessions. ';
process.stdin.on('end', () => {
  let input;
  try {
    input = JSON.parse(raw);
  } catch (err) {
    deny(CANNOT_CHECK + 'Its input is not JSON.', 'input not JSON');
  }
  if (!input || typeof input !== 'object' || Array.isArray(input) || typeof input.tool_name !== 'string' ||
    !input.tool_name) {
    deny(CANNOT_CHECK + 'Its input names no tool.', 'no tool name');
  }
  try {
    run(input);
  } catch (err) {
    deny(CANNOT_CHECK + 'It failed while checking, ' + err.message, input.tool_name + ' ' + err.message);
  }
  if (LOG_ONLY) trial('allow', input.tool_name + ' ' + String((input.tool_input || {}).command || ''), '');
  process.exit(0);
});

function run(input) {
  PROJECT = path.resolve(process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd());
  CWD = path.resolve(input.cwd || PROJECT);
  const tool = input.tool_name || '';
  const args = input.tool_input || {};
  if (tool === 'Bash') {
    checkCall(String(args.command || ''));
  } else if (tool === 'PowerShell') {
    deny('The PowerShell tool is refused. Sessions use Bash, the owner\'s rule, and the guard reads bash alone.',
      'PowerShell');
  } else if (tool === 'Monitor') {
    // Monitor runs its command in the same shell as Bash, so the command gets Bash's rules, and its WebSocket reaches
    // outside the repo (D-060)
    if (args.ws && MODE === 'reviewer') deny('Reviewers open no WebSocket. Monitor with ws is refused.', 'Monitor ws');
    checkCall(String(args.command || ''));
  } else if (FILE_TOOLS.test(tool)) {
    checkFileTool(String(args.file_path || args.notebook_path || ''));
  } else if (tool === 'Read' || tool === 'Grep' || tool === 'Glob') {
    checkReadTool(tool, args);
  } else if (MODE === 'reviewer' && OUTWARD_TOOLS.test(tool)) {
    deny('Reviewers use no connector, artifact, message, schedule or notification tool. ' + tool + ' is refused.', tool);
  } else if (/^mcp__/i.test(tool) && !MCP_ALLOWED.has(tool)) {
    deny(MCP_WHY + tool + ' is not on it.', tool);
  }
}

function norm(p) {
  return String(p).replace(/\\/g, '/').toLowerCase();
}

// a dot segment, ~/.config/git/./config or a/../.git/config, names the same file, so it is folded first (D-062)
function isProtected(p) {
  const n = path.posix.normalize(norm(p));
  if (PROTECTED.some((r) => r.test(n))) return true;
  // the same path from the folder the shell is in, so cd .claude && cp x settings.json names .claude/settings.json
  const abs = String(p).startsWith('-') ? '' : norm(resolvedPath(String(p)));
  return Boolean(abs) && PROTECTED.some((r) => r.test(abs));
}

// A path as the shell would open it from the folder it is in, Git Bash's /d/x and ~ forms read, or '' for nothing.
function resolvedPath(p) {
  if (!p) return '';
  try {
    let s = String(p).replace(/\\/g, '/');
    if (s === '~' || s.startsWith('~/')) s = os.homedir() + s.slice(1);
    const drive = /^\/([a-zA-Z])(\/|$)/.exec(s);
    if (drive) s = drive[1] + ':/' + s.slice(3);
    return path.resolve(CWD, s).replace(/\\/g, '/');
  } catch (err) {
    return '';
  }
}

// The review archive, the one folder a reviewer writes in. The separator on the end keeps a look alike such as
// docs/reviews-old outside it.
function insideReviewsDir(p) {
  const fold = (s) => (process.platform === 'win32' ? s.toLowerCase() : s);
  const root = fold(path.join(PROJECT, 'docs', 'reviews') + path.sep);
  return fold(path.resolve(PROJECT, p) + path.sep).startsWith(root);
}

function checkFileTool(target) {
  if (isProtected(target)) deny(GUARDRAIL_WHY, target);
  checkClosed(target, target);
  if (MODE === 'reviewer' && !insideReviewsDir(target)) {
    deny('Reviewers write only under docs/reviews, the review archive. ' + target + ' is outside it.', target);
  }
  if (MODE === 'reviewer' && trackedByGit(target)) {
    deny('Reviewers write only new files, their report and notes. ' + target + ' is tracked, a brief, a plan or a log.',
      target);
  }
}

// ------------------------------------------------------------ secret files, every session

// An error that says the path is not there, a missing file or a parent that is a file, the one error a check reads as
// an answer. Any other is a check that could not run (D-059, D-060).
function missingPath(err) {
  return Boolean(err) && (err.code === 'ENOENT' || err.code === 'ENOTDIR');
}

// The variable names a .env.local holds no value for, the built in credentials and those its repo's .env.kdf.example
// names.
function credentialNames(dir) {
  const names = new Set(KDF_CREDENTIALS);
  try {
    for (const m of fs.readFileSync(path.join(dir, '.env.kdf.example'), 'utf8').matchAll(EXAMPLE_NAME)) names.add(m[1]);
  } catch (err) {
    // no example, the built in names alone. An example that exists and cannot be read is a check that failed (D-059).
    if (!missingPath(err)) throw err;
  }
  return names;
}

// Whether a .env.local still holds a credential. The guard reads the file itself and never shows a value to anyone. A
// file that does not exist holds nothing to leak, and one that exists and cannot be read is a check that could not
// run, a lock that clears before the session's own read for example, so it refuses (D-060).
function holdsCredential(p) {
  const abs = path.resolve(CWD, p);
  let text;
  try {
    text = fs.readFileSync(abs, 'utf8');
  } catch (err) {
    if (missingPath(err)) return false;
    throw err;
  }
  const names = credentialNames(path.dirname(abs));
  for (const m of text.matchAll(ENV_LINE)) {
    const value = m[2].replace(/[ \t]#.*$/, '').trim().replace(/^(["'])(.*)\1$/, '$2');
    if (names.has(m[1]) && value !== '') return true;
  }
  return false;
}

// A .env.local is open only in a repo that has adopted the env standard, a tracked .env.kdf.example beside it, and
// only while it holds none of the credentials that example and the built in list name. Until then it may hold anything,
// a file vercel env pull wrote for example, so it stays closed.
function localEnvOpen(p) {
  const abs = path.resolve(CWD, p);
  return trackedByGit(path.join(path.dirname(abs), '.env.kdf.example')) && !holdsCredential(p);
}

// A file no session reads, writes, copies, sources or passes to a command.
function isClosed(p) {
  const s = String(p || '');
  if (!s) return false;
  if (LOCAL_ENV.test(s) ? !localEnvOpen(s) : isSecretFile(s)) return true;
  // the same path from the folder the shell is in, so cd keys && cat id_rsa names keys/id_rsa (D-068)
  const abs = s.startsWith('-') ? '' : resolvedPath(s);
  return Boolean(abs) && abs !== s && !LOCAL_ENV.test(s) && KEY_FILE.test(abs);
}

function checkClosed(p, detail) {
  if (!isClosed(p)) return;
  const s = String(p);
  deny(LOCAL_ENV.test(s) ? CREDENTIAL_WHY : ADMIN_ENV.test(s) ? ADMIN_WHY : SECRET_WHY, detail);
}

// Programs whose first word is a pattern, which may spell .env with a backslash or a caret, '^\.env' for example.
const PATTERN_FIRST = new Set(['grep', 'egrep', 'fgrep', 'rg', 'sed', 'awk', 'gawk', 'select-string', 'sls']);

// A search pattern, not a path. It has a regex or escape character and names no file on disk, so it holds nothing.
function isPattern(prog, word) {
  return PATTERN_FIRST.has(prog) && /[\\^$|()[\]*+?{}]/.test(word) && !fs.existsSync(path.resolve(CWD, word));
}

// Bash expands an unquoted *, ? or [...] into the paths it matches before the program runs, so cat .env* reads
// .env.kdf though no word names it. The guard judges every call as written, then once more for each path a glob
// matches, the glob swapped for that path whole and in the form bash gives it, and for the whole list bash would give,
// so a match meets every rule a named path or word meets, the secret files, a reviewer's ignored and held paths, the
// protected ones, and git's subcommand, branch and flags. Each extra judgment can only refuse, so a glob never makes
// the guard allow what it would refuse as written. A glob whose last part starts with a dot and could match a secret's
// name is refused wherever it runs, since a cd earlier in the line can move it (D-060).
const GLOB_CHAR = /[*?[]/;
const DOT_SECRET_NAMES = ['.env', '.env.kdf', '.env.dev', '.env.prod', '.env.x'];
const GLOB_LIMIT = 200;
const ASSIGNMENT = /^[A-Za-z_][A-Za-z0-9_]*=/;
const ALL_WILD = () => true;
// the matches counted across the whole call, and whether the call turns on dotglob, which lets * match a dot name
let GLOB_TOTAL = 0;
let HIDDEN_TOO = false;
const STAR = { star: true };
const ONE = { one: true };

// Two characters the same, and on Windows the same in either case, since its file system ignores case. Compared one
// character at a time, so a letter whose lower case is two characters, such as İ, still lines up.
function sameChar(a, b) {
  if (a === b) return true;
  return process.platform === 'win32' && (a.toLowerCase() === b.toLowerCase() || a.toUpperCase() === b.toUpperCase());
}

// Where the bracket expression whose [ is at start ends, at the first ] outside quotes after its first member, with
// [:alpha:], [=a=] and [.a.] held whole, or -1 when it never ends and the [ is itself. wild says which characters
// came outside quotes.
function bracketEnd(part, start, wild) {
  let j = start + 1;
  if (part[j] === '!' || part[j] === '^') j++;
  if (part[j] === ']') j++;
  while (j < part.length) {
    if (part[j] === '[' && ':=.'.includes(part[j + 1] || ' ')) {
      const close = part.indexOf(part[j + 1] + ']', j + 2);
      if (close < 0) return -1;
      j = close + 2;
      continue;
    }
    if (part[j] === ']' && wild(j)) return j;
    j++;
  }
  return -1;
}

// One part of a glob as steps, a character, one of any character, or a run of any. Only a *, ? or [ that came outside
// quotes is a wildcard, so work"[1]" stays itself. A bracket expression is taken as one of any character, which
// matches more than bash does, never less. Characters are read whole, so ? matches a character outside the basic
// plane as bash does.
function globSteps(part, wild) {
  const steps = [];
  for (let i = 0; i < part.length;) {
    const c = String.fromCodePoint(part.codePointAt(i));
    if (wild(i) && c === '*') {
      if (steps[steps.length - 1] !== STAR) steps.push(STAR);
    } else if (wild(i) && c === '?') {
      steps.push(ONE);
    } else if (wild(i) && c === '[' && bracketEnd(part, i, wild) >= 0) {
      steps.push(ONE);
      i = bracketEnd(part, i, wild) + 1;
      continue;
    } else {
      steps.push(c);
    }
    i += c.length;
  }
  return steps;
}

function hasWildcard(part, wild) {
  for (let i = 0; i < part.length; i++) if (wild(i) && GLOB_CHAR.test(part[i])) return true;
  return false;
}

// Whether a name matches the steps, in time bounded by the name's length times the steps' count, a run of any retried
// from the last one seen only, so no pattern can make the check take long.
function globMatch(steps, name) {
  const s = Array.from(name);
  let i = 0;
  let j = 0;
  let star = -1;
  let mark = 0;
  while (i < s.length) {
    if (j < steps.length && steps[j] !== STAR && (steps[j] === ONE || sameChar(steps[j], s[i]))) {
      i++;
      j++;
    } else if (j < steps.length && steps[j] === STAR) {
      star = j++;
      mark = i;
    } else if (star >= 0) {
      j = star + 1;
      i = ++mark;
    } else {
      return false;
    }
  }
  while (j < steps.length && steps[j] === STAR) j++;
  return j === steps.length;
}

// Whether a path is there, a missing one or one under a file being no, any other error a check that could not run.
function pathThere(p) {
  try {
    fs.lstatSync(p);
    return true;
  } catch (err) {
    if (missingPath(err)) return false;
    throw err;
  }
}

// The paths a glob matches that exist, whole and sorted, part by part from the folder the call runs in or from the
// root, whose own characters are never a glob, so a folder named work[1] stays itself. wild says which of the word's
// characters came outside quotes. A name starting with a dot matches only a part that starts with one, as in bash. A
// folder that is not there matches nothing, any other error reading one is a check that could not run, and more than
// GLOB_LIMIT paths are more than the guard checks.
function globMatches(word, wild) {
  const from = globBase(word);
  let found = [from.base];
  let start = from.start;
  for (let i = start; i <= word.length; i++) {
    if (i < word.length && word[i] !== '/' && word[i] !== '\\') continue;
    const part = word.slice(start, i);
    const at = start;
    start = i + 1;
    if (!part) continue;
    const local = (j) => wild(at + j);
    const next = [];
    for (const dir of found) {
      if (!hasWildcard(part, local)) {
        next.push(path.join(dir, part));
        continue;
      }
      let names;
      try {
        names = fs.readdirSync(dir);
      } catch (err) {
        if (missingPath(err)) continue;
        throw err;
      }
      const steps = globSteps(part, local);
      for (const name of names) {
        if (name.startsWith('.') && !part.startsWith('.') && !HIDDEN_TOO) continue;
        if (globMatch(steps, name)) next.push(path.join(dir, name));
      }
      if (next.length > GLOB_LIMIT) throw new Error('a glob matched more than ' + GLOB_LIMIT + ' paths');
    }
    found = next;
    if (!found.length) break;
  }
  return found.filter(pathThere).sort();
}

// Where a glob starts, the home folder for ~, the drive for Git Bash's /c/, the root for a whole path, otherwise the
// folder the call runs in, and the place in the word its own parts begin. None of these is ever read as a glob.
function globBase(word) {
  if (word === '~' || word.startsWith('~/')) return { base: os.homedir(), start: Math.min(2, word.length) };
  const drive = process.platform === 'win32' ? /^\/([A-Za-z])(\/|$)/.exec(word) : null;
  if (drive) return { base: drive[1].toUpperCase() + ':\\', start: drive[0].length };
  if (path.isAbsolute(word)) {
    const root = path.parse(word).root;
    return { base: path.resolve(root), start: root.length };
  }
  return { base: CWD, start: 0 };
}

// A match in the form bash gives it, whole for a glob that starts from a root or ~, otherwise relative to the call's
// folder, ./ kept.
function bashForm(word, p) {
  if (globBase(word).base !== CWD) return p;
  const rel = path.relative(CWD, p).split(path.sep).join('/');
  return word.startsWith('./') ? './' + rel : rel;
}

const REDIRECT_OP = /^\d*(?:<|>>?|&>>?)$/;
const REDIRECT_JOINED = /^(\d*(?:<|>>?|&>>?))(.+)$/;

// The segment once more for each path an unquoted glob matches, in both forms, for each glob's whole list in each
// form, and with every glob's whole list at once in each form, which is bash's own expansion when there are several,
// `git p* origin ma*` for example. Each is a token list analyze judges like the segment, a redirect's target behind
// its operator. A glob in an assignment before the program is left, as bash leaves it, and a segment led by a command
// that only shows a file exists, ls for example, gets these only for its redirect targets, since analyze checks
// nothing else of it.
function globVariants(toks) {
  let lead = 0;
  while (lead < toks.length && !toks[lead].lq && ASSIGNMENT.test(toks[lead].t)) lead++;
  const existence = lead < toks.length && EXISTENCE_ONLY.has(base(toks[lead].t));
  const variants = [];
  const whole = new Map();
  const shapedAll = new Map();
  for (let k = lead; k < toks.length; k++) {
    const t = toks[k];
    if (!t.g) continue;
    const joined = REDIRECT_JOINED.exec(t.t);
    const target = Boolean(joined) || (k > 0 && !toks[k - 1].q && REDIRECT_OP.test(toks[k - 1].t));
    if (existence && !target) continue;
    const op = joined ? joined[1] : '';
    const word = t.t.slice(op.length);
    const found = globMatches(word, (j) => t.gm.has(j + op.length));
    GLOB_TOTAL += found.length;
    if (GLOB_TOTAL > GLOB_LIMIT) throw new Error('globs matched more than ' + GLOB_LIMIT + ' paths in the call');
    if (!found.length) continue;
    const shaped = found.map((p) => op + bashForm(word, p));
    const paths = found.map((p) => op + p);
    whole.set(k, paths);
    shapedAll.set(k, shaped);
    for (const w of paths.concat(shaped)) variants.push(swapWords(toks, new Map([[k, [w]]])));
    variants.push(swapWords(toks, new Map([[k, shaped]])), swapWords(toks, new Map([[k, paths]])));
  }
  if (whole.size > 1) variants.push(swapWords(toks, shapedAll), swapWords(toks, whole));
  return variants;
}

// A token list with the words at the given places replaced, each new word a plain token.
function swapWords(toks, words) {
  const out = [];
  toks.forEach((t, k) => {
    if (!words.has(k)) {
      out.push(t);
      return;
    }
    // a swapped redirect target stays a target, so the redirect rules still meet it
    for (const w of words.get(k)) out.push({ t: w, q: false, lq: false, g: false, gm: new Set(), target: t.target });
  });
  return out;
}

// A glob whose last part starts with a dot and could match a secret's name, refused wherever it runs, since a cd
// earlier in the line can move it. Every glob character counts here, quoted or not, which refuses more, never less.
function checkDotGlob(word, whole) {
  const last = String(word || '').split(/[\\/]/).pop();
  if (!last.startsWith('.') || !GLOB_CHAR.test(last)) return;
  const steps = globSteps(last, ALL_WILD);
  if (DOT_SECRET_NAMES.some((name) => globMatch(steps, name))) deny(SECRET_WHY, whole);
}

// A command names a secret file only to check that it exists. The words are the program, its arguments, the value
// after an =, a curl style @file, and a redirect's target, so --env-file=.env.prod, -d @.env.kdf and >.env.kdf count.
// A redirect reads or writes its target whatever the program, so it is checked before the existence checks pass.
function checkSecretWords(toks, prog, args, whole) {
  for (let k = 0; k < toks.length; k++) {
    const m = toks[k].q ? null : /^\d*(?:<|>>?|&>>?)(.*)$/.exec(toks[k].t);
    if (!m) continue;
    const target = m[1] || (toks[k + 1] ? toks[k + 1].t : '');
    checkClosed(target, whole);
    if (m[1] ? toks[k].g : toks[k + 1] && toks[k + 1].g) checkDotGlob(target, whole);
  }
  if (EXISTENCE_ONLY.has(prog)) return;
  if (prog === 'git' && gitSplit(args).sub === 'check-ignore') return;
  for (const t of toks) {
    if (t.g) checkDotGlob(t.t, whole);
    if (isPattern(prog, t.t)) continue;
    const words = [t.t];
    const eq = t.t.indexOf('=');
    if (eq > 0) words.push(t.t.slice(eq + 1));
    const redirect = /^\d*(?:<|>>?|&>>?)(.+)$/.exec(t.t);
    if (redirect) words.push(redirect[1]);
    for (const w of words.filter((x) => x.startsWith('@'))) words.push(w.slice(1));
    for (const w of words) checkClosed(w, whole);
  }
}

// ------------------------------------------------------------ reading files

// Whether git ran and answered no, exit 1, or said the path is in no repository, exit 128 with git's own message for
// that at the start of its output, so the words elsewhere in another fatal error do not count. Anything else, git
// failing to start, stopped at its timeout or a fatal error of another kind, is a check that could not run and
// refuses the call (D-059).
function gitSaidNo(err) {
  if (err.code || err.signal || typeof err.status !== 'number') return false;
  if (err.status === 1) return true;
  return err.status === 128 && /^fatal: not a git repository/.test(String(err.stderr || '').trimStart());
}
// git's answers, each within the guard's own deadline
const gitQuiet = () => ({
  stdio: ['ignore', 'ignore', 'pipe'], timeout: Math.min(10000, timeLeft()), windowsHide: true
});

// The nearest folder that exists, the path's own or one above it, since git cannot be started in a folder that does
// not exist, a new report's or a tracked file's whose folder was deleted.
function nearestFolder(dir) {
  let at = dir;
  while (!fs.existsSync(at)) {
    const up = path.dirname(at);
    if (up === at) break;
    at = up;
  }
  return at;
}

// Git's answers in this call, by question and path, since a glob's extra judgments ask about the same path again.
const GIT_ANSWERS = new Map();
function remembered(kind, abs, ask) {
  const key = kind + ' ' + abs;
  if (!GIT_ANSWERS.has(key)) GIT_ANSWERS.set(key, ask());
  return GIT_ANSWERS.get(key);
}

// A path git tracks, judged by the repo that holds it, asked from the nearest folder that exists. Anything git answers
// no to counts as untracked.
function trackedByGit(p) {
  const abs = path.resolve(CWD, p);
  return remembered('tracked', abs, () => askTracked(abs));
}

function askTracked(abs) {
  try {
    execFileSync('git', ['-C', nearestFolder(path.dirname(abs)), 'ls-files', '--error-unmatch', '--', abs], gitQuiet());
    return true;
  } catch (err) {
    if (!gitSaidNo(err)) throw err;
    return false;
  }
}

// A path git ignores, judged by the repo that holds it. A path that does not exist holds nothing to read, and any
// other error reading it is a check that could not run (D-060).
function ignoredByGit(p) {
  const abs = path.resolve(CWD, p);
  return remembered('ignored', abs, () => askIgnored(abs));
}

function askIgnored(abs) {
  let dir;
  try {
    dir = fs.statSync(abs).isDirectory() ? abs : path.dirname(abs);
  } catch (err) {
    if (missingPath(err)) return false;
    throw err;
  }
  try {
    execFileSync('git', ['-C', dir, 'check-ignore', '-q', '--', abs], gitQuiet());
    return true;
  } catch (err) {
    if (!gitSaidNo(err)) throw err;
    return false;
  }
}

// Reviewers. The reports the launcher holds, a secret file, and a path git ignores stay closed. .env.local is the one
// ignored file a reviewer may open, and the credential rule decides it.
function checkReviewerOpens(p, detail) {
  if (/\/\.git\/kdf-review(\/|$)/.test(norm(path.resolve(CWD, p)))) deny(HELD_WHY, detail);
  checkClosed(p, detail);
  if (!LOCAL_ENV.test(p) && ignoredByGit(p)) deny(IGNORED_WHY + ' ' + p + ' is ignored.', detail);
}

// The Read, Grep and Glob tools. Glob lists names and never content, so only a reviewer's Glob is checked.
function checkReadTool(tool, args) {
  const target = String((tool === 'Read' ? args.file_path : args.path) || '');
  if (target && tool !== 'Glob') checkClosed(target, tool + ' ' + target);
  if (MODE !== 'reviewer') return;
  if (target) checkReviewerOpens(target, tool + ' ' + target);
  if (tool === 'Glob') {
    // the pattern's leading directories before its first wildcard, node_modules/** for example
    const literal = [];
    for (const part of String(args.pattern || '').split(/[\\/]+/)) {
      if (!part || /[*?[\]{}]/.test(part)) break;
      literal.push(part);
    }
    if (literal.length) checkReviewerOpens(path.join(target || CWD, ...literal), tool + ' ' + args.pattern);
  }
}

// ------------------------------------------------------------ the approved list (D-068)

// The guard lets a command through only when it is plain and on the owner's list below, each program with the
// subcommands and flags written there, and refuses everything else. Plain means words, single quotes, double quotes
// with no $, backtick or backslash inside, &&, ||, ;, |, a newline, and a redirect into the temp folder, so the guard
// reads the command exactly as bash runs it and never has to work out what bash would make of it. A removal asks the
// owner, the command shown in the prompt, unless every path it names is a temporary file. The owner changes the list
// by pull request, and only the owner installs it.

const MAX_COMMAND = 10000;
const NOT_PLAIN = 'The guard reads only plain commands, words, quotes, &&, ||, ;, | and a redirect into the temp '
  + 'folder, so it refuses this one. ';
const notListed = (name) => name + ' is not on the owner\'s list of approved commands. Write it with listed commands, '
  + 'or ask the owner, who runs it or adds it to the list by pull request.';
// The variables a command may set for itself, each an exact name and value.
const ALLOWED_ASSIGNS = new Set(['PYTHONIOENCODING=utf-8', 'NO_COLOR=1', 'FORCE_COLOR=0', 'GIT_PAGER=cat']);
// Characters a word may hold outside quotes, each one bash reads as itself.
const PLAIN_CHAR = /[A-Za-z0-9/._\-=:,@+%^~#*?[\]]/;
// What may follow a $ for bash to expand it, a name, a digit, a brace, a parenthesis, a bracket or a special parameter.
const EXPANDS = /^[A-Za-z0-9_{(@*#?$!\-[]/;
// Where a session writes, and removes, freely. The owner's word of 2026-10-12, "All scrath pads, temp files, and other
// temporary files should be allowed to be deleted as they are temporary".
const TEMP_ROOTS = (process.env.KDF_GUARD_TEMP_ROOTS || [os.tmpdir(), 'D:/KriegerDataForge/temp'].join(';'))
  .split(';').filter(Boolean).map((r) => path.resolve(r).replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase());

// A call read into its commands, each a list of tokens. A redirect is a token of its own, op, followed by its target,
// so the checks that read tokens see the target after its operator. Anything not plain refuses the call.
function readPlain(cmd) {
  const cmds = [];
  let cur = [];
  let tok = null;
  let wantTarget = false;
  const refuse = (why) => deny(NOT_PLAIN + why, cmd);
  const start = () => {
    if (!tok) tok = { t: '', q: false, lq: false, g: false, gm: new Set() };
  };
  const endTok = () => {
    if (!tok) return;
    tok.g = tok.gm.size > 0;
    if (wantTarget) {
      tok.target = true;
      wantTarget = false;
    }
    cur.push(tok);
    tok = null;
  };
  const endCmd = (op) => {
    endTok();
    if (wantTarget) refuse('A redirect has no target.');
    if (!cur.length) {
      if (op && op !== '\n') refuse('Nothing comes before ' + op + '.');
      return;
    }
    cmds.push({ toks: cur, op });
    cur = [];
  };
  const quoted = (body) => {
    start();
    if (!tok.t && !tok.q) tok.lq = true;
    tok.q = true;
    tok.t += body;
  };
  for (let i = 0; i < cmd.length; i++) {
    const c = cmd[i];
    const n = cmd[i + 1];
    if (c === ' ' || c === '\t' || (c === '\r' && n === '\n')) {
      endTok();
      continue;
    }
    if (c === '\n') {
      endCmd('\n');
      continue;
    }
    if (c === '#' && !tok) {
      while (i + 1 < cmd.length && cmd[i + 1] !== '\n') i++;
      continue;
    }
    if (c === '\'') {
      const end = cmd.indexOf('\'', i + 1);
      if (end < 0) refuse('A quote is never closed.');
      quoted(cmd.slice(i + 1, end));
      i = end;
      continue;
    }
    if (c === '"') {
      // bash's own reading of double quotes. A backslash escapes only $, a backtick, ", \ and a newline, and stays a
      // character before anything else. A $ expands only before a name, a digit, a brace, a parenthesis, a bracket or
      // a special parameter, and a backtick always runs a command.
      let j = i + 1;
      let body = '';
      for (; j < cmd.length && cmd[j] !== '"'; j++) {
        const ch = cmd[j];
        if (ch === '\\' && j + 1 < cmd.length && '$`"\\\n'.includes(cmd[j + 1])) {
          if (cmd[j + 1] !== '\n') body += cmd[j + 1];
          j++;
          continue;
        }
        if (ch === '`' || (ch === '$' && EXPANDS.test(cmd[j + 1] || ''))) {
          refuse('Double quotes hold a $ or a backtick that bash would expand. Use single quotes, write the value out, '
            + 'or put the text in a file, git commit -F and gh --body-file.');
        }
        body += ch;
      }
      if (j >= cmd.length) refuse('A quote is never closed.');
      quoted(body);
      i = j;
      continue;
    }
    if (c === '\\') {
      // outside quotes a backslash makes the next character itself, and before a newline joins the lines
      if (n === '\n') {
        i++;
        continue;
      }
      if (n === '\r' && cmd[i + 2] === '\n') {
        i += 2;
        continue;
      }
      if (n === undefined) refuse('A backslash ends the command.');
      quoted(n);
      i++;
      continue;
    }
    if (c === '$' && !EXPANDS.test(n || '') && n !== '\'' && n !== '"') {
      // a $ before nothing it could expand is the character itself, as in grep 'x' file$ or a word that ends in $
      start();
      tok.t += c;
      continue;
    }
    if (c === '&' && n === '&') {
      endCmd('&&');
      i++;
      continue;
    }
    if (c === '|' && n === '|') {
      endCmd('||');
      i++;
      continue;
    }
    if (c === '|') {
      if (n === '&') refuse('|& is refused, write 2>&1 | instead.');
      endCmd('|');
      continue;
    }
    if (c === ';') {
      if (n === ';') refuse(';; belongs to a case, which is refused.');
      endCmd(';');
      continue;
    }
    if (c === '<' || c === '>' || (c === '&' && n === '>')) {
      i = readRedirect(cmd, i);
      continue;
    }
    if (c === '&') refuse('A background & is refused. Run it in the foreground, or use the tool\'s own background.');
    if (c === '~') {
      const prev = tok ? tok.t[tok.t.length - 1] : '';
      if (!tok && !(n === undefined || n === '/' || /[\s;&|<>]/.test(n))) {
        refuse('~ is allowed alone or as ~/ at the start of a word.');
      }
      if (tok && (prev === '=' || prev === ':')) refuse('A ~ after = or : would be expanded. Write the path out.');
      start();
      tok.t += c;
      continue;
    }
    if (PLAIN_CHAR.test(c)) {
      start();
      if (c === '*' || c === '?' || c === '[') tok.gm.add(tok.t.length);
      tok.t += c;
      continue;
    }
    if (c === '$') refuse('A $ would expand a variable or run a command. Write the value out.');
    if (c === '`') refuse('A backtick runs a command. Run it as a command of its own.');
    if (c === '(' || c === ')') refuse('A parenthesis opens a subshell or a function. Write the commands out.');
    if (c === '{' || c === '}') refuse('A brace is refused. Quote it, or write the words out.');
    if (c === '!') refuse('! is refused outside quotes.');
    refuse('The character ' + JSON.stringify(c) + ' is refused outside quotes. Quote it.');
  }
  endCmd('');
  const last = cmds[cmds.length - 1];
  if (last && (last.op === '&&' || last.op === '||' || last.op === '|')) refuse('Nothing comes after ' + last.op + '.');
  return cmds;

  // A redirect, its file descriptor taken from the word before when that word is digits joined to it, 2> for example.
  // A copy of one descriptor to another, 2>&1, needs no target. A heredoc, a here-string and every rarer form refuse.
  function readRedirect(text, i) {
    let fd = '';
    if (tok && !tok.q && /^\d+$/.test(tok.t)) {
      fd = tok.t;
      tok = null;
    } else {
      endTok();
    }
    if (wantTarget) refuse('A redirect has no target.');
    let op;
    const rest = text.slice(i, i + 4);
    if (rest.startsWith('&>>')) op = '&>>';
    else if (rest.startsWith('&>')) op = '&>';
    else if (rest.startsWith('<<')) refuse('A heredoc or a here-string is refused. Put the text in a file.');
    else if (rest.startsWith('<>') || rest.startsWith('>|')) refuse('That redirect is refused.');
    else if (rest.startsWith('<(') || rest.startsWith('>(')) refuse('A process substitution is refused.');
    else if (rest.startsWith('>>')) op = '>>';
    else if (rest.startsWith('>&') || rest.startsWith('<&')) op = rest.slice(0, 2);
    else op = rest[0];
    let j = i + op.length;
    if (op === '>&' || op === '<&') {
      const m = /^(\d+|-)/.exec(text.slice(j));
      if (!m || m[1] === '-') refuse('Only a copy of one numbered output to another, such as 2>&1, is allowed.');
      cur.push({ t: fd + op + m[1], q: false, lq: false, g: false, gm: new Set(), redir: true, dup: true });
      return j + m[1].length - 1;
    }
    cur.push({ t: fd + op, q: false, lq: false, g: false, gm: new Set(), redir: true });
    wantTarget = true;
    return j - 1;
  }
}

// A path as Windows names it, from Git Bash's spellings, /d/x for D:/x, /tmp for the temp folder and ~ for home.
function toAbs(p) {
  let s = String(p);
  if (s === '~' || s.startsWith('~/')) s = os.homedir() + s.slice(1);
  s = s.replace(/\\/g, '/');
  const drive = /^\/([a-zA-Z])(\/|$)/.exec(s);
  if (drive) s = drive[1] + ':/' + s.slice(3);
  else if (/^\/tmp(\/|$)/i.test(s)) s = os.tmpdir() + s.slice(4);
  return path.resolve(CWD, s).replace(/\\/g, '/');
}

function inTemp(p) {
  const abs = toAbs(p).toLowerCase();
  return TEMP_ROOTS.some((root) => abs.startsWith(root + '/'));
}

// Whether a path lies inside a git working tree under its temp root, a .git between it and the root. A worktree under
// the temp folder holds a repo's files and work never committed, so it is never a temporary file.
function insideWorkTree(p) {
  const abs = toAbs(p);
  const root = TEMP_ROOTS.find((r) => abs.toLowerCase().startsWith(r + '/'));
  for (let dir = abs; root && dir.length > root.length; dir = path.posix.dirname(dir)) {
    if (fs.existsSync(path.join(dir, '.git'))) return true;
  }
  return false;
}

// A temp file a session writes freely, inside a temp root and outside every working tree.
function tempFile(p) {
  return inTemp(p) && !insideWorkTree(p);
}

// Whether a path is, holds or lies inside a git working tree. Holds means a .git at any depth below it, and a
// folder too large to look through counts as holding one.
function holdsWorkTree(p) {
  if (insideWorkTree(p)) return true;
  const abs = toAbs(p);
  let seen = 0;
  const walk = (dir, depth) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch (err) {
      if (missingPath(err) || err.code === 'ENOTDIR') return false;
      throw err;
    }
    for (const e of entries) {
      if (++seen > 5000) return true;
      if (e.name === '.git') return true;
      if (e.isDirectory() && walk(path.join(dir, e.name), depth + 1)) return true;
    }
    return false;
  };
  return walk(abs, 1);
}

// A path removed or written over runs without asking only when it is written out, lies inside a temp root and holds
// no working tree.
function freeToRemove(t) {
  return !t.g && inTemp(t.t) && !holdsWorkTree(t.t);
}

function exists(p) {
  try {
    fs.statSync(toAbs(p));
    return true;
  } catch (err) {
    if (missingPath(err)) return false;
    throw err;
  }
}

function isDir(p) {
  try {
    return fs.statSync(toAbs(p)).isDirectory();
  } catch (err) {
    if (missingPath(err)) return false;
    throw err;
  }
}

// ---- the list's options

// An option list is space separated. -x takes no value, -x= takes one, joined or the next word, and -x? takes an
// optional one joined to it. --long takes none, --long= takes one after = or as the next word, --long? one after =
// only. -# is a number standing alone, head -20. ANY is a program none of whose options writes a file, reads a file
// unasked or runs a command, so every option passes.
const ANY = 'any';
const SPECS = new Map();
function spec(list) {
  if (list === ANY) return ANY;
  if (!SPECS.has(list)) {
    const m = new Map();
    for (const o of list.split(/\s+/).filter(Boolean)) {
      const kind = /[=?]$/.test(o) ? o.slice(-1) : '';
      m.set(kind ? o.slice(0, -1) : o, kind);
    }
    SPECS.set(list, m);
  }
  return SPECS.get(list);
}

// The options and operands of a command's words, each option checked against its list. With first, it stops at the
// first operand and leaves the rest, a subcommand's or a script's own words. The reason for a refused option comes
// from why when it names one.
function readOpts(list, args, label, whole, why = {}, first = false) {
  const s = spec(list);
  const operands = [];
  const seen = [];
  // each option's value as the program reads it, joined or the next word, so a check can read a value wherever it
  // was written, sed -ne'p' among them
  const values = [];
  let k = 0;
  const refuse = (opt) => deny((why[opt] || (label + ' ' + opt + ' is not on the owner\'s list for ' + label
    + '. Use another form, or ask the owner.')), whole);
  for (; k < args.length; k++) {
    const a = args[k];
    if (a === '--') {
      operands.push(...args.slice(k + 1));
      k = args.length;
      break;
    }
    if (a === '-' || !a.startsWith('-')) {
      if (first) break;
      operands.push(a);
      continue;
    }
    if (s === ANY) {
      seen.push(a);
      continue;
    }
    if (a.startsWith('--')) {
      const eq = a.indexOf('=');
      const name = eq < 0 ? a : a.slice(0, eq);
      if (!s.has(name)) refuse(name);
      const kind = s.get(name);
      if (kind === '' && eq >= 0) refuse(name);
      seen.push(name);
      if (eq >= 0) values.push({ name, value: a.slice(eq + 1) });
      else if (kind === '=') values.push({ name, value: args[++k] === undefined ? '' : args[k] });
      continue;
    }
    if (/^-\d+$/.test(a) && s.has('-#')) {
      seen.push('-#');
      continue;
    }
    for (let j = 1; j < a.length; j++) {
      const name = '-' + a[j];
      if (!s.has(name)) refuse(name);
      seen.push(name);
      const kind = s.get(name);
      if (kind === '=') {
        if (j === a.length - 1) values.push({ name, value: args[++k] === undefined ? '' : args[k] });
        else values.push({ name, value: a.slice(j + 1) });
        break;
      }
      if (kind === '?') {
        if (j < a.length - 1) values.push({ name, value: a.slice(j + 1) });
        break;
      }
    }
  }
  return { operands, seen, values, rest: args.slice(k), has: (o) => seen.includes(o) };
}

// ---- the list itself, by group

const TEXT = { text: true };
const GREP_WHY = {
  '-r': 'grep -r can read a secret file. Search with rg, which skips hidden and ignored files, or git grep.',
  '-R': 'grep -R can read a secret file. Search with rg, which skips hidden and ignored files, or git grep.',
  '--recursive': 'grep --recursive can read a secret file. Search with rg or git grep.',
  '--dereference-recursive': 'grep --dereference-recursive can read a secret file. Search with rg or git grep.',
  '-d': 'grep -d recurse can read a secret file. Search with rg or git grep.',
  '--directories': 'grep --directories=recurse can read a secret file. Search with rg or git grep.'
};
const RG_WHY = {
  '--hidden': 'rg --hidden reads hidden files, every secret file among them. Drop the flag.',
  '-.': 'rg -. reads hidden files, every secret file among them. Drop the flag.',
  '-u': 'rg -u reads ignored files, every secret file among them. Drop the flag.',
  '--unrestricted': 'rg --unrestricted reads ignored files, every secret file among them. Drop the flag.',
  '--no-ignore': 'rg --no-ignore reads ignored files, every secret file among them. Drop the flag.',
  '--pre': 'rg --pre runs a command on each file. Drop the flag.'
};
const LIST = {
  // read and search, none of whose options writes or runs anything
  cat: ANY, head: ANY, tail: ANY, wc: ANY, cut: ANY, tr: ANY, nl: ANY, tac: ANY, rev: ANY, paste: ANY, comm: ANY,
  join: ANY, fold: ANY, column: ANY, seq: ANY, basename: ANY, dirname: ANY, realpath: ANY, cygpath: ANY, md5sum: ANY,
  sha1sum: ANY, sha256sum: ANY, cmp: ANY, od: ANY, hexdump: ANY, stat: ANY, du: ANY, df: ANY, ls: ANY, which: ANY,
  type: ANY, pwd: ANY, true: ANY, false: ANY, sleep: ANY, jq: ANY, base64: ANY, hostname: ANY, nproc: ANY, ps: ANY,
  where: ANY, tasklist: ANY, ipconfig: ANY, readlink: ANY, actionlint: ANY,
  xxd: { opts: ANY, maxOperands: 1 },
  file: { opts: '-b -i -L -h -z -s -k -r -N -0 -F= -e= -m= --brief --mime --mime-type --mime-encoding --dereference '
    + '--no-dereference --uncompress --special-files --keep-going --raw --separator= --exclude= --magic-file=' },
  grep: {
    opts: '-n -E -F -G -P -v -i -y -c -o -l -L -w -x -h -H -q -s -a -I -z -Z -T -b -U -A= -B= -C= -m= -e= -f= -# '
      + '--line-number --extended-regexp --fixed-strings --basic-regexp --perl-regexp --invert-match --ignore-case '
      + '--no-ignore-case --count --only-matching --files-with-matches --files-without-match --word-regexp '
      + '--line-regexp --no-filename --with-filename --quiet --silent --no-messages --text --binary-files= --null '
      + '--null-data --initial-tab --byte-offset --line-buffered --after-context= --before-context= --context= '
      + '--max-count= --regexp= --file= --color? --colour? --label= --include= --exclude= --exclude-dir=',
    why: GREP_WHY
  },
  rg: {
    opts: '-n -i -S -s -w -x -v -c -l -o -F -N -H -I -U -L -p -q -0 -r= -e= -t= -T= -g= -A= -B= -C= -m= -d= -j= '
      + '-M= --line-number --no-line-number --ignore-case --smart-case --case-sensitive --word-regexp --line-regexp '
      + '--invert-match --count --count-matches --files-with-matches --files-without-match --only-matching '
      + '--fixed-strings --no-filename --with-filename --no-heading --heading --multiline --multiline-dotall --follow '
      + '--pretty --quiet --null --replace= --regexp= --type= --type-not= --glob= --iglob= --after-context= '
      + '--before-context= --context= --max-count= --max-depth= --threads= --max-columns= --sort= --sortr= --files '
      + '--type-list --json --column --vimgrep --stats --trim --color= --colors= --passthru --no-messages --unicode '
      + '--no-unicode --crlf --encoding= -E= --engine= --pcre2 --auto-hybrid-regex --max-filesize= --version -V',
    why: RG_WHY
  },
  sort: {
    opts: '-b -d -f -g -h -i -M -n -R -r -V -c -C -m -s -u -z -k= -t= -S= --ignore-leading-blanks --dictionary-order '
      + '--ignore-case --general-numeric-sort --human-numeric-sort --month-sort --numeric-sort --random-sort --reverse '
      + '--version-sort --check --merge --stable --unique --zero-terminated --key= --field-separator= --buffer-size= '
      + '--parallel= --sort= --debug',
    why: { '-o': 'sort -o writes a file. Redirect into the temp folder instead.' }
  },
  uniq: {
    opts: '-c -d -D -u -i -z -f= -s= -w= --count --repeated --all-repeated? --unique --ignore-case --zero-terminated '
      + '--skip-fields= --skip-chars= --check-chars= --group?',
    maxOperands: 1
  },
  diff: {
    opts: '-u -U= -c -C= -q -s -y -w -b -B -i -a -t -p -d -n -e -T -Z -E -W= -I= --brief --report-identical-files '
      + '--unified? --context? --side-by-side --width= --ignore-all-space --ignore-space-change --ignore-blank-lines '
      + '--ignore-case --text --expand-tabs --strip-trailing-cr --color? --suppress-common-lines --label= --minimal '
      + '--normal --show-c-function --ignore-matching-lines= --left-column --speed-large-files '
      + '--ignore-tab-expansion --ignore-trailing-space --tabsize= --initial-tab',
    why: { '-r': 'diff -r can read a secret file in either folder. Compare files by name, or use git diff.' }
  },
  date: { opts: '-u -d= -r= -I? -R --utc --universal --date= --reference= --iso-8601? --rfc-3339= --rfc-email --debug',
    operands: /^\+/ },
  echo: TEXT, test: TEXT,
  // printf -v sets a variable, PATH among them, so printf prints and nothing more
  printf: { form: (args, whole) => {
    if (/^-v/.test(args[0] || '') || (args[0] === '--' && /^-v/.test(args[1] || ''))) {
      deny('printf -v sets a variable, which a plain command never does. Print the value instead.', whole);
    }
    return { operands: [] };
  } },
  cd: { opts: '-L -P', maxOperands: 1 },
  mkdir: '-p -v -m= --parents --verbose --mode=',
  touch: '-a -c -m -d= -t= -r= --no-create --date= --reference=',
  cp: '-r -R -p -a -n -v -f -L -P --recursive --preserve? --no-clobber --verbose --force --archive',
  mv: '-f -n -v --no-clobber --verbose --force',
  tee: '-a --append',
  rm: '-r -R -f -v -d --recursive --force --verbose --dir',
  rmdir: '-p -v --parents --verbose --ignore-fail-on-non-empty',
  unlink: '',
  find: { form: findForm },
  sed: { form: sedForm },
  awk: { form: awkForm },
  command: { form: (args, whole) => {
    if (!/^-[vV]$/.test(args[0] || '')) deny('command runs only as command -v, to show where a program is.', whole);
    return { operands: args.slice(1) };
  } },
  exit: { form: (args, whole) => {
    if (args.length > 1 || (args[0] !== undefined && !/^\d{1,3}$/.test(args[0]))) deny('exit takes a number.', whole);
    return { operands: [] };
  } },
  git: { form: gitForm },
  gh: { form: ghForm },
  npm: { form: npmForm },
  npx: { form: npxForm },
  node: { form: (args, whole) => scriptForm('node', '-c --check --test --no-warnings --enable-source-maps '
    + '--experimental-vm-modules --max-old-space-size= --trace-warnings --version -v', args, whole, NODE_WHY) },
  bash: { form: (args, whole) => scriptForm('bash', '-e -x -u -n -v -o= --version', args, whole, BASH_WHY) },
  sh: { form: (args, whole) => scriptForm('sh', '-e -x -u -n -v -o= --version', args, whole, BASH_WHY) },
  python: { form: pythonForm },
  make: { form: (args, whole) => {
    const o = readOpts('-C= -s -j? -k -n -q -w -f= -r -R -p -v --no-print-directory --silent --quiet --dry-run '
      + '--just-print --keep-going --jobs? --directory= --file= --makefile= --print-directory --print-data-base '
      + '--warn-undefined-variables --no-builtin-rules --no-builtin-variables --version', args, 'make', whole);
    return { operands: o.operands, targets: o.operands.filter((x) => !x.includes('=')) };
  } },
  docker: { form: dockerForm },
  'docker-compose': { form: (args, whole) => {
    dockerLocal(whole);
    return composeForm(args, whole);
  } },
  terraform: { form: (args, whole) => {
    const subs = { fmt: '-check -diff -recursive -no-color -list= -write=', validate: '-no-color -json',
      version: '-json' };
    let k = 0;
    while (k < args.length && /^-chdir=/.test(args[k])) k++;
    const sub = args[k] || '';
    if (sub === '-version' || sub === '--version') return { operands: [] };
    if (!Object.prototype.hasOwnProperty.call(subs, sub)) {
      deny('terraform ' + sub + ' is not on the owner\'s list, which holds fmt, validate and version. Ask the owner.',
        whole);
    }
    return { sub, operands: tfOperands(subs[sub], args.slice(k + 1), whole) };
  } },
  claude: { form: (args, whole) => {
    if (!(args.length === 1 && /^(--version|-v)$/.test(args[0]))) {
      deny('claude runs only as claude --version. What loads into a session, and starting one, are the owner\'s.',
        whole);
    }
    return { operands: [] };
  } },
  curl: { form: (args, whole) => {
    checkCurl(args, (why) => deny(why, whole));
    return { operands: [] };
  } },
  codex: { form: (args, whole) => {
    const line = args.join(' ');
    if (!/^(--version|-V|login status|features list)$/.test(line)) {
      deny('codex runs only as codex --version, codex login status and codex features list. A Codex read goes '
        + 'through kdf-ask-codex.sh, and Codex\'s settings are the owner\'s.', whole);
    }
    return { operands: [] };
  } }
};
const NODE_WHY = {
  '-e': 'node -e runs code written in the command. Put it in a file and run node <file>.',
  '--eval': 'node --eval runs code written in the command. Put it in a file and run node <file>.',
  '-p': 'node -p runs code written in the command. Put it in a file and run node <file>.',
  '--print': 'node --print runs code written in the command. Put it in a file and run node <file>.'
};
const BASH_WHY = {
  '-c': 'bash -c runs code written in the command. Put it in a script file and run bash <file>.',
  '-s': 'bash -s runs code from its input. Put it in a script file and run bash <file>.',
  '-i': 'An interactive shell is refused.'
};

// terraform's own options are single dashed words, -check and -list=false.
function tfOperands(list, args, whole) {
  const ok = new Set(list.split(' ').map((o) => o.replace(/=$/, '')));
  const operands = [];
  for (const a of args) {
    if (!a.startsWith('-')) operands.push(a);
    else if (!ok.has(a.split('=')[0])) deny('terraform ' + a + ' is not on the owner\'s list.', whole);
  }
  return operands;
}

// A program that runs a script file, its own options first, then the file, then the script's words, which pass as
// they are, the owner's word of 2026-10-12 that scripts run unread.
function scriptForm(name, list, args, whole, why) {
  const o = readOpts(list, args, name, whole, why, true);
  if (!o.rest.length) {
    if (o.has('--version') || o.has('-v')) return { operands: [] };
    deny(name + ' runs a script file, ' + name + ' <file>. Code from its input or the command line is refused.', whole);
  }
  checkScriptFile(name, o.rest[0], whole);
  return { operands: [o.rest[0]], script: o.rest[0] };
}

// A script is a file on disk. Its input, - or a device such as /dev/stdin or /dev/fd/0, carries code written in the
// command, which is refused like -c.
function checkScriptFile(name, file, whole) {
  if (file === '-' || /^\/(dev|proc)\//i.test(String(file).replace(/\\/g, '/'))) {
    deny(name + ' ' + file + ' runs code from its input. Put it in a file and run ' + name + ' <file>.', whole);
  }
}

// The repo's own venv interpreter, a script or a module, never code written in the command.
function pythonForm(args, whole) {
  const m = args.indexOf('-m');
  const own = m < 0 ? args : args.slice(0, m);
  const o = readOpts('-u -B -I -E -s -S -O -q -X= -W= -V --version', own, 'python', whole, {
    '-c': 'python -c runs code written in the command. Put it in a file and run it with the venv python.'
  }, true);
  if (m >= 0 && o.rest.length === 0) o.rest = args.slice(m);
  if (!o.rest.length) {
    if (o.has('-V') || o.has('--version')) return { operands: [] };
    deny('python runs a file or a module, never code from its input.', whole);
  }
  checkScriptFile('python', o.rest[0], whole);
  if (o.rest[0] === '-m') {
    if (!o.rest[1]) deny('python -m needs a module.', whole);
    return { operands: [], module: o.rest[1], moduleArgs: o.rest.slice(2) };
  }
  return { operands: [o.rest[0]], script: o.rest[0] };
}

// find's tests, single dashed words, each with how many values it takes. Its actions that write a file or run a
// command are refused, -delete, -exec and their kin.
const FIND_TESTS = {
  '-name': 1, '-iname': 1, '-path': 1, '-ipath': 1, '-wholename': 1, '-iwholename': 1, '-regex': 1, '-iregex': 1,
  '-regextype': 1, '-type': 1, '-xtype': 1, '-maxdepth': 1, '-mindepth': 1, '-mtime': 1, '-mmin': 1, '-atime': 1,
  '-amin': 1, '-ctime': 1, '-cmin': 1, '-newer': 1, '-newermt': 1, '-anewer': 1, '-cnewer': 1, '-size': 1, '-perm': 1,
  '-user': 1, '-group': 1, '-links': 1, '-inum': 1, '-samefile': 1, '-lname': 1, '-ilname': 1, '-printf': 1,
  '-empty': 0, '-readable': 0, '-writable': 0, '-executable': 0, '-print': 0, '-print0': 0, '-ls': 0, '-prune': 0,
  '-not': 0, '-o': 0, '-or': 0, '-a': 0, '-and': 0, '-true': 0, '-false': 0, '-depth': 0, '-follow': 0, '-mount': 0,
  '-xdev': 0, '-nouser': 0, '-nogroup': 0, '-quit': 0, '-L': 0, '-H': 0, '-P': 0
};
function findForm(args, whole) {
  const operands = [];
  let tests = false;
  for (let k = 0; k < args.length; k++) {
    const a = args[k];
    if (a === '(' || a === ')' || a === '!' || a === ',') {
      tests = true;
      continue;
    }
    if (!a.startsWith('-')) {
      if (tests) deny('find ' + a + ' is not a test the owner\'s list holds.', whole);
      operands.push(a);
      continue;
    }
    if (!Object.prototype.hasOwnProperty.call(FIND_TESTS, a)) {
      deny('find ' + a + ' is not on the owner\'s list. find only lists, and a removal goes through rm, which asks.',
        whole);
    }
    tests = true;
    k += FIND_TESTS[a];
  }
  return { operands };
}

// A sed script as GNU sed reads it, each command checked. A command that writes a file, reads one or runs one, w, W,
// r, R, e, or an s flag of w or e, refuses the call. Text and labels pass, and a script it cannot read refuses.
function sedScriptOk(script) {
  const s = String(script);
  let i = 0;
  const skipAddress = () => {
    const one = () => {
      if (/\d/.test(s[i])) {
        while (/[\d~]/.test(s[i])) i++;
      } else if (s[i] === '$') {
        i++;
      } else if (s[i] === '/' || s[i] === '\\') {
        const d = s[i] === '\\' ? s[++i] : '/';
        i++;
        while (i < s.length && s[i] !== d) i += s[i] === '\\' ? 2 : 1;
        i++;
        while (s[i] === 'I' || s[i] === 'M') i++;
      } else {
        return false;
      }
      return true;
    };
    if (!one()) return;
    while (s[i] === ' ') i++;
    if (s[i] === ',') {
      i++;
      while (s[i] === ' ') i++;
      if (s[i] === '+' || s[i] === '~') i++;
      one();
    }
  };
  const part = (d) => {
    while (i < s.length && s[i] !== d) {
      if (s[i] === '\n') return false;
      i += s[i] === '\\' ? 2 : 1;
    }
    if (i >= s.length) return false;
    i++;
    return true;
  };
  while (i < s.length) {
    while (i < s.length && /[\s;]/.test(s[i])) i++;
    if (i >= s.length) break;
    if (s[i] === '#') {
      while (i < s.length && s[i] !== '\n') i++;
      continue;
    }
    skipAddress();
    while (s[i] === ' ' || s[i] === '!') i++;
    const c = s[i++];
    if (c === undefined) return false;
    if ('{}pdDnNPgGhHxlz=FqQ'.includes(c)) {
      while (/\d/.test(s[i] || '')) i++;
      continue;
    }
    if (c === ':' || c === 'b' || c === 't' || c === 'T' || c === 'v') {
      while (i < s.length && !/[;\n}]/.test(s[i])) i++;
      continue;
    }
    if (c === 'a' || c === 'i' || c === 'c') {
      while (i < s.length && s[i] !== '\n') i += s[i] === '\\' && s[i + 1] === '\n' ? 2 : 1;
      continue;
    }
    if (c === 's' || c === 'y') {
      const d = s[i++];
      if (!d || d === '\n' || d === '\\') return false;
      if (!part(d) || !part(d)) return false;
      if (c === 's') {
        while (i < s.length && /[gpiImM0-9]/.test(s[i])) i++;
        if (i < s.length && !/[\s;}]/.test(s[i])) return false;
      }
      continue;
    }
    return false;
  }
  return true;
}
function sedForm(args, whole) {
  const why = 'A sed script that writes a file, reads one or runs a command, w, W, r, R or e, is refused, and so is a '
    + 'script the guard cannot read. Change a file with the Edit tool.';
  const o = readOpts('-n -E -r -s -u -z -e= -l= --quiet --silent --regexp-extended --separate --unbuffered '
    + '--null-data --posix --debug --expression= --line-length=', args, 'sed', whole, {
    '-i': 'sed -i edits a file in place. Change a file with the Edit tool.',
    '--in-place': 'sed --in-place edits a file in place. Change a file with the Edit tool.',
    '-f': 'sed -f runs a script from a file the guard does not read. Write the script in the command.',
    '--file': 'sed --file runs a script from a file the guard does not read. Write the script in the command.'
  });
  const scripts = o.values.filter((v) => v.name === '-e' || v.name === '--expression').map((v) => v.value);
  let operands = o.operands;
  if (!scripts.length) {
    if (!operands.length) deny('sed needs a script.', whole);
    scripts.push(operands[0]);
    operands = operands.slice(1);
  }
  if (!scripts.every(sedScriptOk)) deny(why, whole);
  return { operands };
}

// An awk program that runs a command, reads one, writes a file or reads the environment refuses, system, getline, a
// pipe, ENVIRON, an @ directive, and a print or printf with a > in its statement.
function awkForm(args, whole) {
  const o = readOpts('-F= -v= --field-separator= --assign=', args, 'awk', whole, {
    '-f': 'awk -f runs a program from a file the guard does not read. Write the program in the command.',
    '--file': 'awk --file runs a program from a file the guard does not read. Write the program in the command.'
  });
  if (!o.operands.length) deny('awk needs a program.', whole);
  const prog = o.operands[0];
  const bad = /\bsystem\b|\bgetline\b|\||\bENVIRON\b|\bPROCINFO\b|@/.test(prog)
    || prog.split(/[;{}\n]/).some((stmt) => /\bprintf?\b/.test(stmt) && stmt.includes('>'));
  if (bad) {
    deny('An awk program that runs a command, reads the environment or writes a file, system, getline, a pipe, '
      + 'ENVIRON or print >, is refused. Redirect its output into the temp folder instead.', whole);
  }
  return { operands: o.operands.slice(1) };
}

// ---- git

const GIT_DIFF = '-p -u -s -z -R -a -b -w -W -D -U= -G= -S= -O= -M? -C? -B? -l= --patch --no-patch --unified= --raw '
  + '--patch-with-raw --patch-with-stat --stat? --shortstat --numstat --dirstat? --cumulative --dirstat-by-file? '
  + '--summary --name-only --name-status --check --compact-summary --full-index --binary --abbrev? --no-abbrev '
  + '--color? --no-color --color-moved? --no-color-moved --color-moved-ws= --word-diff? --word-diff-regex= '
  + '--color-words? --diff-filter= --find-renames? --find-copies? --find-copies-harder --no-renames --break-rewrites? '
  + '--relative? --no-relative --text --ignore-space-change --ignore-all-space --ignore-blank-lines '
  + '--ignore-space-at-eol --ignore-cr-at-eol --ignore-matching-lines= -I= --function-context --minimal --patience '
  + '--histogram --diff-algorithm= --anchored= --indent-heuristic --no-indent-heuristic --src-prefix= --dst-prefix= '
  + '--no-prefix --default-prefix --line-prefix= --ita-invisible-in-index --ita-visible-in-index --no-ext-diff '
  + '--no-textconv --textconv --pickaxe-all --pickaxe-regex --stat-width= --stat-name-width= --stat-graph-width= '
  + '--stat-count= --inter-hunk-context= --ignore-submodules? --submodule? --output-indicator-new= '
  + '--output-indicator-old= --output-indicator-context= --exit-code --quiet --rename-empty --no-rename-empty '
  + '--skip-to= --rotate-to= --follow';
const GIT_LOG = GIT_DIFF + ' -n= -# -i -E -F -P -g -L= -m -c --cc --dd -t -r -v --oneline --format= --pretty? --date= '
  + '--all --branches? --tags? --remotes? --since= --until= --after= --before= --since-as-filter= --author= '
  + '--committer= --grep= --grep-reflog= --all-match --invert-grep --regexp-ignore-case --extended-regexp '
  + '--fixed-strings --perl-regexp --basic-regexp --merges --no-merges --min-parents= --max-parents= --no-min-parents '
  + '--no-max-parents --first-parent --exclude-first-parent-only --full-history --graph --decorate? --no-decorate '
  + '--decorate-refs= --decorate-refs-exclude= --clear-decorations --abbrev-commit --no-abbrev-commit --reverse '
  + '--max-count= --skip= --left-right --left-only --right-only --cherry-pick --cherry-mark --cherry --boundary '
  + '--ancestry-path? --simplify-by-decoration --simplify-merges --source --topo-order --date-order '
  + '--author-date-order --no-walk? --do-walk --walk-reflogs --relative-date --show-signature --encoding= '
  + '--expand-tabs? --no-expand-tabs --notes? --no-notes --show-notes? --mailmap --no-mailmap --use-mailmap '
  + '--no-use-mailmap --log-size --children --parents --dense --sparse --show-pulls --exclude= --glob= --not '
  + '--remove-empty --diff-merges= --no-diff-merges --combined-all-paths --show-linear-break? --count --objects '
  + '--objects-edge --no-object-names --header --timestamp --oneline --no-commit-id --root --always --stdin '
  + '--reflog --alternate-refs --single-worktree --bisect --in-commit-order --no-patch';
const GIT_SUBS = {
  status: '-s -b -v -z -u? --short --branch --porcelain? --long --verbose --untracked-files? --ignored? --show-stash '
    + '--ahead-behind --no-ahead-behind --renames --no-renames --find-renames? --column? --no-column --null '
    + '--ignore-submodules?',
  diff: GIT_DIFF + ' --cached --staged --merge-base --no-index',
  log: GIT_LOG, show: GIT_LOG, whatchanged: GIT_LOG, 'rev-list': GIT_LOG, shortlog: GIT_LOG + ' -s -e -w? --summary '
    + '--numbered --email --committer --group= --format=',
  'rev-parse': '-q --short? --abbrev-ref? --verify --quiet --git-dir --git-common-dir --absolute-git-dir '
    + '--is-inside-work-tree --is-inside-git-dir --is-bare-repository --is-shallow-repository --show-toplevel '
    + '--show-prefix --show-cdup --show-superproject-working-tree --show-object-format? --symbolic '
    + '--symbolic-full-name --default= --revs-only --no-revs --flags --no-flags --since= --until= --all --branches? '
    + '--tags? --remotes? --path-format= --local-env-vars --resolve-git-dir= --git-path= --sq --not --disambiguate= '
    + '--end-of-options',
  'ls-files': '-c -d -m -o -i -s -u -k -z -t -v -f -x= --cached --deleted --modified --others --ignored --stage '
    + '--unmerged --killed --directory --no-empty-directory --eol --exclude-standard --error-unmatch --full-name '
    + '--recurse-submodules --abbrev? --debug --deduplicate --exclude= --format= --sparse --with-tree=',
  'ls-tree': '-d -r -t -l -z --long --name-only --name-status --object-only --full-name --full-tree --abbrev? --format=',
  grep: '-n -E -F -G -P -i -I -c -l -L -h -H -o -w -v -q -z -p -W -e= -f= -A= -B= -C= -m= -# --line-number --column '
    + '--count --name-only --files-with-matches --files-without-match --no-filename --only-matching --word-regexp '
    + '--invert-match --quiet --null --heading --break --show-function --function-context --after-context= '
    + '--before-context= --context= --max-count= --threads= --and --or --not --all-match --cached --untracked '
    + '--recurse-submodules --text --textconv --no-textconv --ignore-case --basic-regexp --extended-regexp '
    + '--fixed-strings --perl-regexp --full-name --max-depth= --color? --no-color --exclude-standard',
  blame: '-L= -l -t -S= -p -s -e -w -n -f -c -M? -C? --porcelain --line-porcelain --incremental --show-name '
    + '--show-number --show-email --date= --root --first-parent --abbrev? --color-lines --color-by-age --ignore-rev= '
    + '--ignore-revs-file= --progress --no-progress --score-debug',
  describe: '--tags --all --always --long --abbrev? --dirty? --broken? --exact-match --contains --match= --exclude= '
    + '--candidates= --first-parent --debug',
  'cat-file': '-t -s -e -p --batch? --batch-check? --batch-command? --batch-all-objects --textconv --filters --path= '
    + '--follow-symlinks -Z --buffer --unordered --allow-unknown-type',
  'merge-base': '-a --all --is-ancestor --fork-point --octopus --independent',
  'merge-tree': '-z -X= --write-tree --trivial-merge --name-only --messages --no-messages --merge-base= '
    + '--allow-unrelated-histories --stdin --strategy-option=',
  'check-ignore': '-q -v -n -z --quiet --verbose --non-matching --no-index --stdin',
  'check-attr': '-a -z --all --cached --stdin --source=',
  'diff-tree': GIT_DIFF + ' -r -t -m -c -v --root --no-commit-id --stdin --cc --merge-base --always --pretty? '
    + '--format= --encoding=',
  'diff-index': GIT_DIFF + ' -m --cached --merge-base',
  'for-each-ref': '--count= --sort= --format= --color? --shell --perl --python --tcl --points-at= --merged? '
    + '--no-merged? --contains? --no-contains? --ignore-case --omit-empty --exclude= --include-root-refs',
  'show-ref': '-d -s -q --head --branches --tags --heads --dereference --hash? --verify --abbrev? --quiet --exists',
  'name-rev': '--tags --refs= --exclude= --all --annotate-stdin --name-only --no-undefined --always',
  'count-objects': '-v -H --verbose --human-readable',
  'range-diff': GIT_DIFF + ' --creation-factor= --no-dual-color --left-only --right-only',
  'verify-commit': '-v --raw', 'verify-tag': '-v --raw --format=',
  version: '--build-options', var: '-l', help: '-a -g --all --guides --config',
  'ls-remote': '-h -t -q --heads --tags --refs --branches --quiet --exit-code --get-url --sort= --symref -o= '
    + '--server-option=',
  fetch: '-q -v -p -P -t -n -4 -6 --quiet --verbose --prune --prune-tags --tags --no-tags --all --depth= --deepen= '
    + '--shallow-since= --shallow-exclude= --unshallow --update-shallow --dry-run --progress --no-progress --multiple '
    + '--no-write-fetch-head --write-fetch-head --set-upstream --filter= --refetch --jobs= --negotiate-only '
    + '--negotiation-tip= --porcelain --no-show-forced-updates --show-forced-updates',
  pull: '-q -v --quiet --verbose --ff --no-ff --ff-only --rebase? --no-rebase --autostash --no-autostash --stat '
    + '--no-stat --tags --no-tags --prune --depth= --unshallow --no-edit --commit --no-commit --progress --no-progress',
  push: '-u -q -v -n --set-upstream --quiet --verbose --dry-run --porcelain --progress --no-progress --atomic',
  add: '-A -u -N -n -v --all --update --intent-to-add --dry-run --verbose --renormalize --chmod= --ignore-errors '
    + '--sparse --pathspec-from-file= --pathspec-file-nul --no-all --ignore-removal --refresh --ignore-missing',
  commit: '-q -m= -F= -a -s -C= -c= -o -i --amend --no-edit --quiet --all --allow-empty --allow-empty-message '
    + '--signoff --no-signoff --author= --date= --file= --message= --fixup= --squash= --reuse-message= --cleanup= '
    + '--trailer= --only --include --dry-run --short --porcelain --long --branch --status --no-status '
    + '--untracked-files? --reset-author --no-post-rewrite --pathspec-from-file= --pathspec-file-nul',
  switch: '-q -c= -C= -d -t -f --quiet --create= --force-create= --detach --track? --no-track --guess --no-guess '
    + '--progress --no-progress --orphan= --ignore-other-worktrees --force --discard-changes',
  checkout: '-q -b= -B= -t -f --quiet --track? --no-track --detach --force --ours --theirs --progress --no-progress '
    + '--orphan= --ignore-other-worktrees --guess --no-guess',
  restore: '-s= -S -W -q --source= --staged --worktree --quiet --ours --theirs --progress --no-progress '
    + '--ignore-unmerged --overlay --no-overlay',
  reset: '-q -N --quiet --soft --mixed --hard --merge --keep --no-refresh --refresh --intent-to-add '
    + '--pathspec-from-file= --pathspec-file-nul',
  rm: '-q -r -f -n --quiet --cached --dry-run --ignore-unmatch --sparse --force --pathspec-from-file=',
  clean: '-d -f -n -q -x -X -e= --dry-run --quiet --force --exclude=',
  branch: '-a -r -l -v -q -d -D -m -M -c -C -f -u= -t --all --remotes --list --verbose --quiet --delete --move --copy '
    + '--force --show-current --contains? --no-contains? --merged? --no-merged? --points-at= --sort= --format= '
    + '--column? --no-column --color? --no-color --abbrev? --no-abbrev --set-upstream-to= --unset-upstream --track? '
    + '--no-track --create-reflog --ignore-case --omit-empty',
  tag: '-l -n? --list --sort= --contains? --no-contains? --merged? --no-merged? --points-at= --format= --column? '
    + '--no-column --ignore-case --color? --omit-empty',
  config: '-l -z -f= --get --get-all --get-regexp --get-urlmatch --list --show-origin --show-scope --name-only --null '
    + '--local --global --system --worktree --file= --blob= --type= --bool --int --bool-or-int --path --expiry-date '
    + '--default= --includes --no-includes --get-color --get-colorbool',
  archive: '-o= -l -v -# --output= --format= --prefix= --list --verbose --worktree-attributes --add-file=',
  'format-patch': GIT_LOG + ' -o= -N -k -v= --output-directory= --stdout --numbered --no-numbered --start-number= '
    + '--cover-letter --no-cover-letter --subject-prefix= --suffix= --reroll-count= --base= --signoff --no-signature '
    + '--zero-commit --thread? --no-thread',
  'hash-object': '-t= -w --stdin --stdin-paths --path= --no-filters --literally',
  'write-tree': '--missing-ok --prefix=',
  apply: '-p= -C= -R -3 -v -q --check --stat --numstat --summary --index --cached --3way --reverse --whitespace= '
    + '--ignore-whitespace --ignore-space-change --verbose --quiet --recount --unidiff-zero --allow-empty --exclude= '
    + '--include= --directory=',
  reflog: GIT_LOG,
  init: '-q -b= --quiet --bare --initial-branch= --object-format=',
  mv: '-k -n -v --dry-run --verbose',
  merge: '-q -v -m= -F= -s= -X= --quiet --verbose --ff --no-ff --ff-only --no-edit --commit --no-commit --squash '
    + '--no-squash --abort --continue --quit --stat --no-stat --log? --no-log --signoff --allow-unrelated-histories '
    + '--autostash --no-autostash --strategy= --strategy-option= --message= --file= --progress --no-progress',
  rebase: '-q -v -m -f -n -X= -s= --quiet --verbose --onto= --keep-base --continue --abort --skip --quit --autosquash '
    + '--no-autosquash --autostash --no-autostash --update-refs --no-update-refs --committer-date-is-author-date '
    + '--reset-author-date --ignore-date --signoff --root --fork-point --no-fork-point --merge --strategy= '
    + '--strategy-option= --no-rebase-merges --empty= --keep-empty --no-keep-empty --reapply-cherry-picks '
    + '--no-reapply-cherry-picks --allow-empty-message --stat --no-stat --force-rebase --no-ff --whitespace=',
  'cherry-pick': '-x -n -s -m= -X= --no-commit --signoff --mainline= --continue --abort --skip --quit --ff '
    + '--allow-empty --allow-empty-message --keep-redundant-commits --empty= --strategy= --strategy-option=',
  revert: '-n -s -m= -X= --no-edit --no-commit --signoff --mainline= --continue --abort --skip --quit --strategy= '
    + '--strategy-option=',
  'update-index': '-q --chmod= --refresh --really-refresh --add --ignore-missing',
  'symbolic-ref': '-q --short --quiet --no-recurse',
  stash: '', remote: '', worktree: ''
};
const GIT_WHY = {
  '-c': 'git -c sets a setting for one command, and git\'s settings are the owner\'s.',
  '--config-env': 'git --config-env sets a setting for one command, and git\'s settings are the owner\'s.',
  '--git-dir': 'git --git-dir points git at another repo. Use git -C <folder>.',
  '--work-tree': 'git --work-tree points git at another folder. Use git -C <folder>.',
  '--no-verify': 'Skipping git\'s hooks skips the owner\'s secret scan. Drop --no-verify.',
  '-n': 'git commit -n skips git\'s hooks, the owner\'s secret scan among them.',
  '--output': 'git --output writes a file. Redirect into the temp folder instead.',
  '--ext-diff': 'git --ext-diff runs an outside program. Drop the flag.',
  '--upload-pack': 'git --upload-pack runs a command. Drop the flag.',
  '--no-exclude-standard': 'git grep --no-exclude-standard reads ignored files, every secret file among them.',
  '-O': 'git grep -O runs a program on the files. Drop the flag.',
  '--open-files-in-pager': 'git grep --open-files-in-pager runs a program on the files. Drop the flag.',
  '-i': 'An interactive git command waits for an editor. Use its plain form.',
  '--interactive': 'An interactive git command waits for an editor. Use its plain form.',
  '-x': 'git rebase -x runs a command at each step. Run the command yourself.',
  '--exec': 'git rebase --exec runs a command at each step. Run the command yourself.',
  '-f': 'git add -f adds an ignored file, which can put a secret in a commit.',
  '--force': 'This --force can lose work or add an ignored file. Ask the owner.',
  '-e': 'git -e opens an editor, which waits. Pass the text with -m or -F.',
  '--edit': 'git --edit opens an editor, which waits. Pass the text with -m or -F.',
  '-p': 'git -p is interactive and waits. Use its plain form.',
  '--patch': 'git --patch is interactive and waits. Use its plain form.'
};

function gitForm(args, whole) {
  let k = 0;
  for (; k < args.length && args[k].startsWith('-'); k++) {
    const a = args[k];
    if (a === '-C') {
      k++;
      continue;
    }
    if (a === '--no-pager' || a === '-P' || a === '--literal-pathspecs' || a === '--no-optional-locks'
      || a === '--version') continue;
    const name = a.split('=')[0];
    deny(GIT_WHY[name] || ('git ' + name + ' is not on the owner\'s list. Use git -C <folder>.'), whole);
  }
  const sub = (args[k] || '').toLowerCase();
  const rest = args.slice(k + 1);
  if (!sub) {
    if (args.includes('--version')) return { sub: '', operands: [] };
    deny('git needs a subcommand.', whole);
  }
  if (!Object.prototype.hasOwnProperty.call(GIT_SUBS, sub)) {
    deny('git ' + sub + ' is not on the owner\'s list of approved commands. Ask the owner, who runs it or adds it.',
      whole);
  }
  const why = {};
  for (const [opt, text] of Object.entries(GIT_WHY)) why[opt] = text;
  if (sub !== 'commit') delete why['-n'];
  if (sub === 'add') why['-f'] = GIT_WHY['-f'];
  if (sub === 'stash') return stashForm(rest, whole);
  if (sub === 'remote') return remoteForm(rest, whole);
  if (sub === 'worktree') return worktreeForm(rest, whole);
  if (sub === 'symbolic-ref') {
    const o = readOpts(GIT_SUBS[sub], rest, 'git symbolic-ref', whole, why);
    if (o.operands.length > 1) deny('Setting a symbolic ref moves a branch. Ask the owner.', whole);
    return { sub, ...o };
  }
  if (sub === 'config') {
    // git's newer spelling names the reading verb first, git config get and git config list
    const verb = rest[0] === 'get' || rest[0] === 'list' ? rest[0] : '';
    const words = verb ? rest.slice(1) : rest;
    if (!verb && !words.some((a) => /^(--get|--get-all|--get-regexp|--get-urlmatch|--list|-l|--get-color|--get-colorbool)$/.test(a))) {
      deny('git config only reads, git config get, list, --get, --list and their kin. git\'s settings are the owner\'s.',
        whole);
    }
    const o = readOpts(GIT_SUBS.config + ' --all --regexp --value= --fixed-value --url=', words, 'git config', whole, why);
    return { sub, ...o };
  }
  const o = readOpts(GIT_SUBS[sub], rest, 'git ' + sub, whole, why);
  return { sub, ...o };
}

function stashForm(rest, whole) {
  const subs = {
    push: '-m= -q -u -k -a -S --message= --quiet --include-untracked --keep-index --no-keep-index --all --staged '
      + '--pathspec-from-file= --pathspec-file-nul',
    list: GIT_LOG, show: GIT_DIFF + ' -u --include-untracked --only-untracked', apply: '-q --index --quiet',
    pop: '-q --index --quiet', drop: '-q --quiet', clear: '', branch: '', create: '-m=', store: '-m= -q'
  };
  const first = rest[0] || '';
  const sub = Object.prototype.hasOwnProperty.call(subs, first) ? first : 'push';
  const words = sub === first ? rest.slice(1) : rest;
  const o = readOpts(subs[sub], words, 'git stash ' + sub, whole, GIT_WHY);
  return { sub: 'stash', stash: sub, ...o };
}

function remoteForm(rest, whole) {
  // git reads -v before a verb as well as alone, git remote -v set-url among them, so it is passed over first
  let k = 0;
  while (rest[k] === '-v' || rest[k] === '--verbose') k++;
  rest = rest.slice(k);
  const first = rest[0] || '';
  if (first === '') return { sub: 'remote', operands: [] };
  if (first === 'show' || first === 'get-url') {
    const o = readOpts('-n --push --all', rest.slice(1), 'git remote ' + first, whole);
    return { sub: 'remote', ...o };
  }
  deny('git remote ' + first + ' changes where code goes. The owner does that.', whole);
}

function worktreeForm(rest, whole) {
  const subs = {
    list: '-v -z --porcelain --verbose --expire=',
    add: '-b= -B= -f -q --detach --no-checkout --checkout --lock --reason= --track --no-track --guess-remote '
      + '--no-guess-remote --orphan --force --quiet --relative-paths --no-relative-paths',
    remove: '-f --force', prune: '-n -v --dry-run --verbose --expire=', lock: '--reason=', unlock: '',
    move: '', repair: ''
  };
  const first = rest[0] || '';
  if (!Object.prototype.hasOwnProperty.call(subs, first)) {
    deny('git worktree ' + first + ' is not on the owner\'s list.', whole);
  }
  const o = readOpts(subs[first], rest.slice(1), 'git worktree ' + first, whole);
  return { sub: 'worktree', worktree: first, ...o };
}

// ---- gh, npm, npx, docker

// gh's groups and verbs a session uses. Their options pass as they are, since none runs a command, and checkGh holds
// the ones that merge, approve, release or change settings.
const GH_VERBS = {
  pr: ['view', 'list', 'create', 'comment', 'checks', 'diff', 'status', 'edit'],
  run: ['list', 'view', 'watch'],
  issue: ['view', 'list', 'create', 'comment', 'status'],
  repo: ['view'], search: ['code', 'prs', 'issues', 'repos', 'commits'], auth: ['status'],
  workflow: ['list', 'view'], api: null, label: ['list'], release: ['list', 'view']
};
function ghForm(args, whole) {
  if (args.length === 1 && args[0] === '--version') return { operands: [] };
  const words = args.filter((a) => !a.startsWith('-'));
  const group = (words[0] || '').toLowerCase();
  const verb = (words[1] || '').toLowerCase();
  if (!Object.prototype.hasOwnProperty.call(GH_VERBS, group)) {
    deny('gh ' + group + ' is not on the owner\'s list of approved commands. Ask the owner.', whole);
  }
  if (GH_VERBS[group] && !GH_VERBS[group].includes(verb)) {
    deny('gh ' + group + ' ' + verb + ' is not on the owner\'s list of approved commands. Ask the owner.', whole);
  }
  return { group, verb, operands: [] };
}

const NPX_TOOLS = new Set(['jest', 'tsc', 'eslint', 'next', 'playwright', 'prettier', 'vitest', 'tsx']);
function npmForm(args, whole) {
  // every spelling of a global or elsewhere install, --global=true and --location global among them (D-068)
  if (args.some((a) => /^-[A-Za-z]*g/.test(a) && !a.startsWith('--') || /^--(global|location|prefix)(=|$)/.test(a))) {
    deny('A global npm install changes the tools of every session. The owner does that.', whole);
  }
  const subs = ['install', 'i', 'ci', 'run', 'run-script', 'test', 't', 'audit', 'ls', 'list', 'view', 'outdated',
    'uninstall', 'un', 'remove', 'rm', '--version', '-v'];
  const sub = (args.find((a) => !a.startsWith('-') || a === '--version' || a === '-v') || '').toLowerCase();
  if (!subs.includes(sub)) deny('npm ' + sub + ' is not on the owner\'s list of approved commands. Ask the owner.', whole);
  return { sub, operands: [] };
}
function npxForm(args, whole) {
  let k = 0;
  for (; k < args.length && args[k].startsWith('-'); k++) {
    if (args[k] !== '--no' && args[k] !== '--no-install') {
      deny('npx ' + args[k] + ' is refused. npx runs only the repo\'s own tools, ' + [...NPX_TOOLS].join(', ') + '.',
        whole);
    }
  }
  const tool = (args[k] || '').toLowerCase();
  if (!NPX_TOOLS.has(tool)) {
    deny('npx ' + tool + ' is not on the owner\'s list. npx runs only the repo\'s own tools, '
      + [...NPX_TOOLS].join(', ') + '.', whole);
  }
  return { tool, operands: [] };
}

// docker reaches this machine's own engine alone. Its environment and its current context are checked as well as its
// words, since either can point it at another machine.
function dockerLocal(whole) {
  for (const v of ['DOCKER_HOST', 'DOCKER_CONTEXT', 'DOCKER_CONFIG']) {
    if (process.env[v]) deny(v + ' is set, which can point docker at another machine. The owner unsets it.', whole);
  }
  let config;
  try {
    config = JSON.parse(fs.readFileSync(path.join(os.homedir(), '.docker', 'config.json'), 'utf8'));
  } catch (err) {
    if (missingPath(err)) return;
    throw err;
  }
  const ctx = config && config.currentContext;
  if (ctx && !['default', 'desktop-linux'].includes(ctx)) {
    deny('docker\'s current context is ' + ctx + ', which can be another machine. The owner switches it back.', whole);
  }
}
const DOCKER_SUBS = {
  ps: '-a -q -s -n= -l --all --quiet --size --format= --filter= -f= --no-trunc --last= --latest',
  logs: '-f -t -n= --follow --timestamps --tail= --since= --until= --details',
  inspect: '-f= -s --format= --size --type=',
  images: '-a -q --all --quiet --format= --filter= -f= --digests --no-trunc',
  build: '-t= -f= -q --tag= --file= --build-arg= --target= --no-cache --pull --progress= --quiet --platform= --label= '
    + '--load --cache-from=',
  cp: '-a -L -q --archive --follow-link --quiet',
  start: '-a --attach', stop: '-t= --time= -s= --signal=', rm: '-f -v --force --volumes',
  rmi: '-f --force --no-prune', version: '-f= --format=', info: '-f= --format=', port: '',
  pull: '-q -a --quiet --all-tags --platform=', tag: '', network: '', volume: '', image: '', compose: ''
};
function dockerForm(args, whole) {
  dockerLocal(whole);
  if (args.length === 1 && /^(--version|-v)$/.test(args[0])) return { operands: [] };
  if (args[0] && args[0].startsWith('-')) {
    deny('docker ' + args[0] + ' is refused before the subcommand. docker reaches this machine\'s own engine alone.',
      whole);
  }
  const sub = (args[0] || '').toLowerCase();
  if (!Object.prototype.hasOwnProperty.call(DOCKER_SUBS, sub)) {
    const why = sub === 'exec' || sub === 'run'
      ? ' docker exec and run wait for a check of the command they run, a later item of the owner\'s plan.' : '';
    deny('docker ' + sub + ' is not on the owner\'s list of approved commands.' + why, whole);
  }
  if (sub === 'compose') return composeForm(args.slice(1), whole);
  if (sub === 'network' || sub === 'volume' || sub === 'image') {
    const verb = args[1] || '';
    if (!['ls', 'inspect', 'rm'].includes(verb) || (sub !== 'volume' && verb === 'rm')) {
      deny('docker ' + sub + ' ' + verb + ' is not on the owner\'s list.', whole);
    }
    const o = readOpts('-q -f= --format= --quiet --filter=', args.slice(2), 'docker ' + sub, whole);
    return { sub, verb, ...o };
  }
  const o = readOpts(DOCKER_SUBS[sub], args.slice(1), 'docker ' + sub, whole);
  return { sub, ...o };
}
const COMPOSE_SUBS = {
  up: '-d -t= -V --detach --build --no-build --wait --wait-timeout= --force-recreate --no-recreate --remove-orphans '
    + '--no-deps --quiet-pull --pull= --timeout= --abort-on-container-exit --exit-code-from= --scale= --no-start '
    + '--renew-anon-volumes --no-color --no-log-prefix --attach= --no-attach= --menu?',
  down: '-v -t= --remove-orphans --volumes --rmi= --timeout=',
  ps: '-a -q --all --quiet --services --format= --filter= --status=',
  logs: '-f -t -n= --follow --timestamps --tail= --since= --until= --no-color --no-log-prefix',
  build: '-q --no-cache --pull --progress= --quiet --build-arg=',
  config: '-q --services --volumes --format= --quiet --images --profiles --hash= --no-interpolate',
  version: '--short --format='
};
function composeForm(args, whole) {
  let k = 0;
  for (; k < args.length && args[k].startsWith('-'); k++) {
    if (/^(-f|--file|-p|--project-name|--profile|--env-file|--project-directory|--ansi|--progress)$/.test(args[k])) k++;
    else if (!/^(--file|--project-name|--profile|--env-file|--project-directory|--ansi|--progress)=/.test(args[k])) {
      deny('docker compose ' + args[k] + ' is not on the owner\'s list.', whole);
    }
  }
  const sub = (args[k] || '').toLowerCase();
  if (!Object.prototype.hasOwnProperty.call(COMPOSE_SUBS, sub)) {
    const why = sub === 'exec' || sub === 'run'
      ? ' compose exec and run wait for a check of the command they run, a later item of the owner\'s plan.' : '';
    deny('docker compose ' + sub + ' is not on the owner\'s list of approved commands.' + why, whole);
  }
  const o = readOpts(COMPOSE_SUBS[sub], args.slice(k + 1), 'docker compose ' + sub, whole);
  return { sub: 'compose', compose: sub, ...o };
}

// ---- removals

// What a command removes or writes over, for the owner's prompt, or null. A removal whose every path is a temporary
// file runs without asking.
function removalOf(prog, form, args, argToks, whole) {
  const named = (words) => argToks.filter((t) => words.includes(t.t));
  const all = (toks) => toks.length > 0 && toks.every(freeToRemove);
  if (prog === 'rmdir' && args.some((a) => a === '-p' || a === '--parents' || /^-[a-z]*p/.test(a))) {
    return 'rmdir -p removes each empty folder above ' + form.operands.join(', ') + ' too.';
  }
  if (prog === 'rm' || prog === 'rmdir' || prog === 'unlink') {
    const targets = named(form.operands);
    return all(targets) ? null : prog + ' removes ' + form.operands.join(', ') + '.';
  }
  if (prog === 'cp' || prog === 'mv') {
    if (form.operands.length < 2) return null;
    const dest = form.operands[form.operands.length - 1];
    const destTok = named([dest]).pop();
    const over = isDir(dest)
      ? form.operands.slice(0, -1).map((src) => dest.replace(/\/+$/, '') + '/' + path.basename(src)).filter(exists)
      : exists(dest) ? [dest] : [];
    if (destTok && destTok.g) return prog + ' writes to a pattern, ' + dest + '.';
    const kept = over.filter((p) => !(inTemp(p) && !holdsWorkTree(p)));
    return kept.length ? prog + ' writes over ' + kept.join(', ') + '.' : null;
  }
  if (prog === 'git') return gitRemoval(form, argToks);
  if (prog === 'npm' && ['ci', 'uninstall', 'un', 'remove', 'rm'].includes(form.sub)) {
    return 'npm ' + form.sub + ' removes ' + (form.sub === 'ci' ? 'node_modules before it installs.' : 'a package.');
  }
  if (prog === 'python' && form.module === 'pip' && /^(uninstall)$/.test(form.moduleArgs[0] || '')) {
    return 'pip uninstall removes a package.';
  }
  if (prog === 'make') {
    const t = form.targets.find((x) => /(^|[-_.:])(clean|reset|reseed|prune|down|purge|wipe|nuke)([-_.:]|$)/i.test(x));
    return t ? 'make ' + t + ' is named for removing.' : null;
  }
  if (prog === 'docker' || prog === 'docker-compose') {
    if (form.verb === 'rm' && form.sub === 'volume') return 'docker volume rm removes a volume and its data.';
    if (form.sub === 'rm' && (form.has('-v') || form.has('--volumes'))) return 'docker rm -v removes the container\'s volumes.';
    if (form.compose === 'down' && (form.has('-v') || form.has('--volumes'))) return 'compose down -v removes volumes.';
    if (form.compose === 'up' && (form.has('-V') || form.has('--renew-anon-volumes'))) {
      return 'compose up -V removes the anonymous volumes.';
    }
  }
  return null;
}

function gitRemoval(form, argToks) {
  const has = (...o) => o.some((x) => form.seen && form.seen.includes(x));
  switch (form.sub) {
    case 'rm':
      return has('--cached', '-n', '--dry-run') ? null : 'git rm removes ' + form.operands.join(', ') + '.';
    case 'clean':
      return has('-n', '--dry-run') ? null : 'git clean removes untracked files.';
    case 'reset':
      return has('--hard', '--merge', '--keep') ? 'git reset --hard discards uncommitted work.' : null;
    case 'restore':
      return has('--staged', '-S') && !has('--worktree', '-W') ? null
        : 'git restore discards uncommitted changes to ' + form.operands.join(', ') + '.';
    case 'checkout': {
      if (has('-f', '--force', '-B', '--ours', '--theirs')) return 'git checkout with that option discards work.';
      if (argToks.some((t) => t.t === '--')) return 'git checkout -- discards uncommitted changes.';
      if (!has('-b', '--orphan') && form.operands.some((p) => p === '.' || exists(p))) {
        return 'git checkout of a path discards its uncommitted changes.';
      }
      return null;
    }
    case 'switch':
      return has('-f', '--force', '--discard-changes', '-C', '--force-create')
        ? 'git switch with that option discards work or resets a branch.' : null;
    case 'branch':
      return has('-d', '-D', '--delete', '-M', '-C', '-f', '--force') ? 'git branch with that option deletes or '
        + 'overwrites a branch.' : null;
    case 'stash':
      return ['drop', 'clear', 'pop'].includes(form.stash) ? 'git stash ' + form.stash + ' removes a stash.' : null;
    case 'worktree':
      if (form.worktree === 'add' && has('-B')) return 'git worktree add -B resets a branch.';
      if (form.worktree === 'prune' && !has('-n', '--dry-run')) return 'git worktree prune removes registrations.';
      if (form.worktree === 'remove') {
        const targets = argToks.filter((t) => form.operands.includes(t.t));
        if (has('-f', '--force')) return 'git worktree remove --force can remove work never committed.';
        return targets.length && targets.every((t) => !t.g && inTemp(t.t)) ? null
          : 'git worktree remove removes a worktree outside the temp folder.';
      }
      return null;
    default:
      return null;
  }
}

// ---- judging a call

// The program a command names. A path names a program only when it is a repo's venv interpreter or a script, which
// runs as bash would run it. Any other program is a bare name from the list.
function programName(word, whole) {
  const w = word.replace(/\\/g, '/');
  if (w.includes('/')) {
    if (/(^|\/)\.venv\/(scripts\/python(\.exe)?|bin\/python3?)$/i.test(w)) return 'python';
    if (/\.sh$/i.test(w)) return 'script';
    deny(NOT_PLAIN + 'A program is a bare name from the owner\'s list. A script runs as bash <file>, and Python as the '
      + 'repo\'s venv interpreter, <repo>/.venv/Scripts/python.exe.', whole);
  }
  const name = w.toLowerCase().replace(/\.exe$/, '');
  if (/^(python[0-9.]*|py|pip[0-9.]*)$/.test(name)) {
    deny('A bare ' + name + ' is refused. Use the repo\'s own venv interpreter, <repo>/.venv/Scripts/python.exe.', whole);
  }
  return name;
}

function entryOf(prog) {
  const e = LIST[prog];
  return typeof e === 'string' ? { opts: e } : e;
}

// A whole call, each of its commands judged from every folder a cd earlier in the call could have left the shell in.
// The folders are followed down both of each command's outcomes, since && runs the next command only after a success
// and || only after a failure, a cd that fails leaves the shell where it was, and a cd in a pipe moves nothing after
// it. Every refusal ends the call at once, and every removal that asks is gathered into one prompt for the owner.
function checkCall(cmd) {
  if (cmd.length > MAX_COMMAND) {
    deny('The command is longer than the guard reads, ' + MAX_COMMAND + ' characters. Split it, or put long text in '
      + 'a file.', cmd.slice(0, 120));
  }
  const cmds = readPlain(cmd);
  const asks = [];
  const start = CWD;
  const union = (a, b) => [...new Set([...a, ...b])];
  let ok = [CWD];
  let fail = [];
  cmds.forEach((c, i) => {
    const before = i === 0 ? '' : cmds[i - 1].op;
    const input = before === '&&' ? ok : before === '||' ? fail : union(ok, fail);
    let moved = input;
    for (const dir of input) {
      CWD = dir;
      timeLeft();
      const to = judgeCommand(c.toks, cmd, asks, cmds.length === 1, false);
      if (to && before !== '|' && c.op !== '|') moved = union(moved === input ? [] : moved, to);
    }
    ok = before === '||' ? union(moved, ok) : moved;
    fail = before === '&&' ? union(input, fail) : input;
  });
  CWD = start;
  if (asks.length) ask([...new Set(asks)], cmd);
}

// One command, judged in order. The checks every command meets, its redirects, the guardrail files and the secret
// files, then the program's own rules kept from before the list, then the list, then whether it removes anything.
// A cd answers the folders it could move to.
function judgeCommand(toks, whole, asks, single, variant) {
  const words = toks.filter((t) => !t.redir && !t.target);
  let p = 0;
  const assigns = [];
  while (p < words.length && !words[p].lq && ASSIGNMENT.test(words[p].t)) assigns.push(words[p++].t);
  for (const a of assigns) {
    if (!ALLOWED_ASSIGNS.has(a)) {
      deny(NOT_PLAIN + 'A variable is set only as one of the owner\'s fixed pairs, ' + [...ALLOWED_ASSIGNS].join(', ')
        + '. Write the value out instead.', whole);
    }
  }
  if (p >= words.length) deny(NOT_PLAIN + 'A variable set on its own is refused, nothing in a plain command reads it.',
    whole);
  const progTok = words[p];
  if (progTok.q || progTok.g) deny(NOT_PLAIN + 'The program is written out, never quoted or a pattern.', whole);
  let prog = programName(progTok.t, whole);
  let argToks = words.slice(p + 1);
  if (prog === 'script') {
    prog = 'bash';
    argToks = [progTok, ...argToks];
  }
  const args = argToks.map((t) => t.t);
  if (!Object.prototype.hasOwnProperty.call(LIST, prog)) deny(notListed(prog), whole);

  for (let k = 0; k < toks.length; k++) {
    const t = toks[k];
    if (!t.redir || t.dup || t.t.includes('<')) continue;
    const target = toks[k + 1];
    if (/^\/dev\/null$/i.test(target.t)) continue;
    if (target.g || !tempFile(target.t)) {
      deny('A redirect writes only into a temp folder, ' + TEMP_ROOTS.join(' or ') + ', outside any worktree, or '
        + '/dev/null. Change a repo file with the Edit tool.', whole);
    }
  }
  checkProtectedInShell(toks, prog, args, whole);
  checkSecretWords(toks, prog, args, whole);
  if (MODE === 'reviewer') checkRedirects(toks, whole);
  if (prog === 'git') checkGit(args, whole, single && !assigns.length && !variant);
  else if (prog === 'gh') checkGh(args, whole);
  else checkOther(prog, args, assigns, whole);
  if (MODE === 'reviewer') checkReviewerProgram(prog, args, assigns, whole);

  const e = entryOf(prog);
  let form;
  if (e === ANY) form = readOpts(ANY, args, prog, whole);
  else if (e.text) form = { operands: args };
  else if (e.form) form = e.form(args, whole);
  else form = readOpts(e.opts, args, prog, whole, e.why || {});
  if (e.maxOperands !== undefined && form.operands.length > e.maxOperands) {
    deny(prog + ' with ' + form.operands.length + ' paths writes the last one. Redirect into the temp folder instead.',
      whole);
  }
  if (e.operands && !form.operands.every((x) => e.operands.test(x))) {
    deny(prog + ' ' + form.operands.join(' ') + ' is not on the owner\'s list for ' + prog + '.', whole);
  }
  checkWrites(prog, form, args, argToks, whole);
  if (!variant) {
    const removal = removalOf(prog, form, args, argToks, whole);
    if (removal) {
      if (MODE === 'reviewer') deny('Reviewers remove nothing. ' + removal, whole);
      asks.push(removal);
    }
    // each path a glob matches, judged too, each judgment able only to refuse (D-060)
    for (const v of globVariants(toks)) judgeCommand(v, whole, asks, single, true);
  }
  if (prog === 'cd') {
    const to = form.operands[0];
    if (to === '-') deny('cd - is refused. Write the folder out.', whole);
    return [toAbs(to === undefined ? '~' : to)];
  }
  return null;
}

// The files a listed program writes by a path it is given, each held to a temp folder.
function checkWrites(prog, form, args, argToks, whole) {
  const temp = (p, what) => {
    if (!/^\/dev\/null$/i.test(p) && !tempFile(p)) {
      deny(what + ' writes only into a temp folder, ' + TEMP_ROOTS.join(' or ') + ', outside any worktree.', whole);
    }
  };
  if ((prog === 'cp' || prog === 'mv') && form.operands.length >= 2) checkCopyTree(prog, form.operands, whole);
  if (prog === 'tee') {
    for (const t of argToks.filter((x) => form.operands.includes(x.t))) {
      if (t.g) deny('tee writes to a pattern. Write the path out.', whole);
      temp(t.t, 'tee');
    }
  }
  if (prog === 'git' && (form.sub === 'archive' || form.sub === 'format-patch')) {
    for (let k = 0; k < args.length; k++) {
      const m = /^(--output=|--output-directory=)(.+)$/.exec(args[k]);
      if (m) temp(m[2], 'git ' + form.sub);
      else if (args[k] === '-o' || args[k] === '--output' || args[k] === '--output-directory') temp(args[k + 1] || '',
        'git ' + form.sub);
      else if (/^-o./.test(args[k])) temp(args[k].slice(2), 'git ' + form.sub);
    }
  }
  if (prog === 'docker' && form.sub === 'cp' && form.operands.length === 2) {
    const dest = form.operands[1];
    if (!/^[^/\\:]{2,}:/.test(dest) && exists(dest) && !tempFile(dest)) {
      deny('docker cp writes over ' + dest + '. Copy into the temp folder.', whole);
    }
  }
}

// A copy or a move checked file by file, so a folder copied out carries no secret file, and nothing copied or moved in
// lands on a guardrail file, a folder named .claude among them. A move takes its source's guardrail files with it.
// A folder too large to look through is refused, since what it holds cannot be known.
function checkCopyTree(prog, operands, whole) {
  const dest = operands[operands.length - 1];
  const intoDir = isDir(dest);
  let seen = 0;
  const each = (src, rel) => {
    const from = rel ? path.join(toAbs(src), rel) : toAbs(src);
    const base = intoDir ? path.join(toAbs(dest), path.basename(toAbs(src))) : toAbs(dest);
    const to = rel ? path.join(base, rel) : base;
    if (isClosed(from)) deny(SECRET_WHY, whole);
    if (isProtected(to) || (prog === 'mv' && isProtected(from))) deny(GUARDRAIL_WHY, whole);
  };
  for (const src of operands.slice(0, -1)) {
    each(src, '');
    if (!isDir(src)) continue;
    const walk = (rel) => {
      for (const e of fs.readdirSync(path.join(toAbs(src), rel), { withFileTypes: true })) {
        if (++seen > 2000) {
          deny(prog + ' of a folder this large cannot be checked file by file. Copy what you need by name.', whole);
        }
        const next = path.join(rel, e.name);
        each(src, next);
        if (e.isDirectory()) walk(next);
      }
    };
    walk('');
  }
}

// The owner's prompt for the removals a call makes, the command shown with what each one removes. A reviewer, and a
// run with no one to answer, never sees it, the reviewer's removal refused above and Claude Code denying the other.
function ask(reasons, whole) {
  const why = 'kdf-guard asks the owner, since this removes or writes over something. ' + reasons.join(' ');
  if (LOG_ONLY) trial('ask', whole, why);
  process.stdout.write(JSON.stringify({
    hookSpecificOutput: { hookEventName: 'PreToolUse', permissionDecision: 'ask', permissionDecisionReason: why }
  }) + '\n');
  process.exit(0);
}

// The trial, the week the new guard runs beside the old one. It logs what it would refuse, ask or allow, and lets
// every call through, the old guard still refusing.
function trial(decision, detail, why) {
  try {
    fs.appendFileSync(TRIAL_LOG, JSON.stringify({ at: new Date().toISOString(), mode: MODE, decision,
      command: String(detail || '').slice(0, 400), why: String(why || '').slice(0, 400) }) + '\n');
  } catch (err) {
    // a log that cannot be written must not change the answer
  }
  process.exit(0);
}

// ------------------------------------------------------------ guardrail files

// A program's bare name, its folder and a Windows ending dropped.
function base(t) {
  return path
    .basename(String(t).replace(/\\/g, '/'))
    .toLowerCase()
    .replace(/\.(exe|cmd|bat|ps1|com)$/, '');
}

function checkProtectedRedirects(toks, whole) {
  for (let i = 0; i < toks.length; i++) {
    if (toks[i].q) continue;
    const m = /^(\d*)(>>?|&>>?)(.*)$/.exec(toks[i].t);
    if (!m) continue;
    const target = m[3] || (toks[i + 1] ? toks[i + 1].t : '');
    if (isProtected(target)) deny(GUARDRAIL_WHY, whole);
  }
}

function checkProtectedInShell(toks, prog, args, whole) {
  checkProtectedRedirects(toks, whole);
  let readOnly = READ_ONLY_PROGRAMS.has(prog);
  if (prog === 'git') {
    const { sub, rest } = gitSplit(args);
    readOnly = GIT_READ.has(sub) || (sub === 'config' && configReads(rest));
  }
  if (!readOnly && args.some((a) => isProtected(a))) deny(GUARDRAIL_WHY, whole);
}

// ------------------------------------------------------------ git

function gitSplit(args) {
  const withValue = new Set(['-c', '--git-dir', '--work-tree', '--namespace', '--super-prefix', '--config-env']);
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === '-C' || withValue.has(a)) {
      i++;
      continue;
    }
    if (a.startsWith('-')) continue;
    return { sub: a.toLowerCase(), rest: args.slice(i + 1) };
  }
  return { sub: '', rest: [] };
}

// The options a push may carry, none of which takes a value (D-062).
const PUSH_OPTIONS = new Set([
  '-u', '--set-upstream', '-q', '--quiet', '-v', '--verbose', '-n', '--dry-run', '--porcelain', '--progress',
  '--no-progress', '--atomic'
]);
// A git setting can run a command, hide a refused one behind an alias, or send code somewhere else.
const DANGEROUS_GIT_KEY = new RegExp(
  '^(alias\\.|core\\.(hookspath|sshcommand|fsmonitor|editor|pager|askpass|gitproxy)|sequence\\.editor|pager\\.|'
  + 'credential\\.|url\\.|include|filter\\.|diff\\.|merge\\.|gpg\\.|http\\.|protocol\\.|'
  + 'remote\\..*\\.(url|pushurl|receivepack|uploadpack))',
  'i'
);

function checkGit(args, whole, plain) {
  checkGitOptions(args, whole);
  const { sub, rest } = gitSplit(args);
  if (MODE === 'reviewer') reviewerGit(sub, rest, whole);
  if (sub === 'push') checkPush(rest, whole, plain ? plainGitDir(args) : '');
  else if (sub === 'tag') checkTag(rest, whole);
  else if (sub === 'config') checkConfig(rest, whole);
  else if (sub === 'remote') checkRemote(rest, whole);
  else if (sub === 'update-ref') {
    deny('Moving a ref by hand can move main or a tag. Use a branch and a pull request.', whole);
  } else if (sub === 'send-pack' || sub === 'http-push') {
    deny('That is a push by another name. Push the branch with git push -u origin <branch>.', whole);
  }
}

// Settings given before the subcommand, git -c key=value and --config-env, count as settings.
function checkGitOptions(args, whole) {
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    let key = '';
    if ((a === '-c' || a === '--config-env') && i + 1 < args.length) key = args[++i];
    else if (/^--config-env=/.test(a)) key = a.slice(a.indexOf('=') + 1);
    else if (a === '-C' || /^--(git-dir|work-tree|namespace|super-prefix)$/.test(a)) {
      i++;
      continue;
    } else if (!a.startsWith('-')) return;
    if (key && DANGEROUS_GIT_KEY.test(key.split('=')[0])) {
      deny('Git settings that run commands or change where code goes are the owner\'s.', whole);
    }
  }
}

// The directory a plain git command runs in, the shell's own moved by each -C. Any other option before the
// subcommand, a -c setting, --git-dir or --work-tree, makes the command not plain, and the answer is ''.
function plainGitDir(args) {
  let dir = CWD;
  for (let i = 0; i < args.length; i++) {
    if (args[i] === '-C' && i + 1 < args.length) {
      dir = path.resolve(dir, args[++i]);
      continue;
    }
    return args[i].startsWith('-') ? '' : dir;
  }
  return '';
}

// The one push to main a session makes, cicd D-046. The owner keeps the live status of the work in STATUS.md of
// kriegerdataforge-context and has sessions commit it straight to main, so it is current wherever the owner reads
// it. The repo is judged by its remote, the push URL included, and every commit the push carries must change
// STATUS.md alone. Anything git cannot answer refuses the push.
const CONTEXT_ON_GITHUB = /^\/?needless2say\/kriegerdataforge-context(\.git)?\/?$/i;
const CONTEXT_ON_DISK = /(^|[\\/])needless2say[\\/]kriegerdataforge-context(\.git)?[\\/]?$/i;
const STATUS_FILE = 'STATUS.md';
const STATUS_MAX_COMMITS = 50;
const STATUS_PUSH_WHY = 'Only commits that change STATUS.md alone go straight to main of kriegerdataforge-context.';
// Variables that point git at another repo, object store or configuration than the one the push is judged by.
const GIT_REDIRECT_VAR = new RegExp(
  '^GIT_(DIR|WORK_TREE|INDEX_FILE|OBJECT_DIRECTORY|ALTERNATE_OBJECT_DIRECTORIES|NAMESPACE|COMMON_DIR|CONFIG|'
  + 'CONFIG_GLOBAL|CONFIG_SYSTEM|CONFIG_NOSYSTEM|CONFIG_PARAMETERS|CONFIG_COUNT|CONFIG_KEY_\\d+|CONFIG_VALUE_\\d+)$',
  'i'
);

// A remote URL that names kriegerdataforge-context, on github.com by https or ssh, or a path on this machine, which
// a push never leaves. The URL may hold a credential, so it is read here and never printed.
function contextRemote(url) {
  const u = String(url || '').trim();
  const scheme = /^([a-z][a-z0-9+.-]*):\/\/(?:[^@/]*@)?([^/:]*)(?::\d+)?(\/.*)?$/i.exec(u);
  if (scheme) {
    const proto = scheme[1].toLowerCase();
    const host = scheme[2].toLowerCase();
    if (proto === 'file' && host === '') return CONTEXT_ON_DISK.test(scheme[3] || '');
    return (proto === 'https' || proto === 'ssh') && host === 'github.com' && CONTEXT_ON_GITHUB.test(scheme[3] || '');
  }
  const scp = /^(?:[^@/\\]+@)?([^/\\:]+):(.*)$/.exec(u);
  if (scp && !/^[a-z]$/i.test(scp[1])) return scp[1].toLowerCase() === 'github.com' && CONTEXT_ON_GITHUB.test(scp[2]);
  return CONTEXT_ON_DISK.test(u);
}

function statusPush(dir) {
  const git = (args) => execFileSync('git', ['-C', dir, ...args], {
    encoding: 'utf8',
    stdio: ['ignore', 'pipe', 'ignore'],
    timeout: Math.min(20000, timeLeft()),
    windowsHide: true,
    env: { ...process.env, GIT_TERMINAL_PROMPT: '0' }
  }).trim();
  let fetchUrl;
  let pushUrl;
  try {
    fetchUrl = git(['remote', 'get-url', 'origin']);
    pushUrl = git(['remote', 'get-url', '--push', 'origin']);
  } catch (err) {
    return { context: false };
  }
  if (!contextRemote(fetchUrl)) return { context: false };
  if (!contextRemote(pushUrl)) return { context: true, why: 'Its push URL leads somewhere else.' };
  if (Object.keys(process.env).some((k) => GIT_REDIRECT_VAR.test(k))) {
    return { context: true, why: 'A GIT_ variable in the environment could point git at another repo or setting.' };
  }
  let head = '';
  try {
    head = git(['symbolic-ref', '-q', '--short', 'HEAD']);
  } catch (err) {
    head = '';
  }
  if (head !== 'main') return { context: true, why: 'Check out main first, the push is judged from main.' };
  try {
    git(['-c', 'gc.auto=0', '-c', 'maintenance.auto=false', 'fetch', '--quiet', '--no-tags', 'origin',
      '+refs/heads/main:refs/remotes/origin/main']);
    const range = 'refs/remotes/origin/main..refs/heads/main';
    const commits = git(['rev-list', '--max-count=' + (STATUS_MAX_COMMITS + 1), range]).split('\n').filter(Boolean);
    if (commits.length > STATUS_MAX_COMMITS) {
      return { context: true, why: 'More than ' + STATUS_MAX_COMMITS + ' commits wait, open a pull request.' };
    }
    if (git(['rev-list', '--merges', range])) return { context: true, why: 'A merge commit is in the push.' };
    for (const sha of commits) {
      const names = git(['diff-tree', '--no-commit-id', '--name-only', '-r', '--no-renames', sha]).split('\n')
        .filter(Boolean);
      if (names.length !== 1 || names[0] !== STATUS_FILE) {
        return { context: true, why: 'Commit ' + sha.slice(0, 7) + ' changes more than STATUS.md, or nothing.' };
      }
    }
  } catch (err) {
    return { context: true, why: 'git could not read the remote or the commits, so the push is refused.' };
  }
  return { allowed: true };
}

function checkPush(rest, whole, dir) {
  if (MODE !== 'reviewer' && dir && rest.length === 2 && rest[0] === 'origin' && rest[1] === 'main') {
    const verdict = statusPush(dir);
    if (verdict.allowed) return;
    if (verdict.context) deny(STATUS_PUSH_WHY + ' ' + verdict.why, whole);
  }
  const opts = rest.filter((a) => a.startsWith('-'));
  const pos = rest.filter((a) => !a.startsWith('-'));
  const long = /^--(force|force-with-lease|force-if-includes|delete|tags|mirror|all|prune|follow-tags|no-verify)(=.*)?$/;
  if (opts.some((a) => long.test(a) || /^-[a-zA-Z]*[fd][a-zA-Z]*$/.test(a))) {
    deny('Force, delete, tag, mirror and no-verify pushes are refused. Push the branch plainly.', whole);
  }
  // an option outside the list may take the next word as its value, which leaves the guard judging a word git never
  // reads as the remote, and git takes an abbreviation of a long option the list above names in full (D-062)
  const unknown = opts.find((a) => !PUSH_OPTIONS.has(a) && !/^-[uqvn]+$/.test(a));
  if (unknown) {
    deny('A push takes -u, --set-upstream, -q, -v, -n, --dry-run, --porcelain, --progress or --atomic, written in '
      + 'full. ' + unknown + ' is refused, since another option can carry a word git reads as the remote.', whole);
  }
  if (pos.length < 2) {
    deny('Name the branch, git push -u origin <branch>. A bare push, or one with no branch, is refused.', whole);
  }
  if (pos[0] !== 'origin') {
    deny('Push only to origin. A URL or another remote is refused.', whole);
  }
  for (const ref of pos.slice(1)) {
    if (ref.startsWith('+')) deny('A + refspec forces the push.', whole);
    if (ref === 'tag') deny('Pushing a tag is refused. Only the owner tags.', whole);
    if (ref === 'HEAD') deny('Name the branch, not HEAD, so a push from main cannot slip through.', whole);
    if (ref.startsWith(':')) deny('Deleting a remote ref is refused.', whole);
    let dst = ref.includes(':') ? ref.slice(ref.indexOf(':') + 1) : ref;
    if (dst === '') deny('Deleting a remote ref is refused.', whole);
    dst = dst.replace(/^refs\/heads\//i, '').replace(/^origin\//i, '');
    if (/^refs\/tags\//i.test(dst)) deny('Pushing a tag is refused. Only the owner tags.', whole);
    if (/^(main|master)$/i.test(dst)) {
      deny('Nothing is pushed to main. Push a branch and open a pull request, the owner merges it.', whole);
    }
    if (/^v?\d+\.\d+/.test(dst)) deny('A version number looks like a tag. Only the owner tags.', whole);
  }
}

function checkTag(rest, whole) {
  const listing = rest.some((a) => /^(-l|--list|--contains|--points-at|--merged|--no-merged|--sort(=.*)?|--format(=.*)?|--column)$/.test(a));
  const creating = rest.some((a) => /^-[a-zA-Z]*[asfdmu]/.test(a) || /^--(annotate|sign|force|delete|message|local-user)/.test(a));
  const named = rest.filter((a) => !a.startsWith('-')).length > 0;
  if (!listing && (creating || named)) deny('Tags cut releases. Only the owner tags.', whole);
}

// git config in both forms, the options of before git 2.46 and its subcommands since, get, list, set, unset, edit and
// the section moves. Every word that is not an option is judged as a key, since an option such as --file takes the
// next word as its value and the subcommand comes first, so a value never hides the key (D-062).
// A long option git takes in any unique abbreviation, so --rename-sect is --rename-section (D-062).
function shortens(arg, option, least) {
  return arg.length >= least && option.startsWith(arg);
}
const CONFIG_EDITS = (a) => a === '-e' || shortens(a, '--edit', 3);
const CONFIG_SECTIONS = (a) => shortens(a, '--rename-section', 5) || shortens(a, '--remove-section', 5);
const CONFIG_READ_OPTS = new RegExp('^(--get|--get-all|--get-regexp|--get-urlmatch|--get-color|--get-colorbool|--list|'
  + '-l|--show-origin|--show-scope|--name-only)$');

// Whether a git config call only reads, by its subcommand or its older read options, with nothing that writes.
function configReads(rest) {
  const sub = (rest.find((a) => !a.startsWith('-')) || '').toLowerCase();
  if (/^(get|list|get-color|get-colorbool)$/.test(sub)) return true;
  if (/^(set|unset|edit|rename-section|remove-section)$/.test(sub)) return false;
  if (rest.some((a) => CONFIG_EDITS(a) || CONFIG_SECTIONS(a))) return false;
  return rest.some((a) => CONFIG_READ_OPTS.test(a));
}

function checkConfig(rest, whole) {
  const words = rest.filter((a) => !a.startsWith('-'));
  const sub = (words[0] || '').toLowerCase();
  if (sub === 'edit' || rest.some(CONFIG_EDITS)) {
    deny('Editing git config hands the whole file to an editor the guard cannot judge. The owner edits it.', whole);
  }
  if (/^(rename|remove)-section$/.test(sub) || rest.some(CONFIG_SECTIONS)) {
    deny('Moving or removing a section of git config can change where code goes. The owner does that.', whole);
  }
  if (configReads(rest)) return;
  if (words.some((w) => DANGEROUS_GIT_KEY.test(w))) {
    deny('Git settings that run commands or change where code goes are the owner\'s.', whole);
  }
}

function checkRemote(rest, whole) {
  const first = (rest.find((a) => a !== '-v' && a !== '--verbose') || '').toLowerCase();
  if (['add', 'set-url', 'rename', 'remove', 'rm', 'set-head'].includes(first)) {
    deny('Changing a git remote can send code somewhere else. The owner does that.', whole);
  }
}

function reviewerGit(sub, rest, whole) {
  const READ = new Set([
    'status', 'diff', 'log', 'show', 'blame', 'annotate', 'ls-files', 'ls-tree', 'rev-parse', 'rev-list', 'describe',
    'cat-file', 'grep', 'shortlog', 'diff-tree', 'diff-index', 'name-rev', 'merge-base', 'for-each-ref', 'show-ref',
    'count-objects', 'check-ignore', 'check-attr', 'ls-remote', 'help', 'version', 'whatchanged', 'range-diff',
    'verify-commit', 'verify-tag', 'tag', ''
  ]);
  if ((sub === 'grep' || sub === 'diff') && rest.some((a) => /^--(no-index|no-exclude-standard)$/.test(a))) {
    deny('git ' + sub + ' with --no-index or --no-exclude-standard reads what git does not track. ' + IGNORED_WHY, whole);
  }
  if (READ.has(sub)) return;
  const first = (rest[0] || '').toLowerCase();
  if (sub === 'branch') {
    const bad = rest.some((a) => /^-[a-zA-Z]*[dDmMcCfu]/.test(a) || /^--(delete|move|copy|force|set-upstream-to|unset-upstream|edit-description|track|no-track)/.test(a));
    const pos = rest.filter((a) => !a.startsWith('-'));
    const listing = rest.some((a) => /^(-l|--list|--contains|--merged|--no-merged|--points-at|--sort(=.*)?|--format(=.*)?)$/.test(a));
    if (!bad && (pos.length === 0 || listing)) return;
  } else if (sub === 'stash') {
    if (first === 'list' || first === 'show') return;
  } else if (sub === 'remote') {
    if (rest.length === 0 || ['-v', 'show', 'get-url'].includes(first)) return;
  } else if (sub === 'config') {
    if (rest.some((a) => /^(--get|--get-all|--get-regexp|--list|-l)$/.test(a))) return;
  } else if (sub === 'worktree') {
    if (first === 'list') return;
  } else if (sub === 'reflog') {
    if (!['expire', 'delete'].includes(first)) return;
  }
  deny('Reviewers get read only git. git ' + sub + ' is refused.', whole);
}

// ------------------------------------------------------------ gh, deploy tools

function checkGh(args, whole) {
  if (MODE === 'reviewer') deny('Reviewers do not use the GitHub CLI.', whole);
  const lower = args.map((a) => a.toLowerCase());
  const words = [];
  for (let i = 0; i < lower.length; i++) {
    if (lower[i] === '-r' || lower[i] === '--repo' || lower[i] === '--hostname') {
      i++;
      continue;
    }
    if (!lower[i].startsWith('-')) words.push(lower[i]);
  }
  const group = words[0];
  const verb = words[1];
  if (group === 'pr' && ['merge', 'review', 'ready'].includes(verb)) {
    deny('Only the owner merges, approves and marks a pull request ready. Leave it open and notify the owner.', whole);
  }
  if (group === 'release') deny('Releases are the owner\'s, publishing one starts a deployment.', whole);
  if (group === 'workflow' && ['run', 'enable', 'disable'].includes(verb)) {
    deny('Dispatching or switching a workflow can deploy. Only the owner does that.', whole);
  }
  if (group === 'run' && ['rerun', 'cancel', 'delete'].includes(verb)) {
    deny('Re-running, cancelling or deleting a workflow run can redeploy or hide one. Push a commit to re-run a pull '
      + 'request\'s checks, or ask the owner.', whole);
  }
  if (group === 'ssh-key' || group === 'gpg-key') deny('Account keys are the owner\'s.', whole);
  if (group === 'secret' || group === 'variable') deny('Actions secrets and variables are the owner\'s.', whole);
  if (group === 'gist') deny('A gist publishes text outside the repo. Only the owner does that.', whole);
  if (group === 'repo' && ['delete', 'edit', 'archive', 'rename', 'create', 'sync', 'deploy-key'].includes(verb)) {
    deny('Repository settings, keys and lifecycle are the owner\'s.', whole);
  }
  if (group === 'auth' && ['token', 'logout', 'refresh', 'setup-git'].includes(verb)) {
    deny('The login and its token are the owner\'s.', whole);
  }
  if (group === 'alias' || group === 'extension') deny('gh aliases and extensions can hide a refused command.', whole);
  if (group === 'api') {
    // a method or a field in any spelling, -XPOST and -iXPOST joined to their option among them (D-068)
    const mutating = args.some((a) => /^-[A-Za-z]*[XFf]/.test(a) && !a.startsWith('--'))
      || lower.some((a) => /^--(method|field|raw-field|input)(=.*)?$/.test(a));
    const endpoint = words[1] || '';
    if (mutating) deny('gh api with a method, fields or input can merge, release or change settings. Use a gh subcommand.', whole);
    if (endpoint.includes('graphql')) deny('GraphQL through gh api can merge or change settings. Use a gh subcommand.', whole);
    if (/(\/merge|\/releases|\/dispatches|\/git\/refs|\/rulesets|\/protection|\/actions\/(secrets|variables)|\/hooks|\/collaborators|\/keys|\/deployments)/.test(endpoint)) {
      deny('That gh api endpoint reaches merges, releases, deployments or settings. Only the owner uses it.', whole);
    }
  }
}

function checkOther(prog, args, assigns, whole) {
  const words = args.filter((a) => !a.startsWith('-')).map((a) => a.toLowerCase());
  if (prog === 'terraform' || prog === 'tofu') {
    if (words.some((w) => ['apply', 'destroy', 'import', 'taint', 'untaint', 'force-unlock'].includes(w))
      || (words.includes('state') && words.some((w) => ['rm', 'mv', 'push', 'replace-provider'].includes(w)))) {
      deny('Only the owner runs terraform apply, destroy or a state change.', whole);
    }
  } else if (prog === 'make' || prog === 'gmake' || prog === 'mingw32-make') {
    checkMake(args, assigns, whole);
  } else if (/^(python[0-9.]*|py|pypy[0-9.]*)$/.test(prog)) {
    checkPython(args, whole);
  } else if (/\.py$/.test(prog)) {
    checkOps(prog, args, whole);
  } else if (prog === 'vercel') {
    deny('Deploys are the owner\'s.', whole);
  } else if (prog === 'docker' || prog === 'docker-compose') {
    if (words.includes('push')) deny('docker push publishes an image. Only the owner does that.', whole);
  } else if (['npm', 'pnpm', 'yarn', 'bun'].includes(prog)) {
    if (words.includes('publish')) deny('Publishing a package is the owner\'s.', whole);
    checkPackageScript(prog, words, whole);
  } else if (['npx', 'pnpx', 'bunx'].includes(prog) || (prog === 'pnpm' && words.includes('dlx'))) {
    if (words.some((w) => /^(vercel|firebase-tools|netlify-cli)/.test(w))) deny('Deploys are the owner\'s.', whole);
  } else if (prog === 'twine' && words.includes('upload')) {
    deny('Publishing a package is the owner\'s.', whole);
  } else if (prog === 'gcloud' && words.includes('deploy')) {
    deny('Deploys are the owner\'s.', whole);
  }
  if (words.includes('twine') && words.includes('upload')) deny('Publishing a package is the owner\'s.', whole);
}

// Words in a make target that mean it reaches the DEV or PROD environment, or changes what is deployed. A target
// named for dev reaches DEV unless it also names local, the ecosystem's word for the developer's own machine.
const REMOTE_MAKE_WORDS = new Set(['prod', 'production', 'deploy', 'apply', 'destroy', 'publish', 'release', 'promote', 'rollout']);
const MAKE_VALUE_OPTS = /^(-C|-f|-I|-j|-l|-o|-W|--directory|--file|--makefile|--include-dir|--jobs|--load-average|--old-file|--assume-old|--what-if|--new-file|--assume-new)$/;
// ENVIRONMENT and HUB_ENV pick the environment a seed or migration target reaches.
const REMOTE_ENV_ASSIGN = /^(ENVIRONMENT|HUB_ENV)=["']?(dev|prod|production)["']?$/i;

// A package script named for a deploy, a release or a remote environment is the owner's, the way a make target is.
// npm needs run or run-script before a script, yarn, pnpm and bun take its name alone. npm run dev, the local dev
// server, stays allowed, since a package script names DEV only by saying prod or production.
function checkPackageScript(prog, words, whole) {
  let script = '';
  if (words[0] === 'run' || words[0] === 'run-script') script = words[1] || '';
  else if (prog !== 'npm') script = words[0] || '';
  if (script.split(/[-_.:/]/).some((w) => REMOTE_MAKE_WORDS.has(w))) {
    deny('A package script that deploys, releases or reaches DEV or PROD is the owner\'s. Ask the owner.', whole);
  }
}

function checkMake(args, assigns, whole) {
  const why = 'Make targets that reach DEV or PROD, or apply, deploy or publish, are the owner\'s. Ask the owner.';
  if (assigns.some((a) => REMOTE_ENV_ASSIGN.test(a))) deny(why, whole);
  for (let i = 0; i < args.length; i++) {
    const a = String(args[i]);
    // a redirect and its target belong to the shell and name no target, so make ci >/dev/null runs
    const redirect = /^(\d*)(>>?|&>>?|<)(.*)$/.exec(a);
    if (redirect) {
      if (!redirect[3]) i++;
      continue;
    }
    if (MAKE_VALUE_OPTS.test(a)) {
      i++;
      continue;
    }
    if (a.startsWith('-')) continue;
    if (a.includes('=')) {
      if (REMOTE_ENV_ASSIGN.test(a)) deny(why, whole);
      continue;
    }
    const words = a.toLowerCase().split(/[-_.:/]/);
    if (words.some((w) => REMOTE_MAKE_WORDS.has(w)) || (words.includes('dev') && !words.includes('local'))) {
      deny(why, whole);
    }
  }
}

// cicd's ops scripts act on GitHub and Vercel with the owner's tokens. A session runs only their read only modes.
const OPS_SCRIPTS = {
  rotate_secret: { mode: 'check' },
  distribute_app_secrets: { refuse: ['execute'] },
  distribute_kit: { refuse: ['distribute'] },
  distribute_scripts: { refuse: ['distribute'] },
  provision_projects: { refuse: ['execute'] },
  trigger_triage: { refuse: null }
};

// The script a Python interpreter runs, its first .py argument or the module after -m. Inline code after -c is opaque.
function checkPython(args, whole) {
  for (let i = 0; i < args.length; i++) {
    const a = String(args[i]);
    if (a === '-c') return;
    if (a === '-m') {
      if (i + 1 < args.length) checkOps(String(args[i + 1]).split('.').pop(), args.slice(i + 2), whole);
      return;
    }
    if (/\.py$/i.test(a)) {
      checkOps(a, args.slice(i + 1), whole);
      return;
    }
  }
}

function checkOps(script, rest, whole) {
  const name = path.basename(String(script).replace(/\\/g, '/')).toLowerCase().replace(/\.py$/, '');
  if (!Object.prototype.hasOwnProperty.call(OPS_SCRIPTS, name)) return;
  const rule = OPS_SCRIPTS[name];
  const lower = rest.map((x) => String(x).toLowerCase());
  if (lower.includes('-h') || lower.includes('--help')) return;
  const k = lower.findIndex((x) => x === '--mode' || x.startsWith('--mode='));
  const mode = k < 0 ? '' : lower[k].includes('=') ? lower[k].slice(lower[k].indexOf('=') + 1) : lower[k + 1] || '';
  const allowed = rule.mode ? mode === rule.mode : rule.refuse !== null && !lower.some((x) => rule.refuse.includes(x));
  if (!allowed) {
    deny(name + '.py acts on GitHub or Vercel with the owner\'s tokens. A session runs only its read only mode.', whole);
  }
}

// ------------------------------------------------------------ reviewer only

const READER_DENIED = new Set([
  'rm', 'rmdir', 'del', 'erase', 'rd', 'ri', 'remove-item', 'mv', 'move', 'move-item', 'mi', 'cp', 'copy', 'copy-item',
  'cpi', 'ren', 'rename', 'rename-item', 'rni', 'mkdir', 'md', 'new-item', 'ni', 'touch', 'chmod', 'chown', 'tee',
  'tee-object', 'dd', 'truncate', 'set-content', 'sc', 'add-content', 'ac', 'clear-content', 'clc', 'out-file',
  'set-item', 'set-itemproperty', 'wget', 'iwr', 'irm', 'invoke-webrequest', 'invoke-restmethod', 'scp',
  'ssh', 'sftp', 'ftp', 'start-process', 'saps', 'stop-process', 'kill', 'taskkill', 'expand-archive',
  'compress-archive', 'tar', 'zip', 'unzip', '7z', 'robocopy', 'xcopy', 'attrib', 'icacls', 'takeown', 'setx', 'reg',
  'kubectl'
]);
// A reviewer reads the running stack and never changes it, docker ps and docker logs, their compose forms too, and
// curl to this machine alone. Neither takes an environment assignment, which can point it at another host.
const DOCKER_VALUE_OPTS = /^(--config|-l|--log-level|-f|--file|-p|--project-name|--project-directory|--env-file|--profile|--ansi|--progress|--tlscacert|--tlscert|--tlskey)$/;
// -H, --host, -c and --context point docker at another machine's daemon.
const DOCKER_REMOTE = /^(-H|-c|--host|--context)(=|$)|^-[Hc]./;
// curl has hundreds of options and many write a file, read one, follow a redirect or send the request somewhere else,
// so a reviewer's curl takes these alone. A value that starts with @ reads a file, and so does --data-urlencode name@file.
const CURL_SHORT_FLAGS = new Set('sSiIvkfGN46q#0g'.split(''));
const CURL_SHORT_VALUES = new Set('HXdAewmru'.split(''));
const CURL_LONG_FLAGS = new Set(['silent', 'show-error', 'include', 'head', 'verbose', 'insecure', 'fail', 'fail-with-body',
  'get', 'compressed', 'no-buffer', 'ipv4', 'ipv6', 'http1.0', 'http1.1', 'http2', 'disable', 'progress-bar',
  'no-progress-meter', 'globoff']);
const CURL_LONG_VALUES = new Set(['url', 'header', 'request', 'data', 'data-ascii', 'data-binary', 'data-raw',
  'data-urlencode', 'json', 'user-agent', 'referer', 'write-out', 'max-time', 'connect-timeout', 'range', 'user', 'retry',
  'retry-delay', 'retry-max-time']);
const CURL_AT_READS = new Set(['H', 'd', 'w', 'header', 'data', 'data-ascii', 'data-binary', 'json', 'write-out']);
// The host is matched as text in one strict shape, never through a URL parser, whose reading of an odd URL need not
// match curl's own. A URL in any other shape is refused, even one curl would send to this machine.
const LOCAL_URL = /^(?:https?:\/\/)?(?:localhost|127\.0\.0\.1|\[::1\])(?::(\d+))?(?:[/?#].*)?$/i;
// The Docker Engine API and Caddy's admin API listen here, and a request to either starts or stops the stack.
const CONTROL_PORTS = new Set(['2375', '2376', '2019']);

function checkReviewerStack(prog, args, assigns, whole) {
  const refuse = (why) => deny('A reviewer only reads the running stack. ' + why, whole);
  if (assigns.length) refuse('Its ' + prog + ' takes no environment assignment, which can point it at another host.');
  if (prog === 'docker' || prog === 'docker-compose') {
    let compose = prog === 'docker-compose';
    let sub     = '';
    for (let i = 0; i < args.length && !sub; i++) {
      if (DOCKER_REMOTE.test(args[i])) refuse('docker reaches the daemon on this machine alone.');
      if (DOCKER_VALUE_OPTS.test(args[i])) i++;
      else if (!args[i].startsWith('-')) {
        if (!compose && args[i] === 'compose') compose = true;
        else sub = args[i].toLowerCase();
      }
    }
    if (sub !== 'ps' && sub !== 'logs') refuse('docker ' + (compose ? 'compose ' : '') + sub + ' is refused, only ps and logs.');
    return;
  }
  checkCurl(args, refuse);
}

// curl to this machine alone, every session's since the owner's word of 2026-10-12 and a reviewer's before it. Its
// options come from an allow list, so nothing writes a file, reads one with @, follows a redirect, goes through a
// proxy or a socket, or reaches the Docker Engine or Caddy admin API, and the host is matched as text in one shape.
function checkCurl(args, refuse) {
  const urls  = [];
  const value = (opt, v) => {
    if (CURL_AT_READS.has(opt) && v.startsWith('@')) refuse('A curl value that starts with @ reads a file.');
    // curl 8.3's %output{file} in a write-out format writes a file
    if ((opt === 'w' || opt === 'write-out') && /%output\{/i.test(v)) refuse('curl -w with %output writes a file.');
    if (opt === 'data-urlencode' && /^[^=]*@/.test(v)) refuse('curl --data-urlencode name@file reads a file.');
    if (opt === 'url') urls.push(v);
  };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const name = a.slice(2);
      if (CURL_LONG_FLAGS.has(name)) continue;
      if (!CURL_LONG_VALUES.has(name)) refuse('curl ' + a + ' is refused, see the curl options in the guard.');
      value(name, args[++i] || '');
    } else if (a.length > 1 && a.startsWith('-')) {
      for (let k = 1; k < a.length; k++) {
        if (CURL_SHORT_FLAGS.has(a[k])) continue;
        if (!CURL_SHORT_VALUES.has(a[k])) refuse('curl -' + a[k] + ' is refused, see the curl options in the guard.');
        value(a[k], k + 1 < a.length ? a.slice(k + 1) : args[++i] || '');
        break;
      }
    } else {
      urls.push(a);
    }
  }
  if (!urls.length) refuse('curl needs a URL on this machine.');
  for (const u of urls) {
    const m = LOCAL_URL.exec(u);
    if (!m) refuse('curl reaches this machine alone, http or https to localhost, 127.0.0.1 or [::1], and ' + u + ' is not that.');
    // curl reads a port as a number, so 02019 is 2019
    const port = m[1] ? String(Number(m[1])) : '';
    if (port && CONTROL_PORTS.has(port)) {
      refuse('Port ' + port + ' is the Docker Engine or Caddy admin API, which changes the stack.');
    }
  }
}
const INSTALLERS = new Set(['install', 'uninstall', 'download', 'wheel', 'add', 'remove', 'sync', 'lock']);
const NODE_WRITERS = new Set(['install', 'i', 'add', 'remove', 'uninstall', 'update', 'upgrade', 'ci', 'publish', 'link', 'unlink', 'dedupe', 'prune']);
const MAKE_WRITERS = /^(setup|clean.*|bump.*|docker.*|compile.*|release.*|publish.*|install.*|deploy.*)$/;

function checkReviewerProgram(prog, args, assigns, whole) {
  const a = args.map((x) => x.toLowerCase());
  const refuse = () => deny('Reviewers only read and write their report. ' + prog + ' is refused.', whole);
  if (CONTENT_READERS.has(prog)) args.filter((x) => !x.startsWith('-')).forEach((x) => checkReviewerOpens(x, whole));
  if (/^(grep|egrep|fgrep)$/.test(prog) && a.some((x, k) => /^-[a-z]*r/.test(x)
    || /^--(recursive|dereference-recursive|directories=recurse)$/.test(x)
    || ((x === '-d' || x === '--directories') && a[k + 1] === 'recurse'))) {
    deny('A recursive grep reads what .gitignore excludes. Use git grep or rg, which honour it.', whole);
  }
  if (prog === 'rg' && args.some((x) => /^-[a-zA-Z]*u/.test(x) || /^--(no-ignore(-[a-z-]+)?|unrestricted)$/.test(x))) {
    deny('rg -u and --no-ignore read what .gitignore excludes. Drop the flag.', whole);
  }
  if (READER_DENIED.has(prog)) refuse();
  if (prog === 'docker' || prog === 'docker-compose' || prog === 'curl') checkReviewerStack(prog, args, assigns, whole);
  if ((prog === 'sed' || prog === 'perl') && a.some((x) => /^-[a-z]*i/.test(x) || x.startsWith('--in-place'))) refuse();
  if (/^(pip[0-9.]*|pipx|uv)$/.test(prog) && a.some((x) => INSTALLERS.has(x))) refuse();
  if (/^(python[0-9.]*|py)$/.test(prog)) {
    const m = a.indexOf('-m');
    if (m >= 0 && a[m + 1] === 'pip' && a.some((x) => INSTALLERS.has(x))) refuse();
  }
  if (/^(npm|pnpm|yarn|bun)$/.test(prog) && a.some((x) => NODE_WRITERS.has(x))) refuse();
  if (prog === 'make' && a.some((x) => MAKE_WRITERS.test(x))) refuse();
  if (prog === 'find' && a.includes('-delete')) refuse();
}

function checkRedirects(toks, whole) {
  for (let i = 0; i < toks.length; i++) {
    if (toks[i].q) continue;
    const m = /^(\d*)(>>?|&>>?)(.*)$/.exec(toks[i].t);
    if (!m) continue;
    const target = m[3] || (toks[i + 1] ? toks[i + 1].t : '');
    const harmless = /^(\/dev\/null|nul|\$null)$/i.test(target) || target.startsWith('&');
    if (!harmless && !insideReviewsDir(target)) {
      deny('Reviewers may not redirect output into a file. Write the report with the file tools under docs/reviews.', whole);
    }
  }
}
