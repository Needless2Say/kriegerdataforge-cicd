# Feature. The review questions

_Last updated: 2026-10-30 (questions 15, 16, 17 and 19 on trial, ADR D-094, after D-056 and D-070) · Status: live_

## 1. Overview

`tools/claude-code/kdf-ask-codex.sh` sets a session's brief in a standard frame and asks Codex a read only review or
second opinion (ADRs **D-052** and **D-053**, see
[`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)). The frame closes with the questions the read
answers, each in a line or two apart from its findings. Their words live
in the array `questions` alone (`kdf-ask-codex.sh:237` to `:267`), so every reader of one question reads the same
words (D-056).

The bank holds nineteen questions. Each kind asks five of the first fourteen, and the session may declare any other
by its number.

| Kind | The five it asks |
| --- | --- |
| `plan` | 1 outcome, 2 assumptions, 3 blast radius, 6 failure, order and undo, 14 pre mortem |
| `decision` | 1 outcome, 2 assumptions, 9 evidence of success, 13 the doer and the cost, 14 pre mortem |
| `review` | 2, 3, 4, 6 and 9, with `--fix` asking 10 in place of 3 and `--security` asking 5 in place of 6 |
| `rules` | 3 blast radius, 7 time, 11 enforcement and wording, 12 contradiction and drift, 13 the doer and the cost |

## 2. The questions on trial

Questions 15 to 19 are in no kind's five, and each is asked only by `--also` with its number. Each kept the number it
had among the candidates it was chosen from, so a record of its trial and the bank agree.

| Number | Question | Since |
| --- | --- | --- |
| 15 | Existing state. What the change must meet that already exists, stored data, caches, issued tokens or keys, config files, other machines or installs | D-094 |
| 16 | Exposure. What leaves the machine or a private repository, to which service or public place, and whether it can be pulled back | D-094 |
| 17 | Supply. What new package, image, tool or service is trusted, who publishes it, how it is pinned, and what happens when it changes or disappears | D-094 |
| 18 | Proportion. Which part is heavier than the risk it guards | D-070 |
| 19 | Detection. If it fails quietly, how and when anyone would notice | D-094 |

A trial asks a question of past readings again, once with it and once without, and the question is kept only on what
that shows. One whose trial does not earn it a place comes out again, its words and its number together.

## 3. How a question reaches a frame

- **The bound.** `--also` takes one whole number, 1 to 19 (`kdf-ask-codex.sh:109` to `:116`), so an empty, spaced,
  padded or wildcard value is refused before anything runs, with exit 2.
- **The list.** The kind's five come first (`:141` to `:146`), then each declared number once, in the order given
  (`:151` to `:153`). `--fix` and `--security` add 10 or 5 to any kind but a review.
- **The frame.** `ask` (`:269`) prints each question whole after the closing instruction, and the answer's header names
  every question asked, such as `Questions. plan, 1 2 3 6 14 16` (`:450`), so a frame from a clone that was never
  pulled shows at once.
- **A dry run.** `--dry-run` prints the frame and starts nothing, the way to see which questions a read will ask.

## 4. Tests

`scripts/tests/test_kdf_ask_codex.py` holds the bank whole, every number from 1 to 19 once, each worded as a question.
It runs each kind with declared questions, 15 to 19 among them, and checks the frame asks exactly those and the
header names them. A dry run of each kind with `--also 16` must print 16 once, after the kind's five. The refusals
cover 20, 190, 019, 0, a word, an empty value, two numbers in one value and a wildcard.

## 5. Consumers

The tool runs on the owner's machines from each machine's cicd clone and is not synced to other repos. A caller that
keeps its own copy of the bound, as a panel of several readers may, widens it in its own change. No workflow, input,
kit page or guard rule changed.
