# The example review, slice S1, a fixture for kdf-retro.js. Answer key

## 1. The commits each reader read

| Reader | Step | Commit read | State commit | Model, as its report or the run names it | Its report or answers |
| --- | --- | --- | --- | --- | --- |
| Fresh Claude reviewer | Step 2 | `aaaaaaa` | `bbbbbbb` | claude-fable-5-1, max | `step-2-review/` |

## 3. The findings

| Id | Source | Reviewer model | Sev | Blocks | Verdict | Where at the pin | Present from | Fixed in | At the step 2 pin | How decided | Needs | The defect | Log row |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| EX-S1-D1-R1-1 | Sol R1, dispatch 1 | ChatGPT Sol | P | yes | Agreed | `src/a.py:10` | before the review | `ccccccc` | yes | read the file at the pin | the repo alone | A token reaches a log line. | section 9 |
| EX-S1-1 | Step 2, Claude | claude-fable-5-1 | M | no | Agreed | `src/b.py:4` | before the review | `ccccccc` | yes | read the file at the pin | the repo alone | A retry never stops. | section 6 |
| EX-S1-FIN-1 | Step 5 final, Claude | claude-fable-5-1 | E | no | Agreed in part | `src/c.py:7` | before the review | `ddddddd` | yes | a probe | the repo alone | A stale comment names the old rule. | section 11 |
| EX-S1-2 | Step 2, Claude | claude-fable-5-1 | E | no | Deferred, row 4 | `src/d.py:2` | before the review | none | unsure | could not settle at the pin | a running stack | A slow path under load. | section 6 |
| EX-S1-FIN-C1 | Step 5 final, Codex | gpt-5.5-codex | L | no | Agreed | `src/e.py:3` | `eeeeeee` | `fffffff` | no | the commit that brought it in | the repo alone | A new helper skips a check. | section 11 |
| S1-1 | Step 1, orchestrator | claude-fable-5-1 | M | no | Agreed | `src/f.py:8` | before the review | `0000000` | no | fixed before the pin | the repo alone | A default was unsafe. | section 1 |
| EX-S1-C1 | Step 2, Codex | gpt-5.5-codex | E | no | Declined | `src/g.py:1` | | | declined | measured | the repo alone | A pipe \| in a name breaks nothing. | section 7 |

## 5. Counts

Not read by the tool.
