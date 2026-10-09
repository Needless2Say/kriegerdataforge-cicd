#!/usr/bin/env node
'use strict';
/*
 * kdf-guard.js, the KDF Code Review Process guard. A Claude Code PreToolUse hook.
 *
 *   node kdf-guard.js                   owner rules, for every session the owner starts
 *   node kdf-guard.js reviewer          reviewer rules, on top of the owner rules
 *   KDF_ROLE=reviewer node kdf-guard.js the same reviewer rules, chosen when the session is launched
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
 * A permission deny rule matches one tool and one spelling. This guard reads the command the way a shell does,
 * so it also catches the PowerShell tool, git -C, a nested shell, an env prefix, find -exec and a command after a
 * shell keyword such as do, then or !, and it ignores quoted text such as a commit message. Exit 0 allows the
 * call. Exit 2 blocks it and stderr tells the model why. Input it cannot read, a call with no tool name, or an error
 * while it checks refuses the call with exit 2, every tool, since an error before a check would let that check's
 * call through (D-059). A guard that cannot start exits 1 or 127, which Claude Code lets through, so its settings line
 * runs node ... || exit 2, and a hook that times out still lets a call through. To switch it off, remove the hook
 * from the settings file.
 *
 * Environment. KDF_ROLE=reviewer picks the reviewer rules. KDF_GUARD_ALLOW_SELF_EDIT=1, set by the owner when the
 * session is started, lets that session edit guardrail files. KDF_GUARD_LOG=<file> appends one line per refusal.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');

const ROLE = String(process.argv[2] || process.env.KDF_ROLE || '').toLowerCase();
const MODE = ROLE === 'reviewer' ? 'reviewer' : 'orchestrator';
const SELF_EDIT_OK = process.env.KDF_GUARD_ALLOW_SELF_EDIT === '1';
const MAX_DEPTH = 5;
const FILE_TOOLS = /^(Edit|Write|MultiEdit|NotebookEdit)$/;
// Tools that reach outside the repo, or run code the guard cannot read. A reviewer uses none of them. The IDE
// diagnostics tool alone stays allowed, its code runner is refused like any other (D-060).
const OUTWARD_TOOLS = /^(mcp__(?!ide__getDiagnostics$)|Artifact|SendUserFile$|SendMessage$|PushNotification$|RemoteTrigger$|Cron|DesignSync$|EnterWorktree$|Workflow$|WebFetch$|WebSearch$)/;
const WRAPPERS = new Set([
  'env', 'command', 'sudo', 'nohup', 'time', 'exec', 'builtin', 'nice', 'timeout', 'xargs', 'setsid', 'stdbuf',
  'ionice', 'winpty'
]);
// Wrapper options that take a value, so the value is not mistaken for the program that follows.
const WRAPPER_VALUE_OPTS = {
  env: /^(-u|--unset|-C|--chdir|-S|--split-string)$/,
  sudo: /^(-u|-g|-h|-p|-C|-D|-R|-T|-U)$/,
  nice: /^-n$/,
  timeout: /^(-s|-k|--signal|--kill-after)$/,
  xargs: /^(-I|-n|-P|-d|-E|-L|-s|-a)$/,
  stdbuf: /^(-i|-o|-e)$/,
  ionice: /^(-c|-n|-p|-P|-u)$/
};
// Shell keywords that open a clause. The command after them is the one that runs.
const KEYWORD_PREFIXES = new Set(['if', 'then', 'else', 'elif', 'do', 'while', 'until', '!', 'coproc']);
// Shell keywords whose segment is a word list, a pattern or an end. A loop's or a case's body is a segment of its own.
const KEYWORD_LISTS = new Set(['for', 'select', 'case', 'in', 'function', 'done', 'fi', 'esac']);

// Files that hold the guardrails. A session never edits them, the owner does. Git's global and system config are
// among them, since a remote's push URL or a pushInsteadOf there sends every repo's origin somewhere else (D-062).
const PROTECTED = [
  /(^|\/)\.claude\/(settings(\.local)?\.json|hooks(\/|$))/,
  /(^|\/)\.claude\.json$/,
  /(^|\/)\.mcp\.json$/,
  /(^|\/)\.git\/(hooks(\/|$)|config$)/,
  /(^|\/)\.gitconfig$/,
  /(^|\/)\.config\/git\/config$/,
  /(^|\/)etc\/gitconfig$/
];
const GUARDRAIL_WHY = 'Guardrails are the owner\'s to change. Settings, hooks, the MCP list, git hooks and git\'s own '
  + 'config files are edited by hand.';
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
  process.exit(0);
});

function run(input) {
  PROJECT = path.resolve(process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd());
  CWD = path.resolve(input.cwd || PROJECT);
  const tool = input.tool_name || '';
  const args = input.tool_input || {};
  if (tool === 'Bash' || tool === 'PowerShell') {
    check(String(args.command || ''), 0);
  } else if (tool === 'Monitor') {
    // Monitor runs its command in the same shell as Bash, so the command gets Bash's rules, and its WebSocket reaches
    // outside the repo (D-060)
    if (args.ws && MODE === 'reviewer') deny('Reviewers open no WebSocket. Monitor with ws is refused.', 'Monitor ws');
    check(String(args.command || ''), 0);
  } else if (FILE_TOOLS.test(tool)) {
    checkFileTool(String(args.file_path || args.notebook_path || ''));
  } else if (tool === 'Read' || tool === 'Grep' || tool === 'Glob') {
    checkReadTool(tool, args);
  } else if (MODE === 'reviewer' && OUTWARD_TOOLS.test(tool)) {
    deny('Reviewers use no connector, artifact, message, schedule or notification tool. ' + tool + ' is refused.', tool);
  }
}

function norm(p) {
  return String(p).replace(/\\/g, '/').toLowerCase();
}

// a dot segment, ~/.config/git/./config or a/../.git/config, names the same file, so it is folded first (D-062)
function isProtected(p) {
  const n = path.posix.normalize(norm(p));
  return PROTECTED.some((r) => r.test(n));
}

// The review archive, the one folder a reviewer writes in. The separator on the end keeps a look alike such as
// docs/reviews-old outside it.
function insideReviewsDir(p) {
  const fold = (s) => (process.platform === 'win32' ? s.toLowerCase() : s);
  const root = fold(path.join(PROJECT, 'docs', 'reviews') + path.sep);
  return fold(path.resolve(PROJECT, p) + path.sep).startsWith(root);
}

function checkFileTool(target) {
  if (!SELF_EDIT_OK && isProtected(target)) deny(GUARDRAIL_WHY, target);
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
  return LOCAL_ENV.test(s) ? !localEnvOpen(s) : isSecretFile(s);
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
    if (!words.has(k)) out.push(t);
    else for (const w of words.get(k)) out.push({ t: w, q: false, lq: false, g: false });
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
const GIT_QUIET = { stdio: ['ignore', 'ignore', 'pipe'], timeout: 10000, windowsHide: true };

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
    execFileSync('git', ['-C', nearestFolder(path.dirname(abs)), 'ls-files', '--error-unmatch', '--', abs], GIT_QUIET);
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
    execFileSync('git', ['-C', dir, 'check-ignore', '-q', '--', abs], GIT_QUIET);
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

// ------------------------------------------------------------ reading a command like a shell

function stripHeredocs(cmd) {
  const lines = cmd.split(/\r?\n/);
  const out = [];
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    out.push(line);
    const here = line.match(/<<-?\s*(['"]?)([A-Za-z_][\w-]*)\1/);
    if (here && line[here.index - 1] !== '<') {
      while (i + 1 < lines.length && lines[i + 1].trim() !== here[2]) i++;
      i++;
    } else if (/@['"]\s*$/.test(line)) {
      while (i + 1 < lines.length && !/^\s*['"]@/.test(lines[i + 1])) i++;
      i++;
    }
  }
  return out.join('\n');
}

function segments(cmd) {
  const segs = [];
  let cur = [];
  let tok = '';
  let has = false;
  let quoted = false;
  // the token began inside quotes, so FOO="x" is still an assignment and "FOO=x" is a word
  let lead = false;
  // where a *, ?, [ or ] came outside quotes, so bash's glob is known to the character, ".e"nv* a glob and
  // work"[1]" not (D-060)
  let wildAt = new Set();
  const endTok = () => {
    if (has) {
      const g = [...wildAt].some((p) => tok[p] === '*' || tok[p] === '?' || tok[p] === '[');
      cur.push({ t: tok, q: quoted, lq: lead, g, gm: wildAt });
    }
    tok = '';
    has = false;
    quoted = false;
    lead = false;
    wildAt = new Set();
  };
  const endSeg = () => {
    endTok();
    if (cur.length) segs.push(cur);
    cur = [];
  };
  const text = stripHeredocs(cmd);
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    const n = text[i + 1];
    if (c === "'") {
      if (!has) lead = true;
      has = true;
      quoted = true;
      for (i++; i < text.length && text[i] !== "'"; i++) tok += text[i];
      continue;
    }
    if (c === '"') {
      if (!has) lead = true;
      has = true;
      quoted = true;
      for (i++; i < text.length && text[i] !== '"'; i++) {
        if ((text[i] === '\\' || text[i] === '`') && text[i + 1] === '"') {
          tok += '"';
          i++;
          continue;
        }
        tok += text[i];
      }
      continue;
    }
    if ((c === '\\' || c === '`') && (n === '\n' || n === '\r')) {
      i += n === '\r' && text[i + 2] === '\n' ? 2 : 1;
      endTok();
      continue;
    }
    if (c === '#' && !has) {
      while (i < text.length && text[i] !== '\n') i++;
      endSeg();
      continue;
    }
    if (c === '\n' || c === '\r' || c === ';' || c === '|') {
      endSeg();
      continue;
    }
    if (c === '&') {
      if (text[i - 1] === '>' || n === '>') {
        tok += c;
        has = true;
      } else {
        endSeg();
      }
      continue;
    }
    if (c === '(' || c === ')' || c === '{' || c === '}') {
      endSeg();
      continue;
    }
    if (c === ' ' || c === '\t') {
      endTok();
      continue;
    }
    if (c === '*' || c === '?' || c === '[' || c === ']') wildAt.add(tok.length);
    tok += c;
    has = true;
  }
  endSeg();
  return segs;
}

function base(t) {
  return path
    .basename(String(t).replace(/\\/g, '/'))
    .toLowerCase()
    .replace(/\.(exe|cmd|bat|ps1|com)$/, '');
}

function check(cmd, depth) {
  if (depth > MAX_DEPTH) deny('Nested shells are too deep to check.', cmd);
  // dotglob or GLOBIGNORE anywhere in the call lets a glob match a dot name, so the guard's globs do too (D-060)
  if (depth === 0) HIDDEN_TOO = /dotglob|GLOBIGNORE/.test(cmd);
  // a GIT_CONFIG name written as an assignment, anywhere in the call's text (D-062)
  if (GIT_CONFIG_TEXT.test(cmd)) deny(GIT_CONFIG_WHY, cmd);
  if (/GIT_CONFIG/i.test(cmd) && ENV_DRIVE_TEXT.test(cmd) && ENV_WRITE_WORD.test(cmd)) deny(GIT_CONFIG_WHY, cmd);
  if (SET_ENV_CALL.test(cmd) && /GIT_CONFIG/i.test(cmd)) deny(GIT_CONFIG_WHY, cmd);
  if (NEW_DRIVE_WORD.test(cmd) && /GIT_CONFIG/i.test(cmd)) {
    deny('A drive made in a call that names a GIT_CONFIG variable can write it under a name the guard does not know, '
      + 'and send a push elsewhere. Make the drive in a call of its own, or ask the owner.', cmd);
  }
  for (const seg of segments(cmd)) {
    analyze(seg, depth, cmd, true);
    // a glob's matches, judged too, each judgment able only to refuse (D-060)
    for (const variant of globVariants(seg)) analyze(variant, depth, cmd, true);
  }
}

// own is true for a segment of the call itself, false for a command another one runs, such as find -exec's
function analyze(toks, depth, whole, own) {
  const assigns = [];
  let i = 0;
  // env and sudo read NAME=value among their own arguments, so a quoted one is an assignment there too (D-062)
  let readsAssigns = false;
  while (i < toks.length) {
    const t = toks[i];
    if ((!t.lq || readsAssigns) && /^[A-Za-z_][A-Za-z0-9_]*=/.test(t.t)) {
      assigns.push(t.t);
      i++;
      continue;
    }
    if (!t.q && (t.t === '.' || KEYWORD_PREFIXES.has(t.t))) {
      i++;
      continue;
    }
    const b = base(t.t);
    if (!WRAPPERS.has(b)) break;
    readsAssigns = b === 'env' || b === 'sudo';
    i++;
    while (i < toks.length && /^-/.test(toks[i].t)) {
      const opt = toks[i].t;
      i++;
      // env -S runs its value as a command line of its own
      if (b === 'env' && /^(-S|--split-string)$/.test(opt) && i < toks.length) check(splitString(toks[i].t), depth + 1);
      else if (b === 'env' && /^(-S.|--split-string=)/.test(opt)) {
        check(splitString(opt.replace(/^(-S|--split-string=)/, '')), depth + 1);
      }
      if (WRAPPER_VALUE_OPTS[b] && WRAPPER_VALUE_OPTS[b].test(opt)) i++;
    }
    if (b === 'timeout' && i < toks.length && /^\d/.test(toks[i].t)) i++;
  }
  checkGitConfigVars(toks, assigns, i < toks.length ? base(toks[i].t) : '', toks.slice(i + 1).map((x) => x.t), whole);
  if (i >= toks.length) return;
  if (!toks[i].q && KEYWORD_LISTS.has(toks[i].t)) {
    // a for, select or case header is a list or a pattern, its body is a segment of its own, but a redirect after
    // done, fi or esac still writes
    checkProtectedRedirects(toks, whole);
    checkSecretWords(toks, toks[i].t, [], whole);
    if (MODE === 'reviewer') checkRedirects(toks, whole);
    return;
  }
  const prog = base(toks[i].t);
  const args = toks.slice(i + 1).map((x) => x.t);

  if (prog === 'find') {
    const k = toks.findIndex((x, idx) => idx > i && /^-(exec|execdir|ok|okdir)$/.test(x.t));
    if (k >= 0 && k + 1 < toks.length) analyze(toks.slice(k + 1), depth, whole, false);
  }
  checkProtectedInShell(toks, prog, args, whole);
  checkSecretWords(toks, prog, args, whole);
  if (MODE === 'reviewer') checkRedirects(toks, whole);
  if (nestedShell(prog, args, depth)) return;
  // a plain git command is the whole call, one segment, with no wrapper, keyword, assignment or shell around it
  if (prog === 'git') checkGit(args, whole, own && depth === 0 && i === 0 && segments(whole).length === 1);
  else if (prog === 'gh') checkGh(args, whole);
  else checkOther(prog, args, assigns, whole);
  if (MODE === 'reviewer') checkReviewerProgram(prog, args, assigns, whole);
}

// env -S's string, read as more of env's own arguments, its line ends as spaces, so a quoted NAME=value there is an
// assignment as env reads it (D-062)
function splitString(s) {
  return 'env ' + String(s).replace(/[\r\n]+/g, ' ');
}

function nestedShell(prog, args, depth) {
  let inner;
  if (/^(bash|sh|zsh|dash|ksh)$/.test(prog)) {
    const k = args.findIndex((a) => /^-[a-z]*c[a-z]*$/.test(a));
    if (k >= 0) inner = args[k + 1];
  } else if (/^(pwsh|powershell)$/.test(prog)) {
    if (args.some((a) => /^-(e|ec|enc|encodedcommand)$/i.test(a))) {
      deny('An encoded command cannot be checked, so it is refused.', prog);
    }
    const k = args.findIndex((a) => /^-c(ommand)?$/i.test(a));
    if (k >= 0) inner = args.slice(k + 1).join(' ');
  } else if (prog === 'cmd') {
    const k = args.findIndex((a) => /^\/\/?[ck]$/i.test(a));
    if (k >= 0) inner = args.slice(k + 1).join(' ');
  } else if (prog === 'eval' || prog === 'invoke-expression' || prog === 'iex') {
    inner = args.join(' ');
  } else {
    return false;
  }
  if (inner !== undefined) check(inner, depth + 1);
  return true;
}

// ------------------------------------------------------------ guardrail files

function checkProtectedRedirects(toks, whole) {
  if (SELF_EDIT_OK) return;
  for (let i = 0; i < toks.length; i++) {
    if (toks[i].q) continue;
    const m = /^(\d*)(>>?|&>>?)(.*)$/.exec(toks[i].t);
    if (!m) continue;
    const target = m[3] || (toks[i + 1] ? toks[i + 1].t : '');
    if (isProtected(target)) deny(GUARDRAIL_WHY, whole);
  }
}

function checkProtectedInShell(toks, prog, args, whole) {
  if (SELF_EDIT_OK) return;
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
// A variable that hands git settings no word of a call shows, so a push that names origin still goes where the settings
// say (D-062). Two readings, so neither one's blind spots let one through. The call's text refuses a GIT_CONFIG name
// written as an assignment in any shell, bash, cmd's set or PowerShell's $env:, ${env:} and SetEnvironmentVariable,
// spaced or quoted. Quoted text counts too, since cmd /c and env -S unquote what bash would not, so a commit message
// that writes such an assignment goes in a file, git commit -F. The call's words refuse the forms that set a variable
// by its name alone, bash's builtins, cmd's setx and PowerShell's item commands on the env drive. Reading one is open.
const GIT_CONFIG_VAR = /^GIT_CONFIG(_[A-Za-z0-9_]*)?$/i;
const GIT_CONFIG_WHY = 'A GIT_CONFIG variable hands git settings the guard never sees, such as a push URL for origin. '
  + 'The owner sets git\'s settings. A commit message that names such an assignment goes in a file, git commit -F.';
const GIT_CONFIG_TEXT = new RegExp(
  '(^|[^A-Za-z0-9_])GIT_CONFIG[A-Za-z0-9_]*[\'"}]*([-+*/%&|^]?=|\\s+[-+*/%&|^]?=(?!=))|'
  + 'SetEnvironmentVariable\\s*\\(\\s*[\'"]?\\s*GIT_CONFIG',
  'i'
);
// the builtins that set a shell variable by its name, which set -a or an export then hands to git, and cmd's two
// (cmd's set writes NAME=value, which the text check refuses, and bash's set -- only sets positional parameters)
const NAME_SETTERS = /^(export|declare|typeset|readonly|local|mapfile|readarray|getopts|setx)$/;
// read's options that take a value that is not a name
const READ_VALUE_OPTS = /^-[pdtnNui]$/;
// PowerShell's commands that write an item, an env drive path among them
const PS_ITEM_WRITE = new RegExp('^(set-item|si|new-item|ni|set-content|sc|add-content|ac|copy-item|copy|cpi|cp|'
  + 'move-item|move|mi|mv|rename-item|ren|rni)$', 'i');
// A call that names a GIT_CONFIG variable and the env drive, Env: or Environment:: as a path and not $env: as a read,
// beside a command that writes an item or moves onto the drive, wherever its words fall, since PowerShell binds
// parameters by name, position and abbreviation in ways no guess at its words follows. A read, $env:NAME or
// Get-Item Env:NAME with no such command, stays open.
// ${env:NAME} is a read, while {Env:NAME} and every other spelling of the drive is a path
const ENV_DRIVE_TEXT = /(?<![A-Za-z0-9_$])(?<!\$\{)(env:|environment::)/i;
// a command that makes a drive, whose provider PowerShell may bind from a name, a position or a piped object, so a
// drive on the Environment provider writes variables under a name no check knows. A drive lives only in its call, so
// one made in a call that names a GIT_CONFIG variable is refused, however its provider is bound
const NEW_DRIVE_WORD = /(^|[^A-Za-z0-9_-])(new-psdrive|ndr|mount)(?![A-Za-z0-9_-])|Drive\s*\.\s*['"]?New\b|PSDriveInfo/i;
// PowerShell's SetEnvironmentVariable naming a GIT_CONFIG variable anywhere, a cast or a parenthesis around it
// included, since its argument is an expression
const SET_ENV_CALL = /SetEnvironmentVariable/i;
const ENV_WRITE_WORD = new RegExp('(^|[^A-Za-z0-9_-])(set-item|si|new-item|ni|set-content|sc|add-content|ac|copy-item|'
  + 'copy|cpi|cp|move-item|move|mi|mv|rename-item|ren|rni|set-location|cd|sl|chdir|pushd|push-location)'
  + '(?![A-Za-z0-9_-])', 'i');
// the env drive by its drive name or its provider's, Env:, Environment:: or Microsoft.PowerShell.Core\Environment::
const PS_ENV = '(env:|(microsoft\\.powershell\\.core\\\\)?environment::)[\\\\/]?';
const PS_ENV_ITEM = new RegExp('^(-[a-z]+:)?' + PS_ENV, 'i');
const PS_ENV_PATH = new RegExp('^(-[a-z]+:)?' + PS_ENV + 'GIT_CONFIG', 'i');
const PS_NEW_NAME = /^(-newname:)?GIT_CONFIG/i;

function namesGitConfig(word) {
  return GIT_CONFIG_VAR.test(String(word).split('=')[0].trim());
}

function checkGitConfigVars(toks, assigns, prog, args, whole) {
  if (assigns.some(namesGitConfig)) deny(GIT_CONFIG_WHY, whole);
  if (NAME_SETTERS.test(prog) && args.some(namesGitConfig)) deny(GIT_CONFIG_WHY, whole);
  if (prog === 'let' && args.some((a) => /GIT_CONFIG/i.test(a))) deny(GIT_CONFIG_WHY, whole);
  if (prog === 'printf') {
    const k = args.findIndex((a) => a === '-v' || /^-v./.test(a));
    if (k >= 0 && namesGitConfig(args[k] === '-v' ? args[k + 1] || '' : args[k].slice(2))) deny(GIT_CONFIG_WHY, whole);
  }
  if (prog === 'read') {
    for (let k = 0; k < args.length; k++) {
      if (READ_VALUE_OPTS.test(args[k])) k++;
      else if (args[k] === '-a' ? namesGitConfig(args[++k] || '') : !args[k].startsWith('-') && namesGitConfig(args[k])) {
        deny(GIT_CONFIG_WHY, whole);
      }
    }
  }
  // a rename's new name counts only when what it renames is on the env drive, so a file named GIT_CONFIG.md stays open
  if (!PS_ITEM_WRITE.test(prog)) return;
  // a rename's new name counts only when what it renames is on the env drive, so a file named GIT_CONFIG.md stays open.
  // A copy is refused either way, since PowerShell binds its parameters by name, position and abbreviation in ways a
  // guess at the destination misreads
  const onEnv = args.some((a) => PS_ENV_ITEM.test(a));
  if (args.some((a) => PS_ENV_PATH.test(a) || (onEnv && PS_NEW_NAME.test(a)))) deny(GIT_CONFIG_WHY, whole);
}

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
    timeout: 20000,
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
  const first = (rest[0] || '').toLowerCase();
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
    const mutating = lower.some((a) => /^(-x|-f|--method|--field|--raw-field|--input)(=.*)?$/.test(a));
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
  const urls  = [];
  const value = (opt, v) => {
    if (CURL_AT_READS.has(opt) && v.startsWith('@')) refuse('A curl value that starts with @ reads a file.');
    if (opt === 'data-urlencode' && /^[^=]*@/.test(v)) refuse('curl --data-urlencode name@file reads a file.');
    if (opt === 'url') urls.push(v);
  };
  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a.startsWith('--')) {
      const name = a.slice(2);
      if (CURL_LONG_FLAGS.has(name)) continue;
      if (!CURL_LONG_VALUES.has(name)) refuse('curl ' + a + ' is refused, see the reviewer\'s curl options in the guard.');
      value(name, args[++i] || '');
    } else if (a.length > 1 && a.startsWith('-')) {
      for (let k = 1; k < a.length; k++) {
        if (CURL_SHORT_FLAGS.has(a[k])) continue;
        if (!CURL_SHORT_VALUES.has(a[k])) refuse('curl -' + a[k] + ' is refused, see the reviewer\'s curl options in the guard.');
        value(a[k], k + 1 < a.length ? a.slice(k + 1) : args[++i] || '');
        break;
      }
    } else {
      urls.push(a);
    }
  }
  for (const u of urls) {
    const m = LOCAL_URL.exec(u);
    if (!m) refuse('curl reaches this machine alone, http or https to localhost, 127.0.0.1 or [::1], and ' + u + ' is not that.');
    if (m[1] && CONTROL_PORTS.has(m[1])) refuse('Port ' + m[1] + ' is the Docker Engine or Caddy admin API, which changes the stack.');
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
