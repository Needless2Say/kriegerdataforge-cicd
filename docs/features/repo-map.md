# Feature. The repo map

_Last updated: 2026-10-21 (a second round, ADR D-084, after D-082) · Status: live_

## 1. Overview

`tools/claude-code/kdf-repo-map.sh` runs `tools/claude-code/kdf_repo_map.py`, a read only lookup over the Python
clones a session names, each read from git's objects at one commit (ADRs **D-082** and **D-084**, see
[`../CHANGELOG_AND_DECISION_LOG.md`](../CHANGELOG_AND_DECISION_LOG.md)). It answers five questions in one call.

| Command | The answer |
| --- | --- |
| `defs <name>` | Where a bare or dotted name is defined, where an import binds it, and where an assignment does |
| `imports <dotted>` | The imports of a module, of a name in it and of every module under it, directly or through a re-export |
| `callers <dotted>` | The resolved static calls of a function, class or method, its uses that are not calls, and the unchecked matches |
| `callees <dotted>` | What the one body of a function or method the clone defines calls and uses, the clone's class members and module values it reads among them, each resolved as `callers` resolves, then the attributes it writes, a def nested in it left to its own query |
| `test-importers <dotted>` | The test files that import a module or a name, then the test candidates whose own bodies use it, never the set of tests that reach it |

It exists because a lookup of who uses a name otherwise costs a search worker tens of thousands of tokens, repo by
repo, and text matching blurs an import with a mention, an alias with another name and a facade with its origin. The
map follows a name to its definition through explicit re-exports and aliases, tells a call from a value passed on, and
names the function each use sits in. It is a floor, never a whole. An empty group proves no absence. Its `--help`
prints a worker's brief, the words a session hands a worker it briefs to use the map.

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
        │                                with its statement, form and directness, use, write, import and definition
        ├─ Resolver                      each use resolved inside its own clone, the asked name led to its
        │                                definition, or for callees each use and write in the asked body
        └─ render                        each clone's first line, three groups, four for callees and
                                         test-importers, capped at 40 lines across clones
```

- **The fence.** `fence` (`kdf_repo_map.py:2053`) looks for `kdf-review/open`, the folder `kdf-review.sh` makes while a
  review is open, in the clone's git dir, its common dir and every worktree administration folder registered there,
  and refuses before any file of the clone is read, and `open_clone` refuses a name that leads outside the root
  through a link. `main` (`:2409`) refuses `KDF_ROLE=reviewer` before it parses anything, `--help` included, and the
  wrapper does the same before it looks for an interpreter.
- **The read.** `git` (`:1949`) drops every inherited `GIT_` variable and sets `GIT_NO_LAZY_FETCH=1` and
  `GIT_TERMINAL_PROMPT=0`. `listing` (`:2143`) keeps tracked regular blobs ending in `.py`, and `closed` (`:1985`)
  drops a secret file's name in any case, a backslash read as a separator, and anything under `keys/`, the list
  `SECRET_GLOBS` (`:40`) held to `kdf-ask-codex.sh`'s and `kdf-preflight.sh`'s by a test. `contents` (`:2173`) reads
  every blob in one call with no text conversion or filter, and a missing object is named in the answer as not
  fetched. Every file read is scanned, and where a package and a module file share a name, the package resolves it.
- **The scopes.** `Collector` (`:336`) builds module, function, lambda, comprehension and class scopes, a lambda and a
  generator expression marked as running later. A def's decorators, defaults and annotations and a class's bases are
  walked in the enclosing scope, a comprehension's first iterable too, and `global`, `nonlocal` and a walrus bind where
  Python binds them. Each binding keeps the statement that made it, its form, an assignment, an import, a def, a
  `del`, a name Python mangles or another, and whether it stands directly in the body of the scope it lands in, which
  no binding inside an `if`, `try`, loop, `with` or `match`, or made through `global`, does. Every call is recorded,
  whatever it calls through, every attribute assigned or deleted as a write, each star import with its place, an
  import of a private name inside a class as mangled, and every node of an annotation is marked, since Python 3.14
  never runs one with the code around it, so a call there is unchecked.
- **The resolution.** `lookup` (`:1053`) climbs the scopes nearest first, skipping a class body for the scopes inside
  it, its `global` and `nonlocal` declarations with it. A module built into the interpreter or frozen in it, the set
  `UNSHADOWED`, is outside the clone even where a file bears its name. `settle` (`:988`) leaves a name unchecked when
  it is bound twice to different things, or used in a module or class body before its binding, a def's name bound
  only once its statement ends, and settles a class's members the same way in `member_of_class` (`:1123`), so a member
  bound twice to different things is unchecked and one imported leads to its origin. `follow` (`:810`) leads a module
  level name through explicit imports to its definition, stopping at a star import with no explicit binding, a
  `__getattr__`, a competing binding or a cycle, a `del` competing with nothing but leaving the binding beside it
  unchecked. `established` (`:962`) lets a dotted module receiver resolve only when every package on the way is read
  and binds no other object under the next name. `attribute` (`:1255`) resolves an attribute only on an established
  module or a class the clone defines, and keeps any other as a candidate with its label. `through_package` (`:1325`)
  lists, unchecked, a use of the asked name reached through a parent or child package the clone does not hold.
- **The rules that move a line toward unchecked.** `doubt` (`:872`) reads a scope's bindings of a name. A private name
  bound or imported under its mangled name is mangled, a binding `displaced` (`:897`) finds a star import may replace
  is unchecked, and a value bound by more than one statement, or by one that is no assignment or import standing
  directly in its scope, is unchecked. `follow` and `settle` apply it at every step of a path, a value's binding rule
  only where the path ends at a value. A module or class reached through a binding that is no import or def standing
  directly in its scope, here or on the way, or reached through `self` or `cls`, passes a doubt to every value read
  through it, `receiver_doubt` (`:858`) saying which. The names on a path stay on it, so a write to a receiver on the
  way reaches a value read through it, and an attribute of a receiver a star or a mangled name leaves unchecked still
  leads to its origin, unchecked. `mangled` (`:1206`) leaves a private name used inside a class unchecked, as
  `member_of_class` does one read through a class, keeping where it leads, and `marks` (`:915`) reads every write the
  clone makes through a class it defines or an established module, the member or value written elsewhere and the
  private name written inside a class. An unchecked path keeps its origin, so a use reaching it moves to the unchecked
  matches and never drops out. `def_lines` (`:1405`) with `defined_doubt` (`:1444`) and `import_line` (`:1376`) hold
  the same rules for a definition, an import binding and a re-export, and `def_lines` names every binding on the way
  from a dotted name to its definition.
- **What a body calls, reads and writes.** `callee_lines` (`:1463`) reads only the module resolution selects for the
  asked name, so a file a package shadows is never read, nor a file named like a module built into the interpreter,
  and keeps every line unchecked when the name has several bodies or `rebound` (`:1650`) finds its name, or a class's
  holding it, bound more than once, declared `global` or `nonlocal`, or open to a star import. `inside_body`
  (`:1624`) stops at a nested def, labels a lambda or a generator expression as running later and a nested class body
  as running with the function, and `callee_words` (`:1676`) words each use with its target's kind, a `self` or `cls`
  call adding that an override may run, and labels a call through a parameter, a local, a subscript, a call's result,
  a builtin or a method of a value whose type the `ast` cannot know, and a use in an annotation. `value_words`
  (`:1733`) words a class's member or a module's value, a `self` or `cls` read of one unchecked and one written
  elsewhere unchecked with the write's place, `receiver_words` (`:1770`) names a chain at its longest receiver that is
  such a value, and `base_words` (`:1794`) a member read through a class that leaves it to a base. `write_words`
  (`:1507`) words each write by its receiver alone, a first parameter found by `lead_of` (`:1550`) from the source, a
  class, an established module or a name outside the clone that the clone's code never replaces, and else its type
  unknown. `callee_note` (`:1578`) heads each clone with the body read, or says the name is a class with its methods to
  ask, outside the clone or not defined, and a body with no line says it makes no call, use or write the `ast` sees.
- **The test candidates.** `candidate_lines` (`:1850`) walks each test file's uses up their scopes to the candidate
  holding them, `candidate` (`:1892`) taking `test*` functions at module level and `test*` methods of `Test*` classes
  at module level, and `candidate_use` (`:1911`) keeping a use that resolves to the asked name or one under it, a value
  the test file binds read bare among them, each taking every doubt `callees` reads on a value, so a `self` read, a
  value written elsewhere and a use in an annotation alone are unchecked, as is one by name alone. A candidate prints
  its certain uses among the candidates and each doubt with its uses among the unchecked matches, and one whose name
  or class is bound more than once is unchecked whole.
- **The answer.** `render` (`:2262`) prints each clone's first line from `heading` (`:2080`), the commit read, when
  `origin/main` last moved by its reflog, and a checkout that differs, then its groups, each with every clone's count
  and at most `CAP` (`:57`) lines chosen in turn from each clone by `spread` (`:2242`), then printed by clone, path
  and line. Every line is `<clone>@<short hash> <path>:<line>` and its words. `test-importers` closes saying a
  candidate is a place to look and not proof, and what it does not read.

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
  class and a name outside the clone, a package over a file it shadows, and a `self` call naming an override.
- The binding rule, a member and a value each bound by a chained assignment, twice, assigned then deleted, inside an
  `if`, a `try`, a `try` with `except*`, a loop and a `with`, by a walrus, in a comprehension and through `global`,
  written elsewhere through its class or module, reached through a base, and re-exported through a module that binds
  it twice, deletes it or imports it conditionally, each unchecked, a value imported in a function resolved and one
  imported in an `if` unchecked, a value through a module imported conditionally unchecked and through one imported
  twice resolved, and a def and a class answering as before in every other form.
- A class's member read through its class and as a receiver, a module's value through an import, an established
  module and bare in its own module, a `self` and a `cls` read, a `self` chain through a name its class does not bind
  left out, each new line carrying the annotation, deferred and several bodies labels, and `callers`, `imports` and
  `test-importers` moving only toward unchecked.
- A private name read through a class, bound in a class body, imported inside a class from a private module or under
  a private name, and written inside a method as a module's attribute and as a bare name, unchecked as mangled in
  `callees`, `callers` and `imports`, a private alias and a module held under a private member keeping their origin, a
  write through a private module alias still reaching the value it replaces, and a binding a later star import or one
  inside a loop may replace, a def and a value, unchecked in `callees`, `callers`, `imports`, `test-importers` and
  `defs`, its body unchecked too, an alias of it and an attribute through it moving to the unchecked matches.
- A value read through a module or class a module on the way imports on a condition, through a class the reader
  imports on one, through `self` past the member, and through a receiver the clone replaces on the way or a class
  replaced in its own module, each unchecked, and `defs` naming every binding on the way to a deleted alias.
- The writes, an assignment, an augmented one, a `for` and a `with` target, a tuple's part and a `del`, a first
  parameter worded from the source in a plain method, a classmethod, a method whose parameter is named `cls`, a
  `staticmethod` and one through an alias, a class, an established module and a facade with its origin, a parameter,
  a local, a call's result, a subscript, a chain through `self`, a rebound first parameter, a def with no positional
  parameter and a class the body replaces with their type unknown, an annotated attribute with no value writing
  nothing, and the labels of a nested class body and a generator expression.
- The test candidates, at module level and in a `Test*` class, a use in a nested def, lambda and class, one through a
  package that re-exports its module, one in `conftest.py`, a value the test file binds read bare, one by name alone,
  through a `self` read, a value written elsewhere or an annotation alone unchecked, a candidate and a `Test*` class
  bound twice unchecked, and a helper, a fixture parameter, a method that is no `test*` and a class that is no `Test*`
  left out.
- The wrapper's usage, the README and `--help` naming every command and the new groups, and `--help` printing the
  worker's brief whole.
- The refusals, the reviewer role with and without `--help` in the module and the wrapper, a review marker in a git
  dir, a common dir and a sibling worktree, a missing or unusable interpreter naming `make venv`, and bad names and
  flags.

## 4. What it cannot see

Uncommitted edits, `importlib` and `getattr`, a name held in a string such as a `mock.patch` target, a star import, a
method on an instance whose class the `ast` cannot know, which lands by name among the unchecked matches, a class
decorator's or a metaclass's change to a class, a value replaced by code the clone does not hold, and a write through
`setattr`, `vars()` or `__dict__`. A class's member and a module's value are the static binding the source makes, never
the object Python reads at run time. The answer says so at its end. A session reads the lines an answer names at their
commit, `git -C <clone> show <hash>:<path>`, and searches text for what the answer names as unseen.

The rules of D-084 only ever move a line toward unchecked. A resolved call or use of `callers`, an import or an import
through a re-export of `imports` and `test-importers`, and a definition or an import binding of `defs` may move to the
unchecked matches with its label where a value is bound in a form the map does not take as certain, a private name is
mangled, or a star import may replace a binding.

## 5. Operating notes

- The wrapper needs cicd's `.venv` with Python 3.14 or newer. `make venv` makes it, removing `.venv` first, so it runs
  only while the interpreter is missing.
- `--root` names the folder the clones sit in and is for tests. By default it is the folder holding the main checkout
  of the cicd clone the module sits in, found from git's common dir, so a worktree of cicd reads the same clones.
- The module is one file, past the formatter's advisory line count, which `kdf-fmt.toml` turns off for it alone, since
  the wrapper runs it isolated, which keeps its own folder off the import path, so a second module would be loaded by
  its path.
- Later, each deferred by its design, callers two calls out, `callers` listing the writes of an attribute, test
  candidates reached through a fixture, a private name's mangled name formed, a def or class the clone's code replaces
  elsewhere read as unchecked as a value is, a repo report of its most used names, a
  receiver typed by an annotation or a constructor, a filter of a group by kind of use, a cache, a run over every
  clone at once, TypeScript, and the owner's tooling core calling the same lookup.
