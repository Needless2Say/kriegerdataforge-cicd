# kriegerdataforge-cicd — Agent instructions

**The canonical agent guide for this repo is [`AGENTS.md`](./AGENTS.md). Read it first.**

It covers this repo's vision & purpose, tech stack, module map, critical rules, **required reading**,
and the commands you'll need.

Then, for every task:

- Follow the standard workflow in [`WORKFLOW.md`](./WORKFLOW.md) — pick a lane (Quick / Standard / Epic),
  **plan → owner approves** → implement → `make ci` green locally → PR → confirm GitHub CI is green → owner merges.
- Before any security-sensitive work, read the security playbook in [`skills.md`](./skills.md).

Everything an agent needs lives in those files — this file is just the entry point Claude Code loads.
