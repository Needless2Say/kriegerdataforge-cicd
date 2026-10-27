"""
Tests for scripts/token_repositories.py and the workflows that mint an App token from its list (D-085, design 5.7, row
L19). Each list equals the targets its operation acts on, read through the operation's own selection, and each
workflow lists its repos before its mint and hands that list to the token.
"""
from __future__ import annotations

# standard imports
import json
from pathlib import Path

# third party imports
import distribute_all
import ecosystem_watch as ew
import pytest
import token_repositories as tr
from common.repo_sync import _select_repos

# ======================================================================================================================
# Configuration
# ======================================================================================================================

ROOT      = Path(__file__).resolve().parents[2]
WORKFLOWS = ROOT / ".github" / "workflows"
SCRIPTS   = ROOT / "scripts"
# each workflow whose token reads a computed list, and the list's kind
COMPUTED = {
    "distribute-gh-pat.yml": "secrets GH_PACKAGES_PAT",
    "distribute-kit.yml": 'kit "$REPOS"',
    "ops-distribute-all.yml": 'all "$REPOS"',
    "ops-distribute-kit.yml": 'kit "$REPOS"',
    "ops-distribute-scripts.yml": 'scripts "$REPOS"',
    "ops-rotate-secrets.yml": 'secrets "$SECRETS"',
    "rotate-vercel-tokens.yml": "secrets VERCEL_DEPLOYMENT_TOKEN",
    "ecosystem-watch.yml": "watch",
}


def registry(name: str) -> dict:
    return json.loads((SCRIPTS / name).read_text(encoding = "utf-8"))


def listed(capsys, *argv: str) -> set[str]:
    assert tr.main(list(argv)) == 0
    line = capsys.readouterr().out.strip()
    assert line.startswith("repositories=")
    return set(line.removeprefix("repositories=").split(","))


def names(repos: list[str]) -> set[str]:
    return {repo.split("/", 1)[-1] for repo in repos}

# ======================================================================================================================
# Each list, the operation's own targets
# ======================================================================================================================

@pytest.mark.parametrize(("kind", "file"), [("kit", "kit_registry.json"), ("scripts", "scripts_registry.json")])
@pytest.mark.parametrize("repos", [None, "fitness-app-frontend,Needless2Say/tiffanys-space"])
def test_a_distributes_list_is_its_registrys_filtered_as_repo_sync_filters(capsys, kind, file, repos):
    expected = names([entry["repo"] for entry in _select_repos(registry(file), repos)])
    assert listed(capsys, kind, repos or "") == expected


def test_distribute_alls_list_is_both_registries_merged_as_it_merges_them(capsys):
    merged = distribute_all.merged_entries(registry("kit_registry.json"), registry("scripts_registry.json"))
    assert listed(capsys, "all") == names([entry["repo"] for entry in merged])


def test_a_repos_filter_matching_nothing_fails_as_the_distribute_would():
    with pytest.raises(SystemExit):
        tr.main(["kit", "no-such-repo"])


@pytest.mark.parametrize("entry", registry("secret_registry.json")["secrets"], ids = lambda entry: entry["name"])
def test_a_secrets_list_holds_every_repo_the_rotation_writes_for_it(capsys, entry):
    expected = set()
    for key in ("github_env_secrets", "github_repo_secrets", "retired_github_env_secrets"):
        expected |= names([target["repo"] for target in entry.get(key, [])])
    if not expected:
        with pytest.raises(SystemExit):
            tr.main(["secrets", entry["name"]])
        return
    assert listed(capsys, "secrets", entry["name"]) == expected


def test_all_secrets_and_an_unknown_one(capsys):
    every = set()
    for entry in registry("secret_registry.json")["secrets"]:
        for key in ("github_env_secrets", "github_repo_secrets", "retired_github_env_secrets"):
            every |= names([target["repo"] for target in entry.get(key, [])])
    assert listed(capsys, "secrets", "all") == every
    with pytest.raises(SystemExit):
        tr.main(["secrets", "NO_SUCH_SECRET"])
    with pytest.raises(SystemExit):
        tr.main(["secrets", ""])


def test_the_watchs_list_is_the_repos_ecosystem_watch_reads(capsys):
    assert listed(capsys, "watch") == names(ew.read_registries()[0])


def test_the_oidc_drift_tokens_fixed_list_is_its_manifests_pair():
    manifest = registry("oidc_drift_manifest.json")
    text     = (WORKFLOWS / "check-oidc-rp-drift.yml").read_text(encoding = "utf-8")
    pair     = sorted(names([manifest["left"]["repo"], manifest["right"]["repo"]]))
    assert f"          repositories: {','.join(pair)}\n" in text

# ======================================================================================================================
# Each workflow lists before it mints and hands the list to its token
# ======================================================================================================================

@pytest.mark.parametrize(("workflow", "kind"), sorted(COMPUTED.items()))
def test_each_workflow_lists_its_repos_before_its_mint_and_hands_them_to_the_token(workflow, kind):
    text  = (WORKFLOWS / workflow).read_text(encoding = "utf-8")
    call  = f"scripts/token_repositories.py {kind} >> \"$GITHUB_OUTPUT\"\n"
    mint  = text.index("uses: actions/create-github-app-token@")
    assert call in text and text.index(call) < mint, workflow
    assert "          repositories: ${{ steps.targets.outputs.repositories }}\n" in text[mint:], workflow


@pytest.mark.parametrize("workflow", ["ops-distribute-all.yml", "ops-distribute-kit.yml", "ops-distribute-scripts.yml",
                                      "ops-rotate-secrets.yml"])
def test_an_issue_driven_workflow_mints_only_after_it_reads_the_issues_fields(workflow):
    text = (WORKFLOWS / workflow).read_text(encoding = "utf-8")
    assert text.index("- name: Extract and validate fields") < text.index("uses: actions/create-github-app-token@")
