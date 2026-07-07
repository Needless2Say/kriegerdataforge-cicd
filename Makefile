# =============================================================================
# KriegerDataForge CI/CD — Makefile
# =============================================================================
#
# Targets:
#   help                 — list all targets with descriptions
#   lint                 — lint GitHub Actions workflow files (actionlint)
#   check-all            — run all local checks
#   codeql-db            — create/refresh CodeQL database
#   codeql-scan-security — security-extended scan (SARIF)
#   codeql-scan-quality  — security-and-quality scan (SARIF)
#   codeql-scan-all      — all SARIF scans
#   codeql-scan-*-csv    — CSV variants (easy to share with AI)
#
# Requirements:
#   actionlint — https://github.com/rhysd/actionlint
#                brew install actionlint  OR  go install github.com/rhysd/actionlint/cmd/actionlint@latest
#   codeql     — https://github.com/github/codeql-cli-binaries
# =============================================================================

.DEFAULT_GOAL := help
.PHONY: help lint test check-all \
        bump-patch bump-minor bump-major \
        e2e-install e2e-up e2e-down e2e-seed-user e2e e2e-typecheck \
        e2e-ci-up e2e-ci e2e-ci-down e2e-ci-logs \
        codeql-db codeql-scan-security codeql-scan-quality codeql-scan-all \
        codeql-scan-security-csv codeql-scan-quality-csv codeql-scan-csv-all

ifeq ($(OS),Windows_NT)
    PY3 := py
else
    PY3 := python3
endif

# ── Colors ────────────────────────────────────────────────────────────────────

BLUE   := \033[0;34m
GREEN  := \033[0;32m
YELLOW := \033[1;33m
RED    := \033[0;31m
NC     := \033[0m

# ── Help ──────────────────────────────────────────────────────────────────────

help: ## List all available make targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-30s\033[0m %s\n", $$1, $$2}'

# ── Lint ──────────────────────────────────────────────────────────────────────

lint: ## Lint GitHub Actions workflow files with actionlint
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  Linting GitHub Actions workflows$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	@if command -v actionlint >/dev/null 2>&1; then \
		actionlint; \
		printf "$(GREEN)actionlint passed$(NC)\n"; \
	else \
		printf "$(YELLOW)actionlint not found — skipping (install: brew install actionlint)$(NC)\n"; \
	fi

test: ## Run Python script unit tests with coverage
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  Running Python unit tests$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	cd scripts && pip install -r requirements-test.txt -q && \
		pytest tests/ --cov=. --cov-report=term-missing \
		       --cov-omit="tests/*,backups/*"
	@printf "$(GREEN)Tests passed!$(NC)\n"

check-all: lint test ## Run all local checks
	@printf "$(GREEN)All checks passed!$(NC)\n"

# ── Tier 2 E2E (Playwright) ─────────────────────────────────────────────────────
# The E2E suite drives the real ecosystem stack in a browser. See e2e/README.md.
# Kept out of `check-all` so the fast lint+pytest gate stays quick.

e2e-install: ## Install E2E deps + Playwright chromium (in e2e/)
	cd e2e && npm ci && npx playwright install --with-deps chromium

e2e-up: ## Bring the full local stack up (delegates to fitness-app-frontend)
	@printf "$(BLUE)Bringing up the full stack (hub + auth-UI + fitness be/fe)...$(NC)\n"
	cd ../fitness-app-frontend && $(MAKE) --no-print-directory docker-up

e2e-down: ## Stop the full local stack
	-cd ../fitness-app-frontend && $(MAKE) --no-print-directory docker-stop

e2e-seed-user: ## Seed the deterministic active test user (e2e-user) in the running hub
	docker exec kdf-api python -c "from api.auth.service import AuthDatabaseService as S; from api.auth.schemas import RegisterRequest as R; svc=S(); print('e2e-user already exists') if svc.get_user_by_username('e2e-user') else print('created id=%s' % svc.create_user(R(username='e2e-user', password='E2eTest123!', email='e2e-user@example.com'), auto_activate=True).id)"

e2e-typecheck: ## Type-check the E2E suite (stages every journey's spec, then tsc)
	$(PY3) e2e/ci_stack.py stage --all
	cd e2e && npx tsc --noEmit

# Which journey's specs to stage for `make e2e` (delegated stack = fitness).
# Override, e.g.:  make e2e JOURNEY=tiffanys
JOURNEY ?= fitness

e2e: ## Run the Playwright E2E suite (stack must be up; stages JOURNEY's specs first)
	$(PY3) e2e/ci_stack.py stage --journey "$(JOURNEY)"
	cd e2e && E2E_USERNAME="$${E2E_USERNAME:-e2e-user}" E2E_PASSWORD="$${E2E_PASSWORD:-E2eTest123!}" npm test

# ── Self-contained E2E stack (CI-usable; no .env.local, no bind-mounts) ──────────
# ci_stack.py builds every service from source, generates ephemeral keys + OIDC
# creds, migrates + seeds both DBs. This is what the e2e-compose CI workflow runs.

e2e-ci-up: ## Build+up the SELF-CONTAINED stack from source, migrate + seed (leaves it up)
	$(PY3) e2e/ci_stack.py up

e2e-ci: e2e-ci-up ## Self-contained stack: build+up+seed, run Playwright, then tear down
	cd e2e && E2E_USERNAME="e2e-user" E2E_PASSWORD="E2eTest123!" npm test; status=$$?; $(PY3) ci_stack.py down; exit $$status

e2e-ci-down: ## Tear down the self-contained stack (containers, volumes, network)
	$(PY3) e2e/ci_stack.py down

e2e-ci-logs: ## Tail logs from the self-contained stack (SERVICE=<name> optional)
	$(PY3) e2e/ci_stack.py logs $(SERVICE)

# ── Version Bumping ───────────────────────────────────────────────────────────
# Edits VERSION (and any other version files) then prints next-step instructions.
# Open a PR after running — CI's bump-version-check.yml validates the increment.

bump-patch: ## Bump patch version (0.0.X) and update VERSION
	@$(PY3) scripts/common/bump_version.py patch

bump-minor: ## Bump minor version (0.X.0) and update VERSION
	@$(PY3) scripts/common/bump_version.py minor

bump-major: ## Bump major version (X.0.0) and update VERSION
	@$(PY3) scripts/common/bump_version.py major

# ── CodeQL Security Scanning ──────────────────────────────────────────────────
# Language: javascript-typescript — scans any JS/TS scripts that get added.
# When this repo grows to include more source files, update CODEQL_LANG
# and CODEQL_PACK accordingly.

CODEQL_DB      := ../codeql/codeql-dbs/kriegerdataforge-cicd
CODEQL_RESULTS := ../codeql/codeql-results
CODEQL_LANG    := javascript-typescript
CODEQL_PACK    := codeql/javascript-queries

codeql-db: ## Create or refresh the CodeQL database
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  CodeQL — Building Database$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	@rm -rf $(CODEQL_DB)
	codeql database create $(CODEQL_DB) \
		--language=$(CODEQL_LANG) \
		--source-root=.
	@printf "$(GREEN)Database created at $(CODEQL_DB)$(NC)\n"

codeql-scan-security: ## Run security-extended queries (SARIF output)
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  CodeQL — Security Scan$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/javascript-security-extended.qls" \
		--format=sarif-latest \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd.sarif
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd.sarif$(NC)\n"

codeql-scan-quality: ## Run security-and-quality queries (SARIF output)
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  CodeQL — Quality Scan$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/javascript-security-and-quality.qls" \
		--format=sarif-latest \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.sarif
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.sarif$(NC)\n"

codeql-scan-all: codeql-scan-security codeql-scan-quality ## Run all CodeQL query suites (SARIF)

codeql-scan-security-csv: ## Run security scan (CSV — easy to share with AI for fix suggestions)
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  CodeQL — Security Scan (CSV)$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/javascript-security-extended.qls" \
		--format=csv \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd.csv
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd.csv$(NC)\n"
	@printf "$(YELLOW)Columns: name, description, severity, message, path, start_line, start_col, end_line, end_col$(NC)\n"
	@printf "$(YELLOW)Paste this file into an AI chat to get fix suggestions$(NC)\n"

codeql-scan-quality-csv: ## Run quality scan (CSV)
	@printf "$(BLUE)========================================$(NC)\n"
	@printf "$(BLUE)  CodeQL — Quality Scan (CSV)$(NC)\n"
	@printf "$(BLUE)========================================$(NC)\n"
	@mkdir -p $(CODEQL_RESULTS)
	codeql database analyze $(CODEQL_DB) \
		"$(CODEQL_PACK):codeql-suites/javascript-security-and-quality.qls" \
		--format=csv \
		--output=$(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.csv
	@printf "$(GREEN)Results saved to $(CODEQL_RESULTS)/kriegerdataforge-cicd-quality.csv$(NC)\n"
	@printf "$(YELLOW)Columns: name, description, severity, message, path, start_line, start_col, end_line, end_col$(NC)\n"

codeql-scan-csv-all: codeql-scan-security-csv codeql-scan-quality-csv ## Run all CodeQL query suites (CSV)
