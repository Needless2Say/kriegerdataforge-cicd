#!/usr/bin/env node
'use strict';
/*
 * kdf-brief.js, the facts a review brief states, measured at the pin instead of remembered. Read only.
 *
 *   node kdf-brief.js facts  --repo <root> --pin <commit> [--base <branch>]
 *        the slice's state commit, the branch that holds it and the tip of main it sits on, for the brief's "The
 *        commit" line. Run it on the state, before the brief's own commit, which becomes the pin. No commit holds its
 *        own hash, so the brief names the state and says the pin is the commit that adds the brief on top of it
 *   node kdf-brief.js counts --repo <root> --pin <commit> [<label>=]<path or glob> ...
 *        one scope table row per argument, every file it names at the pin with its line count
 *   node kdf-brief.js check  --repo <root> --pin <commit> [--disk] <brief>
 *        checks every row of the brief's "| Files | Lines |" table against the pin, and every commit hash the brief
 *        names, a run of 7 to 40 lowercase hex characters in a backticked span or a fenced block and joined to no
 *        letter, digit, dash or underscore, against the repo and the git clones beside it. It refuses a hash in the
 *        "**The commit.**" paragraph that names no commit, a hash git calls ambiguous anywhere, and a brief with a
 *        scope table and no commit paragraph, and warns of a hash outside the paragraph that names no commit, a
 *        digest, a value or a sibling not yet pulled. A run of digits alone that names no commit is a
 *        number. The brief is read at the pin, or from disk when the pin lacks it, and --disk reads it from
 *        disk alone, so whoever places a brief checks the file it is about to commit, never an older one at the pin
 *   node kdf-brief.js cites  --repo <root> --pin <commit> [--since <commit>] [--only <path or glob>]... [<doc>...]
 *        every `file:line` cite of the docs named, or of every living doc, beside the lines it names at the pin, for
 *        the orchestrator to read by eye. A living doc is a tracked Markdown file outside docs/reviews/, a dated record
 *        folder and a changelog or log, which keep the lines of their own day. A cite is a backticked path, a colon and
 *        lines, `src/a.py:12`, `a.py:12-20` or `a.py:12, 40-41`, whose path names a tracked file, holds a slash or has
 *        an extension and names no host, so `localhost:5432` is not one and `Makefile:12` is. A code span may cross a
 *        line break, as Markdown's do, a quote's markers are read off, and a fenced code block holds no cite.
 *        A dated record is one under docs/<kind>/<YYYY-MM-DD>-<slug>/. Its path resolves against the
 *        whole repo, the exact path or else the one file whose path ends with it, never by --only or --since, which
 *        filter afterwards. --only keeps the cites into the files it names, --since the cites into a file changed
 *        since that commit and every cite of a doc changed since it. A path no file matches, more than one file
 *        matching, a line past the end and a range that runs backwards are flagged. Another repository's path and a
 *        line named with no file are listed apart for a hand read and flag nothing
 *
 * A line count is the number of lines as an editor numbers them, so a last line without a newline counts. A table row
 * holds its paths in backticks and its counts in the same order, "| `a.py`, `b.py` | 120, 1,203 |", or one count for
 * all of them. A path may be a directory, whose files are summed. A row with a line range or a placeholder is skipped.
 *
 * Exit codes. 0 done, or every checked row matches and every hash resolves, or no cite is flagged. 1 a count differs,
 * a path is missing at the pin, a hash does not resolve or a cite is flagged. 2 bad arguments.
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

// every value of an option that may be given more than once
function options(name) {
  const out = [];
  for (let i = 1; i < argv.length; i++) {
    if (argv[i] !== name) continue;
    if (i + 1 >= argv.length) fail(2, name + ' needs a value');
    out.push(argv[++i]);
  }
  return out;
}

function positionals() {
  const out = [];
  for (let i = 1; i < argv.length; i++) {
    if (['--repo', '--pin', '--base', '--since', '--only'].includes(argv[i])) i++;
    else if (argv[i] !== '--disk') out.push(argv[i]);
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

if (!['facts', 'counts', 'check', 'cites'].includes(command)) {
  fail(2, 'say facts, counts, check or cites. See the head of ' + path.basename(__filename) + '.');
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
  // nosemgrep: detect-non-literal-regexp a brief's glob with every other pattern character escaped above
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
  process.stdout.write('state   ' + pin + '\nbranch  ' + (branch || '(none, push the state first)') + '\nbase    ' + tip
    + '\n');
  process.stdout.write('line    The pin is the commit that adds this brief and nothing else, on top of the slice\'s state `'
    + pin.slice(0, 10) + '`, on branch `' + (branch || '?') + '`, which sits on `' + base + '` at `' + tip.slice(0, 10)
    + '`.\n');
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

// ------------------------------------------------------------ cites

// Every named file's text at the pin, read in one git process, its lines as an editor numbers them.
function linesAtPin(files) {
  const out = git(repo, ['cat-file', '--batch'], files.map((f) => pin + ':' + f).join('\n') + '\n');
  const texts = new Map();
  let pos = 0;
  for (const f of files) {
    const nl = out.indexOf(0x0a, pos);
    const m = /^\S+ \S+ (\d+)$/.exec(out.slice(pos, nl).toString('utf8'));
    pos = nl + 1;
    if (!m) continue;
    const size = Number(m[1]);
    const lines = out.slice(pos, pos + size).toString('utf8').split(/\r?\n/);
    if (lines.length && lines[lines.length - 1] === '') lines.pop();
    texts.set(f, lines);
    pos += size + 1;
  }
  return texts;
}

// A doc's blocks, where a code span can live, each with the number of its first line. A quote's markers are read off
// first, so a quoted paragraph is one block and a quoted fence a fence, which ends with its quote. An unmarked line
// after a quoted paragraph continues it, as Markdown's lazy continuation does. Otherwise a blank line, a change in how
// deep the quote is, a heading, a table row and a list item's first line each start a block, and a fenced code block
// is left out, so a span pairs its backticks across a line break, as Markdown does, but never across a block.
function blocksOf(lines) {
  const STARTS = /^\s*(#|\||[-*+]\s|\d+[.)]\s|`{3,}|~{3,})/;
  const blocks = [];
  let current = null;
  let fence = '';
  let fenceLevel = 0;
  let depth = 0;
  lines.forEach((raw, k) => {
    const quote = /^\s*((?:>\s?)*)/.exec(raw)[1];
    const line = raw.slice(raw.indexOf(quote) + quote.length);
    const level = (quote.match(/>/g) || []).length;
    const opens = /^\s*(`{3,}|~{3,})/.exec(line);
    if (fence && level >= fenceLevel) {
      if (opens && opens[1][0] === fence[0] && opens[1].length >= fence.length) fence = '';
      return;
    }
    fence = '';
    if (current && depth > 0 && level === 0 && line.trim() && !STARTS.test(line)) {
      current.lines.push(line);
      return;
    }
    if (opens || !line.trim() || level !== depth) current = null;
    depth = level;
    if (opens) {
      fence = opens[1];
      fenceLevel = level;
      return;
    }
    if (!line.trim()) return;
    if (!current || STARTS.test(line)) {
      current = { first: k + 1, lines: [] };
      blocks.push(current);
    }
    current.lines.push(line);
    if (/^\s*(#|\|)/.test(line)) current = null;
  });
  return blocks;
}

// A doc that keeps the lines of its own day, a review's record, a dated record under docs/<kind>/, a changelog or a
// log.
function isHistory(file) {
  const name = file.split('/').pop();
  return file.startsWith('docs/reviews/') || /^docs\/[^/]+\/\d{4}-\d{2}-\d{2}-[^/]+\//.test(file)
    || /changelog/i.test(name) || /(^|_)log\.md$/i.test(name);
}

if (command === 'cites') {
  const tracked = filesAtPin();
  const trackedSet = new Set(tracked);
  const topLevel = new Set(tracked.map((f) => f.split('/')[0]));
  const named = positionals().map((d) => path.relative(repo, path.resolve(repo, d)).replace(/\\/g, '/'));
  for (const d of named) {
    if (!trackedSet.has(d)) fail(2, 'the doc ' + d + ' is not tracked at the pin ' + pin.slice(0, 10));
  }
  const docs = named.length ? named : tracked.filter((f) => /\.md$/i.test(f) && !isHistory(f));

  const onlySpecs = options('--only');
  const only = new Set(onlySpecs.flatMap(expand));
  if (onlySpecs.length && !only.size) fail(2, '--only names no file at the pin ' + pin.slice(0, 10));
  const sinceName = option('--since');
  let changed = null;
  if (sinceName) {
    let since;
    try {
      since = gitText(repo, ['rev-parse', '--verify', '--quiet', sinceName + '^{commit}']);
    } catch (err) {
      fail(2, '--since ' + sinceName + ' is not a commit in ' + repo);
    }
    const diff = git(repo, ['diff', '--name-only', '-z', since, pin]).toString('utf8');
    changed = new Set(diff.split('\0').filter(Boolean));
  }

  // A path resolves against the whole repo, never against a filter, the exact path or the files whose path ends with
  // it. A span is a cite when its path names a tracked file, holds a slash, or is a name with an extension, a dot and
  // a letter then letters or digits, unless the name is a host, `localhost`, an address or a name under a common top
  // level domain, so `localhost:5432` and `api.example.com:443` are not cites, and `Makefile:12` and `gone.dart:3` are.
  const CITE = /^(?:\.\/)?([\w.\/-]+):(\d+(?:-\d+)?(?:,\s*\d+(?:-\d+)?)*)$/;
  const EXTENSION = /\.[A-Za-z][A-Za-z0-9]*$/;
  const HOST = new RegExp('^(localhost|\\d+(\\.\\d+){3}|[\\w-]+(\\.[\\w-]+)*'
    + '\\.(com|org|net|io|dev|app|ai|co|us|uk|eu|de|local|internal|test|example|invalid|cloud))$', 'i');
  const isCite = (cited, files) => files.length > 0 || cited.includes('/')
    || (EXTENSION.test(cited) && !HOST.test(cited));
  const resolve = (cited) => (trackedSet.has(cited) ? [cited] : tracked.filter((f) => f.endsWith('/' + cited)));
  const found = [];
  const elsewhere = [];
  const noFile = [];
  const docText = linesAtPin(docs);
  for (const doc of docs) {
    for (const block of blocksOf(docText.get(doc) || [])) {
      const text = block.lines.join('\n');
      const lineAt = (offset) => block.first + text.slice(0, offset).split('\n').length - 1;
      // a code span is a run of backticks, its text, and a run of the same length, and may cross a line break
      const SPAN = /(?<!`)(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g;
      for (const span of text.matchAll(SPAN)) {
        const inner = span[2].replace(/\s+/g, ' ').trim();
        const at = lineAt(span.index);
        const m = CITE.exec(inner);
        const files = m ? resolve(m[1]) : [];
        if (m && isCite(m[1], files)) {
          const before = text.slice(Math.max(0, span.index - 60), span.index).replace(/\s+/g, ' ').trim();
          found.push({ doc, at, before, cited: m[1], parts: m[2].replace(/\s/g, '').split(','), files });
        } else if (/^:\d+(-\d+)?$/.test(inner)) noFile.push(doc + ':' + at + '  `' + inner + '`');
      }
      const prose = text.replace(SPAN, (whole) => whole.replace(/[^\n]/g, ' '));
      for (const named of prose.matchAll(/\blines? \d+(?:-\d+)?\b/gi)) {
        noFile.push(doc + ':' + lineAt(named.index) + '  "' + named[0] + '"');
      }
    }
  }
  const keep = (c) => {
    if (onlySpecs.length && !c.files.some((f) => only.has(f))) return false;
    if (changed && !changed.has(c.doc) && !c.files.some((f) => changed.has(f))) return false;
    return true;
  };
  const shown = [];
  for (const c of found) {
    if (!c.files.length && c.cited.includes('/') && !topLevel.has(c.cited.split('/')[0])) {
      elsewhere.push(c.doc + ':' + c.at + '  ' + c.cited + ':' + c.parts.join(','));
    } else if (!c.files.length || keep(c)) shown.push(c);
  }

  const sources = linesAtPin([...new Set(shown.flatMap((c) => c.files))]);
  const clip = (s, n) => (s.length > n ? s.slice(0, n - 1) + '…' : s);
  const say = (s) => process.stdout.write(s + '\n');
  const quoteLine = (lines, n) => '         ' + String(n).padStart(5) + ' | ' + clip(lines[n - 1].trim(), 100);
  let flagged = 0;
  let lastDoc = '';
  for (const c of shown) {
    if (c.doc !== lastDoc) process.stdout.write('#### ' + c.doc + '\n');
    lastDoc = c.doc;
    const where = String(c.at).padStart(5) + '  ';
    if (!c.files.length) {
      flagged++;
      process.stdout.write(where + 'MISSING ' + c.cited + ', no tracked file at the pin\n');
      continue;
    }
    let bad = c.files.length > 1;
    if (bad) {
      process.stdout.write(where + 'AMBIGUOUS ' + c.cited + ':' + c.parts.join(',') + ', ' + c.files.length
        + ' files, give the doc a longer path  ..' + clip(c.before, 60) + '\n');
    } else process.stdout.write(where + c.files[0] + ':' + c.parts.join(',') + '  ..' + clip(c.before, 60) + '\n');
    for (const file of c.files) {
      const lines = sources.get(file) || [];
      if (c.files.length > 1) process.stdout.write('         candidate ' + file + '\n');
      for (const part of c.parts) {
        const [first, last] = part.split('-').map(Number);
        const end = last === undefined ? first : last;
        if (end < first) {
          bad = true;
          say('         BACKWARDS ' + part);
        } else if (first < 1) {
          bad = true;
          say('         NO LINE 0 ' + part + ', a file\'s first line is 1');
        } else if (end > lines.length) {
          bad = true;
          say('         PAST THE END ' + part + ', ' + file + ' has ' + format(lines.length) + ' lines');
        } else {
          say(quoteLine(lines, first));
          if (end !== first) say(quoteLine(lines, end));
        }
      }
    }
    if (bad) flagged++;
  }
  const list = (title, rows) => {
    if (rows.length) say('#### ' + title + ', read by hand\n' + rows.map((s) => '       ' + s).join('\n'));
  };
  list('another repository\'s', elsewhere);
  list('a line named with no file', noFile);
  process.stdout.write('kdf-brief: ' + format(shown.length) + ' cites listed from ' + format(docs.length) + ' docs at '
    + pin.slice(0, 10) + ', ' + format(flagged) + ' flagged, ' + format(elsewhere.length) + ' of another repository, '
    + format(noFile.length) + ' with no file\n');
  process.exit(flagged ? 1 : 0);
}

// ------------------------------------------------------------ check

const briefArg = positionals()[0];
if (!briefArg) fail(2, 'name the brief to check');
const briefRel = path.relative(repo, path.resolve(repo, briefArg)).replace(/\\/g, '/');
// --disk reads the brief from disk alone, as whoever places a brief checks it before its commit, a brief at the pin
// being an older one. Without it the pin's brief is read first, as the launcher reads it at the pin.
let text;
const fromDisk = () => {
  try {
    return fs.readFileSync(path.resolve(repo, briefArg), 'utf8');
  } catch (err) {
    const where = argv.includes('--disk') ? ' is not on disk' : ' is neither in the pin nor on disk';
    return fail(2, 'the brief ' + briefArg + where);
  }
};
if (argv.includes('--disk')) text = fromDisk();
else {
  try {
    text = git(repo, ['show', pin + ':' + briefRel]).toString('utf8');
  } catch (err) {
    text = fromDisk();
  }
}

const cells = (line) => line.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim());
const rows = [];
let inTable = false;
let scopeTable = false;
for (const line of text.split(/\r?\n/)) {
  if (!line.trim().startsWith('|')) {
    inTable = false;
    continue;
  }
  const c = cells(line);
  if (c.length >= 2 && c[0].toLowerCase() === 'files' && c[1].toLowerCase() === 'lines') {
    inTable = true;
    scopeTable = true;
    continue;
  }
  if (inTable && !/^-+$/.test(c[0].replace(/[:\s]/g, ''))) rows.push(c);
}

// Every commit hash the brief names is resolved, read before the table so a brief with no scope table is read too. A
// hash is a run of 7 to 40 lowercase hexadecimal characters, joined to no letter, digit, dash or underscore, inside a
// backticked span or on a line of a fenced block, the whole span or a run inside a command. One the repo resolves
// passes. One git calls ambiguous is refused. One the repo does not hold is looked up in each git clone beside the
// repo, a sibling's commit passing. One that resolves nowhere is refused in the commit paragraph, where the pin, the
// state and the tip are named, and warned of elsewhere, where a digest, a value or a sibling not yet pulled can stand.
// A run of digits alone that resolves nowhere is a number and passes.
// Markdown's rules, read the way CommonMark reads them. A blockquote's markers are read off a line first, so a quoted
// fence or span is read as an unquoted one. A fence opens with three or more backticks or tildes, a backtick fence's
// info text holding no backtick, and closes on a line of the same character, at least as many, and nothing else.
// Outside a fence a code span opens on a backtick run no backslash escapes and closes on the next run of the same
// length, a backslash inside the span being literal, and it may cross a line break, never a blank line. The commit
// paragraph is the paragraph whose first line starts with "**The commit.**", up to its blank line, a heading or a
// fence. A hex run joined to a letter, a digit, a dash or an underscore is part of a longer word, a run id or a name,
// and is not read as a hash.
const hashes = [];
const HEX = /(?<![0-9A-Za-z_-])[0-9a-f]{7,40}(?![0-9A-Za-z_-])/g;
const briefLines = text.split(/\r?\n/);
const unquote = (line) => line.replace(/^(\s{0,3}>\s?)+/, '');
let fence = null;
let prose = [];
let commitParagraph = false;
let commitFrom = 0;
let commitTo = 0;
let commitTwice = 0;
// every code span of a run of prose lines, its start and its text
function codeSpans(s) {
  const out = [];
  const blankAfter = (k) => /^[ \t]*(\n|$)/.test(s.slice(k + 1, k + 202));
  let i = 0;
  while (i < s.length) {
    if (s[i] !== '`') {
      i++;
      continue;
    }
    let slashes = 0;
    while (i - 1 - slashes >= 0 && s[i - 1 - slashes] === '\\') slashes++;
    if (slashes % 2 === 1) {
      // the escaped backtick is a character of the text, and the run's rest may open a span
      i++;
      continue;
    }
    let j = i;
    while (j < s.length && s[j] === '`') j++;
    const run = j - i;
    let k = j;
    let close = -1;
    while (k < s.length) {
      if (s[k] === '\n' && blankAfter(k)) break;
      if (s[k] === '`') {
        let m = k;
        while (m < s.length && s[m] === '`') m++;
        if (m - k === run) {
          close = k;
          break;
        }
        k = m;
        continue;
      }
      k++;
    }
    if (close < 0) {
      i = j;
      continue;
    }
    out.push({ start: j, text: s.slice(j, close) });
    i = close + run;
  }
  return out;
}
function readProse() {
  if (!prose.length) return;
  const joined = prose.map((p) => p.text).join('\n');
  const first = prose[0].line;
  for (const span of codeSpans(joined)) {
    const spanLine = first + (joined.slice(0, span.start).match(/\n/g) || []).length;
    for (const h of span.text.matchAll(HEX)) {
      hashes.push({ hash: h[0], line: spanLine + (span.text.slice(0, h.index).match(/\n/g) || []).length });
    }
  }
  prose = [];
}
briefLines.forEach((raw, k) => {
  const line = unquote(raw);
  if (fence) {
    const close = /^ {0,3}(`{3,}|~{3,})\s*$/.exec(line);
    if (close && close[1][0] === fence[0] && close[1].length >= fence.length) fence = null;
    else for (const h of line.matchAll(HEX)) hashes.push({ hash: h[0], line: k + 1 });
    return;
  }
  const open = /^ {0,3}(`{3,}|~{3,})(.*)$/.exec(line);
  const opens = open && !(open[1][0] === '`' && open[2].includes('`'));
  // the commit paragraph ends at its blank line, a heading or a fence
  if (commitFrom && !commitTo && (!line.trim() || /^\s*#/.test(line) || opens)) commitTo = k;
  if (opens) {
    readProse();
    fence = open[1];
    return;
  }
  if (/^\s*\*\*The commit\.\*\*/.test(line)) {
    // one commit paragraph names the pin, so a second is refused and never moves the first one's range
    if (commitParagraph) commitTwice = k + 1;
    else {
      commitParagraph = true;
      commitFrom = k + 1;
    }
  }
  prose.push({ text: line, line: k + 1 });
});
readProse();
const inCommitParagraph = (line) => commitFrom > 0 && line >= commitFrom && (!commitTo || line <= commitTo);
function resolveIn(where, hash) {
  try {
    git(where, ['rev-parse', '--verify', hash + '^{commit}']);
    return 'commit';
  } catch (err) {
    return /ambiguous/i.test(String(err.stderr || '')) ? 'ambiguous' : 'none';
  }
}
let siblings;
function siblingClones() {
  if (siblings) return siblings;
  const parent = path.dirname(repo);
  try {
    siblings = fs.readdirSync(parent).sort()
      .map((d) => path.join(parent, d))
      .filter((d) => d !== repo && fs.existsSync(path.join(d, '.git')));
  } catch (err) {
    process.stdout.write('kdf-brief: cannot list the clones beside the repo, ' + err.code + ', so a hash the repo does '
      + 'not hold names no commit\n');
    siblings = [];
  }
  return siblings;
}
let hashBad = 0;
let hashWarned = 0;
const seen = new Map();
for (const { hash, line } of hashes) {
  if (!seen.has(hash)) {
    let found = resolveIn(repo, hash);
    if (found === 'none') {
      // an ambiguous answer anywhere stands, a sibling's single commit never hides it
      const elsewhere = siblingClones().map((d) => resolveIn(d, hash));
      found = elsewhere.includes('ambiguous') ? 'ambiguous' : elsewhere.includes('commit') ? 'sibling' : 'none';
    }
    if (found === 'none' && /^[0-9]+$/.test(hash)) found = 'number';
    seen.set(hash, found);
  }
  const found = seen.get(hash);
  if (found === 'ambiguous') {
    hashBad++;
    process.stdout.write('AMBIGUOUS hash ' + hash + ' at line ' + line + ', git names more than one commit\n');
  } else if (found === 'none' && inCommitParagraph(line)) {
    hashBad++;
    process.stdout.write('NO COMMIT ' + hash + ' at line ' + line + ', in the commit paragraph, in the repo or a '
      + 'clone beside it\n');
  } else if (found === 'none') {
    hashWarned++;
    process.stdout.write('WARNING ' + hash + ' at line ' + line + ' names no commit in the repo or a clone beside '
      + 'it, a digest, a value or a sibling not yet pulled, or a slip to fix\n');
  }
}
if (scopeTable && !commitParagraph) {
  hashBad++;
  process.stdout.write('NO COMMIT PARAGRAPH, the brief has a scope table and no "**The commit.**" paragraph\n');
}
if (commitTwice) {
  hashBad++;
  process.stdout.write('A SECOND COMMIT PARAGRAPH at line ' + commitTwice + ', one names the pin, after line '
    + commitFrom + '\n');
}
const hashLine = hashBad
  ? 'kdf-brief: ' + hashBad + ' commit hash(es) or the commit paragraph do not hold\n'
  : hashWarned
    ? 'kdf-brief: the commit paragraph\'s hashes resolve, ' + hashes.length + ' read, ' + hashWarned
      + ' warned of outside it\n'
    : 'kdf-brief: every commit hash in the brief resolves, ' + hashes.length + ' read\n';
if (!rows.length) {
  process.stdout.write(hashLine);
  process.stdout.write('kdf-brief: no "| Files | Lines |" table in ' + briefRel + ', nothing more to check\n');
  process.exit(hashBad ? 1 : 0);
}
process.stdout.write(hashLine);

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
process.exit(bad || hashBad ? 1 : 0);
