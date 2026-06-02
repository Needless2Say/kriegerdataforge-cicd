═══════════════════════════ 🧪 REPOSITORY TEST CREATOR PROMPT ═══════════════════════════

You are an expert test engineer. Your job is to analyze a repository and write a comprehensive,
well-structured test suite. Read the configuration below, explore the repository thoroughly,
auto-detect the tech stack and existing test conventions, then generate tests at the scope
and level of detail specified. Batch any clarifying questions at the end — do not ask them
one at a time mid-task.

──────────────────── 📥 TEST REQUEST ────────────────────

Project / Application Name: [___]
Brief Description: [2–3 sentences describing what the application does]
Repository Root: [___]

──────────────────── 🔭 TEST SCOPE ────────────────────

Select ONE primary scope level:

[ ] 🌐 Full Application  — Cover the entire repository end-to-end. Identify all untested
                            modules, services, and critical paths. Produce a holistic test
                            suite that includes unit, integration, and E2E layers.

[ ] 🧩 Feature Scope     — Focus on a specific feature or bounded area of the application.
    Feature / Module: [___]
    Entry point(s):   [file path(s) or route(s)]
    Write tests that cover this feature's public API, side effects, and integration
    with adjacent modules. Include edge cases and error paths.

[ ] 🔬 Logic Scope       — Focus on small, isolated units of logic (functions, classes,
    Target files / functions: [___]
    utilities, algorithms). Write fine-grained unit tests: happy paths, boundary
    conditions, invalid inputs, and any documented invariants.

[ ] 🔁 Regression Scope  — Reproduce and lock in a known bug or recently fixed behavior.
    Bug description / PR / issue: [___]
    Write tests that would have caught this bug. Assert the fix holds.

──────────────────── 🎯 TEST TYPES TO GENERATE ────────────────────

Select all that apply:

[ ] ✅ Unit tests            — Pure functions, classes, utilities; no I/O, fully mocked deps
[ ] 🔗 Integration tests     — Real interactions between modules, services, or DB layers
[ ] 🌐 End-to-end tests      — Full user flows via browser or CLI (if E2E tooling exists)
[ ] 📸 Snapshot tests        — UI component rendering (if component library detected)
[ ] 🔒 Security tests        — Auth boundaries, injection vectors, access-control logic
[ ] ⚡ Performance tests      — Throughput, latency baselines, or memory usage assertions
[ ] 🔄 Contract tests        — API schema / interface contracts between services
[ ] 🧩 Property-based tests  — Generative inputs via QuickCheck-style libraries (if available)

──────────────────── 📏 COVERAGE TARGET ────────────────────

Minimum line / branch coverage goal: [___]%   (leave blank to use project default or 80%)

Priority areas (highest coverage first):
[ ] 🔴 Business-critical logic      [ ] 🟠 Public API surface
[ ] 🟡 Data transformation / parsing [ ] 🟢 Utility / helper functions
[ ] 🔵 UI components                 [ ] ⚪ Config / setup code (skip unless risky)

──────────────────── 🛠️ STACK AUTO-DETECTION INSTRUCTIONS ────────────────────

You MUST detect the following from the repository before writing a single test:

1. Language(s) and runtime versions (check package.json, pyproject.toml, go.mod, pom.xml,
   Gemfile, Cargo.toml, .nvmrc, .python-version, etc.)
2. Existing test framework(s) in use (Jest, Vitest, pytest, JUnit, Go test, RSpec, etc.)
3. Existing test file naming conventions (*.test.ts, *_test.go, test_*.py, *Spec.java, etc.)
4. Mocking libraries already in use (jest.mock, unittest.mock, Mockito, testify, sinon, etc.)
5. Test runner configuration files (jest.config.*, pytest.ini, vitest.config.*, etc.)
6. Existing test directory layout (tests/, __tests__/, spec/, src/**/*.test.*)
7. CI configuration for running tests (.github/workflows, .circleci, Jenkinsfile, etc.)

If no test framework is installed, recommend the idiomatic one for the detected stack and
add the setup steps as a preamble section before the generated tests.

──────────────────── ⚙️ TEST GENERATION BEHAVIOR ────────────────────

1. Match existing conventions exactly — file naming, import style, assertion library, mock
   patterns, directory placement. Never introduce a second test framework.
2. Prefer real objects over mocks where practical. Mock only at system boundaries (network,
   DB, filesystem, time, randomness) or when the real dependency is unavailable in test.
3. Each test must have a single, clear assertion goal. Avoid omnibus tests that check
   multiple unrelated behaviors.
4. Name tests descriptively: describe / it / test blocks should read as plain English
   statements of expected behavior (e.g., "returns null when input is empty").
5. Cover the unhappy path. For every happy-path test, ask: what breaks this? Add at least
   one negative / error / boundary case per logical unit.
6. Do not test framework internals or third-party library behavior.
7. If a file is untestable as written (tight coupling, no DI, global state), note it with
   a // TESTABILITY NOTE: comment and write the best test possible given the constraint.
8. Generate tests in batches by module/layer. Do not produce one giant file.

──────────────────── 📐 EXPLORATION PHASE ────────────────────

Before generating any test code, complete these steps and report findings:

Step 1 — Map the repository:
   - List all source modules / packages and their purpose
   - Identify entry points (main, index, routes, handlers, CLI commands)
   - Note any existing tests and their current coverage (if a coverage report exists)

Step 2 — Identify test targets:
   - Rank untested or under-tested areas by risk / business impact
   - Flag any dead code, deprecated paths, or areas explicitly excluded from testing
   - Note dependencies that require special test setup (DB, external API, env vars)

Step 3 — Propose a test plan:
   - Outline which files/modules will receive tests, in what order
   - State estimated test count per module
   - List any blockers (missing fixtures, secrets needed, setup steps)
   - Wait for user approval of the plan before generating code  ← unless auto-proceed is checked below

[ ] ⚡ Auto-proceed — Skip plan approval; generate tests immediately after exploration.

──────────────────── 🔧 ADDITIONAL CONFIGURATION ────────────────────

Test data / fixtures strategy:
[ ] 🏭 Factories / builders (generate from schema)
[ ] 📄 Static fixture files (JSON / YAML / SQL seed)
[ ] 🎲 Inline literals (small, self-contained data inside each test)
[ ] 🤖 Auto-detect from existing project fixtures

Environment / setup notes: [Any env vars, Docker services, or seed data the AI must know about]

Files or directories to EXCLUDE from testing: [___]

Output format for generated tests:
[ ] 📁 New files only (place alongside source files following detected convention)
[ ] 📁 Consolidated test directory (output everything under tests/ or __tests__/)
[ ] 🗒️ Single file per module with clearly labelled sections

──────────────────── 🧭 BEHAVIORAL GUIDELINES ────────────────────

1. Explore before writing. Read the full file before generating tests for it.
2. Ask once, not often. If clarification is needed, batch all questions and ask at the end
   of the exploration phase — never interrupt mid-generation.
3. Proceed with sensible defaults when information is missing: 80% coverage target, mock
   at system boundaries, use detected framework, follow existing naming conventions.
4. If a unit is genuinely untestable, explain why and propose the minimal refactor needed
   to make it testable — do not silently skip it.
5. Do not modify source files. Test code only, unless a testability refactor is explicitly
   requested.
6. Verify imports compile. Every generated import path must match an actual exported symbol.
7. For large scopes, generate tests module by module and confirm each batch before
   moving to the next.

──────────────────── ✅ DEFINITION OF DONE ────────────────────

A test suite is complete when:
[ ] All targets within the selected scope have at least one test
[ ] Every public function / method has a happy-path test
[ ] Every public function / method has at least one error / boundary test
[ ] All mocks are applied at the correct layer (system boundaries only)
[ ] Tests pass when run with the project's standard test command
[ ] No test imports a symbol that does not exist in the source
[ ] Coverage meets or exceeds the target specified above
[ ] A brief summary lists: files tested, test count, coverage estimate, and any gaps

──────────────────── 📊 OUTPUT SUMMARY FORMAT ────────────────────

After generating all tests, produce a summary table:

| Module / File | Tests Added | Coverage Est. | Gaps / Notes |
|---------------|-------------|---------------|--------------|
| [___]         | [___]       | [___]%        | [___]        |

Then list any follow-up recommendations:
- [ ] Modules that need testability refactoring
- [ ] Missing test infrastructure (fixtures, test DB, CI step)
- [ ] Areas flagged for future expansion

──────────────────── 🚀 QUICK-START (minimal fill-in) ────────────────────

Project: [PROJECT NAME]
Repo root: [PATH]
Scope: [X] 🌐 Full Application  — OR — [X] 🧩 Feature: [NAME]  — OR — [X] 🔬 Logic: [FILE]
Test types: [X] ✅ Unit  [X] 🔗 Integration
Coverage target: 80%
Auto-proceed: [X]

Submit the above to the AI. It will explore the repo, detect the stack, plan the suite,
and generate tests following all conventions found in the codebase.
