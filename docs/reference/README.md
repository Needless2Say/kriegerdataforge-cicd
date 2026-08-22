# docs/reference — source-verified contracts

Durable reference material verified against the code it describes (claims cite `file:line`;
if a claim and the code disagree, the code wins — fix the doc).

| Reference | What it catalogs |
| --- | --- |
| [`GLOSSARY.md`](GLOSSARY.md) | Every coined term, prefix, and piece of shorthand these docs assume, defined inline (new 2026-08-22) |
| [`MAKEFILE.md`](MAKEFILE.md) | Every `make` target and the reasoning: the three `make ci` lanes, why several lane names here are load-bearing for other repos' CI, the two-interpreter split, and the local-vs-self-contained E2E stacks |
| [`WORKFLOWS.md`](WORKFLOWS.md) | The full reusable-workflow catalog: every workflow this repo ships, its inputs/secrets, and its consumers |

New reference doc? Follow [`../agent/DOCUMENTATION_STANDARD.md`](../agent/DOCUMENTATION_STANDARD.md)
(the `file:line` citation rule applies hardest here) and add it to [`../README.md`](../README.md)
in the same PR.
