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
# the labels the binding rule, a private name and a star import leave on a line they move to unchecked
SHAKY   = "bound more than once, or in a form the map does not take as certain, unchecked"
MANGLED = "a private name, which Python mangles inside a class, unchecked"
STARRED = "a star import in its scope may replace it, unchecked"
# how a written attribute names a receiver the ast cannot type, and the first parameter of a method of WRITES' class
UNKNOWN = "its type unknown to the ast"
FIRST   = "the first parameter of a def in the body of class wr.body.Store"
# the words a session hands a worker it briefs to use the map, which --help prints whole
WORKER_BRIEF = """\
Start with the repo map, a lookup over the repos' Python at the commits above, read from git's objects. Run it in
Bash on one line with single quotes, since the guard refuses a $ or a backtick inside double quotes, as
bash <the wrapper> <command> <name> --repo <clone> --at <clone>=<commit>
with a --repo and an --at for each repo the lookup names. Its commands are defs <name> (where a bare or dotted name
is defined), imports <dotted module> (who imports it or a name in it), callers <dotted name> (resolved calls, uses
that are not calls, and unchecked matches kept by name), callees <dotted function> (what that function's own body
calls and uses, the repo's class members and module values among them, then the attributes it writes, a def nested
in it apart), and test-importers <dotted> (test files that import it, those through a re-export, the unchecked
matches, then the test candidates that use it). What a function does, its conditions and its values, is read in its
body. Add --tests to keep tests in imports and callers, and --full to print a group past its 40 lines. Each answer
gives its resolved lines first, each line <clone>@<hash> <path>:<line>. An empty group proves no absence, so search
before you say there is none. Read a line at the answer's commit, with git -C <clone> show <hash>:<path>, or with
Read in a checkout you know is clean at that commit, and search for a name the map was not given or what it names
as unseen with git -C <clone> grep -n '<pattern>' <hash>, or with Grep in such a checkout. The guard refuses grep
-r, and an awk program that runs a command, reads the environment or writes a file, so use neither.
"""
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

VALUES = {
    "val/__init__.py": "",
    "val/enums.py": """
        import os

        FLAG = True


        class Status:
            active = "active"
            same = same = "same"
            twice = 1
            twice = 2
            dropped = 1
            del dropped
            if FLAG:
                guarded = 1
            try:
                tried = 1
            except ValueError:
                pass
            try:
                grouped = 1
            except* ValueError:
                pass
            for _ in range(1):
                looped = 1
            with os.scandir(".") as entries:
                held = 1
            FLAG and (walrus := 1)
            written = 1

            def describe(self):
                return 1


        class Child(Status):
            pass


        Status.written = 2
        """,
    "val/limits.py": """
        import os

        MAX = 3
        SAME = SAME = 4
        TWICE = 1
        TWICE = 2
        GONE = 1
        del GONE
        CHANGED = 1
        FLAG = True
        FLAG and (WALRUS := 1)
        COMPREHENDED = [(LEAKED := item) for item in range(2)]
        if os.sep:
            GUARDED = 1


        def setter():
            global GLOBALLED
            GLOBALLED = 1


        def own():
            return MAX, SAME, TWICE, CHANGED, LEAKED, GLOBALLED
        """,
    "val/relay.py": """
        import os

        from val.limits import MAX
        from val.limits import MAX as DOUBLE
        from val.limits import MAX as DOUBLE
        from val.limits import MAX as DELETED
        del DELETED
        if os.sep:
            from val.limits import MAX as GUARDED_RELAY
        """,
    "val/reader.py": """
        import os

        import val.enums
        import val.limits
        from val.enums import Child, Status
        from val.limits import CHANGED, GLOBALLED, GONE, GUARDED, LEAKED, MAX, SAME, TWICE, WALRUS
        from val.limits import MAX as ALIASED
        from val.relay import DELETED, DOUBLE, GUARDED_RELAY
        from val.relay import MAX as RELAYED

        val.limits.CHANGED = 5

        if os.sep:
            from val.limits import MAX as CONDITIONAL
            import val.limits as maybe_limits


        def members(user):
            user.reason = Status.active
            user.text = Status.active.value
            user.full = val.enums.Status.active
            user.same = Status.same
            return Status.describe


        def doubtful():
            return (
                Status.twice,
                Status.dropped,
                Status.guarded,
                Status.tried,
                Status.grouped,
                Status.looped,
                Status.held,
                Status.walrus,
                Status.written,
                Child.active,
            )


        def values():
            return MAX, ALIASED, val.limits.MAX, SAME, RELAYED


        def doubtful_values():
            return TWICE, GONE, WALRUS, LEAKED, GUARDED, GLOBALLED, CHANGED, val.limits.CHANGED, val.limits.TWICE


        def relayed():
            return DOUBLE, DELETED, GUARDED_RELAY


        def imported_inside():
            from val.limits import MAX as INSIDE
            return INSIDE


        def imported_conditionally():
            return CONDITIONAL


        def through_modules():
            import val.limits as inner_limits
            return inner_limits.MAX, maybe_limits.MAX


        def labelled():
            later = lambda: Status.active
            note: Status.active = None
            return later, note


        class Lockout:
            limit = 3

            def register(self):
                first = self.limit
                second = self.unbound
                return first, second, self.limit.real

            @classmethod
            def build(cls):
                return cls.limit


        class Derived(Status):
            def chain(self):
                return self.unbound.value, Child.active.upper


        class Twice:
            @property
            def size(self):
                return Status.active

            @size.setter
            def size(self, value):
                return SAME
        """,
}

PRIVATE = {
    "priv/__init__.py": "",
    "priv/lib.py": """
        __value = 1
        __hidden = 2


        class Keeper:
            __member = 1

            def read(self):
                return self.__member

            def write(self):
                global __hidden
                __hidden = 3

            def touch(self):
                import priv.lib
                priv.lib.__value = 4
                return priv.lib.__value
        """,
    "priv/use.py": """
        import priv.lib
        from priv.lib import Keeper


        def outside():
            return Keeper.__member


        def plain():
            return priv.lib.__value


        def hidden():
            return priv.lib.__hidden
        """,
}

STARS = {
    "star/__init__.py": "",
    "star/source.py": "def target():\n    return 1\n\n\ndef helper():\n    return 2\n\n\nVALUE = 1\n",
    "star/early.py": """
        from star.source import *


        def target():
            return helper()


        VALUE = 2
        """,
    "star/late.py": """
        from star.source import helper


        def target():
            return helper()


        VALUE = 3

        from star.source import *
        """,
    "star/looped.py": """
        for _ in range(1):
            from star.source import *

        from star.source import VALUE, target
        """,
    "star/use.py": """
        from star.early import VALUE as EARLY
        from star.early import target as early_target
        from star.late import VALUE as LATE
        from star.late import target as late_target
        from star.looped import VALUE as LOOPED
        from star.looped import target as looped_target


        def run():
            early_target()
            late_target()
            looped_target()
            return EARLY, LATE, LOOPED
        """,
    "tests/test_star.py": "from star.looped import target\n",
}

REGRESSION = {
    "reg/__init__.py": "",
    "reg/lib.py": "def helper():\n    return 1\n\n\nclass Thing:\n    def run(self):\n        return 1\n",
    "reg/relay.py": """
        import os

        if os.sep:
            from reg.lib import helper

        from reg.lib import Thing
        from reg.lib import Thing
        """,
    "reg/use.py": """
        import os

        from reg.relay import Thing, helper

        if os.sep:
            from reg.lib import helper as guarded


        def work():
            helper()
            guarded()
            made = Thing()
            made.run()
            return Thing


        def inside():
            if os.sep:
                from reg.lib import helper as nested
            return nested()
        """,
}

WRITES = {
    "wr/__init__.py": "",
    "wr/real.py": "LIMIT = 1\n",
    "wr/facade.py": "from wr.real import LIMIT\n",
    "wr/settings.py": "FLAG = False\n",
    "wr/body.py": """
        import os

        import wr.facade
        import wr.settings

        static = staticmethod


        def make():
            return Store()


        def replace(item):
            return item


        class Store:
            import wr.settings as settings

            count = 0

            def plain(self, user, items, handle):
                self.count = 1
                self.count += 1
                for self.item in items:
                    pass
                with handle as self.held:
                    pass
                self.first, user.second = 1, 2
                del self.held
                user.name = "name"
                local = object()
                local.size = 2
                make().attr = 3
                items[0].attr = 4
                self.settings.FLAG = True
                Store.count = 5
                wr.settings.FLAG = True
                wr.facade.LIMIT = 6
                os.environ.extra = 7
                self.__secret = 8
                make().hint: int
                nested = [1 for user.slot in items]
                lazy = (1 for user.later in items)

                class Inner:
                    user.inner = 1

                return nested, lazy, Inner

            @classmethod
            def built(self):
                self.made = 1

            def swapped(cls):
                cls.flag = 1

            @staticmethod
            def fixed(self):
                self.fixed = 1

            @static
            def aliased(self):
                self.aliased = 1

            def rebound(self):
                self = replace(self)
                self.value = 1

            def bare(*args):
                self.value = 2
        """,
}

CROSSINGS = {
    "cx/__init__.py": "",
    "cx/cfg.py": "V = 1\n",
    "cx/lib.py": "def target():\n    return 1\n\n\nclass K:\n    V = 1\n",
    "cx/facade.py": "import os\n\nif os.sep:\n    from cx import cfg\n",
    "cx/plain.py": "from cx import cfg\n",
    "cx/alias.py": "from cx.lib import target as alias\n",
    "cx/relay.py": "from cx.cfg import V as X\n\ndel X\n",
    "cx/aliasuse.py": "from cx.relay import X as Alias\n",
    "cx/reader.py": """
        import os

        import cx.facade
        import cx.lib
        import cx.plain

        if os.sep:
            from cx.lib import K


        def through_conditional():
            return cx.facade.cfg.V, K.V


        class Reader:
            from cx.lib import K

            def run(self):
                return self.K.V


        def change(other):
            cx.plain.cfg = other
            cx.lib.K = other


        def through_written():
            return cx.plain.cfg.V, cx.lib.K.V
        """,
    "cx/starred.py": """
        import cx.alias as api
        from cx.cfg import *


        def run():
            return api.alias()
        """,
}

CANDIDATES = {
    "cand/__init__.py": "",
    "cand/service.py": """
        class Lockout:
            def register(self):
                return 1


        def helper():
            return Lockout()
        """,
    "cand/facade/__init__.py": "from cand.service import Lockout\n",
    "tests/__init__.py": "",
    "tests/conftest.py": """
        from cand.service import Lockout


        def test_in_conftest():
            return Lockout()
        """,
    "tests/test_lockout.py": """
        from cand.facade import Lockout
        from cand.service import helper


        def test_module_level():
            return Lockout()


        def test_nested():
            def inner():
                return Lockout

            later = lambda: Lockout

            class Holder:
                kept = Lockout

            return inner, later, Holder


        def test_by_name(service):
            return service.register()


        def test_through_helper():
            return helper()


        def test_fixture(lockout):
            return lockout


        def test_twice():
            return Lockout()


        def test_twice():
            return Lockout()


        class TestKept:
            def test_method(self):
                return Lockout.register

            def helper_method(self):
                return Lockout()


        class TestLock:
            def test_first(self):
                return Lockout()


        class TestLock:
            def test_again(self):
                return Lockout()


        class Other:
            def test_not_a_candidate(self):
                return Lockout()
        """,
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
    Split an answer's lines into its groups, by the titles the module prints, three, or four for callees and
    test-importers.
    """
    titles  = _module().TITLES[command]
    groups  = [[] for _ in titles]
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
    found, _, _, _ = _groups(_run(tmp_path, "test-importers", "api.core", "--repo", "app").stdout, "test-importers")
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
    resolved, values, unchecked, _ = _groups(done.stdout, "callees")
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
    resolved, values, unchecked, _ = _groups(done.stdout, "callees")
    assert "cal.body.Box.size has 2 bodies, at cal/body.py:" in done.stdout
    assert resolved == [] and values == []
    assert all(entry.endswith("one of 2 bodies of this name, unchecked") for entry in unchecked) and unchecked
    done = _run(tmp_path, "callees", "cal.body.twice", "--repo", "app")
    resolved, values, unchecked, _ = _groups(done.stdout, "callees")
    rebound = "its name or a class holding it bound more than once"
    for name in ("cal.body.twice", "cal.body.shadowed", "cal.body.Crate.work", "cal.scoped.Registry.Kept.work"):
        done = _run(tmp_path, "callees", name, "--repo", "app")
        resolved, values, unchecked, _ = _groups(done.stdout, "callees")
        assert f"app, the body of {name} at cal/" in done.stdout, name
        assert f"{rebound}, so every line is unchecked." in done.stdout, name
        assert resolved == [] and values == [], name
        assert unchecked and all(entry.endswith(f"{rebound}, unchecked") for entry in unchecked), name


def test_callees_says_an_empty_body_a_missing_name_a_class_and_a_name_outside_apart(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    done = _run(tmp_path, "callees", "cal.body.empty", "--repo", "app")
    assert done.returncode == 1 and "app, the body of cal.body.empty at cal/body.py:" in done.stdout
    assert ", which makes no call, use or write the ast sees." in done.stdout
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
    assert "app, the body of dup.real.run at dup/real.py:1, which makes no call, use or write the ast sees." in (
        done.stdout
    )
    assert "again" not in done.stdout


def test_callees_names_a_self_call_its_static_target_or_an_override(tmp_path: Path) -> None:
    _clone(tmp_path, "app", BASES)
    resolved, _, _, _ = _groups(_run(tmp_path, "callees", "base.model.Own.store", "--repo", "app").stdout, "callees")
    assert any(entry.endswith("self.save called, resolves to base.model.Own.save, a def, its class's own as the "
                              "static target, or an override") for entry in resolved)


def test_callees_skips_a_class_scope_and_its_global_for_a_method_inside(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    resolved, _, _, _ = _groups(
        _run(tmp_path, "callees", "cal.scoped.outer.Box.work", "--repo", "app").stdout,
        "callees",
    )
    place = _line(CALLEES, "cal/scoped.py", "        target()")
    assert len(resolved) == 1 and _has(resolved, place + "target called, resolves to cal.scoped.outer.target, a def")


def test_callees_never_lets_a_clone_file_replace_a_builtin_module(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CALLEES)
    resolved, _, _, _ = _groups(_run(tmp_path, "callees", "cal.body.system", "--repo", "app").stdout, "callees")
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

# ======================================================================================================================
# the binding rule, a class's members and a module's values in callees, and the two false lines closed
# ======================================================================================================================

def _callees(root: Path, name: str) -> list[list[str]]:
    """
    The groups of a callees answer for one name in the clone app.
    """
    done = _run(root, "callees", name, "--repo", "app")
    assert done.returncode in (0, 1), done.stderr
    return _groups(done.stdout, "callees")


def test_callees_names_a_class_member_read_through_its_class(tmp_path: Path) -> None:
    _clone(tmp_path, "app", VALUES)
    resolved, values, unchecked, _ = _callees(tmp_path, "val.reader.members")
    line   = lambda needle: _line(VALUES, "val/reader.py", needle)
    member = "resolves to val.enums.Status.active, a member bound in the body of class val.enums.Status"
    assert _has(values, line("user.reason = Status.active") + f"Status.active used, {member}")
    assert _has(values, line("Status.active.value") + f"Status.active used, {member}")
    assert _has(values, line("val.enums.Status.active") + f"val.enums.Status.active used, {member}")
    same = "resolves to val.enums.Status.same, a member bound in the body of class val.enums.Status"
    assert _has(values, line("Status.same") + f"Status.same used, {same}"), "V = V = 1 is one statement"
    assert _has(values, line("Status.describe") + "Status.describe used, resolves to val.enums.Status.describe, a def")
    assert not any("Status.active.value" in entry for entry in resolved + values + unchecked)


def test_a_self_or_cls_read_of_a_member_is_unchecked_and_of_a_name_its_class_does_not_bind_left_out(
    tmp_path: Path,
) -> None:
    _clone(tmp_path, "app", VALUES)
    words = "bound in the body of class val.reader.Lockout, an instance or a subclass may hold its own, unchecked"
    line  = lambda needle: _line(VALUES, "val/reader.py", needle)
    resolved, values, unchecked, _ = _callees(tmp_path, "val.reader.Lockout.register")
    assert resolved == [] and values == []
    assert _has(unchecked, line("first = self.limit") + f"self.limit used, {words}")
    assert _has(unchecked, line("self.limit.real") + f"self.limit used, {words}")
    assert not any("self.unbound" in entry for entry in unchecked)
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.Lockout.build")
    assert values == [] and _has(unchecked, line("return cls.limit") + f"cls.limit used, {words}")
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.Derived.chain")
    assert values == [] and not any("self.unbound" in entry for entry in unchecked), "a base never names a self chain"
    assert _has(
        unchecked,
        line("Child.active.upper") + "Child.active used, through its base val.enums.Status, unchecked",
    )


def test_a_member_bound_in_a_form_the_map_does_not_take_as_certain_is_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", VALUES)
    resolved, values, unchecked, _ = _callees(tmp_path, "val.reader.doubtful")
    line = lambda needle: _line(VALUES, "val/reader.py", needle)
    assert resolved == [] and values == []
    for member in ("twice", "dropped", "guarded", "tried", "grouped", "looped", "held", "walrus"):
        words = f"Status.{member} used, {SHAKY}, val.enums.Status.{member}"
        assert _has(unchecked, line(f"Status.{member},") + words), member
    written = _line(VALUES, "val/enums.py", "Status.written = 2").strip()
    words   = f"Status.written used, written elsewhere at {written}, unchecked, val.enums.Status.written"
    assert _has(unchecked, line("Status.written,") + words)
    assert _has(unchecked, line("Child.active,") + "Child.active used, through its base val.enums.Status, unchecked")


def test_a_module_value_resolves_through_an_import_an_established_module_and_bare_in_its_own_module(
    tmp_path: Path,
) -> None:
    _clone(tmp_path, "app", VALUES)
    value = "resolves to val.limits.MAX, a value bound at module level in val.limits"
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.values")
    place = _line(VALUES, "val/reader.py", "return MAX, ALIASED")
    for text in ("MAX", "ALIASED", "val.limits.MAX", "RELAYED"):
        assert _has(values, place + f"{text} used, {value}"), text
    assert _has(values, place + "SAME used, resolves to val.limits.SAME, a value bound at module level in val.limits")
    assert unchecked == []
    _, values, _, _ = _callees(tmp_path, "val.reader.imported_inside")
    assert _has(values, _line(VALUES, "val/reader.py", "return INSIDE") + f"INSIDE used, {value}")
    _, values, _, _ = _callees(tmp_path, "val.limits.own")
    assert _has(values, _line(VALUES, "val/limits.py", "return MAX, SAME") + f"MAX used, {value}")


def test_a_module_value_bound_or_written_uncertainly_is_unchecked_in_every_form(tmp_path: Path) -> None:
    _clone(tmp_path, "app", VALUES)
    line    = lambda needle: _line(VALUES, "val/reader.py", needle)
    written = line("val.limits.CHANGED = 5").strip()
    changed = f"written elsewhere at {written}, unchecked, val.limits.CHANGED"
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.doubtful_values")
    place = line("return TWICE, GONE")
    assert values == []
    for name in ("TWICE", "GONE", "WALRUS", "LEAKED", "GUARDED", "GLOBALLED"):
        assert _has(unchecked, place + f"{name} used, {SHAKY}, val.limits.{name}"), name
    assert _has(unchecked, place + f"val.limits.TWICE used, {SHAKY}, val.limits.TWICE")
    for text in ("CHANGED", "val.limits.CHANGED"):
        assert _has(unchecked, place + f"{text} used, {changed}"), text
    _, values, unchecked, _ = _callees(tmp_path, "val.limits.own")
    place = _line(VALUES, "val/limits.py", "return MAX, SAME")
    assert _has(unchecked, place + f"TWICE used, {SHAKY}, val.limits.TWICE")
    assert _has(unchecked, place + f"CHANGED used, {changed}")
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.relayed")
    assert values == []
    for name in ("DOUBLE", "DELETED", "GUARDED_RELAY"):
        assert _has(unchecked, line("return DOUBLE") + f"{name} used, {SHAKY}, val.limits.MAX"), name
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.imported_conditionally")
    assert values == [] and _has(unchecked, line("return CONDITIONAL") + f"CONDITIONAL used, {SHAKY}, val.limits.MAX")


def test_a_value_through_a_module_imported_conditionally_is_unchecked_and_through_one_imported_twice_is_not(
    tmp_path: Path,
) -> None:
    _clone(tmp_path, "app", VALUES)
    value = "resolves to val.limits.MAX, a value bound at module level in val.limits"
    place = _line(VALUES, "val/reader.py", "return inner_limits.MAX")
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.through_modules")
    assert _has(values, place + f"inner_limits.MAX used, {value}")
    assert _has(unchecked, place + f"maybe_limits.MAX used, {SHAKY}, val.limits.MAX")
    _, values, _, _ = _callees(tmp_path, "val.reader.values")
    place = _line(VALUES, "val/reader.py", "return MAX, ALIASED")
    assert _has(values, place + f"val.limits.MAX used, {value}"), "import val.enums and import val.limits bind val once"
    resolved, values, unchecked = _groups(
        _run(tmp_path, "callers", "val.limits.MAX", "--repo", "app").stdout,
        "callers",
    )
    place = _line(VALUES, "val/reader.py", "return inner_limits.MAX")
    assert _has(values, place + "inner_limits.MAX used in through_modules")
    assert _has(unchecked, place + f"maybe_limits.MAX used in through_modules, {SHAKY}")


def test_a_value_under_the_rule_moves_callers_imports_and_test_importers_toward_unchecked_alone(
    tmp_path: Path,
) -> None:
    files = dict(VALUES, **{"tests/test_values.py": "from val.relay import GUARDED_RELAY\nfrom val.relay import MAX\n"})
    _clone(tmp_path, "app", files)
    line = lambda needle: _line(VALUES, "val/reader.py", needle)
    resolved, values, unchecked = _groups(
        _run(tmp_path, "callers", "val.limits.MAX", "--repo", "app").stdout,
        "callers",
    )
    for text in ("MAX", "ALIASED", "val.limits.MAX", "RELAYED"):
        assert _has(values, line("return MAX, ALIASED") + f"{text} used in values"), text
    assert _has(values, line("return INSIDE") + "INSIDE used in imported_inside")
    for text in ("DOUBLE", "DELETED", "GUARDED_RELAY"):
        assert _has(unchecked, line("return DOUBLE") + f"{text} used in relayed, {SHAKY}"), text
    assert _has(unchecked, line("return CONDITIONAL") + f"CONDITIONAL used in imported_conditionally, {SHAKY}")
    assert not any(_has(group, line("return DOUBLE")) for group in (resolved, values))
    _, through, unchecked = _groups(_run(tmp_path, "imports", "val.limits", "--repo", "app").stdout, "imports")
    relay = "at module level, through a re-export to val.limits.MAX"
    assert _has(through, line("import MAX as RELAYED") + f"imports val.relay.MAX {relay}")
    for name in ("DELETED", "DOUBLE", "GUARDED_RELAY"):
        assert _has(unchecked, line("import DELETED") + f"imports val.relay.{name} {relay}, {SHAKY}"), name
    done = _run(tmp_path, "test-importers", "val.limits", "--repo", "app")
    _, through, unchecked, _ = _groups(done.stdout, "test-importers")
    assert _has(through, f"tests/test_values.py:2 imports val.relay.MAX {relay}")
    assert _has(unchecked, f"tests/test_values.py:1 imports val.relay.GUARDED_RELAY {relay}, {SHAKY}")


def test_a_new_line_carries_the_annotation_deferred_and_several_bodies_labels(tmp_path: Path) -> None:
    _clone(tmp_path, "app", VALUES)
    line   = lambda needle: _line(VALUES, "val/reader.py", needle)
    member = "resolves to val.enums.Status.active, a member bound in the body of class val.enums.Status"
    member = f"Status.active used, {member}"
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.labelled")
    assert values == []
    assert _has(unchecked, line("lambda: Status.active") + f"{member}, inside a lambda, runs when it is called")
    assert _has(
        unchecked,
        line("note: Status.active") + f"{member}, in an annotation, never run with the code around it",
    )
    _, values, unchecked, _ = _callees(tmp_path, "val.reader.Twice.size")
    assert values == []
    assert _has(unchecked, line("return Status.active") + f"{member}, one of 2 bodies of this name, unchecked")
    same = "SAME used, resolves to val.limits.SAME, a value bound at module level in val.limits"
    assert _has(unchecked, line("return SAME") + f"{same}, one of 2 bodies of this name, unchecked")


def test_a_private_name_is_unchecked_as_mangled_in_callees_and_callers(tmp_path: Path) -> None:
    _clone(tmp_path, "app", PRIVATE)
    use = lambda needle: _line(PRIVATE, "priv/use.py", needle)
    lib = lambda needle: _line(PRIVATE, "priv/lib.py", needle)
    _, values, unchecked, _ = _callees(tmp_path, "priv.use.outside")
    assert values == [] and _has(unchecked, use("Keeper.__member") + f"Keeper.__member used, {MANGLED}")
    _, values, unchecked, _ = _callees(tmp_path, "priv.lib.Keeper.read")
    assert values == [] and _has(unchecked, lib("self.__member") + f"self.__member used, {MANGLED}")
    resolved, values, unchecked = _groups(
        _run(tmp_path, "callers", "priv.lib.Keeper.__member", "--repo", "app").stdout,
        "callers",
    )
    assert resolved == [] and values == []
    assert _has(unchecked, use("Keeper.__member") + f"Keeper.__member used in outside, {MANGLED}")
    assert _has(unchecked, lib("self.__member") + f"self.__member used in Keeper.read, {MANGLED}")
    for name, function in (("__hidden", "hidden"), ("__value", "plain")):
        _, values, unchecked, _ = _callees(tmp_path, f"priv.use.{function}")
        assert values == [] and _has(unchecked, use(f"priv.lib.{name}") + f"priv.lib.{name} used, {MANGLED}"), name
        resolved, values, unchecked = _groups(
            _run(tmp_path, "callers", f"priv.lib.{name}", "--repo", "app").stdout,
            "callers",
        )
        assert resolved == [] and values == [], name
        assert _has(unchecked, use(f"priv.lib.{name}") + f"priv.lib.{name} used in {function}, {MANGLED}"), name
    _, _, unchecked = _groups(_run(tmp_path, "callers", "priv.lib.__value", "--repo", "app").stdout, "callers")
    assert _has(unchecked, lib("return priv.lib.__value") + f"priv.lib.__value used in Keeper.touch, {MANGLED}")


def test_a_binding_a_star_import_may_replace_is_unchecked_in_every_command(tmp_path: Path) -> None:
    _clone(tmp_path, "app", STARS)
    line = lambda needle: _line(STARS, "star/use.py", needle)
    resolved, values, unchecked, _ = _callees(tmp_path, "star.use.run")
    assert _has(resolved, line("early_target()") + "early_target called, resolves to star.early.target, a def")
    early = "EARLY used, resolves to star.early.VALUE, a value bound at module level in star.early"
    assert _has(values, line("return EARLY") + early)
    for text, origin in (("late_target", "star.late.target"), ("looped_target", "star.source.target")):
        assert _has(unchecked, line(f"    {text}()") + f"{text} called, {STARRED}, {origin}"), text
    for text, origin in (("LATE", "star.late.VALUE"), ("LOOPED", "star.source.VALUE")):
        assert _has(unchecked, line("return EARLY") + f"{text} used, {STARRED}, {origin}"), text
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "star.late.target", "--repo", "app").stdout, "callers")
    assert resolved == [] and _has(unchecked, line("    late_target()") + f"late_target called in run, {STARRED}")
    resolved, _, _ = _groups(_run(tmp_path, "callers", "star.early.target", "--repo", "app").stdout, "callers")
    assert _has(resolved, line("    early_target()") + "early_target called in run")
    _, through, unchecked = _groups(_run(tmp_path, "imports", "star.source", "--repo", "app").stdout, "imports")
    relay = "imports star.looped.target at module level, through a re-export to star.source.target"
    assert _has(unchecked, line("import target as looped_target") + f"{relay}, {STARRED}")
    assert not _has(through, line("import target as looped_target"))
    done = _run(tmp_path, "test-importers", "star.source", "--repo", "app")
    _, through, unchecked, _ = _groups(done.stdout, "test-importers")
    assert _has(unchecked, f"tests/test_star.py:1 {relay}, {STARRED}") and not _has(through, "tests/test_star.py:1 ")
    found, _, unchecked = _groups(_run(tmp_path, "defs", "target", "--repo", "app").stdout, "defs")
    assert _has(found, _line(STARS, "star/early.py", "def target") + "def star.early.target")
    assert _has(unchecked, _line(STARS, "star/late.py", "def target") + f"def star.late.target, {STARRED}")
    bound = "star.looped.target bound by an import of star.source.target"
    assert _has(unchecked, _line(STARS, "star/looped.py", "import VALUE, target") + f"{bound}, {STARRED}")
    done = _run(tmp_path, "callees", "star.late.target", "--repo", "app")
    resolved, values, unchecked, _ = _groups(done.stdout, "callees")
    assert "a star import in its scope may replace it, so every line is unchecked." in done.stdout
    assert resolved == [] and values == [] and unchecked
    assert all(entry.endswith(STARRED) for entry in unchecked)


def test_a_def_and_a_class_answer_as_before_in_every_other_form(tmp_path: Path) -> None:
    _clone(tmp_path, "app", REGRESSION)
    line = lambda needle: _line(REGRESSION, "reg/use.py", needle)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "reg.lib.helper", "--repo", "app").stdout, "callers")
    for needle, words in (("    helper()", "helper called in work"), ("guarded()", "guarded called in work")):
        assert _has(resolved, line(needle) + words), needle
    assert _has(resolved, line("return nested()") + "nested called in inside") and unchecked == []
    resolved, values, _ = _groups(_run(tmp_path, "callers", "reg.lib.Thing", "--repo", "app").stdout, "callers")
    assert _has(resolved, line("Thing()") + "Thing called in work")
    assert _has(values, line("return Thing") + "Thing used in work")
    resolved, values, _, _ = _callees(tmp_path, "reg.use.work")
    assert _has(resolved, line("    helper()") + "helper called, resolves to reg.lib.helper, a def")
    assert _has(resolved, line("Thing()") + "Thing called, resolves to reg.lib.Thing, a class")
    assert _has(values, line("return Thing") + "Thing used, resolves to reg.lib.Thing, a class")

def test_a_value_through_a_receiver_bound_on_a_condition_or_through_self_is_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CROSSINGS)
    line = lambda needle: _line(CROSSINGS, "cx/reader.py", needle)
    _, values, unchecked, _ = _callees(tmp_path, "cx.reader.through_conditional")
    place = line("return cx.facade.cfg.V")
    assert values == []
    assert _has(unchecked, place + f"cx.facade.cfg.V used, {SHAKY}, cx.cfg.V"), "a module a module on the way imports on a condition"
    assert _has(unchecked, place + f"K.V used, {SHAKY}, cx.lib.K.V"), "a class the reader imports on a condition"
    _, values, unchecked, _ = _callees(tmp_path, "cx.reader.Reader.run")
    hedge = "through self or cls, which an instance or a subclass may replace, unchecked"
    assert values == [] and _has(unchecked, line("return self.K.V") + f"self.K.V used, {hedge}, cx.lib.K.V")


def test_a_write_to_a_receiver_on_the_way_leaves_the_value_read_through_it_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CROSSINGS)
    line = lambda needle: _line(CROSSINGS, "cx/reader.py", needle)
    _, values, unchecked, _ = _callees(tmp_path, "cx.reader.through_written")
    place = line("return cx.plain.cfg.V")
    cfg   = line("cx.plain.cfg = other").strip()
    klass = line("cx.lib.K = other").strip()
    assert values == []
    assert _has(unchecked, place + f"cx.plain.cfg.V used, written elsewhere at {cfg}, unchecked, cx.cfg.V")
    assert _has(unchecked, place + f"cx.lib.K.V used, written elsewhere at {klass}, unchecked, cx.lib.K.V")


def test_a_use_through_a_receiver_a_star_may_replace_stays_in_the_unchecked_matches(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CROSSINGS)
    resolved, _, unchecked = _groups(_run(tmp_path, "callers", "cx.lib.target", "--repo", "app").stdout, "callers")
    place = _line(CROSSINGS, "cx/starred.py", "api.alias()")
    assert not _has(resolved, place) and _has(unchecked, place + f"api.alias called in run, {STARRED}")


def test_defs_keeps_every_binding_on_the_way_to_a_name_a_del_leaves_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CROSSINGS)
    _, _, unchecked = _groups(_run(tmp_path, "defs", "cx.aliasuse.Alias", "--repo", "app").stdout, "defs")
    assert _has(unchecked, "cx/relay.py:3 cx.relay.X bound by assignment, unchecked")
    assert _has(unchecked, f"cx/relay.py:1 cx.relay.X bound by an import of cx.cfg.V, {SHAKY}")

# ======================================================================================================================
# the attributes a body writes, callees' fourth group
# ======================================================================================================================

def test_callees_lists_every_attribute_its_body_writes_in_a_fourth_group(tmp_path: Path) -> None:
    _clone(tmp_path, "app", WRITES)
    done = _run(tmp_path, "callees", "wr.body.Store.plain", "--repo", "app")
    assert done.returncode == 0, done.stderr
    assert "Attributes written, " in done.stdout
    *_, writes = _groups(done.stdout, "callees")
    line = lambda needle: _line(WRITES, "wr/body.py", needle)
    for needle, words in (
        ("self.count = 1", f"self.count written, on self, {FIRST}"),
        ("self.count += 1", f"self.count written, on self, {FIRST}"),
        ("for self.item", f"self.item written, on self, {FIRST}"),
        ("as self.held", f"self.held written, on self, {FIRST}"),
        ("self.first, user.second", f"self.first written, on self, {FIRST}"),
        ("self.first, user.second", f"user.second written, on user, {UNKNOWN}"),
        ("del self.held", f"self.held deleted, on self, {FIRST}"),
        ("self.__secret", f"self.__secret written, on self, {FIRST}, {MANGLED}"),
    ):
        assert _has(writes, line(needle) + words), needle
    assert not any("an instance" in entry or "the class " in entry for entry in writes)


def test_a_written_attribute_names_its_receiver_only_when_the_receiver_itself_is_known(tmp_path: Path) -> None:
    _clone(tmp_path, "app", WRITES)
    resolved, _, _, writes = _callees(tmp_path, "wr.body.Store.plain")
    line   = lambda needle: _line(WRITES, "wr/body.py", needle)
    facade = "wr.facade.LIMIT written, on module wr.facade, which wr.facade imports from wr.real.LIMIT"
    for needle, words in (
        ("Store.count = 5", "Store.count written, on class wr.body.Store"),
        ("wr.settings.FLAG", "wr.settings.FLAG written, on module wr.settings"),
        ("wr.facade.LIMIT", facade),
        ("os.environ.extra", "os.environ.extra written, on os.environ, outside the clone, as imported"),
        ("user.name", f"user.name written, on user, {UNKNOWN}"),
        ("local.size", f"local.size written, on local, {UNKNOWN}"),
        ("make().attr", f"make().attr written, on make(), {UNKNOWN}"),
        ("items[0].attr", f"items[].attr written, on items[], {UNKNOWN}"),
        ("self.settings.FLAG", f"self.settings.FLAG written, on self.settings, {UNKNOWN}"),
    ):
        assert _has(writes, line(needle) + words), needle
    hint = line("make().hint")
    assert not _has(writes, hint), "an annotated attribute with no value writes nothing"
    assert _has(resolved, hint + "make called, resolves to wr.body.make, a def"), "its receiver still runs"


def test_a_first_parameter_is_worded_from_the_source_never_as_an_instance_or_the_class(tmp_path: Path) -> None:
    _clone(tmp_path, "app", WRITES)
    for name, words in (
        ("built", f"self.made written, on self, {FIRST}"),
        ("swapped", f"cls.flag written, on cls, {FIRST}"),
        ("fixed", f"self.fixed written, on self, {FIRST}"),
        ("aliased", f"self.aliased written, on self, {FIRST}"),
        ("rebound", f"self.value written, on self, {UNKNOWN}"),
        ("bare", f"self.value written, on self, {UNKNOWN}"),
    ):
        *_, writes = _callees(tmp_path, f"wr.body.Store.{name}")
        assert len(writes) == 1 and writes[0].endswith(words), (name, writes)


def test_a_write_in_a_nested_class_or_a_generator_takes_the_labels_the_other_groups_take(tmp_path: Path) -> None:
    _clone(tmp_path, "app", WRITES)
    *_, writes = _callees(tmp_path, "wr.body.Store.plain")
    line = lambda needle: _line(WRITES, "wr/body.py", needle)
    assert _has(writes, line("user.slot") + f"user.slot written, on user, {UNKNOWN}")
    later = f"user.later written, on user, {UNKNOWN}, inside a generator expression, runs as it is consumed"
    assert _has(writes, line("user.later") + later)
    inner = f"user.inner written, on user, {UNKNOWN}, in class Store.plain.Inner, whose body runs as the function does"
    assert _has(writes, line("user.inner") + inner)

# ======================================================================================================================
# the test candidates that use a name, test-importers' fourth group
# ======================================================================================================================

def _defs(path: str, needle: str) -> list[str]:
    """
    The path and line of every line of a CANDIDATES file holding the needle, as an answer names them.
    """
    lines = textwrap.dedent(CANDIDATES[path]).splitlines()
    return [f"{path}:{number} " for number, text in enumerate(lines, 1) if needle in text]


def test_test_importers_names_the_test_candidates_that_use_a_name_in_a_fourth_group(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CANDIDATES)
    done = _run(tmp_path, "test-importers", "cand.service.Lockout", "--repo", "app")
    assert done.returncode == 0, done.stderr
    found, through, unchecked, candidates = _groups(done.stdout, "test-importers")
    test     = "tests/test_lockout.py"
    relay    = "imports cand.facade.Lockout at module level, through a re-export to cand.service.Lockout"
    found_at = _defs("tests/conftest.py", "import Lockout")[0]
    assert _has(found, found_at + "imports cand.service.Lockout at module level")
    assert _has(through, _defs(test, "import Lockout")[0] + relay), "through a package that re-exports it"
    for path, qual, words in (
        ("tests/conftest.py", "test_in_conftest", "test_in_conftest uses Lockout"),
        (test, "test_module_level", "test_module_level uses Lockout"),
        (test, "test_nested", "test_nested uses Lockout"),
        (test, "test_method", "TestKept.test_method uses Lockout.register"),
    ):
        assert _has(candidates, _defs(path, f"def {qual}")[0] + words), qual
    assert len(candidates) == 4
    rebound = "its name or a class holding it bound more than once, unchecked"
    for place in _defs(test, "def test_twice"):
        assert _has(unchecked, place + f"test_twice uses Lockout, {rebound}"), place
    for qual in ("test_first", "test_again"):
        assert _has(unchecked, _defs(test, f"def {qual}")[0] + f"TestLock.{qual} uses Lockout, {rebound}"), qual
    for name in ("test_by_name", "test_through_helper", "test_fixture", "helper_method", "test_not_a_candidate"):
        assert name not in done.stdout, name
    for words in (
        "a place to look and not proof",
        "a fixture, a helper, conftest.py or a string is not named",
        "unittest.TestCase",
    ):
        assert words in done.stdout, words


def test_a_test_candidate_reaching_a_name_by_name_alone_is_unchecked(tmp_path: Path) -> None:
    _clone(tmp_path, "app", CANDIDATES)
    done = _run(tmp_path, "test-importers", "cand.service.Lockout.register", "--repo", "app")
    found, through, unchecked, candidates = _groups(done.stdout, "test-importers")
    test = "tests/test_lockout.py"
    assert found == [] and through == []
    assert _has(candidates, _defs(test, "def test_method")[0] + "TestKept.test_method uses Lockout.register")
    words = "test_by_name uses service.register, by name alone, unchecked"
    assert _has(unchecked, _defs(test, "def test_by_name")[0] + words)


def test_the_wrapper_usage_the_readme_and_the_help_name_every_command_and_new_group(tmp_path: Path) -> None:
    commands = _module().COMMANDS
    wrapper  = WRAPPER.read_text(encoding = "utf-8")
    usage    = wrapper.splitlines()[3]
    readme   = (TOOLS / "README.md").read_text(encoding = "utf-8")
    helped   = _run(tmp_path, "--help").stdout
    for command in commands:
        assert f" {command} " in usage, command
        assert f"bash kdf-repo-map.sh {command} " in readme, command
    for title in ("Attributes written", "Test candidates that use it"):
        assert title in wrapper and title in readme and title in helped, title


def test_help_prints_the_workers_brief_word_for_word(tmp_path: Path) -> None:
    done = _run(tmp_path, "--help")
    assert done.returncode == 0 and WORKER_BRIEF in done.stdout

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
