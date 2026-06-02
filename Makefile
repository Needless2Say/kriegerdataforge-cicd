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
        codeql-db codeql-scan-security codeql-scan-quality codeql-scan-all \
        codeql-scan-security-csv codeql-scan-quality-csv codeql-scan-csv-all

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
