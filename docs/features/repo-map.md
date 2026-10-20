# Feature. The repo map

_Last updated: 2026-10-20 (built, ADR D-082) · Status: live_

## 1. Overview

`tools/claude-code/kdf-repo-map.sh` runs `tools/claude-code/kdf_repo_map.py`, a read only lookup over the Python
clones a session names, each read from git's objects at one commit (ADR **D-082**, see
[`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)). It answers five questions in one call.

| Command | The answer |
| --- | --- |
| `defs <name>` | Where a bare or dotted name is defined, where an import binds it, and where an assignment does |
| `imports <dotted>` | The imports of a module, of a name in it and of every module under it, directly or through a re-export |
| `callers <dotted>` | The resolved static calls of a function, class or method, its uses that are not calls, and the unchecked matches |
| `callees <dotted>` | What the one body of a function or method the clone defines calls and uses, each resolved as `callers` resolves, a def nested in it left to its own query |
| `test-importers <dotted>` | The test files that import a module, which is never the set of tests that reach it |

It exists because a lookup of who uses a name otherwise costs a search worker tens of thousands of tokens, repo by
repo, and text matching blurs an import with a mention, an alias with another name and a facade with its origin. The
map follows a name to its definition through explicit re-exports and aliases, tells a call from a value passed on, and
names the function each use sits in. It is a floor, never a whole. An empty group proves no absence.

It runs on the owner's machine, beside the other tools in `tools/claude-code/`, which are not synced to other repos. No
workflow, input, kit page or guard rule changed, so no consumer of this repo sees it.

## 2. How it fits together

```
  kdf-repo-map.sh                       refuses KDF_ROLE=reviewer, finds .venv's Python 3.14, runs -I -B
        │
        ▼
  kdf_repo_map.py main / run            refuses a reviewer again, parses the arguments
        │
        ├─ open_clone, fence             each --repo a folder beside the cicd clone, refused while kdf-review/open
        │                                stands in its git dir, common dir or any registered worktree, one commit
        │                                resolved once, origin/main unless --at <clone>=<rev>
        ├─ listing, contents             git ls-tree and one git cat-file --batch, GIT_ dropped,
        │                                GIT_NO_LAZY_FETCH=1, closed paths, vercel_api/ and --skip folders left out
        │                                before any read
        ├─ read, Collector               ast.parse each file, one walk building Python's scopes and every binding,
        │                                use, import and definition
        ├─ Resolver                      each use resolved inside its own clone, the asked name led to its
        │                                definition, or for callees each use in the asked body
        └─ render                        each clone's first line, three groups capped at 40 lines across clones
```

- **The fence.** `fence` (`kdf_repo_map.py:1376`) looks for `kdf-review/open`, the folder `kdf-review.sh` makes while a
  review is open, in the clone's git dir, its common dir and every worktree administration folder registered there,
  and refuses before any file of the clone is read, and `open_clone` refuses a name that leads outside the root
  through a link. `main` (`:1729`) refuses `KDF_ROLE=reviewer` before it parses anything, `--help` included, and the
  wrapper does the same before it looks for an interpreter.
- **The read.** `git` (`:1272`) drops every inherited `GIT_` variable and sets `GIT_NO_LAZY_FETCH=1` and
  `GIT_TERMINAL_PROMPT=0`. `listing` (`:1466`) keeps tracked regular blobs ending in `.py`, and `closed` (`:1308`)
  drops a secret file's name in any case, a backslash read as a separator, and anything under `keys/`, the list
  `SECRET_GLOBS` (`:40`) held to `kdf-ask-codex.sh`'s and `kdf-preflight.sh`'s by a test. `contents` (`:1496`) reads
  every blob in one call with no text conversion or filter, and a missing object is named in the answer as not
  fetched. Every file read is scanned, and where a package and a module file share a name, the package resolves it.
- **The scopes.** `Collector` (`:226`) builds module, function, lambda, comprehension and class scopes, a lambda and a
  generator expression marked as running later. A def's decorators, defaults and annotations and a class's bases are
  walked in the enclosing scope, a comprehension's first iterable too, and `global`, `nonlocal` and a walrus bind where
  Python binds them. Every call is recorded, whatever it calls through, and every node of an annotation is marked,
  since Python 3.14 never runs one with the code around it, so a call there is unchecked.
- **The resolution.** `lookup` (`:754`) climbs the scopes nearest first, skipping a class body for the scopes inside
  it, its `global` and `nonlocal` declarations with it. A module built into the interpreter or frozen in it, the set
  `UNSHADOWED`, is outside the clone even where a file bears its name. `settle` (`:718`) leaves a name unchecked when
  it is bound twice to different things, or used in a module or class body before its binding, a def's name bound
  only once its statement ends, and settles a class's members the same way, so a member bound twice to different
  things is unchecked and one imported leads to its origin. `follow`
  (`:640`) leads a module level name through explicit imports to its definition, stopping at a star import, a
  `__getattr__`, a competing binding or a cycle. `established` (`:692`) lets a dotted module receiver resolve only when
  every package on the way is read and binds no other object under the next name. `attribute` (`:908`) resolves an
  attribute only on an established module or a class the clone defines, and keeps any other as a candidate with its
  label. `through_package` (`:951`) lists, unchecked, a use of the asked name reached through a parent or child
  package the clone does not hold.
- **What a body calls.** `callee_lines` (`:1059`) reads only the module resolution selects for the asked name, so a
  file a package shadows is never read, nor a file named like a module built into the interpreter, and keeps every
  line unchecked when the name has several bodies or `rebound` (`:1167`) finds its name, or a class's holding it,
  bound more than once or declared `global` or `nonlocal`. `inside_body` (`:1141`) stops at a nested def, labels a
  lambda or a generator expression as running later and a nested class body as running with the function, and
  `callee_words` (`:1189`) words each use with its target's kind, a `self` or `cls` call adding that an override may
  run, and labels a call through a parameter, a local, a subscript, a call's result, a builtin or a method of a value
  whose type the `ast` cannot know, and a use in an annotation. `callee_note` (`:1096`) heads each clone with the body
  read, or says the name is a class with its methods to ask, outside the clone or not defined, and a body with no
  line says it makes no call or use the `ast` sees.
- **The answer.** `render` (`:1585`) prints each clone's first line from `heading` (`:1403`), the commit read, when
  `origin/main` last moved by its reflog, and a checkout that differs, then the three groups, each with every clone's
  count and at most `CAP` (`:57`) lines chosen in turn from each clone by `spread` (`:1565`), then printed by clone,
  path and line. Every line is `<clone>@<short hash> <path>:<line>` and its words.

## 3. The tests that hold it

`scripts/tests/test_kdf_repo_map.py`, in `make ci` and the `test` job, makes its clones with `git init` under the
test's temp folder and runs the module as it ships with `-I -B`, and the wrapper against a stand in interpreter, since
the job makes no repo `.venv`.

- The three groups and the line's shape, a decorated handler queried by its own name, a value passed on, a default.
- Python's scopes, a method body skipping its class, a decorator and a default read in the class scope, a class body
  use before its binding, `global` and `nonlocal`, a name bound in `try` and in `except`, a parameter, an assignment,
  a comprehension variable and a lambda parameter shadowing an import.
- Module receivers, a clean package, an initializer replacing the submodule, a package with `__getattr__`, through
  `from pkg import mod`, `import pkg.mod` and `import pkg.mod as alias`.
- A `self` call in its class and through a two level base, an attribute with an unknown receiver, two clones holding
  the same top level package, a use through a package over the defining module.
- Imports of a package covering its submodules, relative imports, imports in a function, a re-export and a cycle,
  `vercel_api/`, `tests/` and `unit_tests/`, a `src/` layout and `--package-root`, `defs` in its three groups.
- The commit, a checkout behind and ahead of `origin/main`, a reflog absent, `--at` per clone and a leading dash
  refused, a clone with no `origin/main`.
- What is never read or written, an edited tracked file under an unchanged `HEAD`, untracked and ignored files, closed
  paths, a parse error named by path and line with no source text, an inherited `GIT_DIR`, a partial clone's missing
  object left unfetched with its object store unchanged, every fixture's tree and `.git` hashed before and after, and
  no bytecode left beside the module.
- The boundaries a change read found open, a tracked name with backslashes closed before any read, a clone reached
  through a link outside the root refused, a class member bound twice, a `nonlocal` through an intermediate function,
  a package beside a module file of the same name, an import in a class body, a default naming its own def, and a
  tag spelled `origin/main`, a use inside its own class or nested default, a `self` declared global or bound in a
  nested class body, a submodule no import before it loads, a member a module does not bind or only annotates, and a
  class reached through its own module inside its body.
- `callees`, a body within its bounds, a lambda, a generator expression, a comprehension, a nested class and a nested
  def with its decorator, default and annotation, one line for every call the body makes counted with `ast`, a call in
  an annotation, a property and its setter as two bodies, a name bound again as a value or a class, a method's class
  bound again or declared `global`, a class's `global` skipped with it, a clone file named like `sys` read for no
  body, a call in an annotation labelled in `callers` too, an empty body, a missing name, a
  class and a name outside the clone, a package over a file it shadows, a `self` call naming an override, and the
  wrapper's usage and the README naming every command.
- The refusals, the reviewer role with and without `--help` in the module and the wrapper, a review marker in a git
  dir, a common dir and a sibling worktree, a missing or unusable interpreter naming `make venv`, and bad names and
  flags.

## 4. What it cannot see

Uncommitted edits, `importlib` and `getattr`, a name held in a string such as a `mock.patch` target, a star import, and
a method on an instance whose class the `ast` cannot know, which lands by name among the unchecked matches. The answer
says so at its end. A session reads the lines an answer names at their commit, `git -C <clone> show <hash>:<path>`,
and searches text for what the answer names as unseen.

## 5. Operating notes

- The wrapper needs cicd's `.venv` with Python 3.14 or newer. `make venv` makes it, removing `.venv` first, so it runs
  only while the interpreter is missing.
- `--root` names the folder the clones sit in and is for tests. By default it is the folder holding the main checkout
  of the cicd clone the module sits in, found from git's common dir, so a worktree of cicd reads the same clones.
- The module is one file, past the formatter's advisory line count, which `kdf-fmt.toml` turns off for it alone, since
  the wrapper runs it isolated, which keeps its own folder off the import path, so a second module would be loaded by
  its path.
- Later, each deferred by its design, callers two calls out, a repo report of its most used names, a receiver typed by
  an annotation or a constructor, a filter of a group by kind of use, a cache, a run over every clone at once,
  TypeScript, and the owner's tooling core calling the same lookup.
