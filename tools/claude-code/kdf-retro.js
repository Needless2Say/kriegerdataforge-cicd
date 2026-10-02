#!/usr/bin/env node
'use strict';
/*
 * kdf-retro.js, the numbers a slice's retrospective starts from, counted from the slice's own record. Read only.
 *
 *   node kdf-retro.js <slice folder>
 *        reads the folder's answer key, the header of every report in its step folders and its Sol rounds, and prints
 *        three Markdown tables for the retrospective's section 1, pasted as printed. The findings by source (raised,
 *        agreed, declined, the agreed ones that were in the tree the step 2 reviewers read, and the escapes), the
 *        reports (reviewer, minutes, tokens), and the Sol rounds (every dispatch and whether its answer is archived)
 *
 * An escape is an agreed finding that was in the step 2 pin's tree and that a later source found, a Sol round, a final
 * review, a second read, or the orchestrator after step 2. The escape rate is the first number a retrospective reads,
 * since it counts the defects the step 2 reviews had in front of them and missed.
 *
 * The answer key's findings table must carry the columns of templates/review-answer-key.template.md, in its order. A
 * key with other columns is refused rather than guessed at. A report's Time spent, Reviewer and Usage lines are read as
 * templates/review-report.template.md writes them, and a value the report does not give prints as unknown.
 *
 * Exit codes. 0 the tables printed. 2 no answer key, more than one, a key that cannot be read, or a findings table
 * whose columns this tool does not know.
 */
const fs = require('fs');
const path = require('path');

const COLUMNS = [
  'Id', 'Source', 'Reviewer model', 'Sev', 'Blocks', 'Verdict', 'Where at the pin', 'Present from', 'Fixed in',
  'At the step 2 pin', 'How decided', 'Needs', 'The defect', 'Log row'
];

function fail(code, message) {
  process.stderr.write('kdf-retro: ' + message + '\n');
  process.exit(code);
}

const folderArg = process.argv[2];
if (!folderArg || process.argv.length > 3) {
  fail(2, 'name one slice folder, or a spot review folder. See the head of ' + path.basename(__filename) + '.');
}
const folder = path.resolve(folderArg);
if (!fs.existsSync(folder) || !fs.statSync(folder).isDirectory()) fail(2, folderArg + ' is not a folder');

const byName = (a, b) => (a < b ? -1 : a > b ? 1 : 0);
const format = (n) => (n === null || n === undefined ? 'unknown' : n.toLocaleString('en-US'));
const read = (file) => fs.readFileSync(file, 'utf8').replace(/\r\n/g, '\n');

// ------------------------------------------------------------ the answer key

const keys = fs.readdirSync(folder).filter((f) => /_ANSWER_KEY\.md$/.test(f)).sort(byName);
if (!keys.length) {
  fail(2, 'no answer key (*_ANSWER_KEY.md) at the root of ' + folderArg + ', write it first, section 8');
}
if (keys.length > 1) fail(2, 'more than one answer key in ' + folderArg + ', ' + keys.join(', '));
let keyText;
try {
  keyText = read(path.join(folder, keys[0]));
} catch (err) {
  fail(2, 'cannot read ' + keys[0] + ', ' + err.message);
}

// A row's cells, split on the pipes that are not escaped, outer pipes dropped.
const cells = (line) => line.trim().replace(/^\|/, '').replace(/\|$/, '').split(/(?<!\\)\|/).map((c) => c.trim());

const lines = keyText.split('\n');
const header = lines.findIndex((l) => l.trim().startsWith('|') && cells(l)[0] === 'Id');
if (header < 0) fail(2, keys[0] + ' has no findings table, a table whose first column is Id');
const found = cells(lines[header]);
if (found.length !== COLUMNS.length || found.some((c, k) => c !== COLUMNS[k])) {
  fail(2, keys[0] + "'s findings table has the columns " + found.join(', ') + ', and this tool reads only '
    + COLUMNS.join(', ') + ', the answer key template of kit v1.9.0 and later');
}
const col = (name) => COLUMNS.indexOf(name);

const findings = [];
for (let i = header + 1; i < lines.length && lines[i].trim().startsWith('|'); i++) {
  const c = cells(lines[i]);
  if (/^-+$/.test(c[0].replace(/[:\s]/g, ''))) continue;
  if (c[0].includes('{')) continue;
  findings.push({
    id: c[col('Id')],
    source: c[col('Source')].replace(/\s+/g, ' '),
    verdict: c[col('Verdict')] || '',
    atPin: (c[col('At the step 2 pin')] || '').toLowerCase()
  });
}

// Where a source sits in the cycle, so the table reads in the order the review ran and an escape is told apart.
function rank(source) {
  const s = source.toLowerCase();
  if (/second read/.test(s)) return 6;
  if (/final|step 5/.test(s)) return 5;
  if (/\bsol\b|round|dispatch/.test(s)) return 4;
  if (/step 3|adjudicat|after step 2/.test(s)) return 3;
  if (/step 2/.test(s)) return 2;
  if (/step 1|step 0|orchestrator/.test(s)) return 1;
  if (/@codex|pull request/.test(s)) return 7;
  return 9;
}

function kind(verdict) {
  const v = verdict.toLowerCase();
  if (/^agreed|^deferred/.test(v)) return 'agreed';
  if (/^declined|^measured false/.test(v)) return 'declined';
  return 'other';
}

const sources = new Map();
for (const f of findings) {
  if (!sources.has(f.source)) {
    sources.set(f.source, { raised: 0, agreed: 0, declined: 0, other: 0, inTree: 0, escapes: [] });
  }
  const s = sources.get(f.source);
  s.raised++;
  s[kind(f.verdict)]++;
  if (kind(f.verdict) === 'agreed' && f.atPin.startsWith('yes')) {
    s.inTree++;
    if (rank(f.source) > 2) s.escapes.push(f.id);
  }
}
const order = [...sources.keys()].sort((a, b) => rank(a) - rank(b) || byName(a, b));

const out = [];
out.push('# The numbers of ' + path.basename(folder));
out.push('');
out.push('From `' + keys[0] + '`, ' + findings.length
  + ' findings, and the reports and Sol rounds in the step folders.');
out.push('');
out.push('## Findings by source');
out.push('');
out.push('| Source | Raised | Agreed | Declined | Other | Agreed, in the step 2 tree | Escapes it found |');
out.push('| --- | --- | --- | --- | --- | --- | --- |');
const total = { raised: 0, agreed: 0, declined: 0, other: 0, inTree: 0, escapes: [] };
for (const name of order) {
  const s = sources.get(name);
  const esc = rank(name) > 2 ? String(s.escapes.length) : '-';
  out.push('| ' + name.replace(/\|/g, '\\|') + ' | ' + s.raised + ' | ' + s.agreed + ' | ' + s.declined + ' | '
    + s.other + ' | ' + s.inTree + ' | ' + esc + ' |');
  for (const k of ['raised', 'agreed', 'declined', 'other', 'inTree']) total[k] += s[k];
  total.escapes.push(...s.escapes);
}
out.push('| All | ' + total.raised + ' | ' + total.agreed + ' | ' + total.declined + ' | ' + total.other + ' | '
  + total.inTree + ' | ' + total.escapes.length + ' |');
out.push('');
const unsure = findings.filter((f) => kind(f.verdict) === 'agreed' && f.atPin.startsWith('unsure')).length;
const rate = total.inTree ? Math.round((100 * total.escapes.length) / total.inTree) : 0;
const escapeIds = total.escapes.map((id) => '`' + id + '`').join(', ');
const unsureNote = unsure === 1
  ? ' 1 more agreed finding is marked unsure at the step 2 pin and is not counted.'
  : ' ' + unsure + ' more agreed findings are marked unsure at the step 2 pin and are not counted.';
out.push('Escapes, agreed findings in the step 2 tree that a later source found, ' + total.escapes.length + ' of '
  + total.inTree + ' (' + rate + '%)' + (escapeIds ? ', ' + escapeIds : '') + '.' + (unsure ? unsureNote : ''));

// ------------------------------------------------------------ the reports

function headerValue(text, label) {
  const ls = text.split('\n');
  const k = ls.findIndex((l) => l.trim().startsWith('- **' + label + '.**'));
  if (k < 0) return '';
  let value = ls[k].trim().slice(('- **' + label + '.**').length);
  for (let j = k + 1; j < ls.length && /^\s{2,}\S/.test(ls[j]) && !ls[j].trim().startsWith('- **'); j++) {
    value += ' ' + ls[j].trim();
  }
  return value.replace(/\s+/g, ' ').trim();
}

// A clock time as minutes since the epoch when it carries a date, or since midnight when it does not.
function clock(text) {
  const dated = /(\d{4})-(\d{2})-(\d{2})[ T](\d{1,2}):(\d{2})(?::(\d{2}))?\s*(Z|[+-]\d{2}:?\d{2})?/.exec(text);
  if (dated) {
    let ms = Date.UTC(+dated[1], +dated[2] - 1, +dated[3], +dated[4], +dated[5], +(dated[6] || 0));
    if (dated[7] && dated[7] !== 'Z') {
      const sign = dated[7][0] === '-' ? -1 : 1;
      const hhmm = dated[7].slice(1).replace(':', '');
      ms -= sign * (Number(hhmm.slice(0, 2)) * 60 + Number(hhmm.slice(2))) * 60000;
    }
    return { dated: true, minutes: ms / 60000 };
  }
  const bare = /\b(\d{1,2}):(\d{2})\b/.exec(text);
  if (bare) return { dated: false, minutes: Number(bare[1]) * 60 + Number(bare[2]) };
  return null;
}

function minutes(timeSpent) {
  const m = /\bfrom\s+(.+?)\s+to\s+(.+)$/i.exec(timeSpent);
  if (!m) return null;
  const a = clock(m[1]);
  const b = clock(m[2]);
  if (!a || !b || a.dated !== b.dated) return null;
  let d = b.minutes - a.minutes;
  if (!a.dated && d < 0) d += 24 * 60;
  return d < 0 ? null : Math.round(d);
}

function tokens(usage, word) {
  const number = (s) => {
    const m = /^([\d][\d,]*(?:\.\d+)?)\s*([kKmM])?$/.exec(s.trim());
    if (!m) return null;
    const n = Number(m[1].replace(/,/g, ''));
    return Math.round(m[2] ? n * (/[kK]/.test(m[2]) ? 1e3 : 1e6) : n);
  };
  const before = new RegExp('([\\d][\\d,]*(?:\\.\\d+)?\\s*[kKmM]?)\\s*(?:tokens\\s+)?' + word + '\\b').exec(usage);
  if (before) return number(before[1]);
  const after = new RegExp('\\b' + word + '\\b\\s*[:=]?\\s*([\\d][\\d,]*(?:\\.\\d+)?\\s*[kKmM]?)').exec(usage);
  return after ? number(after[1]) : null;
}

const steps = fs.readdirSync(folder)
  .filter((d) => /^step-/.test(d) && d !== 'step-4-sol' && fs.statSync(path.join(folder, d)).isDirectory())
  .sort(byName);
const reports = [];
for (const step of steps) {
  for (const file of fs.readdirSync(path.join(folder, step)).filter((f) => /_REPORT\.md$/.test(f)).sort(byName)) {
    const text = read(path.join(folder, step, file));
    const usage = headerValue(text, 'Usage');
    reports.push({
      step,
      file,
      reviewer: headerValue(text, 'Reviewer') || 'unknown',
      minutes: minutes(headerValue(text, 'Time spent')),
      tokensIn: tokens(usage, 'in'),
      tokensOut: tokens(usage, 'out')
    });
  }
}
out.push('');
out.push('## Reports');
out.push('');
if (!reports.length) out.push('No report in a step folder.');
else {
  out.push('| Step | Report | Reviewer | Minutes | Tokens in | Tokens out |');
  out.push('| --- | --- | --- | --- | --- | --- |');
  for (const r of reports) {
    out.push('| ' + r.step + ' | `' + r.file + '` | ' + r.reviewer.replace(/\|/g, '\\|') + ' | ' + format(r.minutes)
      + ' | ' + format(r.tokensIn) + ' | ' + format(r.tokensOut) + ' |');
  }
}

// ------------------------------------------------------------ the Sol rounds

const solRoot = path.join(folder, 'step-4-sol');
out.push('');
out.push('## Sol rounds');
out.push('');
const missing = [];
if (!fs.existsSync(solRoot)) out.push('No Sol round in this folder.');
else {
  out.push('| Round | Dispatches | Answers | Dispatches without an answer |');
  out.push('| --- | --- | --- | --- |');
  const rounds = fs.readdirSync(solRoot).filter((d) => fs.statSync(path.join(solRoot, d)).isDirectory()).sort(byName);
  for (const round of rounds) {
    const files = fs.readdirSync(path.join(solRoot, round));
    const prompts = files.filter((f) => /_PROMPT\.md$/.test(f)).sort(byName);
    const answers = new Set(files.filter((f) => /_ANSWER\.md$/.test(f)));
    const lacking = prompts.filter((p) => !answers.has(p.replace(/_PROMPT\.md$/, '_ANSWER.md')));
    missing.push(...lacking.map((p) => round + '/' + p));
    out.push('| ' + round + ' | ' + prompts.length + ' | ' + answers.size + ' | '
      + (lacking.length ? lacking.map((p) => '`' + p + '`').join(', ') : 'none') + ' |');
  }
  out.push('');
  out.push(missing.length
    ? missing.length + ' Sol dispatch(es) without an archived answer, the slice does not close until each is in, '
      + 'section 14.'
    : 'Every Sol dispatch has its archived answer.');
}
process.stdout.write(out.join('\n') + '\n');
process.exit(0);
