#!/usr/bin/env node
'use strict';
/*
 * check-wiring.js, read only. Says whether this machine's Claude Code settings wire the KDF guard the way the
 * KDF Code Review Process needs, and prints the block the owner adds when they do not. It changes nothing.
 *
 *   node check-wiring.js                 check ~/.claude/settings.json
 *   node check-wiring.js --home <dir>    check <dir>/.claude/settings.json, for a test or another user
 *   node check-wiring.js --quiet         print failures and warnings only
 *   node check-wiring.js --print         print the settings block to add, with this machine's hook path
 *
 * Exit 0 when nothing failed, warnings allowed. Exit 1 when a check failed.
 */
const crypto = require('crypto');
const fs = require('fs');
const os = require('os');
const path = require('path');

// The tools the guard must see. A hook only runs for tools its matcher names, so a gap here is a hole. Read, Grep
// and Glob carry the .gitignore rule for reviewers and the package token rule for .env.local. Monitor runs a shell
// command like Bash (D-060).
const MATCHER = 'Bash|PowerShell|Monitor|Read|Grep|Glob|Edit|Write|MultiEdit|NotebookEdit|WebFetch|WebSearch|mcp__.*|Artifact.*|SendUserFile|SendMessage|PushNotification|RemoteTrigger|Cron.*|DesignSync|EnterWorktree|Workflow';
const MUST_MATCH = [
  'Bash', 'PowerShell', 'Monitor', 'Read', 'Grep', 'Glob', 'Edit', 'Write', 'MultiEdit', 'NotebookEdit', 'WebFetch',
  'WebSearch', 'mcp__claude_ai_Google_Drive__share_file', 'mcp__ide__executeCode', 'Artifact', 'ArtifactData',
  'SendUserFile', 'SendMessage', 'PushNotification', 'RemoteTrigger', 'CronCreate', 'DesignSync', 'EnterWorktree',
  'Workflow'
];
// A second fence behind the guard, for a call it never sees. .env.local is not among them, the owner opened
// it on 2026-09-29 and the guard keeps one that still holds a credential closed. .env.kdf holds the credentials, and
// .env.dev and .env.prod are the owner's admin files.
const SECRET_READ_DENIES = [
  'Read(**/.env.kdf)', 'Read(**/.env.dev)', 'Read(**/.env.prod)', 'Read(**/.env.test)', 'Read(**/*.tfvars)',
  'Read(**/*.pem)'
];

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(name);
const value = (name) => (argv.includes(name) ? argv[argv.indexOf(name) + 1] : undefined);

const home = path.resolve(value('--home') || process.env.KDF_HOME || os.homedir());
const settingsFile = path.join(home, '.claude', 'settings.json');
const installedGuard = path.join(home, '.claude', 'hooks', 'kdf-guard.js');
const repoGuard = path.join(__dirname, 'kdf-guard.js');
const hookPath = home.replace(/\\/g, '/') + '/.claude/hooks/kdf-guard.js';

function recommended() {
  return {
    defaultShell: 'bash',
    // || exit 2 refuses when the guard cannot start, a missing file or a missing node, which Claude Code lets through
    hooks: {
      PreToolUse: [{ matcher: MATCHER, hooks: [{ type: 'command', command: 'node "' + hookPath + '" || exit 2' }] }]
    },
    permissions: { deny: ['PowerShell'].concat(SECRET_READ_DENIES) }
  };
}

if (flag('--print')) {
  process.stdout.write(
    'Add these keys to ' + settingsFile + ' by hand. The two lists merge with what is already there, so keep your\n'
    + 'existing deny rules and put the new entries beside them. defaultShell and hooks are top level keys.\n\n'
    + JSON.stringify(recommended(), null, 2) + '\n'
  );
  process.exit(0);
}

const rows = [];
const add = (level, what, detail) => rows.push({ level, what, detail: detail || '' });
const sha = (file) => crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');

let settings = null;
try {
  settings = JSON.parse(fs.readFileSync(settingsFile, 'utf8'));
  add('PASS', 'settings file is valid JSON', settingsFile);
} catch (err) {
  add('FAIL', 'settings file is missing or is not valid JSON', settingsFile + ' ' + err.message);
}

if (settings) {
  if (settings.disableAllHooks === true) add('FAIL', 'hooks are switched off', 'disableAllHooks is true');

  if (settings.defaultShell === 'bash') add('PASS', 'Git Bash is the default shell');
  else add('FAIL', 'defaultShell is not "bash"', 'it is ' + JSON.stringify(settings.defaultShell) + ', a top level key');

  const deny = (settings.permissions && settings.permissions.deny) || [];
  if (deny.includes('PowerShell')) add('PASS', 'the PowerShell tool is denied');
  else add('FAIL', 'the PowerShell tool is not denied', 'a Bash deny rule does not cover it, add "PowerShell" to permissions.deny');

  const entries = ((settings.hooks && settings.hooks.PreToolUse) || []).filter((e) => JSON.stringify(e).includes('kdf-guard'));
  if (!entries.length) {
    add('FAIL', 'no PreToolUse hook runs kdf-guard.js', 'run node check-wiring.js --print for the block to add');
  } else {
    const entry = entries[0];
    const command = ((entry.hooks || [])[0] || {}).command || '';
    add('PASS', 'a PreToolUse hook runs kdf-guard.js', command);
    let re = null;
    try {
      re = new RegExp('^(?:' + (entry.matcher || '') + ')$');
    } catch (err) {
      add('FAIL', 'the hook matcher is not a valid pattern', String(entry.matcher));
    }
    if (re) {
      const missed = MUST_MATCH.filter((t) => !re.test(t));
      if (missed.length) add('FAIL', 'the hook matcher misses tools the guard must see', missed.join(', '));
      else add('PASS', 'the hook matcher covers every tool the guard must see');
    }
    const pointed = (command.match(/"([^"]*kdf-guard\.js)"/) || [])[1];
    if (!pointed) add('WARN', 'the hook command does not quote a path to kdf-guard.js', command);
    else if (!fs.existsSync(pointed)) add('FAIL', 'the hook points at a file that does not exist', pointed);
    // A warning, not a failure, so a review the launcher starts is not stopped before the owner adds it (D-059).
    if (!/\|\|\s*exit\s+2\s*$/.test(command)) {
      add('WARN', 'the hook command does not end with || exit 2',
        'a guard that cannot start would let every call through');
    }
  }

  const missingReads = SECRET_READ_DENIES.filter((r) => !deny.includes(r));
  if (missingReads.length) add('WARN', 'secret files are not denied to the Read tool', missingReads.join(' '));
  else add('PASS', 'secret files are denied to the Read tool');
  if (!deny.includes('Bash(gh pr merge *)')) add('WARN', 'the Bash deny rule for gh pr merge is absent', 'the guard still refuses it, the rule is the second fence');
}

if (!fs.existsSync(installedGuard)) {
  add('FAIL', 'the guard is not installed', installedGuard + ', run tools/claude-code/install.sh');
} else if (fs.existsSync(repoGuard) && sha(installedGuard) !== sha(repoGuard)) {
  add('WARN', 'the installed guard differs from this repo\'s copy', 'run tools/claude-code/install.sh to update it');
} else {
  add('PASS', 'the installed guard matches this repo\'s copy');
}

const failed = rows.filter((r) => r.level === 'FAIL').length;
for (const r of rows) {
  if (flag('--quiet') && r.level === 'PASS') continue;
  process.stdout.write(r.level.padEnd(5) + r.what + (r.detail ? '  (' + r.detail + ')' : '') + '\n');
}
process.stdout.write(failed ? '\n' + failed + ' check(s) failed.\n' : '\nAll checks passed.\n');
process.exit(failed ? 1 : 0);
