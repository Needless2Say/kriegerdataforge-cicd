"""
Tests for kdf_repo_map.py, the repo map, a read only lookup over named Python clones read from git's objects.

Each test makes its clones under the test's temp folder with git init, runs the module as it ships with this
interpreter and the -I and -B the wrapper passes, and reads its answer. The module is also loaded by its path for the
helpers a rule rests on, as test_secretless_lanes.py loads a file, with bytecode off so no cache lands beside it. The
tests need git, which GitHub's runners and the owner's machines have.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import os
import re
import shutil
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

TOOLS   = Path(__file__).resolve().parents[2] / "tools" / "claude-code"
MODULE  = TOOLS / "kdf_repo_map.py"
WRAPPER = TOOLS / "kdf-repo-map.sh"
GIT     = shutil.which("git")
BASH    = os.environ.get("KDF_TEST_BASH") or shutil.which("bash")
# a stand in for cicd's venv interpreter, it logs each call and runs this interpreter, or plays one that cannot start
STAND_IN = """#!/usr/bin/env bash
printf '%s\\n' "$*" >> "{log}"
{body}
"""

# ======================================================================================================================
# the fixtures' code
# ======================================================================================================================

SERVICE = {
    "svc/__init__.py": "",
    "svc/core.py": """
        def target():
            return 1


        def depends(dependency):
            return dependency


        def register(function):
            return function
        """,
    "svc/use.py": """
        from svc.core import depends, register, target


        def call_it():
            return target()


        def pass_it(app):
            app.add_middleware(target)


        def handler(value = depends(target)):
            return value


        @register
        def decorated():
            return 2


        def shadowed(target):
            return target()


        def assigned():
            target = 3
            return target()


        def comprehension(callbacks):
            return [target() for target in callbacks]


        def lam():
            return (lambda target: target())(None)
        """,
    "svc/modules.py": """
        import svc.core
        import svc.core as aliased
        from svc import core


        def through_module():
            return core.target()


        def dotted():
            return svc.core.target()


        def through_alias():
            return aliased.target()
        """,
}

SCOPES = {
    "scope/__init__.py": "",
    "scope/lib.py": """
        def target():
            return 1


        def mark(function):
            return function
        """,
    "scope/cases.py": """
        from scope.lib import mark, target


        class Holder:
            def target(self):
                return 0

            def method(self):
                return target()

            def own(self):
                return self.target()


        class Defaults:
            def mark(function):
                return function

            @mark
            def first(self, value = mark):
                return mark()


        class Early:
            before = target()

            def target(self):
                return 0


        def enclosing():
            from scope.elsewhere import target

            def inner():
                global target
                return target()

            def inner_two():
                return target()

            return inner, inner_two


        def counter():
            target = 0

            def bump():
                nonlocal target
                target = target + 1
                return target()

            return bump
        """,
    "scope/either.py": """
        try:
            from scope.lib import target
        except ImportError:
            from scope.backup import target


        def either():
            return target()
        """,
    "scope/klass.py": """
        class Holds:
            from scope.lib import target

            def call(self):
                return self.target()
        """,
    "scope/early.py": """
        def target(value = target()):
            return value


        class Target:
            value = Target()

            def build(self):
                return Target()


        def outer():
            def inner(value = inner()):
                return value

            return inner


        def recurse():
            return recurse()
        """,
    "scope/selfish.py": """
        class Other:
            def target(self):
                return 2


        self = Other()


        class Holder:
            def target(self):
                return 1

            def use(self):
                def nested():
                    global self
                    return self.target()

                return nested

            def inner_class(self):
                class Nested:
                    self = Other()
                    found = self.target()

                return Nested
        """,
    "scope/deep.py": """
        def outer():
            from scope.lib import target

            def middle():
                def inner():
                    nonlocal target
                    target = None

                return inner

            def closure():
                value = target()
                return value

            return middle, closure
        """,
}

PACKAGES = {
    "pkgs/__init__.py": "",
    "pkgs/client.py": "class Client:\n    def run(self):\n        return 0\n",
    "pkgs/good/__init__.py": "",
    "pkgs/good/mod.py": "def run():\n    return 1\n",
    "pkgs/bad/__init__.py": "from pkgs.client import Client\nmod = Client()\n",
    "pkgs/bad/mod.py": "def run():\n    return 1\n",
    "pkgs/lazy/__init__.py": "def __getattr__(name):\n    return name\n",
    "pkgs/lazy/mod.py": "def run():\n    return 1\n",
    "pkgs/use.py": """
        import pkgs.bad.mod
        import pkgs.bad.mod as bad_alias
        from pkgs.bad import mod as bad_mod
        from pkgs.good import mod
        from pkgs.lazy import mod as lazy_mod


        def good():
            return mod.run()


        def bad():
            return bad_mod.run()


        def bad_dotted():
            return pkgs.bad.mod.run()


        def bad_aliased():
            return bad_alias.run()


        def lazy():
            return lazy_mod.run()
        """,
}

BASES = {
    "base/__init__.py": "",
    "base/model.py": """
        class Root:
            def save(self):
                return 1


        class Middle(Root):
            pass


        class Leaf(Middle):
            def store(self):
                return self.save()


        class Own:
            def save(self):
                return 0

            def store(self):
                return self.save()
        """,
    "base/swapped.py": """
        def replacement(self):
            return 2


        class Swapped:
            def save(self):
                return 0

            save = replacement

            def store(self):
                return self.save()
        """,
    "base/events.py": """
        def subscribe(callback):
            return callback


        def wire(receiver):
            return subscribe(receiver.handle)
        """,
}

IMPORTS = {
    "lib/__init__.py": "from lib.inner import helper\n",
    "lib/inner.py": "def helper():\n    return 1\n",
    "lib/sub/__init__.py": "",
    "lib/sub/deep.py": "from ..inner import helper as aliased\nfrom . import sibling\n",
    "lib/sub/sibling.py": "",
    "lib/cycle_a.py": "from lib.cycle_b import loop\n",
    "lib/cycle_b.py": "from lib.cycle_a import loop\n\n\ndef spin():\n    return loop()\n",
    "use/__init__.py": "",
    "use/top.py": """
        import lib.sub.deep
        from lib import helper


        def late():
            from lib.sub import sibling
            return sibling, helper()
        """,
}

SDK_CONSUMER = {
    "svc/__init__.py": "",
    "svc/handlers.py": """
        from sdkpkg.auth import User
        from sdkpkg.auth.models import User as Direct


        def via_package():
            return User()


        def direct():
            return Direct()
        """,
}

LAYOUT = {
    "api/__init__.py": "",
    "api/core.py": "def target():\n    return 1\n",
    "api/use.py": "from api.core import target\n\ntarget()\n",
    "vercel_api/api/use.py": "from api.core import target\n\ntarget()\n",
    "tests/test_core.py": "from api.core import target\n\ntarget()\n",
    "unit_tests/auth/check.py": "from api.core import target\n\ntarget()\n",
    "src/kit_pkg/__init__.py": "",
    "src/kit_pkg/tool.py": "def run():\n    return 1\n",
    "src/kit_pkg/use.py": "from kit_pkg.tool import run\n\nrun()\n",
    "scripts/common/__init__.py": "",
    "scripts/common/helper.py": "def assist():\n    return 1\n",
    "scripts/job.py": "from common.helper import assist\n\nassist()\n",
}

LOADED = {
    "pkg/__init__.py": "",
    "pkg/core.py": "def target():\n    return 1\n\n\ndef other():\n    return 2\n",
    "use/__init__.py": "",
    "use/plain.py": "import pkg\n\npkg.core.target()\n",
    "use/loads.py": "import pkg.core\n\npkg.core.target()\n",
    "use/absent.py": "import pkg.core\n\npkg.core.missing()\n",
    "use/late.py": "import pkg\n\npkg.core.target()\nimport pkg.core\n",
    "use/hinted.py": "target: object\n",
    "use/hint_user.py": "import use.hinted\n\nuse.hinted.target()\n",
    "use/itself.py": "import use.itself\n\n\nclass Self:\n    value = use.itself.Self()\n",
}

CALLEES = {
    "cal/__init__.py": "",
    "cal/lib.py": ("def helper():\n    return 1\n\n\ndef other():\n    return 2\n\n\nclass Thing:\n"
                   "    def build(self):\n        return 1\n\n    def close(self):\n        return 2\n\n\n"
                   "class Plain:\n    pass\n"),
    "cal/scoped.py": """
        def target():
            return 1


        def outer():
            def target():
                return 2

            class Box:
                global target

                def work(self):
                    target()

            return Box


        class Registry:
            global Kept

            class Kept:
                def work(self):
                    return target()


        Kept = object()
        """,
    "cal/annotated.py": "def early(value: late()):\n    return value\n\n\ndef late():\n    return 1\n",
    "sys.py": "def helper():\n    return 1\n\n\ndef target():\n    return helper()\n",
    "cal/body.py": """
        from cal.lib import Thing, helper, other


        def work(callback, handlers):
            helper()
            values = [other() for _ in range(2)]
            later = lambda: other()
            lazy = (helper() for _ in range(2))
            callback()
            handlers["key"]()
            handlers.clear()
            make()()
            len(values)
            register(Thing)

            unused: helper()

            @register
            def nested(flag=other(), size: helper() = 1):
                return other()

            class Inner:
                made = helper()

            return later, lazy, nested, Inner


        def empty():
            return 1


        def twice():
            helper()


        twice = other


        def shadowed():
            helper()


        class shadowed:
            pass


        class Crate:
            def work(self):
                helper()


        Crate = object()


        def system():
            import sys

            sys.target()


        class Box:
            @property
            def size(self):
                return helper()

            @size.setter
            def size(self, value):
                other()
        """,
}

DUPLICATE = {
    "dup/__init__.py": "",
    "dup/real.py": "def run():\n    return 1\n",
    "dup/pkg.py": "from dup.real import run as again\n\n\ndef run():\n    return again()\n",
    "dup/pkg/__init__.py": "from dup.real import run\n",
    "dup/use.py": "from dup.pkg import run\n\nrun()\n",
}

pytestmark = pytest.mark.skipif(GIT is None and not os.environ.get("CI"), reason = "the repo map needs git")

# ======================================================================================================================
# the helpers
# ======================================================================================================================

def _module():
    """
    Load the module by its path, with no bytecode written beside it.
    """
    spec   = importlib.util.spec_from_file_location("kdf_repo_map", MODULE)
    module = importlib.util.module_from_spec(spec)
    sys.modules["kdf_repo_map"] = module
    written, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = written
    return module


def _git(path: Path, *args: str) -> str:
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    return subprocess.run(
        ["git", "-C", str(path), *args],
        check = True,
        capture_output = True,
        text = True,
        env = environment,
    ).stdout.strip()


def _write(path: Path, files: dict[str, str]) -> None:
    for relative, text in files.items():
        target = path / relative
        target.parent.mkdir(parents = True, exist_ok = True)
        target.write_text(textwrap.dedent(text), encoding = "utf-8", newline = "\n")


def _commit(path: Path, files: dict[str, str], message: str = "work") -> str:
    _write(path, files)
    _git(path, "add", "-A")
    _git(path, "commit", "-q", "-m", message)
    return _git(path, "rev-parse", "HEAD")


def _track(path: Path, reflog: bool = True) -> None:
    """
    Point origin/main at HEAD, as a fetch would, with a reflog entry or none.
    """
    if reflog:
        _git(path, "update-ref", "-m", "fetch", "refs/remotes/origin/main", "HEAD")
    else:
        _git(path, "-c", "core.logAllRefUpdates=false", "update-ref", "refs/remotes/origin/main", "HEAD")


def _clone(root: Path, name: str, files: dict[str, str], reflog: bool = True) -> Path:
    path = root / name
    path.mkdir(parents = True)
    _git(path, "init", "-q", "-b", "main")
    _git(path, "config", "user.email", "dev@example.com")
    _git(path, "config", "user.name", "Dev")
    _git(path, "config", "core.autocrlf", "false")
    _commit(path, files, "first")
    _track(path, reflog)
    return path


def _run(root: Path, *args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """
    Run the module as the wrapper does, under the given root, with no role but env's.
    """
    environment = {key: value for key, value in os.environ.items() if key != "KDF_ROLE"}
    environment.update(env or {})
    return subprocess.run(
        [sys.executable, "-I", "-B", str(MODULE), *args, "--root", str(root)],
        capture_output = True,
        text = True,
        env = environment,
    )


def _groups(answer: str, command: str) -> list[list[str]]:
    """
    Split an answer's lines into its three groups, by the titles the module prints.
    """
    titles  = _module().TITLES[command]
    groups  = [[], [], []]
    current = None
    for line in answer.splitlines():
        heading = next((index for index, title in enumerate(titles) if line.startswith(f"{title}, ")), None)
        if heading is not None:
            current = heading
        elif current is not None and "@" in line.split(" ")[0]:
            groups[current].append(line)
    return groups


def _line(files: dict[str, str], path: str, needle: str) -> str:
    """
    The path and line of the first line holding the needle, as an answer names it.
    """
    lines = textwrap.dedent(files[path]).splitlines()
    return f"{path}:{next(number for number, text in enumerate(lines, 1) if needle in text)} "


def _has(group: list[str], place: str) -> bool:
    return any(f" {place}" in line for line in group)


def _snapshot(path: Path) -> str:
    """
    A hash of every file under a fixture, its tree and its .git, since status alone misses ignored files and metadata.
    """
    digest = hashlib.sha256()
    for item in sorted(entry for entry in path.rglob("*") if entry.is_file()):
        digest.update(item.relative_to(path).as_posix().encode())
        digest.update(item.read_bytes())
    return digest.hexdigest()

# ======================================================================================================================
# the closed paths, the test files and module names, each a rule the module holds by a helper
# ======================================================================================================================

def test_the_closed_names_are_exactly_the_two_tools_lists() -> None:
    module = _module()
    for tool in ("kdf-ask-codex.sh", "kdf-preflight.sh"):
        text  = (TOOLS / tool).read_text(encoding = "utf-8")
        block = re.search(r"secret_globs=\(([^)]*)\)", text).group(1)
        assert tuple(re.findall(r"'([^']*)'", block)) == module.SECRET_GLOBS, tool


def test_closed_paths_are_secret_names_in_any_case_and_anything_under_keys() -> None:
    closed = _module().closed
    for path in (
        "keys/x.py",
        "app/keys/deep/x.py",
        ".env_tool.py",
        "conf/.ENV.py",
        "ops/id_rsa_helper.py",
        "keys\\secret.py",
        "conf\\.ENV.py",
        "app\\KEYS\\x.py",
    ):
        assert closed(path), path
    for path in ("api/keystore.py", "api/monkeys.py", "svc/env.py", "api/main.py"):
        assert not closed(path), path


def test_a_test_file_is_named_or_sits_under_a_tests_folder() -> None:
    is_test = _module().is_test
    for path in (
        "test_a.py",
        "a/b_test.py",
        "x/conftest.py",
        "tests/helpers.py",
        "unit_tests/auth/check.py",
        "integration_tests/deep/x.py",
    ):
        assert is_test(path), path
    for path in ("api/testing.py", "api/contest.py", "latest/x.py", "api/tests.py"):
        assert not is_test(path), path


def test_a_module_is_named_from_its_import_root_never_src() -> None:
    module_name = _module().module_name
    assert module_name("api/auth/keys.py", []) == ("api.auth.keys", False)
    assert module_name("api/auth/__init__.py", []) == ("api.auth", True)
    assert module_name("src/pkg_lib/x.py", ["src"]) == ("pkg_lib.x", False)
    assert module_name("scripts/common/helper.py", ["scripts"]) == ("common.helper", False)

# ======================================================================================================================
# the three groups for callers, and how each line reads
# ======================================================================================================================

def test_callers_print_three_groups_each_line_with_its_clone_and_commit(tmp_path: Path) -> None:
    path   = _clone(tmp_path, "app", SERVICE)
    commit = _git(path, "rev-parse", "HEAD")
    done   = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 0, done.stderr
    lines = done.stdout.splitlines()
    assert lines[0].startswith(f"app at origin/main {commit[:7]}, origin/main last moved ")
    assert "checkout at" not in lines[0]
    assert lines[1] == "Left out, vercel_api/, tests."
    resolved, values, unchecked = _groups(done.stdout, "callers")
    prefix = f"app@{commit[:7]} "
    assert all(line.startswith(prefix) for line in resolved + values + unchecked)
    assert _has(resolved, _line(SERVICE, "svc/use.py", "return target()") + "target called in call_it")
    for needle in ("core.target()", "svc.core.target()", "aliased.target()"):
        assert _has(resolved, _line(SERVICE, "svc/modules.py", needle)), needle
    assert _has(values, _line(SERVICE, "svc/use.py", "add_middleware") + "target used in pass_it")
    assert _has(values, _line(SERVICE, "svc/use.py", "depends(target)") + "target used at module level")
    for needle in ("def shadowed", "target = 3", "for target in", "lambda target"):
        number = _line(SERVICE, "svc/use.py", needle).split(":")[1].strip()
        later  = f"svc/use.py:{int(number) + 1} "
        assert not any(
            _has(group, later) or _has(group, f"svc/use.py:{number} ") for group in (resolved, values, unchecked)
        ), needle
    assert done.stdout.rstrip().endswith("git -C <clone> show <hash>:<path>, never the checkout.")
    assert "A floor, an empty group proves no absence." in done.stdout


def test_a_decorated_handler_queried_by_its_own_name_and_its_decorator_are_uses(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SERVICE)
    done = _run(tmp_path, "callers", "svc.use.decorated", "--repo", "app")
    _, values, _ = _groups(done.stdout, "callers")
    assert _has(values, _line(SERVICE, "svc/use.py", "def decorated") + "decorated decorated by register")
    done = _run(tmp_path, "callers", "svc.core.register", "--repo", "app")
    _, values, _ = _groups(done.stdout, "callers")
    assert _has(values, _line(SERVICE, "svc/use.py", "@register") + "register used at module level")


def test_nothing_found_exits_one(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SERVICE)
    done = _run(tmp_path, "callers", "svc.core.absent", "--repo", "app")
    assert done.returncode == 1, done.stdout + done.stderr
    assert "0 in all." in done.stdout

# ======================================================================================================================
# Python's scopes
# ======================================================================================================================

def test_a_method_body_skips_its_class_for_a_bare_name(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, _ = _groups(_run(tmp_path, "callers", "scope.lib.target", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(SCOPES, "scope/cases.py", "    return target()") + "target called in Holder.method")
    resolved, _, _ = _groups(_run(tmp_path, "callers", "scope.cases.Holder.target", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(SCOPES, "scope/cases.py", "self.target()") + "self.target called in Holder.own")
    assert not _has(resolved, _line(SCOPES, "scope/cases.py", "    return target()"))


def test_a_decorator_and_a_default_read_the_enclosing_class_scope(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    done = _run(tmp_path, "callers", "scope.cases.Defaults.mark", "--repo", "app")
    resolved, values, _ = _groups(done.stdout, "callers")
    assert _has(values, _line(SCOPES, "scope/cases.py", "@mark") + "mark used in class Defaults")
    assert _has(values, _line(SCOPES, "scope/cases.py", "value = mark") + "mark used in class Defaults")
    assert not _has(resolved, _line(SCOPES, "scope/cases.py", "return mark()"))
    resolved, _, _ = _groups(_run(tmp_path, "callers", "scope.lib.mark", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(SCOPES, "scope/cases.py", "return mark()") + "mark called in Defaults.first")


def test_a_class_body_use_before_its_own_binding_stays_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "scope.lib.target", "--repo", "app").stdout, "callers")
    place = _line(SCOPES, "scope/cases.py", "before = target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "target called by name in class Early, used before its binding, unchecked")


def test_global_and_nonlocal_are_honoured(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "scope.lib.target", "--repo", "app").stdout, "callers")
    lines = textwrap.dedent(SCOPES["scope/cases.py"]).splitlines()
    calls = [number for number, text in enumerate(lines, 1) if text.strip() == "return target()"]
    inner, inner_two, bump = calls[1], calls[2], calls[3]
    assert _has(resolved, f"scope/cases.py:{inner} target called in enclosing.inner")
    for number in (inner_two, bump):
        assert not any(_has(group, f"scope/cases.py:{number} ") for group in (resolved, unchecked)), number


def test_a_name_bound_twice_to_different_origins_stays_by_name(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "scope.lib.target", "--repo", "app").stdout, "callers")
    place = _line(SCOPES, "scope/either.py", "return target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "target called by name in either, bound more than once, unchecked")

# ======================================================================================================================
# modules, packages, bases and attributes
# ======================================================================================================================

def test_a_module_receiver_resolves_only_when_every_package_on_the_way_is_clean(tmp_path: Path) -> None:
    _clone(tmp_path, "app", PACKAGES)
    resolved, _, _ = _groups(_run(tmp_path, "callers", "pkgs.good.mod.run", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(PACKAGES, "pkgs/use.py", "mod.run()") + "mod.run called in good")
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "pkgs.bad.mod.run", "--repo", "app").stdout, "callers")
    assert resolved == []
    for needle in ("bad_mod.run()", "pkgs.bad.mod.run()", "bad_alias.run()"):
        assert _has(unchecked, _line(PACKAGES, "pkgs/use.py", needle)), needle
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "pkgs.lazy.mod.run", "--repo", "app").stdout, "callers")
    assert resolved == []
    assert _has(unchecked, _line(PACKAGES, "pkgs/use.py", "lazy_mod.run()") + "lazy_mod.run called by name in lazy")


def test_a_self_call_resolves_in_its_class_and_through_a_base_stays_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", BASES)
    resolved, _, _ = _groups(_run(tmp_path, "callers", "base.model.Own.save", "--repo", "app").stdout, "callers")
    lines = textwrap.dedent(BASES["base/model.py"]).splitlines()
    leaf, own = [number for number, text in enumerate(lines, 1) if "self.save()" in text]
    assert _has(resolved, f"base/model.py:{own} self.save called in Own.store")
    resolved, _, unchecked = _groups(
        _run(tmp_path, "callers", "base.model.Root.save", "--repo", "app").stdout,
        "callers",
    )
    assert not _has(resolved, f"base/model.py:{leaf} ")
    label = "through its base base.model.Middle, unchecked"
    assert _has(unchecked, f"base/model.py:{leaf} self.save called by name in Leaf.store, {label}")
    assert not _has(unchecked, f"base/model.py:{own} ")


def test_an_attribute_with_an_unknown_receiver_is_a_reference_by_name(tmp_path: Path) -> None:
    _clone(tmp_path, "app", BASES)
    done = _run(tmp_path, "callers", "base.listener.Listener.handle", "--repo", "app")
    _, _, unchecked = _groups(done.stdout, "callers")
    place = _line(BASES, "base/events.py", "receiver.handle")
    assert _has(unchecked, place + "receiver.handle a reference by name in wire")


def test_two_clones_holding_api_stay_apart(tmp_path: Path) -> None:
    first  = {
        "api/__init__.py": "",
        "api/main.py": "def handle():\n    return 1\n",
        "api/use.py": "from api.main import handle\n\nhandle()\n",
    }
    second = {
        "api/__init__.py": "",
        "api/main.py": "def handle():\n    return 2\n",
        "api/other.py": "from api import main\n\nmain.handle()\n",
    }
    _clone(tmp_path, "first", first)
    _clone(tmp_path, "second", second)
    done = _run(tmp_path, "callers", "api.main.handle", "--repo", "first", "--repo", "second")
    resolved, _, _ = _groups(done.stdout, "callers")
    assert "Resolved calls, 2, first 1, second 1" in done.stdout
    assert any(line.startswith("first@") and " api/use.py:3 " in line for line in resolved)
    assert any(line.startswith("second@") and " api/other.py:3 " in line for line in resolved)


def test_a_use_through_a_package_over_the_defining_module_lands_labelled(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SDK_CONSUMER)
    done = _run(tmp_path, "callers", "sdkpkg.auth.models.User", "--repo", "app")
    resolved, _, unchecked = _groups(done.stdout, "callers")
    assert _has(resolved, _line(SDK_CONSUMER, "svc/handlers.py", "return Direct()") + "Direct called in direct")
    place = _line(SDK_CONSUMER, "svc/handlers.py", "return User()")
    assert _has(unchecked, place + "User called in via_package, through a package, sdkpkg.auth.User")
    done = _run(tmp_path, "imports", "sdkpkg.auth.models.User", "--repo", "app")
    found, _, unchecked = _groups(done.stdout, "imports")
    assert _has(found, "svc/handlers.py:3 imports sdkpkg.auth.models.User at module level")
    assert _has(unchecked, "svc/handlers.py:2 imports sdkpkg.auth.User at module level, through a package")

# ======================================================================================================================
# imports, test importers and definitions
# ======================================================================================================================

def test_imports_of_a_package_cover_its_submodules_relative_imports_and_functions(tmp_path: Path) -> None:
    _clone(tmp_path, "app", IMPORTS)
    found, _, _ = _groups(_run(tmp_path, "imports", "lib.sub", "--repo", "app").stdout, "imports")
    assert _has(found, _line(IMPORTS, "use/top.py", "import lib.sub.deep") + "imports lib.sub.deep at module level")
    assert _has(found, _line(IMPORTS, "use/top.py", "import sibling") + "imports lib.sub.sibling in late")
    assert _has(found, "lib/sub/deep.py:2 imports lib.sub.sibling at module level")
    found, through, _ = _groups(_run(tmp_path, "imports", "lib.inner", "--repo", "app").stdout, "imports")
    assert _has(found, "lib/__init__.py:1 imports lib.inner.helper at module level")
    assert _has(found, "lib/sub/deep.py:1 imports lib.inner.helper at module level")
    place = _line(IMPORTS, "use/top.py", "from lib import helper")
    assert _has(through, place + "imports lib.helper at module level, through a re-export to lib.inner.helper")


def test_a_re_export_is_followed_and_a_cycle_ends(tmp_path: Path) -> None:
    _clone(tmp_path, "app", IMPORTS)
    resolved, _, _ = _groups(_run(tmp_path, "callers", "lib.inner.helper", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(IMPORTS, "use/top.py", "helper()") + "helper called in late")
    done = _run(tmp_path, "callers", "lib.cycle_a.loop", "--repo", "app")
    assert done.returncode in (0, 1), done.stderr
    _, _, unchecked = _groups(done.stdout, "callers")
    assert _has(unchecked, "lib/cycle_b.py:5 loop called by name in spin")


def test_vercel_api_is_left_out_and_tests_only_with_tests(tmp_path: Path) -> None:
    _clone(tmp_path, "app", LAYOUT)
    done = _run(tmp_path, "callers", "api.core.target", "--repo", "app")
    resolved, _, _ = _groups(done.stdout, "callers")
    assert [line.split(" ")[1] for line in resolved] == ["api/use.py:3"]
    done = _run(tmp_path, "callers", "api.core.target", "--repo", "app", "--tests")
    resolved, _, _ = _groups(done.stdout, "callers")
    assert sorted(line.split(" ")[1] for line in resolved) == [
        "api/use.py:3",
        "tests/test_core.py:3",
        "unit_tests/auth/check.py:3",
    ]
    assert "Left out, vercel_api/." in done.stdout
    found, _, _ = _groups(_run(tmp_path, "test-importers", "api.core", "--repo", "app").stdout, "test-importers")
    assert sorted(line.split(" ")[1] for line in found) == ["tests/test_core.py:1", "unit_tests/auth/check.py:1"]


def test_a_src_layout_and_a_package_root_name_modules(tmp_path: Path) -> None:
    _clone(tmp_path, "app", LAYOUT)
    found, _, _ = _groups(_run(tmp_path, "defs", "kit_pkg.tool.run", "--repo", "app").stdout, "defs")
    assert _has(found, "src/kit_pkg/tool.py:1 def kit_pkg.tool.run")
    resolved, _, _ = _groups(_run(tmp_path, "callers", "kit_pkg.tool.run", "--repo", "app").stdout, "callers")
    assert _has(resolved, "src/kit_pkg/use.py:3 run called at module level")
    found, bound, _ = _groups(_run(tmp_path, "defs", "common.helper.assist", "--repo", "app").stdout, "defs")
    assert found == [], "the module is scripts.common.helper until --package-root names scripts"
    assert _has(bound, "scripts/job.py:1 scripts.job.assist bound by an import of common.helper.assist")
    found, _, _ = _groups(
        _run(tmp_path, "defs", "common.helper.assist", "--repo", "app", "--package-root", "scripts").stdout,
        "defs",
    )
    assert _has(found, "scripts/common/helper.py:1 def common.helper.assist")
    done = _run(tmp_path, "callers", "common.helper.assist", "--repo", "app", "--package-root", "scripts")
    resolved, _, _ = _groups(done.stdout, "callers")
    assert _has(resolved, "scripts/job.py:3 assist called at module level")


def test_defs_finds_definitions_re_exports_and_assignments(tmp_path: Path) -> None:
    files = dict(IMPORTS, **{"lib/values.py": "helper = 3\n"})
    _clone(tmp_path, "app", files)
    found, bound, unchecked = _groups(_run(tmp_path, "defs", "helper", "--repo", "app").stdout, "defs")
    assert _has(found, "lib/inner.py:1 def lib.inner.helper")
    assert _has(bound, "lib/__init__.py:1 lib.helper bound by an import of lib.inner.helper")
    assert _has(unchecked, "lib/values.py:1 lib.values.helper bound by assignment, unchecked")
    found, bound, _ = _groups(_run(tmp_path, "defs", "lib.inner.helper", "--repo", "app").stdout, "defs")
    assert _has(found, "lib/inner.py:1 def lib.inner.helper")
    assert _has(bound, "lib/__init__.py:1 lib.helper bound by an import of lib.inner.helper")

# ======================================================================================================================
# the commit read and the first line
# ======================================================================================================================

def test_the_first_line_names_a_checkout_behind_or_ahead_of_origin_main(tmp_path: Path) -> None:
    path  = _clone(tmp_path, "app", SERVICE)
    first = _git(path, "rev-parse", "HEAD")
    later = _commit(path, {"svc/extra.py": "from svc.core import target\n\ntarget()\n"})
    done  = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.stdout.splitlines()[0].endswith(f", checkout at {later[:7]}")
    assert "svc/extra.py" not in done.stdout, "origin/main is read, never the checkout"
    _track(path)
    _git(path, "reset", "-q", "--hard", first)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.stdout.splitlines()[0].startswith(f"app at origin/main {later[:7]}, origin/main last moved ")
    assert done.stdout.splitlines()[0].endswith(f", checkout at {first[:7]}")
    assert "svc/extra.py:3 " in done.stdout


def test_an_origin_main_with_no_reflog_moved_at_an_unknown_time(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SERVICE, reflog = False)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert "origin/main last moved unknown, it has no reflog" in done.stdout.splitlines()[0]


def test_at_names_a_commit_for_one_clone_and_refuses_a_dash(tmp_path: Path) -> None:
    path  = _clone(tmp_path, "app", SERVICE)
    first = _git(path, "rev-parse", "HEAD")
    _commit(path, {"svc/extra.py": "from svc.core import target\n\ntarget()\n"})
    _track(path)
    _clone(tmp_path, "other", SERVICE)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", "--at", f"app={first}")
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines()[0].startswith(f"app at --at {first} {first[:7]}, origin/main at ")
    assert "svc/extra.py" not in done.stdout
    assert all(line.startswith(f"app@{first[:7]} ") for line in sum(_groups(done.stdout, "callers"), []))
    assert _run(tmp_path, "callers", "svc.core.target", "--repo", "app", "--at", first).returncode == 0
    for at in ("--at=app=-p", "--at=-p"):
        done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", at)
        assert done.returncode == 2 and done.stdout == "", at
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", "--repo", "other", "--at", first)
    assert done.returncode == 2 and "single --repo" in done.stderr
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", "--at", f"third={first}")
    assert done.returncode == 2
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", "--at", "app=nosuchrev")
    assert done.returncode == 3 and "has no commit nosuchrev" in done.stderr


def test_a_clone_with_no_origin_main_needs_at(tmp_path: Path) -> None:
    path = _clone(tmp_path, "app", SERVICE)
    _git(path, "update-ref", "-d", "refs/remotes/origin/main")
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 3 and "has no commit origin/main" in done.stderr
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", "--at", "HEAD")
    assert done.returncode == 0 and ", no origin/main" in done.stdout.splitlines()[0]

# ======================================================================================================================
# what is never read, and what is never written
# ======================================================================================================================

def test_only_tracked_files_at_the_commit_are_read(tmp_path: Path) -> None:
    files = dict(SERVICE, **{".gitignore": "ignored_*.py\n"})
    path  = _clone(tmp_path, "app", files)
    _write(path, {
        "svc/use.py": textwrap.dedent(SERVICE["svc/use.py"]) + "\n\ndef edited():\n    return target()\n",
        "svc/untracked.py": "from svc.core import target\n\ntarget()\n",
        "ignored_local.py": "from svc.core import target\n\ntarget()\n",
    })
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 0, done.stderr
    assert "edited" not in done.stdout and "untracked" not in done.stdout and "ignored_local" not in done.stdout


def test_closed_paths_are_never_read(tmp_path: Path) -> None:
    call  = "from svc.core import target\n\ntarget()\n"
    files = dict(SERVICE, **{"keys/leak.py": call, ".env_tool.py": call, "ops/id_rsa_helper.py": "def oops(:\n"})
    _clone(tmp_path, "app", files)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 0, done.stdout
    assert "leak" not in done.stdout and ".env_tool" not in done.stdout and "id_rsa" not in done.stdout


def test_a_parse_error_is_named_by_path_and_line_never_its_text(tmp_path: Path) -> None:
    files = dict(SERVICE, **{"svc/broken.py": "VISIBLE_MARKER = 1\ndef oops(:\n    SECRET_WORD = 2\n"})
    _clone(tmp_path, "app", files)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 3
    assert "Incomplete, app svc/broken.py:2 did not parse." in done.stdout
    assert "SECRET_WORD" not in done.stdout + done.stderr and "oops" not in done.stdout + done.stderr


def test_an_inherited_git_dir_points_nowhere(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SERVICE)
    other = _clone(tmp_path, "other", {"x.py": "x = 1\n"})
    env   = {"GIT_DIR": str(other / ".git"), "GIT_WORK_TREE": str(other)}
    done  = _run(tmp_path, "callers", "svc.core.target", "--repo", "app", env = env)
    assert done.returncode == 0, done.stderr
    assert "svc/use.py" in done.stdout


def test_a_partial_clone_missing_object_is_never_fetched(tmp_path: Path) -> None:
    source = _clone(tmp_path / "upstream", "source", SERVICE)
    _git(source, "config", "uploadpack.allowFilter", "true")
    root = tmp_path / "root"
    root.mkdir()
    _git(root, "clone", "-q", "--no-checkout", "--filter=blob:none", source.as_uri(), "partial")
    objects = _snapshot(root / "partial" / ".git" / "objects")
    done    = _run(root, "callers", "svc.core.target", "--repo", "partial")
    assert done.returncode == 3, done.stdout + done.stderr
    assert "Incomplete, partial svc/use.py, its object is missing and was not fetched." in done.stdout
    assert _snapshot(root / "partial" / ".git" / "objects") == objects


def test_no_run_changes_a_fixture_tree_or_its_git(tmp_path: Path) -> None:
    path   = _clone(tmp_path, "app", dict(SERVICE, **IMPORTS))
    before = _snapshot(path)
    for args in (("defs", "target"), ("imports", "lib"), ("callers", "svc.core.target"), ("test-importers", "lib")):
        done = _run(tmp_path, *args, "--repo", "app")
        assert done.returncode in (0, 1) and "in all." in done.stdout, args
    assert _snapshot(path) == before


def test_a_run_leaves_no_bytecode(tmp_path: Path) -> None:
    copy = tmp_path / "tools"
    copy.mkdir()
    shutil.copy2(MODULE, copy / MODULE.name)
    _clone(tmp_path, "app", SERVICE)
    query = ("callers", "svc.core.target", "--repo", "app", "--root", str(tmp_path))
    done  = subprocess.run(
        [sys.executable, "-I", "-B", str(copy / MODULE.name), *query],
        capture_output = True,
        text = True,
    )
    assert done.returncode == 0, done.stderr
    assert sorted(item.name for item in copy.rglob("*")) == [MODULE.name]

# ======================================================================================================================
# refusals before any read
# ======================================================================================================================

def test_a_reviewer_is_refused_before_anything_help_included(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SERVICE)
    for args in (("callers", "svc.core.target", "--repo", "app"), ("--help",)):
        done = _run(tmp_path, *args, env = {"KDF_ROLE": "reviewer"})
        assert done.returncode == 2 and done.stdout == "", args
        assert "reviewer role never runs the repo map" in done.stderr


def test_a_clone_under_review_is_refused_before_any_read(tmp_path: Path) -> None:
    path = _clone(tmp_path, "app", SERVICE)
    (path / ".git" / "kdf-review" / "open").mkdir(parents = True)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 2 and done.stdout == ""
    assert "app has a review open" in done.stderr


def test_a_review_in_the_common_dir_or_a_sibling_worktree_refuses_every_checkout(tmp_path: Path) -> None:
    path = _clone(tmp_path, "app", SERVICE)
    _git(path, "worktree", "add", "-q", "--detach", str(tmp_path / "first"))
    _git(path, "worktree", "add", "-q", "--detach", str(tmp_path / "second"))
    common = path / ".git" / "kdf-review" / "open"
    common.mkdir(parents = True)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "first")
    assert done.returncode == 2 and "first has a review open" in done.stderr
    common.rmdir()
    admin = Path(_git(tmp_path / "first", "rev-parse", "--path-format=absolute", "--absolute-git-dir"))
    (admin / "kdf-review" / "open").mkdir(parents = True)
    for name in ("app", "second", "first"):
        done = _run(tmp_path, "callers", "svc.core.target", "--repo", name)
        assert done.returncode == 2 and done.stdout == "", name


def test_names_flags_and_folders_are_checked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SERVICE)
    for args in (
        ("callers", "target", "--repo", "app"),
        ("callers", "svc.core.target", "--repo", "app", "--repo", "app"),
        ("callers", "svc.core.target", "--repo", "../app"),
        ("callers", "svc.core.target", "--repo", "app", "--skip", "../x"),
        ("callers", "not a name", "--repo", "app"),
    ):
        assert _run(tmp_path, *args).returncode == 2, args
    assert _run(tmp_path, "callers", "svc.core.target", "--repo", "absent").returncode == 3


def test_help_names_the_rules_a_session_reads(tmp_path: Path) -> None:
    done = _run(tmp_path, "--help")
    assert done.returncode == 0
    for words in ("conftest.py", "What it cannot see", "--root", "for tests", "Exit codes", "at most 40 lines"):
        assert words in done.stdout, words

# ======================================================================================================================
# groups spread across clones
# ======================================================================================================================

def test_a_group_spreads_its_forty_lines_across_clones_and_full_prints_the_rest(tmp_path: Path) -> None:
    files = {
        "api/__init__.py": "",
        "api/core.py": "def target():\n    return 1\n",
        "api/many.py": "from api.core import target\n" + "target()\n" * 20,
    }
    for name in ("one", "two", "three"):
        _clone(tmp_path, name, files)
    args = ("callers", "api.core.target", "--repo", "one", "--repo", "two", "--repo", "three")
    done = _run(tmp_path, *args)
    assert "Resolved calls, 60, one 20, two 20, three 20" in done.stdout
    resolved, _, _ = _groups(done.stdout, "callers")
    assert len(resolved) == 40 and "20 more, --full prints them" in done.stdout
    assert {line.split("@")[0] for line in resolved} == {"one", "two", "three"}
    assert [line.split("@")[0] for line in resolved] == sorted(
        (line.split("@")[0] for line in resolved),
        key = ["one", "two", "three"].index,
    )
    resolved, _, _ = _groups(_run(tmp_path, *args, "--full").stdout, "callers")
    assert len(resolved) == 60

# ======================================================================================================================
# the boundaries a change read found open, each held by its own case
# ======================================================================================================================

def _plumb(path: Path, text: str, *args: str) -> str:
    """
    Run git plumbing with bytes on its input, since text mode on Windows would write each newline as CR LF.
    """
    done = subprocess.run(["git", "-C", str(path), *args], input = text.encode(), check = True, capture_output = True)
    return done.stdout.decode().strip()


def test_a_tracked_name_with_backslashes_is_closed_before_any_read(tmp_path: Path) -> None:
    path   = _clone(tmp_path, "app", SERVICE)
    blob   = _plumb(path, "def oops(:\n    SECRET_WORD = 1\n", "hash-object", "-w", "--stdin")
    listed = _git(path, "ls-tree", "HEAD")
    names  = "".join(f"100644 blob {blob}\t{name}\n" for name in ("keys\\secret.py", "conf\\.ENV.py"))
    tree   = _plumb(path, f"{listed}\n{names}", "mktree")
    commit = _plumb(path, "", "commit-tree", tree, "-p", "HEAD", "-m", "names with backslashes")
    _git(path, "update-ref", "refs/remotes/origin/main", commit)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 0, done.stdout + done.stderr
    assert "secret" not in done.stdout and ".ENV" not in done.stdout and "Incomplete" not in done.stdout


def test_a_clone_reached_through_a_link_outside_the_root_is_refused(tmp_path: Path) -> None:
    outside = _clone(tmp_path / "outside", "app", SERVICE)
    root    = tmp_path / "root"
    root.mkdir()
    try:
        os.symlink(outside, root / "link", target_is_directory = True)
    except OSError:
        pytest.skip("this machine makes no symbolic link")
    done = _run(root, "callers", "svc.core.target", "--repo", "link")
    assert done.returncode == 2 and done.stdout == "" and "through a link" in done.stderr


def test_a_class_member_bound_twice_stays_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", BASES)
    done = _run(tmp_path, "callers", "base.swapped.Swapped.save", "--repo", "app")
    resolved, _, unchecked = _groups(done.stdout, "callers")
    place = _line(BASES, "base/swapped.py", "self.save()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "self.save called by name in Swapped.store, bound more than once in its class")


def test_a_nonlocal_through_an_intermediate_function_unsettles_the_outer_binding(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "scope.lib.target", "--repo", "app").stdout, "callers")
    place = _line(SCOPES, "scope/deep.py", "value = target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "target called by name in outer.closure, bound more than once, unchecked")


def test_a_package_wins_over_a_module_file_of_the_same_name(tmp_path: Path) -> None:
    _clone(tmp_path, "app", DUPLICATE)
    done = _run(tmp_path, "callers", "dup.real.run", "--repo", "app")
    resolved, _, _ = _groups(done.stdout, "callers")
    assert done.returncode == 0 and "Incomplete" not in done.stdout
    assert _has(resolved, "dup/use.py:3 run called at module level")
    assert _has(resolved, "dup/pkg.py:5 again called in run"), "the module file the package shadows is still scanned"


def test_an_import_in_a_class_body_leads_a_self_call_to_its_origin(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, _ = _groups(_run(tmp_path, "callers", "scope.lib.target", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(SCOPES, "scope/klass.py", "self.target()") + "self.target called in Holds.call")


def test_a_default_naming_its_own_def_comes_before_the_binding(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    done = _run(tmp_path, "callers", "scope.early.target", "--repo", "app")
    resolved, _, unchecked = _groups(done.stdout, "callers")
    place = _line(SCOPES, "scope/early.py", "value = target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "target called by name at module level, used before its binding, unchecked")


def test_a_use_inside_its_own_statement_runs_before_the_binding_and_a_body_runs_after(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "scope.early.Target", "--repo", "app").stdout, "callers")
    place = _line(SCOPES, "scope/early.py", "value = Target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "Target called by name in class Target, used before its binding, unchecked")
    assert _has(resolved, _line(SCOPES, "scope/early.py", "return Target()") + "Target called in Target.build")
    resolved, _, unchecked = _groups(
        _run(tmp_path, "callers", "scope.early.outer.inner", "--repo", "app").stdout,
        "callers",
    )
    place = _line(SCOPES, "scope/early.py", "value = inner()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "inner called by name in outer, used before its binding, unchecked")
    resolved, _, _ = _groups(_run(tmp_path, "callers", "scope.early.recurse", "--repo", "app").stdout, "callers")
    assert _has(resolved, _line(SCOPES, "scope/early.py", "return recurse()") + "recurse called in recurse")


def test_a_self_declared_global_is_no_method_receiver(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    done = _run(tmp_path, "callers", "scope.selfish.Holder.target", "--repo", "app")
    resolved, _, unchecked = _groups(done.stdout, "callers")
    place = _line(SCOPES, "scope/selfish.py", "return self.target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "self.target a reference by name") or _has(unchecked, place + "self.target called")


def test_a_submodule_resolves_only_where_an_import_loads_it_and_a_missing_member_never(tmp_path: Path) -> None:
    _clone(tmp_path, "app", LOADED)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "pkg.core.target", "--repo", "app").stdout, "callers")
    assert _has(resolved, "use/loads.py:3 pkg.core.target called at module level")
    assert not _has(resolved, "use/plain.py:3 ")
    assert _has(
        unchecked,
        "use/plain.py:3 pkg.core.target called at module level, a submodule no import of it here " "loads, unchecked",
    )
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "pkg.core.missing", "--repo", "app").stdout, "callers")
    assert not _has(resolved, "use/absent.py:3 ")
    assert _has(unchecked, "use/absent.py:3 pkg.core.missing called at module level, not bound in pkg.core, unchecked")


def test_an_import_after_a_module_level_use_loads_nothing_for_it(tmp_path: Path) -> None:
    _clone(tmp_path, "app", LOADED)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "pkg.core.target", "--repo", "app").stdout, "callers")
    assert not _has(resolved, "use/late.py:3 ")
    assert _has(unchecked, "use/late.py:3 pkg.core.target called at module level, a submodule no import of it here")


def test_an_annotation_with_no_value_binds_no_module_member(tmp_path: Path) -> None:
    _clone(tmp_path, "app", LOADED)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "use.hinted.target", "--repo", "app").stdout, "callers")
    assert not _has(resolved, "use/hint_user.py:3 ")
    assert _has(unchecked, "use/hint_user.py:3 use.hinted.target called at module level, not bound in use.hinted")


def test_a_class_reached_through_its_module_inside_its_own_body_is_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", LOADED)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "use.itself.Self", "--repo", "app").stdout, "callers")
    assert not _has(resolved, "use/itself.py:5 ")
    assert _has(unchecked, "use/itself.py:5 use.itself.Self called by name in class Self, used before its binding")


def test_a_nested_class_body_binding_self_is_no_method_receiver(tmp_path: Path) -> None:
    _clone(tmp_path, "app", SCOPES)
    done = _run(tmp_path, "callers", "scope.selfish.Holder.target", "--repo", "app")
    resolved, _, unchecked = _groups(done.stdout, "callers")
    place = _line(SCOPES, "scope/selfish.py", "found = self.target()")
    assert not _has(resolved, place)
    assert _has(unchecked, place + "self.target called by name in class Holder.inner_class.Nested")


def test_the_default_reads_the_remote_ref_never_a_tag_spelled_like_it(tmp_path: Path) -> None:
    path  = _clone(tmp_path, "app", SERVICE)
    first = _git(path, "rev-parse", "HEAD")
    later = _commit(path, {"svc/extra.py": "from svc.core import target\n\ntarget()\n"})
    _track(path)
    _git(path, "tag", "origin/main", first)
    done = _run(tmp_path, "callers", "svc.core.target", "--repo", "app")
    assert done.returncode == 0, done.stderr
    assert done.stdout.startswith(f"app at origin/main {later[:7]}, ")
    assert "svc/extra.py:3 " in done.stdout

# ======================================================================================================================
# callees, what a body calls, its bounds, its body chosen and every call it makes
# ======================================================================================================================

def test_callees_lists_a_body_within_its_bounds_and_every_call_it_makes(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    done = _run(tmp_path, "callees", "cal.body.work", "--repo", "app")
    assert done.returncode == 0, done.stderr
    assert "app, the body of cal.body.work at " + _line(CALLEES, "cal/body.py", "def work").strip() in done.stdout
    resolved, values, unchecked = _groups(done.stdout, "callees")
    line = lambda needle: _line(CALLEES, "cal/body.py", needle)
    assert _has(resolved, line("    helper()") + "helper called, resolves to cal.lib.helper, a def")
    assert _has(resolved, line("[other()") + "other called, resolves to cal.lib.other, a def")
    helper = "helper called, resolves to cal.lib.helper, a def"
    assert _has(
        resolved,
        line("made = helper()") + helper + ", in class work.Inner, whose body runs as the function does",
    )
    assert _has(values, line("register(Thing)") + "Thing used, resolves to cal.lib.Thing, a class")
    assert _has(unchecked, line("lambda: other()") + "other called, resolves to cal.lib.other, a def, inside a lambda")
    assert _has(unchecked, line("(helper() for") + helper + ", inside a generator expression")
    assert _has(unchecked, line("callback()") + "callback called by name, a parameter, a local or an assignment")
    assert _has(unchecked, line('handlers["key"]()') + "handlers[] called by name, a call through a subscript")
    assert _has(unchecked, line("handlers.clear()") + "handlers.clear called by name, a method of a value whose type")
    assert _has(unchecked, line("make()()") + "make() called by name, a call through a subscript or a call's result")
    assert _has(unchecked, line("len(values)") + "len called by name, a builtin, unchecked")
    assert not any(_has(group, line("return other()")) for group in (resolved, values, unchecked)), "a nested def"
    annotation = ", in an annotation, never run with the code around it"
    assert _has(unchecked, line("unused: helper()") + helper + annotation)
    assert _has(unchecked, line("def nested(") + helper + annotation)
    assert _has(resolved, line("def nested(") + "other called, resolves to cal.lib.other, a def")
    assert not any(" values used" in entry or " callback used" in entry for entry in values + unchecked)


def test_callees_lists_one_line_for_every_call_its_body_makes(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    done   = _run(tmp_path, "callees", "cal.body.work", "--repo", "app")
    called = [entry for entry in sum(_groups(done.stdout, "callees"), []) if " called" in entry]
    tree   = ast.parse(textwrap.dedent(CALLEES["cal/body.py"]))
    work   = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "work")
    waiting, calls = list(work.body), 0
    while waiting:
        node = waiting.pop()
        # a nested def's decorators, defaults and annotations stand in the body, its own body never
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            arguments  = node.args
            parameters = [
                *arguments.posonlyargs,
                *arguments.args,
                *arguments.kwonlyargs,
                arguments.vararg,
                arguments.kwarg,
            ]
            waiting.extend([*node.decorator_list, *arguments.defaults, *filter(None, arguments.kw_defaults)])
            waiting.extend(filter(None, [arg.annotation for arg in filter(None, parameters)] + [node.returns]))
            continue
        calls += isinstance(node, ast.Call)
        waiting.extend(ast.iter_child_nodes(node))
    assert calls == 17 and len(called) == calls


def test_callees_of_a_name_with_several_bodies_keeps_every_line_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    done = _run(tmp_path, "callees", "cal.body.Box.size", "--repo", "app")
    resolved, values, unchecked = _groups(done.stdout, "callees")
    assert "cal.body.Box.size has 2 bodies, at cal/body.py:" in done.stdout
    assert resolved == [] and values == []
    assert all(entry.endswith("one of 2 bodies of this name, unchecked") for entry in unchecked) and unchecked
    done = _run(tmp_path, "callees", "cal.body.twice", "--repo", "app")
    resolved, values, unchecked = _groups(done.stdout, "callees")
    rebound = "its name or a class holding it bound more than once"
    for name in ("cal.body.twice", "cal.body.shadowed", "cal.body.Crate.work", "cal.scoped.Registry.Kept.work"):
        done = _run(tmp_path, "callees", name, "--repo", "app")
        resolved, values, unchecked = _groups(done.stdout, "callees")
        assert f"app, the body of {name} at cal/" in done.stdout, name
        assert f"{rebound}, so every line is unchecked." in done.stdout, name
        assert resolved == [] and values == [], name
        assert unchecked and all(entry.endswith(f"{rebound}, unchecked") for entry in unchecked), name


def test_callees_says_an_empty_body_a_missing_name_a_class_and_a_name_outside_apart(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    done = _run(tmp_path, "callees", "cal.body.empty", "--repo", "app")
    assert done.returncode == 1 and "app, the body of cal.body.empty at cal/body.py:" in done.stdout
    assert ", which makes no call or use the ast sees." in done.stdout
    done = _run(tmp_path, "callees", "cal.body.absent", "--repo", "app")
    assert done.returncode == 1 and "app, the clone defines no function cal.body.absent." in done.stdout
    done = _run(tmp_path, "callees", "cal.lib.Thing", "--repo", "app")
    assert done.returncode == 1
    assert "app, cal.lib.Thing is a class, so ask one of its methods, cal.lib.Thing.build, cal.lib.Thing.close." in (
        done.stdout
    )
    done = _run(tmp_path, "callees", "cal.lib.Plain", "--repo", "app")
    assert done.returncode == 1
    assert "app, cal.lib.Plain is a class that defines no method, so no body is read here." in done.stdout
    done = _run(tmp_path, "callees", "sdkpkg.auth.models.make", "--repo", "app")
    assert done.returncode == 1
    assert "app, sdkpkg.auth.models.make leads outside the clone, as imported, so no body is read here." in done.stdout
    assert _run(tmp_path, "callees", "work", "--repo", "app").returncode == 2


def test_callees_reads_the_body_resolution_selects_never_a_shadowed_file(tmp_path: Path) -> None:
    _clone(tmp_path, "app", DUPLICATE)
    done = _run(tmp_path, "callees", "dup.pkg.run", "--repo", "app")
    assert "app, the body of dup.real.run at dup/real.py:1, which makes no call or use the ast sees." in done.stdout
    assert "again" not in done.stdout


def test_callees_names_a_self_call_its_static_target_or_an_override(tmp_path: Path) -> None:
    _clone(tmp_path, "app", BASES)
    resolved, _, _ = _groups(_run(tmp_path, "callees", "base.model.Own.store", "--repo", "app").stdout, "callees")
    assert any(entry.endswith("self.save called, resolves to base.model.Own.save, a def, its class's own as the "
                              "static target, or an override") for entry in resolved)


def test_callees_skips_a_class_scope_and_its_global_for_a_method_inside(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    resolved, _, _ = _groups(_run(tmp_path, "callees", "cal.scoped.outer.Box.work", "--repo", "app").stdout, "callees")
    place = _line(CALLEES, "cal/scoped.py", "        target()")
    assert len(resolved) == 1 and _has(resolved, place + "target called, resolves to cal.scoped.outer.target, a def")


def test_callees_never_lets_a_clone_file_replace_a_builtin_module(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    resolved, _, _ = _groups(_run(tmp_path, "callees", "cal.body.system", "--repo", "app").stdout, "callees")
    assert any(entry.endswith("sys.target called, resolves to sys.target, outside the clone, as imported")
               for entry in resolved)
    assert not any("a def" in entry for entry in resolved)
    done = _run(tmp_path, "callees", "sys.target", "--repo", "app")
    assert done.returncode == 1 and "app, sys.target leads outside the clone, as imported, so no body" in done.stdout


def test_callers_labels_a_call_in_an_annotation_whatever_it_resolves_to(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    _, _, unchecked = _groups(_run(tmp_path, "callers", "cal.annotated.late", "--repo", "app").stdout, "callers")
    assert _has(unchecked, "cal/annotated.py:1 late called by name at module level, used before its binding")
    assert all(entry.endswith("in an annotation, never run with the code around it") for entry in unchecked)


def test_the_wrapper_usage_and_the_readme_name_every_command() -> None:
    commands = _module().COMMANDS
    usage    = WRAPPER.read_text(encoding = "utf-8").splitlines()[3]
    readme   = (TOOLS / "README.md").read_text(encoding = "utf-8")
    for command in commands:
        assert f" {command} " in usage, command
        assert f"bash kdf-repo-map.sh {command} " in readme, command

# ======================================================================================================================
# the wrapper, against a stand in interpreter, since GitHub's test job makes no repo .venv
# ======================================================================================================================

def _layout(tmp_path: Path, interpreter: str | None) -> tuple[Path, Path]:
    """
    A checkout holding the wrapper and the module, with a stand in at .venv/bin/python that runs or fails, or none.
    """
    tools = tmp_path / "cicd" / "tools" / "claude-code"
    tools.mkdir(parents = True)
    shutil.copy2(WRAPPER, tools / WRAPPER.name)
    shutil.copy2(MODULE, tools / MODULE.name)
    log = tmp_path / "interpreter.log"
    if interpreter is not None:
        body  = f'exec "{Path(sys.executable).as_posix()}" "$@"' if interpreter == "runs" else "exit 1"
        stand = tmp_path / "cicd" / ".venv" / "bin" / "python"
        stand.parent.mkdir(parents = True)
        stand.write_text(STAND_IN.format(log = log.as_posix(), body = body), encoding = "utf-8", newline = "\n")
        stand.chmod(0o755)
    return tools / WRAPPER.name, log


def _wrap(wrapper: Path, *args: str, role: str | None = None) -> subprocess.CompletedProcess[str]:
    environment = {key: value for key, value in os.environ.items() if key != "KDF_ROLE"}
    if role is not None:
        environment["KDF_ROLE"] = role
    return subprocess.run([str(BASH), str(wrapper), *args], capture_output = True, text = True, env = environment)


@pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "the wrapper needs bash")
def test_the_wrapper_refuses_a_reviewer_before_help_and_before_the_interpreter(tmp_path: Path) -> None:
    wrapper, log = _layout(tmp_path, None)
    for args in (("--help",), ("callers", "svc.core.target", "--repo", "app")):
        done = _wrap(wrapper, *args, role = "reviewer")
        assert done.returncode == 2 and done.stdout == "", args
        assert "reviewer role never runs the repo map" in done.stderr
    assert not log.exists()


@pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "the wrapper needs bash")
def test_the_wrapper_exits_three_naming_make_venv_with_no_usable_interpreter(tmp_path: Path) -> None:
    for interpreter in (None, "fails"):
        wrapper, _ = _layout(tmp_path / str(interpreter), interpreter)
        for args in (("--help",), ("callers", "svc.core.target", "--repo", "app")):
            done = _wrap(wrapper, *args)
            assert done.returncode == 3 and done.stdout == "", (interpreter, args)
            assert "make venv" in done.stderr


@pytest.mark.skipif(BASH is None and not os.environ.get("CI"), reason = "the wrapper needs bash")
def test_the_wrapper_passes_isolated_no_bytecode_and_every_argument_to_the_module(tmp_path: Path) -> None:
    wrapper, log = _layout(tmp_path, "runs")
    done = _wrap(wrapper, "--help")
    assert done.returncode == 0 and "What it cannot see" in done.stdout, done.stderr
    _clone(tmp_path, "app", SERVICE)
    done = _wrap(wrapper, "callers", "svc.core.target", "--repo", "app", "--root", str(tmp_path))
    assert done.returncode == 0, done.stderr
    assert "svc/use.py" in done.stdout
    last = log.read_text(encoding = "utf-8").splitlines()[-1]
    assert last.startswith("-I -B ") and "kdf_repo_map.py" in last
    assert last.endswith(f"callers svc.core.target --repo app --root {tmp_path}")
    assert not list((wrapper.parent).rglob("__pycache__"))
