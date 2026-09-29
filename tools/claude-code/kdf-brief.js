#!/usr/bin/env node
'use strict';
/*
 * kdf-brief.js, the facts a review brief states, measured at the pin instead of remembered. Read only.
 *
 *   node kdf-brief.js facts  --repo <root> --pin <commit> [--base <branch>]
 *        the pin, the branch that holds it and the tip of main it sits on, for the brief's "The commit" line
 *   node kdf-brief.js counts --repo <root> --pin <commit> [<label>=]<path or glob> ...
 *        one scope table row per argument, every file it names at the pin with its line count
 *   node kdf-brief.js check  --repo <root> --pin <commit> <brief>
 *        checks every row of the brief's "| Files | Lines |" table against the pin
 *
 * A line count is the number of lines as an editor numbers them, so a last line without a newline counts. A table row
 * holds its paths in backticks and its counts in the same order, "| `a.py`, `b.py` | 120, 1,203 |", or one count for
 * all of them. A path may be a directory, whose files are summed. A row with a line range or a placeholder is skipped.
 *
 * Exit codes. 0 done, or every checked row matches. 1 a count differs or a path is missing at the pin. 2 bad arguments.
 */
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

const argv = process.argv.slice(2);
const command = argv[0];

function fail(code, message) {
  process.stderr.write('kdf-brief: ' + message + '\n');
  process.exit(code);
}

function option(name) {
  const k = argv.indexOf(name);
  if (k < 0) return undefined;
  if (k + 1 >= argv.length) fail(2, name + ' needs a value');
  return argv[k + 1];
}

function positionals() {
  const out = [];
  for (let i = 1; i < argv.length; i++) {
    if (['--repo', '--pin', '--base'].includes(argv[i])) i++;
    else out.push(argv[i]);
  }
  return out;
}

function git(repo, args, input) {
  return execFileSync('git', ['-C', repo].concat(args), {
    input,
    maxBuffer: 1 << 30,
    stdio: ['pipe', 'pipe', 'pipe'],
    windowsHide: true
  });
}

function gitText(repo, args) {
  return git(repo, args).toString('utf8').trim();
}

if (!['facts', 'counts', 'check'].includes(command)) {
  fail(2, 'say facts, counts or check. See the head of ' + path.basename(__filename) + '.');
}
const repo = path.resolve(option('--repo') || '.');
const pinName = option('--pin');
if (!pinName) fail(2, '--pin is required');
let pin;
try {
  pin = gitText(repo, ['rev-parse', '--verify', '--quiet', pinName + '^{commit}']);
} catch (err) {
  fail(2, '--pin ' + pinName + ' is not a commit in ' + repo);
}

// ------------------------------------------------------------ files and line counts at the pin

let treeFiles = null;
function filesAtPin() {
  if (!treeFiles) treeFiles = gitText(repo, ['ls-tree', '-r', '--name-only', '-z', pin]).split('\0').filter(Boolean);
  return treeFiles;
}

function globToRegExp(glob) {
  let re = '';
  for (let i = 0; i < glob.length; i++) {
    const c = glob[i];
    if (c === '*' && glob[i + 1] === '*') {
      re += glob[i + 2] === '/' ? '(?:.*/)?' : '.*';
      i += glob[i + 2] === '/' ? 2 : 1;
    } else if (c === '*') re += '[^/]*';
    else if (c === '?') re += '[^/]';
    else re += c.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  }
  return new RegExp('^' + re + '$');
}

// The files a path names at the pin, the file itself, or every file under a directory, or every match of a glob.
function expand(spec) {
  const clean = spec.replace(/\\/g, '/').replace(/^\.\//, '').replace(/\/+$/, '');
  if (/[*?]/.test(clean)) {
    const re = globToRegExp(clean);
    return filesAtPin().filter((f) => re.test(f));
  }
  return filesAtPin().filter((f) => f === clean || f.startsWith(clean + '/'));
}

function lineCount(buf) {
  let n = 0;
  for (let i = 0; i < buf.length; i++) if (buf[i] === 0x0a) n++;
  if (buf.length && buf[buf.length - 1] !== 0x0a) n++;
  return n;
}

// Every file's line count at the pin, read in one git process.
function countLines(files) {
  const out = git(repo, ['cat-file', '--batch'], files.map((f) => pin + ':' + f).join('\n') + '\n');
  const counts = new Map();
  let pos = 0;
  for (const f of files) {
    const nl = out.indexOf(0x0a, pos);
    const header = out.slice(pos, nl).toString('utf8');
    pos = nl + 1;
    const m = /^\S+ \S+ (\d+)$/.exec(header);
    if (!m) continue;
    const size = Number(m[1]);
    counts.set(f, lineCount(out.slice(pos, pos + size)));
    pos += size + 1;
  }
  return counts;
}

const format = (n) => n.toLocaleString('en-US');

// ------------------------------------------------------------ facts

if (command === 'facts') {
  const base = option('--base') || 'main';
  let branch = '';
  try {
    if (gitText(repo, ['rev-parse', 'HEAD']) === pin) branch = gitText(repo, ['symbolic-ref', '-q', '--short', 'HEAD']);
  } catch (err) {
    branch = '';
  }
  if (!branch) {
    const held = gitText(repo, ['for-each-ref', '--contains', pin, '--format=%(refname:short)', 'refs/remotes/origin'])
      .split('\n').filter((b) => b && !/^origin(\/HEAD)?$/.test(b));
    branch = (held[0] || '').replace(/^origin\//, '');
  }
  let tip = '';
  try {
    tip = gitText(repo, ['merge-base', pin, 'origin/' + base]);
  } catch (err) {
    fail(2, 'origin/' + base + ' is unknown here. Fetch it first.');
  }
  process.stdout.write('pin     ' + pin + '\nbranch  ' + (branch || '(none, push the pin first)') + '\nbase    ' + tip + '\n');
  process.stdout.write('line    The pin is `' + pin.slice(0, 10) + '` on branch `' + (branch || '?') + '`, which sits on `'
    + base + '` at `' + tip.slice(0, 10) + '`.\n');
  process.exit(0);
}

// ------------------------------------------------------------ counts

if (command === 'counts') {
  const specs = positionals();
  if (!specs.length) fail(2, 'name at least one path or glob');
  const rows = [];
  const every = [];
  for (const arg of specs) {
    const eq = arg.indexOf('=');
    const label = eq > 0 && !/[/*?]/.test(arg.slice(0, eq)) ? arg.slice(0, eq) : '';
    const spec = label ? arg.slice(eq + 1) : arg;
    const files = expand(spec);
    if (!files.length) fail(1, spec + ' names no file at the pin ' + pin.slice(0, 10));
    rows.push({ label, files });
    every.push(...files);
  }
  const counts = countLines(every);
  let total = 0;
  for (const { label, files } of rows) {
    const names = files.map((f) => '`' + f + '`').join(', ');
    const numbers = files.map((f) => format(counts.get(f))).join(', ');
    files.forEach((f) => (total += counts.get(f)));
    process.stdout.write('| ' + (label ? label + ', ' : '') + names + ' | ' + numbers + ' |\n');
  }
  process.stderr.write('kdf-brief: ' + format(every.length) + ' files, ' + format(total) + ' lines at ' + pin.slice(0, 10) + '\n');
  process.exit(0);
}

// ------------------------------------------------------------ check

const briefArg = positionals()[0];
if (!briefArg) fail(2, 'name the brief to check');
const briefRel = path.relative(repo, path.resolve(repo, briefArg)).replace(/\\/g, '/');
let text;
try {
  text = git(repo, ['show', pin + ':' + briefRel]).toString('utf8');
} catch (err) {
  try {
    text = fs.readFileSync(path.resolve(repo, briefArg), 'utf8');
  } catch (err2) {
    fail(2, 'the brief ' + briefArg + ' is neither in the pin nor on disk');
  }
}

const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
const rows = [];
let inTable = false;
for (const line of text.split(/\r?\n/)) {
  if (!line.trim().startsWith('|')) {
    inTable = false;
    continue;
  }
  const c = cells(line);
  if (c.length >= 2 && c[0].toLowerCase() === 'files' && c[1].toLowerCase() === 'lines') {
    inTable = true;
    continue;
  }
  if (inTable && !/^-+$/.test(c[0].replace(/[:\s]/g, ''))) rows.push(c);
}
if (!rows.length) {
  process.stdout.write('kdf-brief: no "| Files | Lines |" table in ' + briefRel + ', nothing to check\n');
  process.exit(0);
}

const planned = [];
for (const c of rows) {
  const paths = [...c[0].matchAll(/`([^`]+)`/g)].map((m) => m[1]);
  const pieces = (c[1] || '').split(/,\s+/).map((s) => s.trim()).filter(Boolean);
  if (!paths.length || paths.some((p) => /[{}]|:\d|#L\d/.test(p)) || pieces.some((s) => !/^\d{1,3}(,\d{3})*$|^\d+$/.test(s))) {
    process.stdout.write('skip  ' + c[0] + ', not a row of paths and counts\n');
    continue;
  }
  planned.push({ paths, numbers: pieces.map((s) => Number(s.replace(/,/g, ''))), files: paths.map(expand) });
}
const counts = countLines([...new Set(planned.flatMap((r) => r.files.flat()))]);
const sum = (files) => files.reduce((n, f) => n + counts.get(f), 0);
let bad = 0;
for (const { paths, numbers, files } of planned) {
  const missing = paths.filter((p, k) => !files[k].length);
  if (missing.length) {
    bad++;
    process.stdout.write('MISSING at the pin, ' + missing.join(', ') + '\n');
    continue;
  }
  let pairs;
  if (numbers.length === paths.length) pairs = paths.map((p, k) => [p, numbers[k], sum(files[k])]);
  else if (numbers.length === 1) pairs = [[paths.join(', '), numbers[0], sum(files.flat())]];
  else {
    process.stdout.write('skip  ' + paths.join(', ') + ', ' + numbers.length + ' counts for ' + paths.length + ' paths\n');
    continue;
  }
  for (const [what, said, real] of pairs) {
    if (said === real) process.stdout.write('ok    ' + what + ', ' + format(real) + '\n');
    else {
      bad++;
      process.stdout.write('DIFFERS ' + what + ', the brief says ' + format(said) + ', the pin has ' + format(real) + '\n');
    }
  }
}
process.stdout.write(bad ? 'kdf-brief: ' + bad + ' count(s) or path(s) do not match ' + pin.slice(0, 10) + '\n' : 'kdf-brief: the scope table matches ' + pin.slice(0, 10) + '\n');
process.exit(bad ? 1 : 0);
