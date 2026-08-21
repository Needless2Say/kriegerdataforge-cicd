# ============================================================
#  kriegerdataforge-cicd -- Makefile
# ============================================================
#  `make` or `make help` lists every command, grouped in dev flow order.
#  Full usage + the reasoning behind the conventions: docs/reference/MAKEFILE.md
#
#  This repo is the ecosystem's CONTROL PLANE: the reusable GitHub Actions
#  workflows every other repo calls, the operational scripts behind them, and
#  the Tier-2 Playwright E2E suite that drives the whole stack.
#
#  It is also the ONLY PUBLIC repo in the ecosystem. Nothing here may carry a
#  real credential, hostname or account identifier.
#
#  Fresh clone:
#    make setup
#    make ci      # the PR gate -- must be green before you push
#
#  Several reusable workflows here HARDCODE the make target they invoke in the
#  calling repo (ci-nextjs-lint-typecheck.yml -> `make ci-lint` / `make
#  ci-typecheck`, ci-nextjs-tests.yml -> `make ci-unit-tests`, ci-nextjs-build.yml
#  -> `make ci-build`, ci-npm-audit.yml -> `make ci-npm-audit`). That is what
#  makes those names canonical ecosystem-wide -- see the hub's
#  docs/reference/MAKEFILE_CONVENTIONS.md before renaming anything.
#
#  Requirements:
#    actionlint  https://github.com/rhysd/actionlint  (brew install actionlint)
#    codeql      https://github.com/github/codeql-cli-binaries
#    node + npm  only for the E2E suite (make e2e-install)
#    docker      only for the E2E suite
#
#  Conventions (details in docs/reference/MAKEFILE.md):
#    1. Prerequisites are declared inline on the target that needs them.
#    2. Guards: uses $(PYTHON) -> _ensure-venv.
#    3. `.PHONY` is declared per section, never as one list at the top.
#    4. Internal helpers are `_`-prefixed; a `# Internal: ...` line sits ABOVE the
#       target (never on the target line), keeping them out of help.
#    5. `## text` = a help line; `##@ Name` = a help group (parsed by `help`).
#       `# ==== / # Name / # ====` marks a region with NO targets, invisible to help.
#    6. ASCII only -- this runs in cp1252 Windows consoles.
# ============================================================

# default target is `help`, Makefile is self documenting
.DEFAULT_GOAL := help

# quieter recursive make, individual recipes need not pass --no-print-directory
MAKEFLAGS += --no-print-directory

# ============================================================
# Variables
# ============================================================

# ---------- Dotenv reader ----------

# Reads a variable from a dotenv file. The first argument is the file, the second is the variable name.
from_env_file  = $(shell grep -E '^[[:space:]]*$(2)=' $(1) | head -1 | cut -d= -f2- | tr -d '\042\047\015 ')
from_env_local = $(call from_env_file,.env.local,$(1))

# ---------- Terminal colors ----------

BLUE   := \033[0;34m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m

# ---------- Python / virtual environment ----------

# python version hard coded (can be changed)
# This repo previously ran a bare `py` / `python3` and pip-installed pytest and kdf-fmt
# into the contributor's SYSTEM Python -- the venv keeps that pollution out and pins
# the version.
PYTHON_VERSION ?= 3.14

ifeq ($(OS),Windows_NT)
    VENV_BIN := .venv/Scripts
    PY_CMD   := py -$(PYTHON_VERSION)
else
    VENV_BIN := .venv/bin
    PY_CMD   := python$(PYTHON_VERSION)
endif

# always use venv's python
PYTHON := $(VENV_BIN)/python

# The system interpreter, used ONLY by the e2e/ci_stack.py helpers.
#
# Deliberate, not an oversight: ci_stack.py is stdlib-only (argparse, json, os,
# secrets, shutil, subprocess, sys, dataclasses, pathlib) and CI invokes it as a bare
# `python e2e/ci_stack.py` in .github/actions/run-e2e/action.yml. Routing it through
# the venv would add a venv build to targets that need no packages -- including
# `e2e-ci-down`, a teardown target that must keep working even when the venv does not.
ifeq ($(OS),Windows_NT)
    PY_SYS := py
else
    PY_SYS := python3
endif

# ---------- Private GitHub repo (kdf-fmt, over pip) ----------

# To download private kdf python packages, reads GH_PACKAGES_PAT from .env.local if not already set in the environment.
# The PAT must be a fine grained token with read access to the kriegerdataforge-fmt repo, NOT a classic token.
# Quotes, stray spaces and CRs are stripped: copying .env.example on Windows leaves
# CRLF endings, and a trailing \r corrupts the token silently.
ifeq ($(GH_PACKAGES_PAT),)
  ifneq ($(wildcard .env.local),)
    GH_PACKAGES_PAT := $(call from_env_local,GH_PACKAGES_PAT)
  endif
endif
export GH_PACKAGES_PAT

# ORDER SENSITIVE: must follow the block above -- `ifneq` is immediate, so moving it earlier
# silently leaves PIP_GIT_AUTH empty and private-SDK installs start failing.
# Process scoped -- it never writes the global .gitconfig, whose pollution previously
# caused 403-on-push across every repo. Expands to NOTHING without a PAT so git falls
# back to its own credentials (e.g. Credential Manager); injecting an empty one would
# stop the helper being consulted. `$$GH_PACKAGES_PAT` resolves in the recipe's shell,
# so `make -n` prints the variable name, not the secret.
ifneq ($(GH_PACKAGES_PAT),)
  PIP_GIT_AUTH := GIT_CONFIG_COUNT=1 \
    GIT_CONFIG_KEY_0="url.https://__token__:$$GH_PACKAGES_PAT@github.com/.insteadOf" \
    GIT_CONFIG_VALUE_0="https://github.com/"
endif

# The kdf-fmt pin lives in this repo's own ci.yml (`kdf_fmt_ref`) and is read from
# there. A hardcoded second copy is exactly how local and CI drift onto different
# style rules.
KDF_FMT_VERSION ?= $(shell grep -oE 'kdf_fmt_ref:[[:space:]]*v[0-9.]+' .github/workflows/ci.yml | head -1 | grep -oE 'v[0-9.]+')

# ---------- E2E ----------

# Which journey's specs to stage for `make e2e` (the delegated stack is fitness).
# Override: make e2e JOURNEY=tiffanys
JOURNEY ?= fitness

FITNESS_FE := $(MAKE) -C ../fitness-app-frontend

# ---------- CodeQL ----------

# CodeQL database and results directories, language, and query pack
# These are used by the codeql.yml workflow and the local `make codeql` target
# PYTHON, not javascript-typescript. A real scan showed the TS setup analyzed almost
# nothing: e2e/ holds only playwright.config.ts plus whatever ci_stack.py has STAGED into
# e2e/staged-tests at that moment -- the journey specs live in the app repos (ADR D-006).
# The security-relevant code here is the Python under scripts/: secret rotation, deployer
# authorization, provisioning. Changed 2026-08-09.
CODEQL_DB      := ../codeql/codeql-dbs/kriegerdataforge-cicd
CODEQL_RESULTS := ../codeql/codeql-results
CODEQL_LANG    := python
CODEQL_PACK    := codeql/python-queries

# ---------- Version gate ----------

# Base branch for version check. Used by `make ci-version-check` to ensure
# the version in VERSION is greater than the last release on the base branch.
BASE_BRANCH ?= main

# ============================================================
# Canned recipes
# ============================================================

# $(call banner,<title>)
define banner
@printf "$(BLUE)========================================$(NC)\n"
@printf "$(BLUE)  $(1)$(NC)\n"
@printf "$(BLUE)========================================$(NC)\n"
endef

##@ Help

.PHONY: help

help: ## Show this help message
	$(call banner,kriegerdataforge-cicd - Makefile)
	@awk 'BEGIN { FS = ":.*##" } \
		/^##@/ { printf "\n$(YELLOW)%s$(NC)\n", substr($$0, 5); next } \
		/^[a-zA-Z_][a-zA-Z0-9_-]*:.*##/ { printf "  $(GREEN)%-28s$(NC) %s\n", $$1, $$2 } \
		' $(MAKEFILE_LIST)
	@printf "\n"

##@ Setup & Dependencies

.PHONY: _ensure-venv venv setup install

# Internal: create the Python venv on demand.
# Plain `#`, never `##` -- a `##` here would put an internal guard in `make help`.
_ensure-venv:
	@[ -d "$(VENV_BIN)" ] || $(MAKE) venv

venv: ## Create the Python virtual environment
	@printf "$(GREEN)Creating Python virtual environment...$(NC)\n"
	@rm -rf .venv
	$(PY_CMD) -m venv .venv
	$(PYTHON) -m pip install --upgrade pip
	@printf "$(GREEN)Virtual environment created at .venv$(NC)\n"

# `$(PYTHON) -m pip`, never the bare `pip` shim: on Windows the console scripts are not
# on PATH under Git Bash, so a bare `pip` failed locally while passing in CI.
install: _ensure-venv ## Install the Python test dependencies into the venv
	@printf "$(GREEN)Installing Python test dependencies...$(NC)\n"
	cd scripts && $(CURDIR)/$(PYTHON) -m pip install -r requirements-test.txt -q
	@printf "$(GREEN)Dependencies installed.$(NC)\n"

setup: install ## Full bootstrap -- venv + Python test dependencies
	$(call banner,kriegerdataforge-cicd - setup complete)
	@printf "$(YELLOW)Next:$(NC)\n"
	@printf "  1. make ci          # the PR gate -- three lanes\n"
	@printf "  2. make e2e-install # only if you are working on the E2E suite\n"
	@printf "\n"
	@printf "$(YELLOW)This is the only PUBLIC repo -- no real credentials, ever.$(NC)\n"

##@ Static Analysis

.PHONY: lint style

# Skips with an install hint when actionlint is absent, because this is the local
# convenience form. The CI-parity form (ci-lint) deliberately does NOT skip.
lint: ## Lint the GitHub Actions workflows with actionlint
	@printf "$(GREEN)Linting GitHub Actions workflows...$(NC)\n"
	@if command -v actionlint >/dev/null 2>&1; then \
		actionlint; \
		printf "$(GREEN)actionlint passed.$(NC)\n"; \
	else \
		printf "$(YELLOW)actionlint not found -- skipping.$(NC)\n"; \
		printf "$(YELLOW)  brew install actionlint$(NC)\n"; \
	fi

# kdf-fmt owns Python formatting and style (ADR D-003 toolchain split), config in
# kdf-fmt.toml. Baseline-gated: the pre-existing findings in kdf-style-debt.json are
# recorded debt and only NEW violations fail. Installed on demand, pinned from ci.yml.
style: _ensure-venv ## Style check with kdf-fmt (the KDF house style, baseline-gated)
	@printf "$(GREEN)Running kdf-fmt style check...$(NC)\n"
	@$(PYTHON) -c "import kdf_fmt" 2>/dev/null || $(PIP_GIT_AUTH) $(PYTHON) -m pip install --quiet \
		"kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@$(KDF_FMT_VERSION)"
	$(PYTHON) -m kdf_fmt.cli check --no-cache --baseline kdf-style-debt.json

##@ Testing

.PHONY: test test-coverage check-all

# Plain run, matching what ci.yml's test job does. Coverage lives in test-coverage:
# this target used to run --cov, so `make test` and the CI job silently did different
# things -- the local one slower, and able to fail on coverage config CI never touched.
test: _ensure-venv ## Run the Python script unit tests
	@printf "$(GREEN)Running Python unit tests...$(NC)\n"
	cd scripts && $(CURDIR)/$(PYTHON) -m pytest tests/ --tb=short

# Exclusions live in scripts/.coveragerc, not on the command line: `--cov-omit` is not
# a pytest-cov option, so passing it made pytest exit 4.
test-coverage: _ensure-venv ## Run the unit tests with a coverage report
	@printf "$(GREEN)Running Python unit tests with coverage...$(NC)\n"
	cd scripts && $(CURDIR)/$(PYTHON) -m pytest tests/ --cov=. --cov-report=term-missing

check-all: lint style test ## Run all local checks (lint + style + test)
	@printf "$(GREEN)All checks passed!$(NC)\n"

##@ CI (local parity with GitHub Actions)

.PHONY: ci-lint ci-style ci-unit-tests ci-version-check ci

# The PR gate -- green locally before you push. These mirror ci.yml's jobs one for one,
# including version-check: bump-version-check.yml runs the same scripts/common/
# check_version.py that `make ci-version-check` runs here.
#
# This target did not exist before 2026-08-09, while CLAUDE.md, AGENTS.md, WORKFLOW.md,
# DEFINITION_OF_DONE.md, the PR template and the agent-kit onboarding template all
# instructed contributors to get `make ci` green. In the repo that hands that instruction
# to every other repo.

# No skip-if-missing guard here, unlike `lint`: CI installs actionlint, so a lane that
# quietly passed when the tool was absent would be worse than no lane at all.
ci-lint: ## CI: actionlint over the workflows -- mirrors ci.yml lint
	@printf "$(GREEN)CI [1/4]: actionlint...$(NC)\n"
	actionlint

ci-style: _ensure-venv ## CI: kdf-fmt style check -- mirrors ci.yml style
	@printf "$(GREEN)CI [2/4]: kdf-fmt style...$(NC)\n"
	@$(PYTHON) -c "import kdf_fmt" 2>/dev/null || $(PIP_GIT_AUTH) $(PYTHON) -m pip install --quiet \
		"kdf-fmt @ git+https://github.com/Needless2Say/kriegerdataforge-fmt.git@$(KDF_FMT_VERSION)"
	$(PYTHON) -m kdf_fmt.cli check --no-cache --baseline kdf-style-debt.json

ci-unit-tests: _ensure-venv ## CI: pytest over scripts/tests -- mirrors ci.yml test
	@printf "$(GREEN)CI [3/4]: pytest...$(NC)\n"
	cd scripts && $(CURDIR)/$(PYTHON) -m pip install -r requirements-test.txt -q
	cd scripts && $(CURDIR)/$(PYTHON) -m pytest tests/ --tb=short

# Mirrors the CI version-check job via the SAME script CI runs (scripts/common/
# check_version.py): version-file consistency + the STRICT single-increment rule
# (exactly one patch/minor/major step vs origin/$(BASE_BRANCH) -- a 0.10.6 -> 0.10.8
# jump fails). The script warns-and-skips the increment check when the base ref is
# not fetchable locally, because a missing ref is a checkout problem, not a version
# problem -- CI still enforces it either way.
ci-version-check: _ensure-venv ## CI: version consistency + strict +1 increment vs origin/$(BASE_BRANCH)
	@printf "$(GREEN)CI [4/4]: version check...$(NC)\n"
	@PYTHONUTF8=1 $(PYTHON) scripts/common/check_version.py --base-branch "$(BASE_BRANCH)"
ci: ci-lint ci-style ci-unit-tests ci-version-check ## Run all CI checks locally
	@printf "$(GREEN)========================================$(NC)\n"
	@printf "$(GREEN)  All CI checks passed!$(NC)\n"
	@printf "$(GREEN)========================================$(NC)\n"

##@ End-to-End (Playwright)

.PHONY: e2e-install e2e-up e2e-down e2e-seed-user e2e-typecheck e2e \
        e2e-ci-up e2e-ci e2e-ci-down e2e-ci-logs

# The Tier-2 suite drives the real ecosystem stack in a browser. See e2e/README.md.
# Kept out of check-all and ci so the fast gate stays fast.

e2e-install: ## Install the E2E dependencies + Playwright chromium (in e2e/)
	cd e2e && npm ci && npx playwright install --with-deps chromium

# docker-up-full, NOT docker-up. Under the ecosystem ladder rule `docker-up` starts a
# repo's own layer and everything BELOW it, so in fitness-app-frontend that is frontend
# + backend + db + minio and NOTHING ELSE. `-full` is what adds the hub (KDF backend +
# auth UI). With plain docker-up, e2e-seed-user's `docker exec kdf-api` had no container
# and the OIDC login journey had no auth UI to log in against. e2e-down was already
# cascading the whole ladder, which is what made the asymmetry visible.
e2e-up: ## Bring the FULL local stack up -- hub + auth UI + fitness be/fe
	@printf "$(GREEN)Bringing up the full stack (hub + auth UI + fitness be/fe)...$(NC)\n"
	$(FITNESS_FE) docker-up-full

e2e-down: ## Stop the full local stack
	-$(FITNESS_FE) docker-stop

e2e-seed-user: ## Seed the deterministic active test user (e2e-user) in the running hub
	docker exec kdf-api python -c "from api.auth.service import AuthDatabaseService as S; from api.auth.schemas import RegisterRequest as R; svc=S(); print('e2e-user already exists') if svc.get_user_by_username('e2e-user') else print('created id=%s' % svc.create_user(R(username='e2e-user', password='E2eTest123!', email='e2e-user@example.com'), auto_activate=True).id)"

e2e-typecheck: ## Type-check the E2E suite (stages every journey's spec, then tsc)
	$(PY_SYS) e2e/ci_stack.py stage --all
	cd e2e && npx tsc --noEmit

e2e: ## Run the Playwright E2E suite (stack must be up; stages JOURNEY's specs first)
	$(PY_SYS) e2e/ci_stack.py stage --journey "$(JOURNEY)"
	cd e2e && E2E_USERNAME="$${E2E_USERNAME:-e2e-user}" E2E_PASSWORD="$${E2E_PASSWORD:-E2eTest123!}" npm test

# The self-contained stack: ci_stack.py builds every service from source, generates
# ephemeral keys + OIDC creds, and migrates + seeds the databases. No .env.local and no
# bind mounts, which is why CI can use it -- each repo's e2e.yml runs this via the
# run-e2e composite action.

e2e-ci-up: ## Build+up the SELF-CONTAINED stack from source, migrate + seed (leaves it up)
	$(PY_SYS) e2e/ci_stack.py up

e2e-ci: e2e-ci-up ## Self-contained stack: build+up+seed, run Playwright, then tear down
	cd e2e && E2E_USERNAME="e2e-user" E2E_PASSWORD="E2eTest123!" npm test; status=$$?; $(PY_SYS) ci_stack.py down; exit $$status

e2e-ci-down: ## Tear down the self-contained stack (containers, volumes, network)
	$(PY_SYS) e2e/ci_stack.py down

e2e-ci-logs: ## Tail logs from the self-contained stack (SERVICE=<name> optional)
	$(PY_SYS) e2e/ci_stack.py logs $(SERVICE)

##@ Versioning & Release

.PHONY: bump-patch bump-minor bump-major

# Computes the bump from origin/$(BASE_BRANCH)'s VERSION (falls back to the local file
# with a warning), so a double `make bump-patch` is idempotent instead of stacking to an
# invalid +2 jump. Writes every version target (here: just VERSION), then prints the next
# steps. Open a PR afterwards -- CI's bump-version-check.yml validates the increment.
#
# PYTHONUTF8=1 is parity with the other repos, whose legacy bump scripts printed a U+2705
# that crashes cp1252 on Windows AFTER the files are written. This script is ASCII-only,
# so the prefix is precaution -- it keeps a future emoji from turning a successful bump
# into an apparent failure.
_BUMP := PYTHONUTF8=1 $(PYTHON) scripts/common/bump_version.py --base-branch "$(BASE_BRANCH)"

bump-patch: _ensure-venv ## Bump the patch version (0.0.X) -- updates VERSION
	@$(_BUMP) patch

bump-minor: _ensure-venv ## Bump the minor version (0.X.0) -- updates VERSION
	@$(_BUMP) minor

bump-major: _ensure-venv ## Bump the major version (X.0.0) -- updates VERSION
	@$(_BUMP) major

##@ CodeQL Security Scanning

.PHONY: codeql codeql-db codeql-scan-security codeql-scan-quality codeql-scan-all \
        codeql-scan-security-csv codeql-scan-quality-csv codeql-scan-csv-all

# SARIF opens in VS Code (SARIF Viewer extension); CSV is easier to hand to an AI.

codeql: codeql-db codeql-scan-all ## Build the CodeQL database and run all query suites (mirrors codeql.yml)

codeql-db: _ensure-venv ## Create or refresh the CodeQL database
	$(call banner,CodeQL - building database)
	@mkdir -p $(CODEQL_RESULTS)
	@rm -rf $(CODEQL_DB)
	# venv on PATH: CodeQL's Python autobuild calls a BARE `python`, which on a py-only
	# Windows box hits the Store alias and dies with exit code 9009. $$PWD not $(CURDIR):
	# CURDIR is E:/... and the drive-letter colon splits a :-separated PATH.
	PATH="$$PWD/$(VENV_BIN):$$PATH" codeql database create $(CODEQL_DB) \
		--language=$(CODEQL_LANG) \
		--source-root=. \
		--codescanning-config=.github/codeql/codeql-config.yml
	@printf "$(GREEN)Database created at $(CODEQL_DB)$(NC)\n"

codeql-scan-security: ## Run security-extended queries (SARIF output)
	@printf "$(GREEN)Running CodeQL security scan...$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/python-security-extended.qls" \
		--format=sarif-latest \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd.sarif
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd.sarif$(NC)\n"

codeql-scan-quality: ## Run security-and-quality queries (SARIF output)
	@printf "$(GREEN)Running CodeQL quality scan...$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/python-security-and-quality.qls" \
		--format=sarif-latest \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.sarif
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.sarif$(NC)\n"

codeql-scan-all: codeql-scan-security codeql-scan-quality ## Run all CodeQL query suites (SARIF)

codeql-scan-security-csv: ## Run the security scan (CSV -- easy to hand to an AI)
	@printf "$(GREEN)Running CodeQL security scan (CSV)...$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/python-security-extended.qls" \
		--format=csv \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd.csv
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd.csv$(NC)\n"
	@printf "$(YELLOW)Columns: name, description, severity, message, path, start_line, start_col, end_line, end_col$(NC)\n"

codeql-scan-quality-csv: ## Run the quality scan (CSV)
	@printf "$(GREEN)Running CodeQL quality scan (CSV)...$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/python-security-and-quality.qls" \
		--format=csv \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.csv
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.csv$(NC)\n"

codeql-scan-csv-all: codeql-scan-security-csv codeql-scan-quality-csv ## Run all CodeQL query suites (CSV)

##@ Maintenance

.PHONY: git-setup clean clean-deep

git-setup: ## Install the pre-commit hook (ci-style + ci-lint + gitleaks secret scan)
	@printf "$(GREEN)Setting up git hooks...$(NC)\n"
	@echo "#!/bin/sh" > .git/hooks/pre-commit
	@echo "make ci-style" >> .git/hooks/pre-commit
	@echo "make ci-lint" >> .git/hooks/pre-commit
	@echo "# PL-027: scan staged changes for secrets before they land (CI also enforces post-push)." >> .git/hooks/pre-commit
	@echo "if command -v gitleaks >/dev/null 2>&1; then" >> .git/hooks/pre-commit
	@echo "  gitleaks protect --staged --redact || exit 1" >> .git/hooks/pre-commit
	@echo "else" >> .git/hooks/pre-commit
	@echo "  echo '[git-setup] gitleaks not installed; skipping local secret scan (install: https://github.com/gitleaks/gitleaks, or run: pre-commit install). CI still enforces it.'" >> .git/hooks/pre-commit
	@echo "fi" >> .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit
	@printf "$(GREEN)Git hooks installed!$(NC)\n"

# Removes caches and test artifacts, but keeps the virtual environment intact.
# This is useful for cleaning up the project without losing the Python environment.
clean: ## Remove caches and test artifacts (keeps .venv)
	@printf "$(GREEN)Cleaning up...$(NC)\n"
	rm -rf .pytest_cache scripts/.pytest_cache scripts/.coverage scripts/htmlcov
	find . -type d -name __pycache__ -not -path './.venv/*' -not -path './node_modules/*' -not -path './e2e/node_modules/*' -prune -exec rm -rf {} +
	@printf "$(GREEN)Cleanup complete!$(NC)\n"

# Deliberately NOT guarded by _ensure-venv. This target deletes the venv.
clean-deep: ## Deep clean including virtual environment
	@printf "$(YELLOW)Deep cleaning...$(NC)\n"
	@$(MAKE) clean
	rm -rf .venv/
	@printf "$(GREEN)Deep cleanup complete!$(NC)\n"

