#!/usr/bin/env node
'use strict';
/*
 * kdf-compact.js, the work records' compaction hook. A Claude Code SessionStart hook, matcher compact|resume.
 *
 *   node kdf-compact.js session-start   read the hook's JSON on stdin and print the session's open work records
 *
 * After a compaction or a resume the summary may have lost where the work stands. This hook reads the session's own
 * transcript for the work record files that session wrote with a file tool, a design or bug log, a review's README or
 * a brainstorm's notes, and prints each open one's path and status word, the newest first, so the session reads its
 * record before any task work. It prints paths, never a record's text. Claude Code adds a SessionStart hook's output
 * to the context as its own, and a record's words should reach the session through a Read, as data (the kit's
 * DOCUMENTATION_STANDARD.md, "Work records"). With no record it points at the status page that names each one.
 *
 * It says nothing to a reviewer (KDF_ROLE=reviewer), who keeps no record, or inside a subagent. It never blocks and
 * never fails a session. Any error exits 0 with nothing on stdout and one line on stderr, and a transcript that takes
 * too long to read gives what was found by then, marked as possibly short.
 *
 * Environment. KDF_ROLE=reviewer silences it. KDF_STATUS_FILE names the status page, otherwise the first
 * kriegerdataforge-context/STATUS.md found from the session's folder upward.
 */
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const STARTED = Date.now();
// The transcript gets eight seconds and the whole run ten, inside the settings entry's timeout of fifteen.
const DEADLINE_MS = 8000;
const TOTAL_MS = 10000;
const MAX_RECORDS = 10;
const MAX_CHARS = 1900;
const FILE_TOOLS = new Set(['Edit', 'Write', 'MultiEdit', 'NotebookEdit']);
// The work records the kit's "Work records" names, by where they live.
const RECORD = new RegExp(
  '/docs/(?:(?:design|bugs)/[^/]+/LOG\\.md|reviews/[^/]+/README\\.md|brainstorming/[^/]+/NOTES\\.md)$'
);
// What reaches the context unquoted, a path made of these characters only, and one of the log template's four status
// words, never other text from a record.
const PLAIN = /^[A-Za-z0-9._/:-]+$/;
const STATUSES = ['OPEN', 'WAITING ON THE OWNER', 'DONE', 'DROPPED'];
const CLOSED = new Set(['DONE', 'DROPPED']);

function quit(note) {
  if (note) process.stderr.write('kdf-compact: ' + note + '\n');
  process.exit(0);
}

function normal(file) {
  return String(file).replace(/\\/g, '/');
}

// The status word on a record's own Status line when it is one of the template's four, an empty string otherwise, and
// null when the file cannot be read.
function statusOf(file) {
  let head = '';
  try {
    const fd = fs.openSync(file, 'r');
    const buf = Buffer.alloc(4096);
    const n = fs.readSync(fd, buf, 0, buf.length, 0);
    fs.closeSync(fd);
    head = buf.toString('utf8', 0, n);
  } catch (err) {
    return null;
  }
  const m = /\*\*Status\.\*\*\s*([^,.\n]*)/.exec(head);
  const word = m ? m[1].trim() : '';
  return STATUSES.includes(word) ? word : '';
}

// The status page, from KDF_STATUS_FILE or found from the session's folder upward.
function statusPage(cwd) {
  if (process.env.KDF_STATUS_FILE) return normal(process.env.KDF_STATUS_FILE);
  let dir = path.resolve(cwd || process.cwd());
  for (let i = 0; i < 6; i++) {
    const candidate = path.join(dir, 'kriegerdataforge-context', 'STATUS.md');
    if (fs.existsSync(candidate)) return normal(candidate);
    const base = path.basename(dir);
    if (base === 'kriegerdataforge-context' && fs.existsSync(path.join(dir, 'STATUS.md'))) {
      return normal(path.join(dir, 'STATUS.md'));
    }
    const up = path.dirname(dir);
    if (up === dir) break;
    dir = up;
  }
  return '';
}

// Every record file the transcript's file tools wrote, the newest write last.
function writtenRecords(transcript) {
  return new Promise((resolve) => {
    const seen = new Map();
    let order = 0;
    let short = false;
    let input;
    try {
      input = fs.createReadStream(transcript, { encoding: 'utf8' });
    } catch (err) {
      resolve({ seen, short: true });
      return;
    }
    const lines = readline.createInterface({ input, crlfDelay: Infinity });
    // readline passes the stream's error on, a file that cannot be read, so it ends the read like the deadline does
    lines.on('error', () => {
      short = true;
      clearTimeout(timer);
      resolve({ seen, short });
    });
    const timer = setTimeout(() => {
      short = true;
      lines.close();
      input.destroy();
    }, DEADLINE_MS);
    input.on('error', () => {
      short = true;
      clearTimeout(timer);
      resolve({ seen, short });
    });
    // A write counts once its result comes back without an error, as the measure counts them, so an Edit that failed
    // names no record (D-060). The calls still waiting for their result, by id.
    const asked = new Map();
    lines.on('line', (line) => {
      const call = line.includes('"file_path"') && /(LOG|README|NOTES)\.md/.test(line);
      const result =
        asked.size > 0 && line.includes('"tool_result"') && [...asked.keys()].some((id) => line.includes(id));
      if (!call && !result) return;
      let rec;
      try {
        rec = JSON.parse(line);
      } catch (err) {
        return;
      }
      const content = rec && rec.message && rec.message.content;
      if (!Array.isArray(content)) return;
      for (const block of content) {
        if (!block) continue;
        if (block.type === 'tool_use' && FILE_TOOLS.has(block.name) && typeof block.id === 'string') {
          const file = block.input && block.input.file_path;
          if (typeof file !== 'string') continue;
          const norm = normal(file);
          if (RECORD.test(norm)) asked.set(block.id, norm);
        } else if (block.type === 'tool_result' && asked.has(block.tool_use_id)) {
          if (block.is_error !== true) seen.set(asked.get(block.tool_use_id), ++order);
          asked.delete(block.tool_use_id);
        }
      }
    });
    lines.on('close', () => {
      clearTimeout(timer);
      resolve({ seen, short });
    });
  });
}

async function main(input) {
  if (process.env.KDF_ROLE && process.env.KDF_ROLE.toLowerCase() === 'reviewer') return quit();
  if (input.agent_id) return quit();
  if (input.source && input.source !== 'compact' && input.source !== 'resume') return quit();

  const transcript = typeof input.transcript_path === 'string' ? input.transcript_path : '';
  const found = transcript && fs.existsSync(transcript) && fs.statSync(transcript).isFile()
    ? await writtenRecords(transcript)
    : { seen: new Map(), short: Boolean(transcript) };

  // Newest first, each read for its status until ten are open or the whole run's time is spent.
  const open = [];
  let unplain = 0;
  let unread = 0;
  const sorted = [...found.seen.entries()].sort((a, b) => b[1] - a[1]).map((entry) => entry[0]);
  for (let i = 0; i < sorted.length; i++) {
    if (open.length >= MAX_RECORDS || Date.now() - STARTED > TOTAL_MS) {
      unread = sorted.length - i;
      break;
    }
    const file = sorted[i];
    if (!PLAIN.test(file)) {
      unplain++;
      continue;
    }
    const status = statusOf(file);
    if (status === null || CLOSED.has(status)) continue;
    open.push(file + (status ? ', ' + status : ''));
  }

  // The notes come last but are counted first, so the whole text stays inside MAX_CHARS.
  const notes = [];
  if (unread) notes.push('- and ' + unread + ' older record files not read, so the list may be short.');
  if (unplain) notes.push('- ' + unplain + ' with other characters in the path, left out.');
  if (found.short) notes.push('- The transcript could not be read whole, so the list may be short.');
  const reserved = notes.reduce((sum, note) => sum + note.length + 1, 0);

  const lines = [];
  if (open.length === 0) {
    const page = statusPage(input.cwd);
    const pointer = page && PLAIN.test(page)
      ? ' If its work keeps one, ' + page + ' names each open record and its branch.'
      : '';
    lines.push('kdf-compact. This session has written no open work record.' + pointer);
  } else {
    const event = input.source === 'resume' ? 'resume' : 'compaction';
    lines.push('kdf-compact. Before any task work after this ' + event + ', read your work record\'s header and Now' +
      ' block, then check git, the pull requests and every open Pending line. The open records this session wrote,' +
      ' newest first.');
    // room for the records after the header and the notes, keeping a line for those left out
    const room = MAX_CHARS - reserved - 50;
    let used = lines[0].length + 1;
    let shown = 0;
    for (const entry of open) {
      if (shown >= MAX_RECORDS || used + entry.length + 3 > room) break;
      lines.push('- ' + entry);
      used += entry.length + 3;
      shown++;
    }
    if (shown < open.length) lines.push('- and ' + (open.length - shown) + ' more, left out for length.');
  }
  lines.push(...notes);
  // Exit once the text is written, since a pipe may take it asynchronously.
  process.stdout.write(lines.join('\n') + '\n', () => process.exit(0));
}

// The last net. Whatever goes wrong, the session goes on, with nothing on stdout.
process.on('uncaughtException', (err) => quit('error, nothing printed. ' + (err && err.message)));
process.on('unhandledRejection', (err) => quit('error, nothing printed. ' + (err && err.message)));

if (process.argv[2] !== 'session-start') quit();
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
  raw += chunk;
});
process.stdin.on('end', () => {
  let input;
  try {
    input = JSON.parse(raw);
  } catch (err) {
    return quit('input is not JSON, nothing printed');
  }
  if (!input || typeof input !== 'object' || Array.isArray(input)) {
    return quit('input is not an object, nothing printed');
  }
  main(input).catch((err) => quit('error, nothing printed. ' + (err && err.message)));
});
