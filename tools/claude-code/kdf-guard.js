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
 * to main. A push names its branch and goes to origin, and force, delete, tag and mirror pushes are refused.
 * Guardrails are the owner's to change, so a session cannot edit its own settings, hooks, MCP list or git hooks.
 * Git settings that run commands or change where code goes are refused.
 *
 * Reviewer rules, on top of those. Read only git, no GitHub CLI, no shell command that writes, installs or
 * downloads, no redirect into a file, no secret file, no connector, artifact, message, schedule or notification
 * tool, and file edits only under docs/security.
 *
 * A permission deny rule matches one tool and one spelling. This guard reads the command the way a shell does,
 * so it also catches the PowerShell tool, git -C, a nested shell, an env prefix and find -exec, and it ignores
 * quoted text such as a commit message. Exit 0 allows the call. Exit 2 blocks it and stderr tells the model why.
 * A crash exits 1, which Claude Code treats as a non blocking error, so a bug here never stalls a session and the
 * permission deny rules stay as the first fence. To switch it off, remove the hook from the settings file.
 *
 * Environment. KDF_ROLE=reviewer picks the reviewer rules. KDF_GUARD_ALLOW_SELF_EDIT=1, set by the owner when the
 * session is started, lets that session edit guardrail files. KDF_GUARD_LOG=<file> appends one line per refusal.
 */
const fs = require('fs');
const path = require('path');

const ROLE = String(process.argv[2] || process.env.KDF_ROLE || '').toLowerCase();
const MODE = ROLE === 'reviewer' ? 'reviewer' : 'orchestrator';
const SELF_EDIT_OK = process.env.KDF_GUARD_ALLOW_SELF_EDIT === '1';
const MAX_DEPTH = 5;
const FILE_TOOLS = /^(Edit|Write|MultiEdit|NotebookEdit)$/;
// Tools that reach outside the repo. A reviewer uses none of them. The IDE diagnostics tool stays allowed.
const OUTWARD_TOOLS = /^(mcp__(?!ide__)|Artifact|SendUserFile$|SendMessage$|PushNotification$|RemoteTrigger$|Cron|DesignSync$|EnterWorktree$|Workflow$)/;
const WRAPPERS = new Set(['env', 'command', 'sudo', 'nohup', 'time', 'exec', 'builtin', 'nice', 'timeout', 'xargs']);
// Wrapper options that take a value, so the value is not mistaken for the program that follows.
const WRAPPER_VALUE_OPTS = {
  env: /^(-u|--unset|-C|--chdir|-S|--split-string)$/,
  sudo: /^(-u|-g|-h|-p|-C|-D|-R|-T|-U)$/,
  nice: /^-n$/,
  timeout: /^(-s|-k|--signal|--kill-after)$/,
  xargs: /^(-I|-n|-P|-d|-E|-L|-s|-a)$/
};

// Files that hold the guardrails. A session never edits them, the owner does.
const PROTECTED = [
  /(^|\/)\.claude\/(settings(\.local)?\.json|hooks(\/|$))/,
  /(^|\/)\.claude\.json$/,
  /(^|\/)\.mcp\.json$/,
  /(^|\/)\.git\/(hooks(\/|$)|config$)/
];
// Files that hold secrets. .env.example is not one of them.
const SECRET_FILE = /(^|[\\/])\.env(\.(local|test|github|prod\w*|development))?$|\.tfvars$|\.pem$|(^|[\\/])keys[\\/]/i;
// Programs that only read, so naming a protected file to them is fine.
const READ_ONLY_PROGRAMS = new Set([
  'cat', 'less', 'more', 'head', 'tail', 'grep', 'egrep', 'fgrep', 'rg', 'ls', 'dir', 'wc', 'diff', 'cmp', 'stat',
  'file', 'tree', 'du', 'type', 'realpath', 'readlink', 'basename', 'dirname', 'test', '[', 'echo', 'printf'
]);
const GIT_READ = new Set(['status', 'diff', 'log', 'show', 'blame', 'ls-files', 'check-ignore', 'cat-file', 'rev-parse', 'ls-tree', 'grep']);

let PROJECT = process.cwd();

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
process.stdin.on('end', () => {
  try {
    run(JSON.parse(raw));
  } catch (err) {
    process.stderr.write('kdf-guard error, call allowed. ' + err.message + '\n');
    process.exit(1);
  }
  process.exit(0);
});

function run(input) {
  PROJECT = path.resolve(process.env.CLAUDE_PROJECT_DIR || input.cwd || process.cwd());
  const tool = input.tool_name || '';
  const args = input.tool_input || {};
  if (tool === 'Bash' || tool === 'PowerShell') {
    check(String(args.command || ''), 0);
  } else if (FILE_TOOLS.test(tool)) {
    checkFileTool(String(args.file_path || args.notebook_path || ''));
  } else if (MODE === 'reviewer' && tool === 'Read') {
    if (SECRET_FILE.test(String(args.file_path || ''))) deny('Secret files are the owner\'s, a review never needs their values.', tool);
  } else if (MODE === 'reviewer' && OUTWARD_TOOLS.test(tool)) {
    deny('Reviewers use no connector, artifact, message, schedule or notification tool. ' + tool + ' is refused.', tool);
  }
}

function norm(p) {
  return String(p).replace(/\\/g, '/').toLowerCase();
}

function isProtected(p) {
  const n = norm(p);
  return PROTECTED.some((r) => r.test(n));
}

function insideSecurityDir(p) {
  const fold = (s) => (process.platform === 'win32' ? s.toLowerCase() : s);
  const root = fold(path.join(PROJECT, 'docs', 'security') + path.sep);
  return fold(path.resolve(PROJECT, p) + path.sep).startsWith(root);
}

function checkFileTool(target) {
  if (!SELF_EDIT_OK && isProtected(target)) {
    deny('Guardrails are the owner\'s to change. Settings, hooks, the MCP list and git hooks are edited by hand.', target);
  }
  if (MODE === 'reviewer' && !insideSecurityDir(target)) {
    deny('Reviewers write only under docs/security. ' + target + ' is outside it.', target);
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
  const endTok = () => {
    if (has) cur.push({ t: tok, q: quoted });
    tok = '';
    has = false;
    quoted = false;
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
      has = true;
      quoted = true;
      for (i++; i < text.length && text[i] !== "'"; i++) tok += text[i];
      continue;
    }
    if (c === '"') {
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
  for (const seg of segments(cmd)) analyze(seg, depth, cmd);
}

function analyze(toks, depth, whole) {
  let i = 0;
  while (i < toks.length) {
    const t = toks[i];
    if (!t.q && /^[A-Za-z_][A-Za-z0-9_]*=/.test(t.t)) {
      i++;
      continue;
    }
    if (!t.q && t.t === '.') {
      i++;
      continue;
    }
    const b = base(t.t);
    if (!WRAPPERS.has(b)) break;
    i++;
    while (i < toks.length && /^-/.test(toks[i].t)) {
      const opt = toks[i].t;
      i++;
      if (WRAPPER_VALUE_OPTS[b] && WRAPPER_VALUE_OPTS[b].test(opt)) i++;
    }
    if (b === 'timeout' && i < toks.length && /^\d/.test(toks[i].t)) i++;
  }
  if (i >= toks.length) return;
  const prog = base(toks[i].t);
  const args = toks.slice(i + 1).map((x) => x.t);

  if (prog === 'find') {
    const k = toks.findIndex((x, idx) => idx > i && /^-(exec|execdir|ok|okdir)$/.test(x.t));
    if (k >= 0 && k + 1 < toks.length) analyze(toks.slice(k + 1), depth, whole);
  }
  checkProtectedInShell(toks, prog, args, whole);
  if (MODE === 'reviewer') checkRedirects(toks, whole);
  if (nestedShell(prog, args, depth)) return;
  if (prog === 'git') checkGit(args, whole);
  else if (prog === 'gh') checkGh(args, whole);
  else checkOther(prog, args, whole);
  if (MODE === 'reviewer') checkReviewerProgram(prog, args, whole);
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
    const k = args.findIndex((a) => /^\/[ck]$/i.test(a));
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

function checkProtectedInShell(toks, prog, args, whole) {
  if (SELF_EDIT_OK) return;
  const why = 'Guardrails are the owner\'s to change. Settings, hooks, the MCP list and git hooks are edited by hand.';
  for (let i = 0; i < toks.length; i++) {
    if (toks[i].q) continue;
    const m = /^(\d*)(>>?|&>>?)(.*)$/.exec(toks[i].t);
    if (!m) continue;
    const target = m[3] || (toks[i + 1] ? toks[i + 1].t : '');
    if (isProtected(target)) deny(why, whole);
  }
  let readOnly = READ_ONLY_PROGRAMS.has(prog);
  if (prog === 'git') readOnly = GIT_READ.has(gitSplit(args).sub);
  if (!readOnly && args.some((a) => isProtected(a))) deny(why, whole);
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

function checkGit(args, whole) {
  const { sub, rest } = gitSplit(args);
  if (MODE === 'reviewer') reviewerGit(sub, rest, whole);
  if (sub === 'push') checkPush(rest, whole);
  else if (sub === 'tag') checkTag(rest, whole);
  else if (sub === 'config') checkConfig(rest, whole);
  else if (sub === 'remote') checkRemote(rest, whole);
  else if (sub === 'update-ref') {
    deny('Moving a ref by hand can move main or a tag. Use a branch and a pull request.', whole);
  }
}

function checkPush(rest, whole) {
  const opts = rest.filter((a) => a.startsWith('-'));
  const pos = rest.filter((a) => !a.startsWith('-'));
  const long = /^--(force|force-with-lease|force-if-includes|delete|tags|mirror|all|prune|follow-tags|no-verify)(=.*)?$/;
  if (opts.some((a) => long.test(a) || /^-[a-zA-Z]*[fd][a-zA-Z]*$/.test(a))) {
    deny('Force, delete, tag, mirror and no-verify pushes are refused. Push the branch plainly.', whole);
  }
  if (pos.length < 2) {
    deny('Name the branch, git push -u origin <branch>. A bare push, or one with no branch, is refused.', whole);
  }
  if (!/^(origin|upstream)$/i.test(pos[0])) {
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

// A git setting can run a command, hide a refused one behind an alias, or send code somewhere else.
function checkConfig(rest, whole) {
  if (rest.some((a) => /^(--get|--get-all|--get-regexp|--list|-l|--show-origin|--show-scope|--name-only)$/.test(a))) return;
  const key = rest.find((a) => !a.startsWith('-')) || '';
  if (/^(alias\.|core\.(hookspath|sshcommand|fsmonitor|editor|pager|askpass)|credential\.|url\.|include|filter\.|diff\.external|gpg\.|http\.|remote\..*\.(url|pushurl))/i.test(key)) {
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
  if (group === 'secret' || group === 'variable') deny('Actions secrets and variables are the owner\'s.', whole);
  if (group === 'gist') deny('A gist publishes text outside the repo. Only the owner does that.', whole);
  if (group === 'repo' && ['delete', 'edit', 'archive', 'rename', 'create'].includes(verb)) {
    deny('Repository settings and lifecycle are the owner\'s.', whole);
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

function checkOther(prog, args, whole) {
  const words = args.filter((a) => !a.startsWith('-')).map((a) => a.toLowerCase());
  if (prog === 'terraform' || prog === 'tofu') {
    if (words.some((w) => ['apply', 'destroy', 'import', 'taint', 'untaint', 'force-unlock'].includes(w))
      || (words.includes('state') && words.some((w) => ['rm', 'mv', 'push', 'replace-provider'].includes(w)))) {
      deny('Only the owner runs terraform apply, destroy or a state change.', whole);
    }
  } else if (prog === 'vercel') {
    deny('Deploys are the owner\'s.', whole);
  } else if (prog === 'docker' || prog === 'docker-compose') {
    if (words.includes('push')) deny('docker push publishes an image. Only the owner does that.', whole);
  } else if (['npm', 'pnpm', 'yarn', 'bun'].includes(prog)) {
    if (words.includes('publish')) deny('Publishing a package is the owner\'s.', whole);
  } else if (['npx', 'pnpx', 'bunx'].includes(prog) || (prog === 'pnpm' && words.includes('dlx'))) {
    if (words.some((w) => /^(vercel|firebase-tools|netlify-cli)/.test(w))) deny('Deploys are the owner\'s.', whole);
  } else if (prog === 'twine' && words.includes('upload')) {
    deny('Publishing a package is the owner\'s.', whole);
  } else if (prog === 'gcloud' && words.includes('deploy')) {
    deny('Deploys are the owner\'s.', whole);
  }
  if (words.includes('twine') && words.includes('upload')) deny('Publishing a package is the owner\'s.', whole);
}

// ------------------------------------------------------------ reviewer only

const READER_DENIED = new Set([
  'rm', 'rmdir', 'del', 'erase', 'rd', 'ri', 'remove-item', 'mv', 'move', 'move-item', 'mi', 'cp', 'copy', 'copy-item',
  'cpi', 'ren', 'rename', 'rename-item', 'rni', 'mkdir', 'md', 'new-item', 'ni', 'touch', 'chmod', 'chown', 'tee',
  'tee-object', 'dd', 'truncate', 'set-content', 'sc', 'add-content', 'ac', 'clear-content', 'clc', 'out-file',
  'set-item', 'set-itemproperty', 'curl', 'wget', 'iwr', 'irm', 'invoke-webrequest', 'invoke-restmethod', 'scp',
  'ssh', 'sftp', 'ftp', 'start-process', 'saps', 'stop-process', 'kill', 'taskkill', 'expand-archive',
  'compress-archive', 'tar', 'zip', 'unzip', '7z', 'robocopy', 'xcopy', 'attrib', 'icacls', 'takeown', 'setx', 'reg',
  'docker', 'docker-compose', 'kubectl'
]);
const INSTALLERS = new Set(['install', 'uninstall', 'download', 'wheel', 'add', 'remove', 'sync', 'lock']);
const NODE_WRITERS = new Set(['install', 'i', 'add', 'remove', 'uninstall', 'update', 'upgrade', 'ci', 'publish', 'link', 'unlink', 'dedupe', 'prune']);
const MAKE_WRITERS = /^(setup|clean.*|bump.*|docker.*|compile.*|release.*|publish.*|install.*|deploy.*)$/;

function checkReviewerProgram(prog, args, whole) {
  const a = args.map((x) => x.toLowerCase());
  const refuse = () => deny('Reviewers only read and write their report. ' + prog + ' is refused.', whole);
  if (args.some((x) => SECRET_FILE.test(x))) deny('Secret files are the owner\'s, a review never needs their values.', whole);
  if (READER_DENIED.has(prog)) refuse();
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
    if (!harmless && !insideSecurityDir(target)) {
      deny('Reviewers may not redirect output into a file. Write the report with the file tools under docs/security.', whole);
    }
  }
}
