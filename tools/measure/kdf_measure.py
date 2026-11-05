"""
The measure, a read only account of where each secret and rule sits, by name and setting alone.

The owner runs it with their own `gh` login, from a worktree at `origin/main`, and keeps its output, so a later run
is compared with it line by line. For every repository the login owns, or each one `--repo` names, it reads the
visibility and default branch, the Actions settings, the secrets and variables by name, each environment with its
branch rule, its reviewers, the admin bypass and its secrets and variables by name, the protection of `main` and of
the default branch, the rules that reach `main`, every ruleset, the collaborators with their roles, the pending
invitations and the deploy keys. Then every GitHub App installation the login can see, with the App's id, its
permissions and repositories, and the login's own plan and scopes, and whether the account's plan offers rulesets and
the admin bypass switch on a private repository.

It never prints a value. Each line is built from the fields named here alone, so a variable's value and a deploy
key's public key never reach a line, and webhooks are not read at all, since a hook's URL may carry a credential.
Before anything is printed the whole output is checked for the shape of a credential, a GitHub token, a private key,
a JSON web token, a URL with a password, a long base64 run or a long run of mixed case letters and digits with no
separator, and it is refused whole when one appears, naming the line by its number, its opening words and the shape
alone. Every call goes through `gh api`, so the login's
token stays inside `gh` and never passes through this script.

Exit status 0, every read answered. 1, a read was refused or failed, each named by an `unreadable` line. 2, the
output was refused for a credential's shape and nothing was printed. 3, `gh` could not run or the login could not be
read.

Usage:
    python tools/measure/kdf_measure.py > measure.txt
    python tools/measure/kdf_measure.py --repo kriegerdataforge-cicd --repo kriegerdataforge-context
    python tools/measure/kdf_measure.py --login-only

Requirements: standard library only, and the GitHub CLI signed in.
"""

from __future__ import annotations

# standard imports
import argparse
import datetime
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TextIO
from urllib.parse import quote

# ======================================================================================================================
# Configuration
# ======================================================================================================================

MEASURE_VERSION = 1
PAGE_SIZE       = 100
MAX_PAGES       = 50
# the statuses a list read reports beside GitHub's own, a body that is not the expected shape, and a list cut short
MALFORMED = -1
TRUNCATED = -2
# the branch whose protection and rules are read in every repository, beside its default branch when that differs
PROTECTED_BRANCH = "main"
# the words GitHub answers with when the account's plan does not offer a feature on a private repository
UPGRADE_WORDS = ("upgrade to github pro", "make this repository public")
# one GET by its path, answered as a Response, gh in a run and a fake in the tests
Fetch = Callable[[str], "Response"]

# the shapes of a credential that refuse the whole output, each named, so a refusal names the shape and never the text
VALUE_SHAPES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("a GitHub token", re.compile(r"(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("a private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY")),
    ("a JSON web token", re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.")),
    ("a URL with a password", re.compile(r"[A-Za-z][A-Za-z0-9+.-]*://[^\s/:@]+:[^\s/@]+@")),
    # a separator splits a run, so owner/repo-name and a hyphenated title read as short pieces, never one run
    (
        "a long base64 run",
        re.compile(r"(?=[A-Za-z0-9+/]*[a-z])(?=[A-Za-z0-9+/]*[A-Z])(?=[A-Za-z0-9+/]*[0-9])[A-Za-z0-9+/]{40,}"),
    ),
    (
        "a long run of mixed case letters and digits",
        re.compile(r"(?=[A-Za-z0-9]*[a-z])(?=[A-Za-z0-9]*[A-Z])(?=[A-Za-z0-9]*[0-9])[A-Za-z0-9]{24,}"),
    ),
)
# the leading words of a refused line a refusal names, so the line is found without printing it
OPENING_WORDS = 2

# ======================================================================================================================
# Reading GitHub through gh
# ======================================================================================================================

@dataclass
class Response:
    """
    One answer from GitHub, its status, its headers with their names in lower case, and its parsed body.
    """
    status:  int
    headers: dict[str, str] = field(default_factory = dict)
    body:    object = None


    def message(self) -> str:
        """
        GitHub's own message on a refused read, in lower case.

        Returns:
            The message, or an empty string when the body holds none
        """
        if isinstance(self.body, dict):
            return str(self.body.get("message", "")).lower()
        return ""


class GhUnavailable(Exception):
    """
    `gh` could not be run, or it answered with nothing at all.
    """


def parse_include(text: str) -> Response:
    """
    Parse what `gh api --include` writes, a status line, the headers, a blank line and the body.

    Args:
        text: The whole of what gh wrote

    Returns:
        The status, the headers and the body, None when the body is empty or not JSON

    Raises:
        GhUnavailable: When the text opens with no status line
    """
    normalized = text.replace("\r\n", "\n")
    head, _, rest = normalized.partition("\n\n")
    head_lines   = head.split("\n")
    status_match = re.match(r"HTTP/\S+\s+(\d{3})", head_lines[0]) if head_lines else None
    if status_match is None:
        raise GhUnavailable("gh answered without a status line")
    headers: dict[str, str] = {}
    for header_line in head_lines[1:]:
        name, separator, content = header_line.partition(":")
        if separator:
            headers[name.strip().lower()] = content.strip()
    body: object = None
    if rest.strip():
        try:
            body = json.loads(rest)
        except json.JSONDecodeError:
            body = None
    return Response(status = int(status_match.group(1)), headers = headers, body = body)


def gh_fetch(path: str, *, run: Callable[..., subprocess.CompletedProcess] = subprocess.run) -> Response:
    """
    One GET through `gh api --include`, so the login's token stays inside `gh`.

    Args:
        path: The API path with its query, such as repos/owner/name/environments?per_page=100&page=1
        run: The process runner, subprocess.run in a run and a stand in for the tests

    Returns:
        GitHub's answer, a refused read included

    Raises:
        GhUnavailable: When gh cannot be run or writes nothing
    """
    try:
        completed = run(
            ["gh", "api", "--include", "--method", "GET", path],
            capture_output = True,
            text = True,
            encoding = "utf-8",
            check = False,
        )
    except OSError as error:
        raise GhUnavailable(f"gh could not be run, {type(error).__name__}") from None
    if not completed.stdout:
        raise GhUnavailable("gh answered with nothing, so it may not be signed in")
    return parse_include(completed.stdout)


def fetch_list(fetch: Fetch, path: str, key: str | None = None) -> tuple[list, int]:
    """
    Every item of a listed endpoint, page by page.

    A wrapped list, one with a `total_count`, ends when the count is reached, since some endpoints cap a page below
    the size asked for. A bare list ends at a page shorter than the size asked for, and either ends at an empty page.

    Args:
        fetch: The GET to use
        path: The endpoint's path, with or without a query
        key: The field that holds a wrapped list's items, None for a bare list

    Returns:
        The items read and 200, or the items read so far and the status that stopped them
    """
    items: list = []
    separator = "&" if "?" in path else "?"
    for page in range(1, MAX_PAGES + 1):
        response = fetch(f"{path}{separator}per_page={PAGE_SIZE}&page={page}")
        if response.status != 200:
            return items, response.status
        body  = response.body
        batch = body.get(key) if key is not None and isinstance(body, dict) else body
        if not isinstance(batch, list):
            return items, MALFORMED
        items.extend(batch)
        total = body.get("total_count") if key is not None and isinstance(body, dict) else None
        if not batch:
            return items, 200
        if isinstance(total, int) and len(items) >= total:
            return items, 200
        if total is None and len(batch) < PAGE_SIZE:
            return items, 200
    return items, TRUNCATED

# ======================================================================================================================
# Writing a line
# ======================================================================================================================

def word(value: object) -> str:
    """
    One field's text as a line shows it.

    Args:
        value: The field's value, None, a bool, a list or any value with a text form

    Returns:
        A hyphen for None or an empty list, a list's words sorted and joined by commas, and text with a space, an
        equals sign, a quote or an unprintable character quoted as JSON
    """
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        parts = sorted(word(part) for part in value)
        return ",".join(parts) if parts else "-"
    text = str(value)
    if not text:
        return '""'
    if re.search(r'[\s="]', text) or not text.isprintable():
        return json.dumps(text)
    return text


def line_of(*parts: object, **fields: object) -> str:
    """
    One line, its leading words then each named field.

    Args:
        parts: The words that say what the line describes
        fields: The settings, each printed as name=value

    Returns:
        The line
    """
    words = [word(part) for part in parts]
    words.extend(f"{name}={word(value)}" for name, value in fields.items())
    return " ".join(words)


def number_of(value: object) -> int:
    """
    An id as a number for sorting.

    Args:
        value: The id as GitHub gave it

    Returns:
        The number, or 0 when it is not one
    """
    try:
        return int(str(value))
    except ValueError:
        return 0


def status_word(status: int) -> str:
    """
    A status as a line shows it.

    Args:
        status: GitHub's status, or MALFORMED or TRUNCATED

    Returns:
        GitHub's number, or the name of the script's own stop
    """
    if status == MALFORMED:
        return "malformed"
    if status == TRUNCATED:
        return "truncated"
    return str(status)


def find_value_shape(lines: list[str]) -> tuple[int, str] | None:
    """
    The first line that holds a credential's shape.

    Args:
        lines: Every line of the output

    Returns:
        The line's number, counted from 1, and the shape's name, or None when no line holds one
    """
    for number, text in enumerate(lines, start = 1):
        for name, pattern in VALUE_SHAPES:
            if pattern.search(text):
                return number, name
    return None


def refusal(lines: list[str], number: int, shape: str) -> str:
    """
    The message for a refused output, naming the line by its number and its opening words, and never its text.

    Args:
        lines: Every line of the output
        number: The refused line's number, counted from 1
        shape: The name of the shape the line holds

    Returns:
        The message, which leaves the opening words out when they hold a shape themselves
    """
    opening = " ".join(lines[number - 1].split(" ")[:OPENING_WORDS])
    if find_value_shape([opening]) is not None:
        return f"Refused, line {number} holds the shape of {shape}, so nothing is printed.\n"
    return f"Refused, line {number}, opening {opening}, holds the shape of {shape}, so nothing is printed.\n"

# ======================================================================================================================
# The measure
# ======================================================================================================================

@dataclass
class Measure:
    """
    The lines of one run, the count of reads that failed, and what the private repositories showed of the plan.
    """
    fetch:            Fetch
    lines:            list[str] = field(default_factory = list)
    unreadable:       int = 0
    private_rulesets: set[str] = field(default_factory = set)
    private_bypass:   set[str] = field(default_factory = set)


    def add(self, *parts: object, **fields: object) -> None:
        """
        Add one line.

        Args:
            parts: The words that say what the line describes
            fields: The settings, each printed as name=value
        """
        self.lines.append(line_of(*parts, **fields))


    def fail(self, *parts: object, status: int) -> None:
        """
        Add an `unreadable` line for a read that failed, and count it.

        Args:
            parts: The words that say what could not be read
            status: The status that stopped the read
        """
        self.unreadable += 1
        self.add("unreadable", *parts, status = status_word(status))


    def list_or_fail(self, path: str, key: str | None, *parts: object) -> list[dict] | None:
        """
        A listed endpoint's objects, or an `unreadable` line naming it.

        Args:
            path: The endpoint's path
            key: The field that holds a wrapped list's items, None for a bare list
            parts: The words that name the list in an `unreadable` line

        Returns:
            The objects read, or None when the read failed
        """
        items, status = fetch_list(self.fetch, path, key)
        if status != 200:
            self.fail(*parts, status = status)
            return None
        return [item for item in items if isinstance(item, dict)]


def unavailable(response: Response) -> bool:
    """
    Whether GitHub refused a read because the plan does not offer the feature on a private repository.

    Args:
        response: GitHub's answer

    Returns:
        True when the answer is a 403 or 404 whose message asks for an upgrade or a public repository
    """
    return response.status in (403, 404) and any(words in response.message() for words in UPGRADE_WORDS)


def read_login(fetch: Fetch) -> tuple[str, str]:
    """
    The login, its plan and the scopes of the token `gh` holds.

    Args:
        fetch: The GET to use

    Returns:
        The login's name and its line

    Raises:
        GhUnavailable: When the login cannot be read
    """
    response = fetch("user")
    if response.status != 200 or not isinstance(response.body, dict) or not response.body.get("login"):
        raise GhUnavailable(f"the login could not be read, status {status_word(response.status)}")
    login      = str(response.body["login"])
    plan       = response.body.get("plan")
    plan_name  = plan.get("name") if isinstance(plan, dict) else None
    scope_text = response.headers.get("x-oauth-scopes")
    scopes     = [scope.strip() for scope in scope_text.split(",") if scope.strip()] if scope_text is not None else None
    return login, line_of("login", login, plan = plan_name, scopes = scopes)


def read_repositories(measure: Measure, login: str, names: list[str]) -> list[dict]:
    """
    The repositories to measure.

    Args:
        measure: The run
        login: The login whose repositories are read
        names: The repositories named, by name or owner/name, or none for every one the login owns

    Returns:
        Each repository as GitHub describes it, sorted by name
    """
    if not names:
        owned = measure.list_or_fail("user/repos?affiliation=owner", None, "repositories")
        if owned is None:
            return []
        mine = [repo for repo in owned if (repo.get("owner") or {}).get("login") == login]
        return sorted(mine, key = lambda repo: str(repo.get("name", "")).lower())
    chosen: list[dict] = []
    for name in sorted(set(names), key = str.lower):
        full_name = name if "/" in name else f"{login}/{name}"
        response  = measure.fetch(f"repos/{full_name}")
        if response.status != 200 or not isinstance(response.body, dict):
            measure.fail("repo", full_name, status = response.status)
            continue
        chosen.append(response.body)
    return chosen


def measure_actions(measure: Measure, slug: str, name: str) -> None:
    """
    Whether Actions runs, what it may run, and what a workflow's own token may do by default.

    Args:
        measure: The run
        slug: The repository as owner/name
        name: The repository's name, as its lines show it
    """
    actions = measure.fetch(f"repos/{slug}/actions/permissions")
    if actions.status == 200 and isinstance(actions.body, dict):
        measure.add(
            "repo",
            name,
            "actions",
            enabled = actions.body.get("enabled"),
            allowed = actions.body.get("allowed_actions"),
        )
    else:
        measure.fail("repo", name, "actions", status = actions.status)
    workflow = measure.fetch(f"repos/{slug}/actions/permissions/workflow")
    if workflow.status == 200 and isinstance(workflow.body, dict):
        measure.add(
            "repo",
            name,
            "workflow_token",
            default = workflow.body.get("default_workflow_permissions"),
            approves_pull_requests = workflow.body.get("can_approve_pull_request_reviews"),
        )
    else:
        measure.fail("repo", name, "workflow_token", status = workflow.status)


def measure_names(measure: Measure, path: str, key: str, *parts: object) -> None:
    """
    The names alone of a secrets or variables list, one line each.

    Args:
        measure: The run
        path: The list's path
        key: The field that holds the list's items
        parts: The words each line opens with
    """
    items = measure.list_or_fail(path, key, *parts)
    if items is None:
        return
    for name in sorted(str(item.get("name", "")) for item in items):
        measure.add(*parts, name)


def environment_rule(environment: dict) -> str:
    """
    An environment's branch rule in one word.

    Args:
        environment: The environment as GitHub describes it

    Returns:
        any, protected, selected, or unknown for a policy of no known form
    """
    policy = environment.get("deployment_branch_policy")
    if not isinstance(policy, dict):
        return "any"
    if policy.get("protected_branches"):
        return "protected"
    if policy.get("custom_branch_policies"):
        return "selected"
    return "unknown"


def environment_reviewers(environment: dict) -> tuple[list[str], object, object]:
    """
    An environment's required reviewers, whether self review is prevented, and its wait timer.

    Args:
        environment: The environment as GitHub describes it

    Returns:
        The reviewers as type:login, the self review flag or None, and the wait timer in minutes
    """
    reviewers:    list[str] = []
    prevent_self: object = None
    wait_timer:   object = 0
    for rule in environment.get("protection_rules") or []:
        if not isinstance(rule, dict):
            continue
        if rule.get("type") == "required_reviewers":
            prevent_self = rule.get("prevent_self_review")
            for entry in rule.get("reviewers") or []:
                reviewer = entry.get("reviewer") if isinstance(entry, dict) else None
                if isinstance(reviewer, dict):
                    reviewers.append(f"{entry.get('type')}:{reviewer.get('login') or reviewer.get('slug')}")
        if rule.get("type") == "wait_timer":
            wait_timer = rule.get("wait_timer")
    return reviewers, prevent_self, wait_timer


def measure_environments(measure: Measure, slug: str, name: str, private: bool) -> None:
    """
    Each environment's rules, its branch policies and its secrets and variables by name.

    Args:
        measure: The run
        slug: The repository as owner/name
        name: The repository's name, as its lines show it
        private: Whether the repository is private, so its answers tell what the plan offers
    """
    environments = measure.list_or_fail(f"repos/{slug}/environments", "environments", "repo", name, "environments")
    if environments is None:
        return
    for environment in sorted(environments, key = lambda env: str(env.get("name", ""))):
        env_name   = str(environment.get("name", ""))
        env_path   = f"repos/{slug}/environments/{quote(env_name, safe = '')}"
        has_switch = "can_admins_bypass" in environment
        if private:
            measure.private_bypass.add("present" if has_switch else "absent")
        rule = environment_rule(environment)
        reviewers, prevent_self, wait_timer = environment_reviewers(environment)
        measure.add(
            "repo",
            name,
            "environment",
            env_name,
            admin_bypass = environment.get("can_admins_bypass") if has_switch else "absent",
            branch_rule = rule,
            reviewers = reviewers,
            prevent_self_review = prevent_self,
            wait_timer = wait_timer,
        )
        if rule == "selected":
            where    = ("repo", name, "environment", env_name)
            policies = measure.list_or_fail(
                f"{env_path}/deployment-branch-policies",
                "branch_policies",
                *where,
                "policies",
            )
            for policy in sorted(policies or [], key = lambda item: (str(item.get("type")), str(item.get("name")))):
                measure.add(*where, "policy", policy.get("type") or "branch", policy.get("name"))
        measure_names(measure, f"{env_path}/secrets", "secrets", "repo", name, "environment", env_name, "secret")
        measure_names(measure, f"{env_path}/variables", "variables", "repo", name, "environment", env_name, "variable")


def enabled(section: object) -> object:
    """
    The `enabled` flag of a protection section.

    Args:
        section: The section as GitHub describes it, or None when absent

    Returns:
        The flag, or None when the section is absent
    """
    return section.get("enabled") if isinstance(section, dict) else None


def actor_names(section: object) -> list[str]:
    """
    The users, teams and apps a protection section names.

    Args:
        section: The section as GitHub describes it, or None when absent

    Returns:
        Each as user:login, team:slug or app:slug
    """
    if not isinstance(section, dict):
        return []
    names: list[str] = []
    for kind in ("users", "teams", "apps"):
        for actor in section.get(kind) or []:
            if isinstance(actor, dict):
                names.append(f"{kind[:-1]}:{actor.get('login') or actor.get('slug')}")
    return names


def measure_protection(measure: Measure, slug: str, name: str, branch: str, private: bool) -> None:
    """
    The classic protection of one branch, every setting by name, none when the branch has none.

    Args:
        measure: The run
        slug: The repository as owner/name
        name: The repository's name, as its lines show it
        branch: The branch to read
        private: Whether the repository is private, so a refusal for the plan reads as unavailable
    """
    response = measure.fetch(f"repos/{slug}/branches/{quote(branch, safe = '')}/protection")
    if response.status == 404 and "not protected" in response.message():
        measure.add("repo", name, "protection", branch, "none")
        return
    if private and unavailable(response):
        measure.add("repo", name, "protection", branch, "unavailable")
        return
    if response.status != 200 or not isinstance(response.body, dict):
        measure.fail("repo", name, "protection", branch, status = response.status)
        return
    body    = response.body
    reviews = body.get("required_pull_request_reviews")
    reviews = reviews if isinstance(reviews, dict) else None
    checks  = body.get("required_status_checks")
    checks  = checks if isinstance(checks, dict) else None
    measure.add(
        "repo",
        name,
        "protection",
        branch,
        pull_request = reviews is not None,
        approvals = reviews.get("required_approving_review_count") if reviews else None,
        dismiss_stale = reviews.get("dismiss_stale_reviews") if reviews else None,
        code_owners = reviews.get("require_code_owner_reviews") if reviews else None,
        last_push_approval = reviews.get("require_last_push_approval") if reviews else None,
        pull_request_bypass = actor_names(reviews.get("bypass_pull_request_allowances") if reviews else None),
        checks_strict = checks.get("strict") if checks else None,
        checks = checks.get("contexts") if checks else None,
        enforce_admins = enabled(body.get("enforce_admins")),
        force_pushes = enabled(body.get("allow_force_pushes")),
        deletions = enabled(body.get("allow_deletions")),
        linear_history = enabled(body.get("required_linear_history")),
        conversation_resolution = enabled(body.get("required_conversation_resolution")),
        signatures = enabled(body.get("required_signatures")),
        lock_branch = enabled(body.get("lock_branch")),
        push_restrictions = actor_names(body.get("restrictions")),
    )


def bypass_names(ruleset: dict) -> list[str]:
    """
    Who may bypass a ruleset.

    Args:
        ruleset: The ruleset as GitHub describes it

    Returns:
        Each actor as type:id:mode
    """
    names: list[str] = []
    for actor in ruleset.get("bypass_actors") or []:
        if isinstance(actor, dict):
            names.append(f"{actor.get('actor_type')}:{actor.get('actor_id')}:{actor.get('bypass_mode')}")
    return names


def measure_rulesets(measure: Measure, slug: str, name: str, private: bool) -> None:
    """
    The rules that reach `main`, then every ruleset with its target, its refs, its rules and who may bypass it.

    Args:
        measure: The run
        slug: The repository as owner/name
        name: The repository's name, as its lines show it
        private: Whether the repository is private, so its answer tells whether the plan offers rulesets
    """
    branch_rules = measure.list_or_fail(
        f"repos/{slug}/rules/branches/{PROTECTED_BRANCH}",
        None,
        "repo",
        name,
        "branch_rules",
        PROTECTED_BRANCH,
    )
    for rule in sorted(branch_rules or [], key = lambda item: (str(item.get("type")), str(item.get("ruleset_id")))):
        measure.add(
            "repo",
            name,
            "branch_rule",
            PROTECTED_BRANCH,
            rule.get("type"),
            ruleset = rule.get("ruleset_id"),
            source = rule.get("ruleset_source"),
        )
    if private and unavailable(measure.fetch(f"repos/{slug}/rulesets?per_page={PAGE_SIZE}&page=1")):
        measure.private_rulesets.add("no")
        measure.add("repo", name, "rulesets", "unavailable")
        return
    rulesets = measure.list_or_fail(f"repos/{slug}/rulesets", None, "repo", name, "rulesets")
    if rulesets is None:
        return
    if private:
        measure.private_rulesets.add("yes")
    for summary in sorted(rulesets, key = lambda item: number_of(item.get("id"))):
        ruleset_id = summary.get("id")
        detail     = measure.fetch(f"repos/{slug}/rulesets/{ruleset_id}")
        if detail.status != 200 or not isinstance(detail.body, dict):
            measure.fail("repo", name, "ruleset", ruleset_id, status = detail.status)
            continue
        body       = detail.body
        conditions = body.get("conditions") if isinstance(body.get("conditions"), dict) else {}
        ref_name   = conditions.get("ref_name") if isinstance(conditions.get("ref_name"), dict) else {}
        measure.add(
            "repo",
            name,
            "ruleset",
            ruleset_id,
            name = body.get("name"),
            target = body.get("target"),
            enforcement = body.get("enforcement"),
            source = body.get("source_type"),
            include = ref_name.get("include"),
            exclude = ref_name.get("exclude"),
            rules = [rule.get("type") for rule in body.get("rules") or [] if isinstance(rule, dict)],
            bypass = bypass_names(body),
        )


def measure_people(measure: Measure, slug: str, name: str) -> None:
    """
    Who can reach the repository, its collaborators with their roles, the pending invitations and the deploy keys.

    Args:
        measure: The run
        slug: The repository as owner/name
        name: The repository's name, as its lines show it
    """
    collaborators = measure.list_or_fail(
        f"repos/{slug}/collaborators?affiliation=all",
        None,
        "repo",
        name,
        "collaborators",
    )
    for person in sorted(collaborators or [], key = lambda item: str(item.get("login", "")).lower()):
        measure.add("repo", name, "collaborator", person.get("login"), role = person.get("role_name"))
    invitations = measure.list_or_fail(f"repos/{slug}/invitations", None, "repo", name, "invitations")
    for invitation in sorted(invitations or [], key = lambda item: str((item.get("invitee") or {}).get("login"))):
        invitee = invitation.get("invitee") if isinstance(invitation.get("invitee"), dict) else {}
        measure.add("repo", name, "invitation", invitee.get("login"), permission = invitation.get("permissions"))
    keys = measure.list_or_fail(f"repos/{slug}/keys", None, "repo", name, "deploy_keys")
    for key in sorted(keys or [], key = lambda item: str(item.get("title", ""))):
        measure.add("repo", name, "deploy_key", key.get("title"), read_only = key.get("read_only"))


def measure_repository(measure: Measure, repo: dict) -> None:
    """
    Every reading of one repository, in a fixed order, so two runs over the same settings print the same lines.

    Args:
        measure: The run
        repo: The repository as GitHub describes it
    """
    name           = str(repo.get("name", ""))
    slug           = str(repo.get("full_name", name))
    private        = bool(repo.get("private"))
    default_branch = str(repo.get("default_branch") or PROTECTED_BRANCH)
    measure.add(
        "repo",
        name,
        visibility = repo.get("visibility") or ("private" if private else "public"),
        default_branch = default_branch,
        archived = repo.get("archived"),
        fork = repo.get("fork"),
    )
    measure_actions(measure, slug, name)
    measure_names(measure, f"repos/{slug}/actions/secrets", "secrets", "repo", name, "secret")
    measure_names(measure, f"repos/{slug}/actions/variables", "variables", "repo", name, "variable")
    measure_environments(measure, slug, name, private)
    for branch in sorted({PROTECTED_BRANCH, default_branch}):
        measure_protection(measure, slug, name, branch, private)
    measure_rulesets(measure, slug, name, private)
    measure_people(measure, slug, name)


def measure_installations(measure: Measure) -> None:
    """
    Every GitHub App installation the login can see, the App's id, its permissions, its events and its repositories.

    Args:
        measure: The run
    """
    installations = measure.list_or_fail("user/installations", "installations", "installations")
    for installation in sorted(installations or [], key = lambda item: number_of(item.get("id"))):
        app             = installation.get("app_slug")
        installation_id = installation.get("id")
        account         = installation.get("account") if isinstance(installation.get("account"), dict) else {}
        permissions     = installation.get("permissions") if isinstance(installation.get("permissions"), dict) else {}
        measure.add(
            "installation",
            app,
            app_id = installation.get("app_id"),
            id = installation_id,
            account = account.get("login"),
            selection = installation.get("repository_selection"),
            suspended = installation.get("suspended_at") is not None,
            permissions = [f"{scope}:{level}" for scope, level in permissions.items()],
            events = installation.get("events"),
        )
        repositories = measure.list_or_fail(
            f"user/installations/{installation_id}/repositories",
            "repositories",
            "installation",
            app,
            "repositories",
        )
        for repository in sorted(repositories or [], key = lambda item: str(item.get("full_name", "")).lower()):
            measure.add("installation", app, "repo", repository.get("full_name"))


def run_measure(fetch: Fetch, names: list[str], login_only: bool, taken: str) -> tuple[list[str], int]:
    """
    Every line of one run.

    Args:
        fetch: The GET to use
        names: The repositories named, or none for every one the login owns
        login_only: Whether to read the login alone
        taken: The time of the run, as its second line shows it

    Returns:
        The lines and the count of reads that failed
    """
    login, login_line = read_login(fetch)
    if login_only:
        return [login_line], 0
    measure = Measure(fetch = fetch)
    measure.add("measure", "kdf-measure", version = MEASURE_VERSION)
    measure.add("taken", taken)
    measure.lines.append(login_line)
    for repo in read_repositories(measure, login, names):
        measure_repository(measure, repo)
    measure_installations(measure)
    measure.add(
        "offers",
        "private",
        rulesets = "/".join(sorted(measure.private_rulesets)) or "unknown",
        admin_bypass_switch = "/".join(sorted(measure.private_bypass)) or "unknown",
    )
    return measure.lines, measure.unreadable

# ======================================================================================================================
# Entry point
# ======================================================================================================================

def build_parser() -> argparse.ArgumentParser:
    """
    The command line, the repositories to read and the login alone.

    Returns:
        The parser
    """
    parser = argparse.ArgumentParser(
        description = "Print where each secret and rule sits, by name and setting alone, never a value.",
    )
    parser.add_argument(
        "--repo",
        action = "append",
        default = [],
        help = "a repository to read, by name or owner/name, repeated for each, every owned one when none is given",
    )
    parser.add_argument(
        "--login-only",
        action = "store_true",
        help = "print the login's line alone, its plan and its scopes",
    )
    return parser


def main(
    argv: list[str] | None = None,
    *,
    fetch: Fetch | None = None,
    out: TextIO | None = None,
    err: TextIO | None = None,
) -> int:
    """
    Run the measure and print its lines, or refuse them whole when one holds a credential's shape.

    Args:
        argv: The arguments, the process's own when None
        fetch: The GET to use, gh when None
        out: Where the lines go, standard output when None
        err: Where the messages go, standard error when None

    Returns:
        0 when every read answered, 1 when a read failed, 2 when the output was refused, 3 when gh or the login
        could not be read
    """
    args  = build_parser().parse_args(argv)
    out   = out if out is not None else sys.stdout
    err   = err if err is not None else sys.stderr
    taken = datetime.datetime.now(datetime.UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        lines, unreadable = run_measure(fetch or gh_fetch, args.repo, args.login_only, taken)
    except GhUnavailable as error:
        err.write(f"The measure could not start, {error}.\n")
        return 3
    found = find_value_shape(lines)
    if found is not None:
        err.write(refusal(lines, *found))
        return 2
    out.write("\n".join(lines) + "\n")
    if unreadable:
        err.write(f"Reads that failed, {unreadable}, each named by an unreadable line.\n")
        return 1
    return 0


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding = "utf-8")
    sys.exit(main())
