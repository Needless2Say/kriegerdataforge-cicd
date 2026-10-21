"""
The repo map, a read only lookup over named Python clones, each parsed with ast out of git's objects at one commit.

Run it through kdf-repo-map.sh beside it, which refuses a reviewer and finds cicd's venv interpreter. A session names
its clones one by one, each a folder under the workspace, and asks where a name is defined (defs), who imports a module
or a name in it (imports), the resolved static callers of a name and its other uses (callers), what a function's own
body calls and uses (callees), or the test files that import a module (test-importers). Each clone is read at one
commit, origin/main as it was last fetched unless --at names
another, through git ls-tree and git cat-file alone, so the working tree and every untracked or ignored file stay
unread, and nothing is written anywhere. Every git call drops the inherited GIT_ variables and sets
GIT_NO_LAZY_FETCH=1, so a partial clone's missing object leaves the answer incomplete and is never fetched. A clone
whose git dir, common dir or any registered worktree holds kdf-review/open, the folder the review launcher makes while
a review is open, is refused before any of its files is read.

A name is resolved by Python's own scopes, and only where they can be followed for certain. A use the rules cannot
place is kept among the unchecked matches with its label and never resolved on a guess, so an answer is a floor and an
empty group proves no absence. Each clone resolves its own modules, never through a table merged across clones.
"""

from __future__ import annotations

# standard imports
import argparse
import ast
import builtins
import fnmatch
import importlib.machinery
import os
import re
import subprocess
import sys
import time
import warnings
from dataclasses import dataclass, field
from pathlib import Path

# module constants
# the names of secret files, matched in any case, exactly the lists of kdf-ask-codex.sh and kdf-preflight.sh beside
# this file, which a test holds them to, and anything under a keys folder is closed whatever its name
SECRET_GLOBS     = (
    ".env*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "*.tfvars",
    "*.tfstate*",
    "id_rsa*",
    "id_dsa*",
    "id_ecdsa*",
    "id_ed25519*",
    ".git-credentials",
    ".netrc",
)
COMMANDS         = ("defs", "imports", "callers", "callees", "test-importers")
GENERATED_FOLDER = "vercel_api"
CAP              = 40
DEFAULT_REF      = "origin/main"
TRACKING_REF     = "refs/remotes/origin/main"
REPO_NAME        = re.compile(r"[A-Za-z0-9._-]+")
DOTTED_NAME      = re.compile(r"[A-Za-z_]\w*(\.[A-Za-z_]\w*)*")
SRC_PACKAGE      = re.compile(r"src/[^/]+/__init__\.py")
# what a place holds once it is resolved, a definition, a module, a value bound at module level, or a name outside
# the clone. A name a module of the clone does not bind is missing, and kept unchecked
RESOLVED = ("def", "module", "value", "external")
# the modules no file of a clone can replace, built into the interpreter or frozen in it, found before any path entry
UNSHADOWED = frozenset(sys.builtin_module_names) | frozenset(
    name for name in sys.stdlib_module_names if importlib.machinery.FrozenImporter.find_spec(name) is not None
)
FOUND      = 0
NOTHING    = 1
REFUSED    = 2
UNREAD     = 3
TITLES     = {
    "defs": ("Definitions", "Bound by an import", "Unchecked matches"),
    "imports": ("Imports", "Imports through a re-export", "Unchecked matches"),
    "callers": ("Resolved calls", "Uses that are not calls", "Unchecked matches"),
    "callees": ("Resolved calls", "Uses that are not calls", "Unchecked matches", "Attributes written"),
    "test-importers": ("Test imports", "Test imports through a re-export", "Unchecked matches"),
}
REBOUND    = "its name or a class holding it bound more than once"
ANNOTATION = "in an annotation, never run with the code around it"
SHAKY      = "bound more than once, or in a form the map does not take as certain, unchecked"
MANGLED    = "a private name, which Python mangles inside a class, unchecked"
STAR       = "a star import in its scope may replace it"
# the statements whose bodies run only on a condition, in a loop or under a handler, so a binding in them is not direct
COMPOUND = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.With, ast.AsyncWith, ast.Try, ast.TryStar, ast.Match)
NOT_SEEN = ("Not seen, uncommitted edits, importlib and getattr, a name held in a string such as a mock.patch target, "
            "a star import, and a method on an instance whose class the ast cannot know, which lands by name.")
HELP     = """\
commands
  defs <name>              where a name is defined, a bare name or a dotted one
  imports <dotted>         the imports of a module, of a name in it, and of every module under it
  callers <dotted>         the resolved calls of a function, class or method, its uses that are not calls, and the
                           unchecked matches, calls kept by name, through a base, a module or a package
  callees <dotted>         what a function or method the clone defines calls and uses in its own body, its lambdas
                           and comprehensions among it and a def nested in it apart, resolved as callers resolves,
                           what the function does read in its body at the commit
  test-importers <dotted>  the test files that import a module, never the tests that reach it

Each clone is a folder under the root, the workspace the cicd checkout this file sits in belongs to. --root names
another and is for tests. A test file is test_*.py, *_test.py or conftest.py, or any file under a folder named tests or
ending in _tests. Tests are left out of imports and callers unless --tests keeps them, and vercel_api/ and every --skip
folder are left out always. Each group prints every clone's count and at most 40 lines spread across the clones, by
clone in the order --repo names them, then path, then line, and --full prints every line.

What it cannot see. Uncommitted edits, importlib and getattr, a name held in a string such as a mock.patch target, a
star import, and a method on an instance whose class the ast cannot know, which lands by name. A use through a package
the clone does not hold is listed unchecked. Read each line it names at its commit, git -C <clone> show <hash>:<path>,
and search text for what it cannot see.

Exit codes. 0 an answer, 1 nothing found, 2 a usage refused, a reviewer's call or a clone under review among them, 3 a
clone or commit that cannot be read or an answer left incomplete.
"""


class Refusal(Exception):
    """
    A query refused before it answers, with the exit code it ends on.
    """
    def __init__(self, code: int, message: str) -> None:
        """
        Keep the exit code beside the message.

        Args:
            code: 2 for a usage refused, 3 for a clone or commit that cannot be read
            message: what was refused and why
        """
        super().__init__(message)
        self.code = code


@dataclass(frozen = True)
class Binding:
    """
    One statement binding a name in a scope, where it stands, what kind of binding it is and what it binds, and the
    statement, form and directness the binding rule for a value reads.
    """
    position: tuple[int, int]
    kind:     str
    origin:   str
    start: tuple[int, int] = (0, 0)
    loads: str = ""
    # the statement that binds it, so V = V = 1 counts once, its form, assign, import, def, del, mangled or other, and
    # whether the scope that runs it is the scope it lands in and it stands directly in that scope's body
    statement: tuple[int, int] = (0, 0)
    form:      str = "other"
    direct:    bool = False


@dataclass(eq = False)
class Scope:
    """
    One of Python's scopes in a module, a module, function, lambda, comprehension or class body.
    """
    kind:           str
    parent:         Scope | None
    qual:           str
    bindings:       dict[str, list[Binding]] = field(default_factory = dict)
    global_names:   set[str] = field(default_factory = set)
    nonlocal_names: set[str] = field(default_factory = set)
    star:           bool = False
    stars:          list[tuple[tuple[int, int], bool]] = field(default_factory = list)
    method_of:      Scope | None = None
    first:          str = ""
    # the class body a def is written in and its first positional parameter, whatever its decorators say
    holder:   Scope | None = None
    lead:     str = ""
    bases:    list[ast.expr] = field(default_factory = list)
    deferred: str = ""


@dataclass(frozen = True)
class Place:
    """
    Where a name or an attribute leads, its origin, what lies there, and why it is unchecked when it is.
    """
    origin:      str
    nature:      str
    established: bool = False
    label:       str = ""
    loaded:      tuple[str, ...] = ()
    # what an unchecked place would hold, the doubt a module's value takes from the import that reached the module, and
    # the names the path passed through, which a write elsewhere may rebind
    holds:   str = ""
    pending: str = ""
    via:     tuple[str, ...] = ()


@dataclass(eq = False)
class Module:
    """
    One tracked Python file of a clone, with its scopes, uses, imports, definitions and decorated definitions.
    """
    name:      str
    path:      str
    package:   bool
    test:      bool
    scope:     Scope
    uses:      list[tuple[Scope, ast.expr, bool, str]] = field(default_factory = list)
    writes:    list[tuple[Scope, ast.Attribute, str, str]] = field(default_factory = list)
    imports:   list[tuple[int, str, str]] = field(default_factory = list)
    defs:      list[tuple[int, str, str]] = field(default_factory = list)
    decorated: list[tuple[int, str, str, str]] = field(default_factory = list)
    classes:   dict[str, Scope] = field(default_factory = dict)
    functions: dict[str, list[Scope]] = field(default_factory = dict)
    annotated: set[int] = field(default_factory = set)


@dataclass(eq = False)
class Clone:
    """
    A named clone, the commit it is read at, its first line, and its modules once read.
    """
    name:    str
    path:    Path
    commit:  str
    heading: str
    files:   list[Module] = field(default_factory = list)
    modules: dict[str, Module] = field(default_factory = dict)
    classes: dict[str, tuple[Module, Scope]] = field(default_factory = dict)
    unread:  list[str] = field(default_factory = list)
    notes:   list[str] = field(default_factory = list)


def dotted_text(node: ast.expr) -> str:
    """
    Name an expression by its dotted names alone, never its source text.

    Args:
        node: a name, an attribute, a call or another expression

    Returns:
        str: the dotted name, with () after a call and [] after a subscript
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{dotted_text(node.value)}.{node.attr}"
    if isinstance(node, ast.Call):
        return f"{dotted_text(node.func)}()"
    if isinstance(node, ast.Subscript):
        return f"{dotted_text(node.value)}[]"
    return "(an expression)"


def private(name: str) -> bool:
    """
    Say whether a name is one Python mangles inside a class, two leading underscores and no trailing pair.

    Args:
        name: the name

    Returns:
        bool: True for __name, never for __name__
    """
    return name.startswith("__") and not name.endswith("__")


def inside_class(scope: Scope | None) -> bool:
    """
    Say whether a scope stands lexically inside a class, its body or any scope nested in it, where Python mangles.

    Args:
        scope: the scope

    Returns:
        bool: True when the scope or any scope holding it is a class body
    """
    while scope is not None:
        if scope.kind == "class":
            return True
        scope = scope.parent
    return False


def self_receiver(node: ast.expr) -> bool:
    """
    Say whether an attribute is read through self or cls.

    Args:
        node: the use

    Returns:
        bool: True for self.name or cls.name
    """
    return isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id in ("self", "cls")


class Collector(ast.NodeVisitor):
    """
    Walk one module once, building its scopes and recording each binding, use, import and definition in them.
    """
    def __init__(self, module: Module) -> None:
        """
        Start the walk at the module's own scope.

        Args:
            module: the module whose tree is walked
        """
        self.module            = module
        self.scope             = module.scope
        self.nonlocal_bindings = []
        self.statement         = None
        self.nested            = 0


    def visit(self, node: ast.AST) -> None:
        """
        Visit a node, keeping the statement the walk stands in and how many compound statements hold it in its scope.

        Args:
            node: the node
        """
        if not isinstance(node, ast.stmt):
            super().visit(node)
            return
        saved, self.statement = self.statement, node
        compound = isinstance(node, COMPOUND)
        self.nested           += compound
        try:
            super().visit(node)
        finally:
            self.statement = saved
            self.nested    -= compound


    def where(self) -> str:
        """
        Name the function or class the walk stands in, as an answer line says it.

        Returns:
            str: in the function or class, or at module level
        """
        scope = self.scope
        while scope.kind in ("lambda", "comprehension") and scope.parent is not None:
            scope = scope.parent
        if scope.kind == "function":
            return f"in {scope.qual}"
        if scope.kind == "class":
            return f"in class {scope.qual}"
        return "at module level"


    def bind(self, name: str, node: ast.AST, kind: str, origin: str = "", loads: str = "", form: str = "other") -> None:
        """
        Record a binding where Python makes it, a global or nonlocal declaration honoured.

        Args:
            name: the name bound
            node: the node whose position the binding takes
            kind: module or from for an import, def for a def or class, local for anything else
            origin: the dotted origin an import or a definition binds
            loads: the dotted module an import statement loads, which import a.b binds as a
            form: assign, import, def, del or other, what the binding rule for a value reads
        """
        scope    = self.scope
        deferred = name in scope.nonlocal_names and scope.parent is not None
        if not deferred and name in scope.global_names:
            while scope.parent is not None:
                scope = scope.parent
        # a private name a class's code binds in another scope lands under its mangled name, which the map never forms
        if private(name) and (deferred or scope is not self.scope) and inside_class(self.scope):
            form = "mangled"
        start     = (getattr(node, "lineno", 0), getattr(node, "col_offset", 0))
        statement = (self.statement.lineno, self.statement.col_offset) if self.statement is not None else start
        direct    = scope is self.scope and not deferred and not self.nested
        # a def or class binds its name once the statement ends, after its decorators, defaults, bases and body run
        end     = (getattr(node, "end_lineno", 0) or 0, getattr(node, "end_col_offset", 0) or 0)
        binding = Binding(end if kind == "def" else start, kind, origin, start, loads, statement, form, direct)
        if deferred:
            # placed once the walk ends, since the enclosing function may bind the name later in its body than this
            self.nonlocal_bindings.append((self.scope, name, binding))
            return
        scope.bindings.setdefault(name, []).append(binding)


    def visit_Module(self, node: ast.Module) -> None:
        """
        Walk the module, then place each nonlocal binding in the nearest enclosing function that binds its name.

        Args:
            node: the module
        """
        self.generic_visit(node)
        for declared, name, binding in self.nonlocal_bindings:
            scope = declared.parent
            while scope.parent is not None and (scope.kind not in ("function", "lambda") or name not in scope.bindings):
                scope = scope.parent
            scope.bindings.setdefault(name, []).append(binding)


    def walk_all(self, nodes: list[ast.AST | None]) -> None:
        """
        Visit each node given, in the scope the walk stands in.

        Args:
            nodes: the nodes, a None among them skipped
        """
        for node in nodes:
            if node is not None:
                self.visit(node)


    def walk_annotations(self, nodes: list[ast.AST | None]) -> None:
        """
        Visit annotations in the scope the walk stands in, marking every node in them, since Python 3.14 runs none.

        Args:
            nodes: the annotations, a None among them skipped
        """
        for node in nodes:
            if node is not None:
                self.module.annotated.update(id(inner) for inner in ast.walk(node))
        self.walk_all(nodes)


    def walk_in(self, scope: Scope, names: list[ast.AST], body: list[ast.AST]) -> None:
        """
        Bind the parameters of a new scope and visit its body inside it.

        Args:
            scope: the new scope
            names: its parameters and type parameters, each binding a local name
            body: the statements or the expression evaluated inside it
        """
        saved, self.scope = self.scope, scope
        nested, self.nested = self.nested, 0
        try:
            for name in names:
                self.bind(getattr(name, "arg", None) or name.name, name, "local")
            self.walk_all(body)
        finally:
            self.scope  = saved
            self.nested = nested


    def define(self, node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef, kind: str) -> str:
        """
        Bind a def or class in the scope it stands in and record it, with its decorators when it has any.

        Args:
            node: the definition
            kind: def or class

        Returns:
            str: its dotted name inside the module
        """
        qual = f"{self.scope.qual}.{node.name}" if self.scope.qual else node.name
        self.bind(node.name, node, "def", f"{self.module.name}.{qual}", form = "def")
        self.module.defs.append((node.lineno, qual, kind))
        if node.decorator_list:
            names = ", ".join(dotted_text(decorator) for decorator in node.decorator_list)
            self.module.decorated.append((node.lineno, qual, self.where(), names))
        return qual


    def visit_Name(self, node: ast.Name) -> None:
        """
        Record a load as a use, and any other context as a binding.

        Args:
            node: the name
        """
        if isinstance(node.ctx, ast.Load):
            self.module.uses.append((self.scope, node, False, self.where()))
            return
        if isinstance(node.ctx, ast.Del):
            form = "del"
        elif isinstance(self.statement, (ast.Assign, ast.AnnAssign)) and self.scope.kind != "comprehension":
            form = "assign"
        else:
            form = "other"
        self.bind(node.id, node, "local", form = form)


    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        """
        Bind an annotated name only where Python does, a module or class body binding it only when a value is given.

        Args:
            node: the annotated assignment
        """
        if node.value is None and isinstance(node.target, ast.Attribute):
            # an annotated attribute with no value writes nothing, though Python still runs its receiver
            self.visit(node.target.value)
        elif node.value is not None or self.scope.kind not in (
            "module",
            "class",
        ) or not isinstance(node.target, ast.Name):
            self.visit(node.target)
        self.walk_annotations([node.annotation])
        self.walk_all([node.value])


    def visit_Attribute(self, node: ast.Attribute) -> None:
        """
        Record an attribute load as a use and an assigned or deleted one as a write, then walk its receiver.

        Args:
            node: the attribute
        """
        if isinstance(node.ctx, ast.Load):
            self.module.uses.append((self.scope, node, False, self.where()))
        else:
            verb = "deleted" if isinstance(node.ctx, ast.Del) else "written"
            self.module.writes.append((self.scope, node, verb, self.where()))
        self.visit(node.value)


    def visit_Call(self, node: ast.Call) -> None:
        """
        Record every call as a call, never also as a use, a call through a subscript or a call's result among them.

        Args:
            node: the call
        """
        self.module.uses.append((self.scope, node.func, True, self.where()))
        if isinstance(node.func, ast.Attribute):
            self.visit(node.func.value)
        elif not isinstance(node.func, ast.Name):
            self.visit(node.func)
        self.walk_all([*node.args, *(keyword.value for keyword in node.keywords)])


    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        """
        Bind a walrus target in the nearest scope that is no comprehension, as Python does.

        Args:
            node: the assignment expression
        """
        self.visit(node.value)
        saved = self.scope
        while self.scope.kind == "comprehension" and self.scope.parent is not None:
            self.scope = self.scope.parent
        self.bind(node.target.id, node.target, "local")
        self.scope = saved


    def visit_Global(self, node: ast.Global) -> None:
        """
        Note the names a scope declares global.

        Args:
            node: the declaration
        """
        self.scope.global_names.update(node.names)


    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        """
        Note the names a scope declares nonlocal.

        Args:
            node: the declaration
        """
        self.scope.nonlocal_names.update(node.names)


    def visit_Import(self, node: ast.Import) -> None:
        """
        Bind each module imported, import a.b binding a and import a.b as c binding c to a.b.

        Args:
            node: the import
        """
        for alias in node.names:
            if alias.asname:
                self.bind(alias.asname, node, "module", alias.name, alias.name, "import")
            else:
                top = alias.name.partition(".")[0]
                self.bind(top, node, "module", top, alias.name, "import")
            self.module.imports.append((node.lineno, alias.name, self.where()))


    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        """
        Bind each name imported from a module, a relative module resolved against this module's package.

        Args:
            node: the import
        """
        base = self.absolute(node.module or "", node.level)
        for alias in node.names:
            if alias.name == "*":
                self.scope.star = True
                self.scope.stars.append(((node.lineno, node.col_offset), not self.nested))
                origin = f"{base}.*" if base else ""
            else:
                origin = f"{base}.{alias.name}".lstrip(".") if base is not None else ""
                # a relative import climbing out of the clone binds a name the map cannot follow, never a value here
                kind = "from" if origin else "local"
                self.bind(alias.asname or alias.name, node, kind, origin, form = "import" if origin else "other")
            if origin:
                self.module.imports.append((node.lineno, origin, self.where()))


    def absolute(self, module: str, level: int) -> str | None:
        """
        Resolve a relative import's module against the package this module sits in.

        Args:
            module: the module as written, empty for from . import x
            level: how many dots led it

        Returns:
            str | None: the absolute dotted module, or None when the dots climb out of the clone
        """
        if not level:
            return module
        parts = self.module.name.split(".")
        if not self.module.package:
            parts = parts[:-1]
        if level - 1 > len(parts):
            return None
        parts = parts[:len(parts) - level + 1]
        return ".".join([*parts, module] if module else parts)


    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        """
        Walk a def's decorators, defaults and annotations in the enclosing scope, then its body in its own.

        Args:
            node: the def
        """
        arguments  = node.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        parameters.extend(arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None)
        self.walk_all([*node.decorator_list, *arguments.defaults, *arguments.kw_defaults])
        self.walk_annotations([*(parameter.annotation for parameter in parameters), node.returns])
        scope      = Scope("function", self.scope, self.define(node, "def"))
        positional = [*arguments.posonlyargs, *arguments.args]
        if self.scope.kind == "class":
            scope.holder = self.scope
            scope.lead   = positional[0].arg if positional else ""
        if self.scope.kind == "class" and "staticmethod" not in map(dotted_text, node.decorator_list):
            scope.method_of = self.scope
            scope.first     = positional[0].arg if positional else ""
        self.module.functions.setdefault(f"{self.module.name}.{scope.qual}", []).append(scope)
        self.walk_in(scope, [*parameters, *getattr(node, "type_params", [])], node.body)


    visit_AsyncFunctionDef = visit_FunctionDef


    def visit_Lambda(self, node: ast.Lambda) -> None:
        """
        Walk a lambda's defaults in the enclosing scope, then its body in its own.

        Args:
            node: the lambda
        """
        arguments  = node.args
        parameters = [*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs]
        parameters.extend(arg for arg in (arguments.vararg, arguments.kwarg) if arg is not None)
        self.walk_all([*arguments.defaults, *arguments.kw_defaults])
        scope = Scope("lambda", self.scope, self.scope.qual, deferred = "inside a lambda, runs when it is called")
        self.walk_in(scope, parameters, [node.body])


    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        """
        Walk a class's decorators and bases in the enclosing scope, then its body in a scope its methods skip.

        Args:
            node: the class
        """
        self.walk_all([*node.decorator_list, *node.bases, *(keyword.value for keyword in node.keywords)])
        qual  = self.define(node, "class")
        scope = Scope("class", self.scope, qual, bases = list(node.bases))
        self.module.classes[f"{self.module.name}.{qual}"] = scope
        self.walk_in(scope, list(getattr(node, "type_params", [])), node.body)


    def visit_ListComp(self, node: ast.ListComp | ast.SetComp | ast.GeneratorExp | ast.DictComp) -> None:
        """
        Walk a comprehension's first iterable in the enclosing scope, and the rest in its own scope.

        Args:
            node: the comprehension
        """
        results = [node.key, node.value] if isinstance(node, ast.DictComp) else [node.elt]
        self.visit(node.generators[0].iter)
        # a generator expression's body runs as it is consumed, which may be after the function returns
        lazy = "inside a generator expression, runs as it is consumed" if isinstance(node, ast.GeneratorExp) else ""
        saved      = self.scope
        self.scope = Scope("comprehension", saved, saved.qual, deferred = lazy)
        try:
            for index, generator in enumerate(node.generators):
                self.visit(generator.target)
                if index:
                    self.visit(generator.iter)
                self.walk_all(generator.ifs)
            self.walk_all(results)
        finally:
            self.scope = saved


    visit_SetComp      = visit_ListComp
    visit_GeneratorExp = visit_ListComp
    visit_DictComp     = visit_ListComp


    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        """
        Bind an except clause's name, then walk the clause.

        Args:
            node: the handler
        """
        if node.name:
            self.bind(node.name, node, "local")
        self.generic_visit(node)


    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar | ast.MatchMapping) -> None:
        """
        Bind a match pattern's capture, then walk the pattern.

        Args:
            node: the pattern
        """
        name = getattr(node, "name", None) or getattr(node, "rest", None)
        if name:
            self.bind(name, node, "local")
        self.generic_visit(node)


    visit_MatchStar    = visit_MatchAs
    visit_MatchMapping = visit_MatchAs


class Resolver:
    """
    Resolve uses, imports and definitions inside one clone for one asked name.
    """
    def __init__(self, clone: Clone, query: str) -> None:
        """
        Take the asked name as the clone's own re-exports lead to it.

        Args:
            clone: the clone, its modules read
            query: the name asked, dotted or bare
        """
        self.clone  = clone
        self.query  = query
        self.marked = None
        self.target = self.canonical(query) if "." in query else query
        self.parent, _, self.name = self.target.rpartition(".")


    def follow(self, origin: str) -> tuple[str, str | None, str, tuple[str, ...]]:
        """
        Follow a module level name through the clone's explicit imports to where it is defined.

        Args:
            origin: a dotted name, a module or a name in one

        Returns:
            tuple[str, str | None, str, tuple[str, ...]]: the origin reached and what lies there, one of RESOLVED or
                missing, or None when a star import, a __getattr__, a competing binding or a cycle stops the walk, then
                the label that leaves it unchecked, empty when it is certain, and the names the walk passed through
        """
        seen = []
        # a star or a mangled name unsettles any path, and the binding rule only a path that ends at a value
        hard = soft = ""
        while origin not in seen:
            seen.append(origin)
            if origin.partition(".")[0] in UNSHADOWED:
                return origin, "external", hard, tuple(seen)
            parent, _, name = origin.rpartition(".")
            module = self.clone.modules.get(parent)
            if module is None:
                return origin, ("module" if origin in self.clone.modules else "external"), hard, tuple(seen)
            bindings = module.scope.bindings.get(name)
            if not bindings:
                if module.scope.star or "__getattr__" in module.scope.bindings:
                    return origin, None, "", tuple(seen)
                return origin, ("module" if origin in self.clone.modules else "missing"), hard, tuple(seen)
            # a del competes with nothing, it leaves the one binding beside it unchecked
            kinds = {(binding.kind, binding.origin) for binding in bindings if binding.form != "del"}
            if len(kinds) != 1:
                return origin, None, "", tuple(seen)
            hard = hard or self.doubt(module.scope, bindings, False)
            soft = soft or self.doubt(module.scope, bindings, True)
            if not soft and private(name) and origin in self.marks()[1]:
                soft = MANGLED
            kind, bound = kinds.pop()
            if kind == "def":
                return origin, "def", hard, tuple(seen)
            if kind == "local":
                return origin, "value", soft, tuple(seen)
            origin = bound
        return origin, None, "", tuple(seen)


    def doubt(self, scope: Scope, bindings: list[Binding], value: bool) -> str:
        """
        Say why the bindings a scope holds for a name leave it unchecked, or that they do not.

        Args:
            scope: the scope they land in
            bindings: every binding of the name there
            value: whether the name holds a value, so the binding rule applies

        Returns:
            str: the label, mangled, a star that may replace it, or bound in a form the map does not take as certain,
                empty when certain
        """
        if any(binding.form == "mangled" for binding in bindings):
            return MANGLED
        if self.displaced(scope, bindings):
            return f"{STAR}, unchecked"
        # one statement, an assignment or an import made directly in the body of the scope that runs it
        lone = len({binding.statement for binding in bindings}) == 1
        sure = lone and bindings[0].form in ("assign", "import") and bindings[0].direct
        if (value and not sure) or any(binding.form == "del" for binding in bindings):
            return SHAKY
        return ""


    def displaced(self, scope: Scope, bindings: list[Binding]) -> bool:
        """
        Say whether a star import in the scope may replace a binding, run after it or the order unknown.

        Args:
            scope: the scope the bindings land in
            bindings: the bindings of one name there

        Returns:
            bool: True unless every star and every binding stand directly in the scope's body, each star before them
        """
        return any(
            not (direct and binding.direct and position < binding.start)
            for position, direct in scope.stars
            for binding in bindings
        )


    def marks(self) -> tuple[dict[str, str], set[str]]:
        """
        Read every attribute the clone's code writes through a class it defines or a module whose identity is known.

        Returns:
            tuple[dict[str, str], set[str]]: each member or value written elsewhere with the label naming where, and
                each private name written inside a class, which Python writes under its mangled name
        """
        if self.marked is not None:
            return self.marked
        # empty while the writes are read, so a path followed for one of them never asks for the marks again
        self.marked = ({}, set())
        written, mangled = {}, set()
        for module in self.clone.files:
            for scope, node, verb, _ in module.writes:
                place = self.resolve(module, scope, node.value)
                known = place.nature == "def" and place.origin in self.clone.classes
                if not known and not (place.nature == "module" and place.established):
                    continue
                origin = f"{place.origin}.{node.attr}"
                if private(node.attr) and inside_class(scope):
                    mangled.add(origin)
                else:
                    written.setdefault(origin, f"{verb} elsewhere at {module.path}:{node.lineno}, unchecked")
        self.marked = (written, mangled)
        return self.marked


    def canonical(self, dotted: str) -> str:
        """
        Lead a dotted name to its definition in the clone, a class's member through its class.

        Args:
            dotted: the name

        Returns:
            str: the name its definition carries, or the name as given when the clone cannot lead it further
        """
        origin, nature, _, _ = self.follow(dotted)
        parent, _, name = dotted.rpartition(".")
        if nature == "external" and "." in parent:
            return f"{self.canonical(parent)}.{name}"
        return origin


    def established(self, dotted: str) -> bool:
        """
        Say whether a dotted module is surely the module, every package on the way read and never shadowing it.

        Args:
            dotted: the module

        Returns:
            bool: True when the clone holds it and each package's __init__.py binds no other object under the next
                name, holds no star import and defines no __getattr__
        """
        if dotted not in self.clone.modules:
            return False
        parts = dotted.split(".")
        for index in range(1, len(parts)):
            package = self.clone.modules.get(".".join(parts[:index]))
            if package is None or not package.package:
                return False
            scope     = package.scope
            submodule = ".".join(parts[:index + 1])
            bound     = scope.bindings.get(parts[index], [])
            if scope.star or "__getattr__" in scope.bindings or any(binding.origin != submodule for binding in bound):
                return False
        return True


    def settle(self, bindings: list[Binding], position: tuple[int, int] | None, scope: Scope, own: str = "") -> Place:
        """
        Turn the bindings a scope holds for a name into the place the name leads.

        Args:
            bindings: every binding of the name in that scope
            position: the use's position when that scope is a module or class body the use stands in, else None
            scope: that scope, whose star imports and binding rule a value reads
            own: the dotted name a value bound there carries, for a module or class body, else empty

        Returns:
            Place: the place, unresolved with a label when the name is bound twice to different things or used
                before its binding, and unchecked with its origin kept when a star, a mangled name or the binding
                rule leaves it so
        """
        if position is not None and all(binding.position > position for binding in bindings):
            return Place("", "unresolved", label = "used before its binding, unchecked")
        # a del competes with nothing, it leaves the one binding beside it unchecked, and a name only deleted is local
        kinds = {(binding.kind, binding.origin) for binding in bindings if binding.form != "del"} or {("local", "")}
        if len(kinds) > 1:
            return Place("", "unresolved", label = "bound more than once, unchecked")
        kind, origin = kinds.pop()
        if kind == "local":
            # a value the module or class body binds, which callees reads and every other command leaves a local
            if not own:
                return Place("", "local")
            return Place(own, "local", label = self.doubt(scope, bindings, True), holds = "value", via = (own,))
        if kind == "def":
            doubt = self.doubt(scope, bindings, False)
            return Place(origin, "candidate", label = doubt, holds = "def") if doubt else Place(origin, "def")
        canon, nature, label, via = self.follow(origin)
        if nature is None:
            return Place("", "unresolved", label = f"through {origin}, unchecked")
        if nature == "missing":
            return Place(canon, "candidate", label = f"not bound in {canon.rpartition('.')[0]}, unchecked")
        via   = (own, *via) if own else via
        doubt = self.doubt(scope, bindings, nature == "value") or label
        if doubt:
            return Place(canon, "candidate", label = doubt, holds = nature, via = via)
        top_level   = kind == "module" and "." not in origin
        established = top_level or (nature == "module" and self.established(canon))
        # in a module or class body an import loads its module only for the statements after it
        loaded = tuple(
            binding.loads for binding in bindings if binding.loads and (position is None or binding.position < position)
        )
        # a value read through this module is certain only when every import of it stands directly in the scope's
        # body, however many statements bind the same package
        sure    = all(binding.direct and binding.form == "import" for binding in bindings)
        pending = SHAKY if nature == "module" and not sure else ""
        return Place(canon, nature, established = established, loaded = loaded, pending = pending, via = via)


    def lookup(self, module: Module, scope: Scope, name: str, position: tuple[int, int]) -> Place:
        """
        Look a bare name up through Python's scopes, nearest first, a class body skipped by the scopes inside it.

        Args:
            module: the module the use stands in
            scope: the scope the use stands in
            name: the name
            position: the use's position

        Returns:
            Place: where the name leads
        """
        own      = scope
        deferred = False
        while scope is not None:
            # a use inside a function runs when it is called, after the statements around it, never during them
            leaving = deferred or scope.kind in ("function", "lambda")
            # a class body skipped by the scopes inside it is skipped whole, its global and nonlocal names too
            if scope.kind == "class" and scope is not own:
                scope, deferred = scope.parent, leaving
                continue
            if scope.kind != "module" and name in scope.global_names:
                scope, deferred = module.scope, leaving
                continue
            if scope.kind != "module" and name in scope.nonlocal_names:
                scope, deferred = scope.parent, leaving
                continue
            bindings = scope.bindings.get(name)
            if bindings:
                # a use inside the def or class statement that binds the name runs before that binding, unless deferred
                if not deferred and any(
                    item.kind == "def" and item.start <= position <= item.position for item in bindings
                ):
                    return Place("", "unresolved", label = "used before its binding, unchecked")
                ordered = scope is own and scope.kind in ("module", "class")
                value   = f"{module.name}.{name}" if scope.kind == "module" else ""
                return self.settle(bindings, position if ordered else None, scope, value)
            if scope.star:
                return Place("", "unresolved", label = "a star import, unchecked")
            scope, deferred = scope.parent, leaving
        return Place("", "unresolved")


    def method_scope(self, scope: Scope, name: str) -> Scope | None:
        """
        Find the method whose first parameter a self or cls in this scope is.

        Args:
            scope: the scope the use stands in
            name: self or cls

        Returns:
            Scope | None: the method, or None when the name is bound otherwise
        """
        own = scope
        while scope is not None and scope.kind != "module":
            # a class body the use stands in sees its own binding of the name first
            if scope.kind == "class" and scope is own and name in scope.bindings:
                return None
            if scope.kind != "class" and (name in scope.global_names or name in scope.nonlocal_names):
                return None
            if scope.kind != "class" and name in scope.bindings:
                if scope.method_of is not None and scope.first == name and len(scope.bindings[name]) == 1:
                    return scope
                return None
            scope = scope.parent
        return None


    def member_of_class(self, owner: Module, klass: Scope, origin: str, attr: str) -> Place:
        """
        Resolve an attribute of a class the clone defines, kept unchecked through its bases when it does not bind it.

        Args:
            owner: the module that defines the class
            klass: the class's scope
            origin: the class's dotted name
            attr: the attribute

        Returns:
            Place: the member, unchecked with its origin when it is a private name or the binding rule leaves it so,
                or unresolved with the bases named
        """
        bindings = klass.bindings.get(attr)
        member   = f"{origin}.{attr}"
        if bindings:
            # settled as a module's names are, so an import in the class body leads to its origin
            place = self.settle(bindings, None, klass, member)
            if place.nature == "local" and place.label:
                place = Place(member, "candidate", label = place.label, holds = "value", via = (member,))
            elif place.nature == "local":
                place = Place(member, "value", via = (member,))
            elif place.label == "bound more than once, unchecked":
                return Place("", "unresolved", label = "bound more than once in its class, unchecked")
            if private(attr):
                holds = place.holds or (place.nature if place.nature in RESOLVED else "")
                return Place(member, "candidate", label = MANGLED, holds = holds, via = (member,))
            return place
        # a private name read through a class is read as its mangled name, which the class body never binds as written
        if private(attr):
            return Place(member, "candidate", label = MANGLED, via = (member,))
        names = []
        for base in klass.bases:
            place = self.resolve(owner, klass.parent, base)
            names.append(place.origin if place.nature in RESOLVED else dotted_text(base))
        if not names:
            return Place("", "unresolved", label = "not defined in its class, unchecked")
        return Place("", "unresolved", label = f"through its base {' and '.join(names)}, unchecked")


    def resolve(self, module: Module, scope: Scope, node: ast.expr) -> Place:
        """
        Resolve a name or an attribute chain to the place it leads.

        Args:
            module: the module the use stands in
            scope: the scope the use stands in
            node: the name or attribute

        Returns:
            Place: where it leads
        """
        if isinstance(node, ast.Name):
            return self.mangled(scope, node.id, self.lookup(module, scope, node.id, (node.lineno, node.col_offset)))
        if not isinstance(node, ast.Attribute):
            return Place("", "unresolved")
        value = node.value
        if isinstance(value, ast.Name) and value.id in ("self", "cls"):
            method = self.method_scope(scope, value.id)
            if method is not None and method.method_of is not None:
                origin = f"{module.name}.{method.method_of.qual}"
                return self.member_of_class(module, method.method_of, origin, node.attr)
        place = self.attribute(self.resolve(module, scope, value), node.attr)
        if place.nature == "def" and self.inside_own_statement(module, scope, place.origin, node):
            return Place("", "unresolved", label = "used before its binding, unchecked")
        return self.mangled(scope, node.attr, place)


    def mangled(self, scope: Scope, name: str, place: Place) -> Place:
        """
        Leave a private name used lexically inside a class unchecked, since Python reads it there as _Class__name.

        Args:
            scope: the scope the use stands in
            name: the bare name or the attribute's name
            place: where the map would lead it

        Returns:
            Place: the place, or unchecked as mangled with its origin kept, a function's own local left as it is
        """
        if not private(name) or not inside_class(scope) or place.label == MANGLED:
            return place
        if place.nature == "local" and not place.origin:
            return place
        if not place.origin:
            return Place("", "unresolved", label = MANGLED)
        holds = place.holds or (place.nature if place.nature in RESOLVED else "")
        return Place(place.origin, "candidate", label = MANGLED, holds = holds, via = place.via)


    def inside_own_statement(self, module: Module, scope: Scope, origin: str, node: ast.expr) -> bool:
        """
        Say whether a use reaches a module's def or class through the module while that statement is still running.

        Args:
            module: the module the use stands in
            scope: the scope the use stands in
            origin: the def or class the use leads to
            node: the use

        Returns:
            bool: True when the def or class is this module's own, its statement holds the use, and no function or
                lambda between the use and the module defers it
        """
        parent, _, name = origin.rpartition(".")
        if parent != module.name:
            return False
        while scope.parent is not None:
            if scope.kind in ("function", "lambda"):
                return False
            scope = scope.parent
        position = (node.lineno, node.col_offset)
        bindings = module.scope.bindings.get(name, [])
        return any(item.kind == "def" and item.start <= position <= item.position for item in bindings)


    def attribute(self, place: Place, attr: str) -> Place:
        """
        Resolve an attribute of a place, only where the place is surely a module or a class the clone defines.

        Args:
            place: where the receiver leads
            attr: the attribute

        Returns:
            Place: where the attribute leads, a candidate with a label when the receiver cannot be established
        """
        joined = f"{place.origin}.{attr}"
        if place.nature == "candidate":
            return Place(joined, "candidate", label = place.label)
        if place.nature == "def":
            found = self.clone.classes.get(place.origin)
            if found is not None:
                return self.member_of_class(found[0], found[1], place.origin, attr)
            return Place(joined, "candidate", label = f"through {place.origin}, unchecked")
        if place.nature == "module" and place.established:
            canon, nature, label, via = self.follow(joined)
            if nature is None:
                return Place("", "unresolved", label = f"through {joined}, unchecked")
            if nature == "missing":
                return Place(joined, "candidate", label = f"not bound in {place.origin}, unchecked")
            # a submodule the package does not bind is an attribute only once an import has loaded it
            package = self.clone.modules.get(place.origin)
            unbound = package is not None and attr not in package.scope.bindings
            if nature == "module" and unbound and not any(
                load == joined or load.startswith(f"{joined}.") for load in place.loaded
            ):
                return Place(joined, "candidate", label = "a submodule no import of it here loads, unchecked")
            label = label or (place.pending if nature == "value" else "")
            if label:
                return Place(canon, "candidate", label = label, holds = nature, via = via)
            established = nature == "module" and self.established(canon)
            pending     = place.pending if nature == "module" else ""
            return Place(canon, nature, established = established, loaded = place.loaded, pending = pending, via = via)
        if place.nature == "external" and place.established:
            return Place(joined, "external")
        if place.nature in ("module", "external", "missing"):
            return Place(joined, "candidate", label = f"through a module unchecked, {place.origin}")
        if place.nature == "value":
            return Place(joined, "candidate", label = f"through {place.origin}, unchecked")
        # a value the module binds stays a local here, so a method on it is matched by name as before
        return Place("", "unresolved", label = "" if place.nature == "local" else place.label)


    def through_package(self, origin: str) -> bool:
        """
        Say whether an origin may be the asked name reached through a package over its module, which is unchecked.

        Args:
            origin: where a use or an import leads

        Returns:
            bool: True when it ends in the asked name under a parent or child package of the asked module that the
                clone does not hold
        """
        parent, _, last = origin.rpartition(".")
        if last != self.name or not parent or parent == self.parent or parent in self.clone.modules:
            return False
        return self.parent.startswith(f"{parent}.") or parent.startswith(f"{self.parent}.")


    def use_line(self, module: Module, use: tuple[Scope, ast.expr, bool, str]) -> tuple[int, str] | None:
        """
        Place one use of a name in a group for callers.

        Args:
            module: the module it stands in
            use: its scope, node, whether it is a call, and where it stands

        Returns:
            tuple[int, str] | None: the group and the line's words, or None when it is no use of the asked name
        """
        scope, node, is_call, where = use
        place = self.resolve(module, scope, node)
        text  = dotted_text(node)
        verb  = "called" if is_call else "used"
        # a call in an annotation is never run with the code around it, whatever it leads to
        noted = f", {ANNOTATION}" if is_call and id(node) in module.annotated else ""
        if place.nature in RESOLVED or place.nature == "candidate":
            if place.origin == self.target:
                if place.nature == "candidate":
                    return 2, f"{text} {verb} {where}, {place.label}{noted}"
                if noted:
                    return 2, f"{text} {verb} {where}{noted}"
                return (0 if is_call else 1), f"{text} {verb} {where}"
            if self.through_package(place.origin):
                return 2, f"{text} {verb} {where}, through a package, {place.origin}{noted}"
            return None
        final = node.id if isinstance(node, ast.Name) else getattr(node, "attr", "")
        if final != self.name or place.nature == "local":
            return None
        how = "called by name" if is_call else "a reference by name"
        return 2, f"{text} {how} {where}" + (f", {place.label}" if place.label else "") + noted


    def import_line(self, origin: str, where: str) -> tuple[int, str] | None:
        """
        Place one imported origin in a group for imports and test-importers.

        Args:
            origin: what the import names, a module, a name in one, or a module with .* for a star import
            where: where the import stands

        Returns:
            tuple[int, str] | None: the group and the line's words, or None when it imports nothing asked
        """
        star = origin.endswith(".*")
        base = origin[:-2] if star else origin
        text = f"imports {origin} {where}"
        if base == self.target or base.startswith(f"{self.target}."):
            return 0, text
        if star:
            return (2, f"{text}, a star import, unchecked") if base == self.parent else None
        canon = self.canonical(base)
        if canon != base and (canon == self.target or canon.startswith(f"{self.target}.")):
            label = self.follow(base)[2]
            if label:
                return 2, f"{text}, through a re-export to {canon}, {label}"
            return 1, f"{text}, through a re-export to {canon}"
        if self.through_package(base):
            return 2, f"{text}, through a package"
        return None


    def def_lines(self, module: Module) -> list[tuple[int, int, str]]:
        """
        Find where the asked name is defined in a module, or bound there by an import or an assignment.

        Args:
            module: the module

        Returns:
            list[tuple[int, int, str]]: each group, line and the line's words
        """
        dotted = "." in self.query
        found  = []
        for line, qual, kind in module.defs:
            full = f"{module.name}.{qual}"
            if (full in (self.query, self.target)) if dotted else qual.rpartition(".")[2] == self.query:
                reason = self.defined_doubt(module, qual)
                found.append((2 if reason else 0, line, f"{kind} {full}, {reason}" if reason else f"{kind} {full}"))
        scopes = [(module.name, module.scope), *module.classes.items()]
        for prefix, scope in scopes:
            for name, bindings in scope.bindings.items():
                full = f"{prefix}.{name}"
                for binding in bindings:
                    imported = binding.kind in ("module", "from")
                    named    = full in (self.query, self.target) if dotted else name == self.query
                    leads    = dotted and imported and self.canonical(binding.origin) == self.target
                    if imported and (named or leads):
                        words = f"{full} bound by an import of {binding.origin}"
                        if scope.kind == "class" and private(name):
                            reason = MANGLED
                        else:
                            _, nature, label, _ = self.follow(binding.origin)
                            reason = self.doubt(scope, bindings, nature == "value") or label
                        group = 2 if reason else 1
                        found.append((group, binding.position[0], f"{words}, {reason}" if reason else words))
                    elif binding.kind == "local" and named:
                        found.append((2, binding.position[0], f"{full} bound by assignment, unchecked"))
        return found


    def defined_doubt(self, module: Module, qual: str) -> str:
        """
        Say why a definition's own line is unchecked, a private name in a class body or a star that may replace it.

        Args:
            module: the module that defines it
            qual: its dotted name inside the module

        Returns:
            str: the label, empty when certain
        """
        parts = qual.split(".")
        for index in range(1, len(parts)):
            if f"{module.name}.{'.'.join(parts[:index])}" in module.classes and private(parts[index]):
                return MANGLED
        bindings = module.scope.bindings.get(parts[0], [])
        return f"{STAR}, unchecked" if bindings and self.displaced(module.scope, bindings) else ""


    def callee_lines(self, module: Module) -> list[tuple[int, int, str]]:
        """
        Find what the asked function calls, uses and writes in its own body, a def nested in it left to its own query.

        Args:
            module: the module

        Returns:
            list[tuple[int, int, str]]: each group, line and the line's words, nothing when the module does not define
                the asked function
        """
        bodies = module.functions.get(self.target, [])
        if not bodies or self.clone.modules.get(module.name) is not module or self.builtin():
            return []
        if len(bodies) > 1:
            several = f"one of {len(bodies)} bodies of this name, unchecked"
        else:
            reason  = self.rebound(bodies[0])
            several = f"{reason}, unchecked" if reason else ""
        # a receiver in a chain, svc in svc.core.target(), is part of its outermost name and never a use of its own
        chained = {id(node.value) for _, node, _, _ in module.uses if isinstance(node, ast.Attribute)}
        found   = []
        for scope, node, is_call, _ in module.uses:
            inside = self.inside_body(scope, bodies)
            if inside is None or (not is_call and id(node) in chained):
                continue
            if id(node) in module.annotated:
                inside = (", ".join(filter(None, [inside[0], ANNOTATION])), True)
            words = self.callee_words(module, scope, node, is_call, inside)
            if words is None:
                continue
            group, text = words
            if several:
                group, text = 2, f"{text}, {several}"
            found.append((group, node.lineno, text))
        # every attribute the body assigns or deletes, in a group of its own, labelled as the other groups are
        for scope, node, verb, _ in module.writes:
            inside = self.inside_body(scope, bodies)
            if inside is not None:
                text = self.write_words(module, scope, node, verb)
                found.append((3, node.lineno, ", ".join(filter(None, [text, inside[0], several]))))
        return found


    def write_words(self, module: Module, scope: Scope, node: ast.Attribute, verb: str) -> str:
        """
        Word one attribute a body writes or deletes, its receiver named only when the receiver itself is known.

        Args:
            module: the module the body stands in
            scope: the scope the write stands in
            node: the attribute written
            verb: written or deleted

        Returns:
            str: the words, a first parameter, a class, a module or a name outside the clone, else its type unknown
        """
        receiver = node.value
        head     = f"{dotted_text(node)} {verb}"
        mangled  = f", {MANGLED}" if private(node.attr) and inside_class(scope) else ""
        root     = receiver
        while isinstance(root, ast.Attribute):
            root = root.value
        holder = self.lead_of(scope, receiver.id) if isinstance(receiver, ast.Name) else None
        if holder is not None:
            where = f"the first parameter of a def in the body of class {module.name}.{holder.qual}"
            return f"{head}, on {receiver.id}, {where}{mangled}"
        # a chain through self, cls or a method's first parameter is never resolved, its type is the instance's
        through = isinstance(
            root,
            ast.Name,
        ) and (root.id in ("self", "cls") or self.lead_of(scope, root.id) is not None)
        place   = Place("", "unresolved") if through else self.resolve(module, scope, receiver)
        if place.nature == "def" and place.origin in self.clone.classes:
            return f"{head}, on class {place.origin}{mangled}"
        if place.nature == "module" and place.established:
            bound    = self.clone.modules[place.origin].scope.bindings.get(node.attr, [])
            imported = next((binding.origin for binding in bound if binding.kind in ("from", "module")), "")
            other    = f", which {place.origin} imports from {imported}" if imported else ""
            return f"{head}, on module {place.origin}{other}{mangled}"
        if place.nature == "external":
            return f"{head}, on {place.origin}, outside the clone, as imported{mangled}"
        return f"{head}, on {dotted_text(receiver)}, its type unknown to the ast{mangled}"


    def lead_of(self, scope: Scope, name: str) -> Scope | None:
        """
        Find the class whose body holds the def a bare name is the first parameter of, bound there once.

        Args:
            scope: the scope the name is read in
            name: the name

        Returns:
            Scope | None: the class body, or None when the nearest scope binding the name binds it otherwise
        """
        own = scope
        while scope is not None and scope.kind != "module":
            # a class body is skipped by the scopes inside it, as Python resolves a name
            if scope.kind == "class" and scope is not own:
                scope = scope.parent
                continue
            if name in scope.global_names or name in scope.nonlocal_names:
                return None
            if name in scope.bindings:
                lone = len(scope.bindings[name]) == 1
                if scope.kind == "function" and scope.holder is not None and scope.lead == name and lone:
                    return scope.holder
                return None
            scope = scope.parent
        return None


    def callee_note(self) -> str:
        """
        Say which body callees reads for the asked name, or why it reads none.

        Returns:
            str: the body's path and def line, its several bodies, a class's methods to ask, a name outside the clone,
                or no such function
        """
        if self.builtin():
            return f"{self.target} leads outside the clone, as imported, so no body is read here"
        # a def comes first, so a name bound to a def and a class says its body is unchecked rather than a class
        for module in self.clone.modules.values():
            if self.clone.modules.get(module.name) is not module:
                continue
            places = [f"{module.path}:{line}" for line, qual, kind in module.defs
                      if kind == "def" and f"{module.name}.{qual}" == self.target]
            reason = self.rebound(module.functions[self.target][0]) if len(places) == 1 else ""
            if reason:
                return f"the body of {self.target} at {places[0]}, {reason}, so every line is unchecked"
            if len(places) == 1:
                return f"the body of {self.target} at {places[0]}"
            if places:
                return f"{self.target} has {len(places)} bodies, at {' and '.join(places)}, so every line is unchecked"
        if self.target in self.clone.classes:
            methods = sorted({f"{module.name}.{qual}" for module in self.clone.modules.values()
                              for _, qual, kind in module.defs
                              if kind == "def" and f"{module.name}.{qual}".rpartition(".")[0] == self.target})
            if not methods:
                return f"{self.target} is a class that defines no method, so no body is read here"
            return f"{self.target} is a class, so ask one of its methods, {', '.join(methods)}"
        parent = self.target.rpartition(".")[0]
        if not any(name == parent or parent.startswith(f"{name}.") for name in self.clone.modules):
            return f"{self.target} leads outside the clone, as imported, so no body is read here"
        return f"the clone defines no function {self.target}"


    def builtin(self) -> bool:
        """
        Say whether the asked name lies in a module built into the interpreter or frozen in it, which no file replaces.

        Returns:
            bool: True when the asked name's top module is one of UNSHADOWED
        """
        return self.target.partition(".")[0] in UNSHADOWED


    def inside_body(self, scope: Scope, bodies: list[Scope]) -> tuple[str, bool] | None:
        """
        Say whether a use stands in one of the asked bodies, and how, a def nested in it left to its own query.

        Args:
            scope: the scope the use stands in
            bodies: the asked function's scopes

        Returns:
            tuple[str, bool] | None: the label of where in the body it stands, empty for the body itself or an eager
                comprehension in it, and whether it runs later than the function, or None for a use outside it
        """
        labels = []
        later  = False
        while scope is not None and scope not in bodies:
            if scope.kind == "function":
                return None
            if scope.deferred:
                labels.append(scope.deferred)
                later = True
            elif scope.kind == "class":
                labels.append(f"in class {scope.qual}, whose body runs as the function does")
            scope = scope.parent
        return (", ".join(reversed(labels)), later) if scope is not None else None


    def rebound(self, body: Scope) -> str:
        """
        Say why no body is certain for a function, its name or a class's holding it bound more than once or a star
        import that may replace it.

        Args:
            body: the function's scope

        Returns:
            str: the reason, empty when the body is certain
        """
        scope = body
        while scope.parent is not None and scope.kind in ("function", "class"):
            name     = scope.qual.rpartition(".")[2]
            bindings = scope.parent.bindings.get(name, [])
            # a name declared global or nonlocal is bound in another scope, so its body is never taken as certain
            if name in scope.parent.global_names or name in scope.parent.nonlocal_names:
                return REBOUND
            if len({binding.statement for binding in bindings}) > 1:
                return REBOUND
            if self.displaced(scope.parent, bindings):
                return STAR
            scope = scope.parent
        return ""


    def callee_words(
        self,
        module: Module,
        scope: Scope,
        node: ast.expr,
        is_call: bool,
        inside: tuple[str, bool],
    ) -> tuple[int, str] | None:
        """
        Word one use in a body for callees, its target and the target's kind, or keep it unchecked with its label.

        Args:
            module: the module the body stands in
            scope: the scope the use stands in
            node: the use
            is_call: whether the use is a call
            inside: where in the body it stands, and whether it runs later than the function

        Returns:
            tuple[int, str] | None: the group and the words, or None for a plain load the answer leaves out
        """
        place = self.resolve(module, scope, node)
        text  = dotted_text(node)
        verb  = "called" if is_call else "used"
        where = f", {inside[0]}" if inside[0] else ""
        found = self.value_words(node, place, is_call)
        if found is not None:
            return (2 if inside[1] else found[0]), found[1] + where
        if place.nature in RESOLVED and (is_call or place.nature in ("def", "external")):
            kind = {"module": "a module", "value": "a value", "external": "outside the clone, as imported"}
            what = "a class" if place.origin in self.clone.classes else kind.get(place.nature, "a def")
            if isinstance(
                node,
                ast.Attribute,
            ) and isinstance(node.value, ast.Name) and node.value.id in ("self", "cls"):
                what = f"{what}, its class's own as the static target, or an override"
            group = 2 if inside[1] else (0 if is_call else 1)
            return group, f"{text} {verb}, resolves to {place.origin}, {what}{where}"
        if not is_call:
            if place.nature == "candidate" and place.holds in ("def", "external"):
                return 2, f"{text} used, {place.label}, {place.origin}{where}"
            # a member read through a class that leaves it to a base, never one read through self or cls
            if place.label.startswith("through its base ") and not self_receiver(node):
                return 2, f"{text} used, {place.label}{where}"
            found = self.receiver_words(module, scope, node)
            return None if found is None else ((2 if inside[1] else found[0]), found[1] + where)
        if place.nature == "candidate":
            return 2, f"{text} called, {place.label}, {place.origin}{where}"
        label = place.label
        if place.nature == "local":
            label = "a parameter, a local or an assignment, unchecked"
        elif not isinstance(node, (ast.Name, ast.Attribute)):
            label = "a call through a subscript or a call's result, unchecked"
        elif not label and isinstance(node, ast.Name) and hasattr(builtins, node.id):
            label = "a builtin, unchecked"
        elif not label and isinstance(node, ast.Attribute):
            label = "a method of a value whose type the ast cannot know, unchecked"
        return 2, f"{text} called by name" + (f", {label}" if label else "") + where


    def value_words(self, node: ast.expr, place: Place, is_call: bool) -> tuple[int, str] | None:
        """
        Word a use that leads to a value the clone binds, a class's member or a module's value, for callees.

        Args:
            node: the use
            place: where it leads
            is_call: whether the use is a call

        Returns:
            tuple[int, str] | None: the group and the words, or None when the place holds no such value, or the use
                calls a value its own module binds, which stays a local as before
        """
        holds = place.holds if place.nature in ("candidate", "local") else place.nature
        if holds != "value" or (is_call and place.nature == "local"):
            return None
        text  = dotted_text(node)
        verb  = "called" if is_call else "used"
        owner = place.origin.rpartition(".")[0]
        if place.label:
            return 2, f"{text} {verb}, {place.label}, {place.origin}"
        if not is_call and self_receiver(node):
            hedge = "an instance or a subclass may hold its own, unchecked"
            return 2, f"{text} {verb}, bound in the body of class {owner}, {hedge}"
        written = self.marks()[0]
        marked  = next((written[step] for step in (place.origin, *place.via) if step in written), "")
        if marked:
            return 2, f"{text} {verb}, {marked}, {place.origin}"
        if owner in self.clone.classes:
            what = f"a member bound in the body of class {owner}"
        else:
            what = f"a value bound at module level in {owner}"
        if self_receiver(node):
            what = f"{what}, its class's own as the static target, or an override"
        return (0 if is_call else 1), f"{text} {verb}, resolves to {place.origin}, {what}"


    def receiver_words(self, module: Module, scope: Scope, node: ast.expr) -> tuple[int, str] | None:
        """
        Find the longest receiver in a chain that leads to a value the clone binds, its unresolved rest never promoted.

        Args:
            module: the module the use stands in
            scope: the scope the use stands in
            node: the chain, such as Status.active.value

        Returns:
            tuple[int, str] | None: the group and the words for that receiver, or None when none leads to such a value
        """
        receiver = node
        while isinstance(receiver, ast.Attribute):
            receiver = receiver.value
            if not isinstance(receiver, (ast.Name, ast.Attribute)):
                return None
            found = self.value_words(receiver, self.resolve(module, scope, receiver), False)
            if found is not None:
                return found
        return None


    def lines(self, module: Module, command: str) -> list[tuple[int, int, str]]:
        """
        Find every line of a module the asked command answers with.

        Args:
            module: the module
            command: defs, imports, callers, callees or test-importers

        Returns:
            list[tuple[int, int, str]]: each group, line and the line's words
        """
        if command == "defs":
            return self.def_lines(module)
        if command == "callees":
            return self.callee_lines(module)
        found = []
        if command == "callers":
            for use in module.uses:
                placed = self.use_line(module, use)
                if placed is not None:
                    found.append((placed[0], use[1].lineno, placed[1]))
            for line, qual, where, names in module.decorated:
                if f"{module.name}.{qual}" == self.target:
                    found.append((1, line, f"{qual} decorated by {names} {where}, its own definition"))
            return found
        for line, origin, where in module.imports:
            placed = self.import_line(origin, where)
            if placed is not None:
                found.append((placed[0], line, placed[1]))
        return found


def git(path: Path, *args: str, stdin: bytes | None = None) -> subprocess.CompletedProcess[bytes]:
    """
    Run git in a clone with every inherited GIT_ variable dropped and lazy fetching off.

    Args:
        path: the clone
        args: git's arguments
        stdin: what git reads on its input, if anything

    Returns:
        subprocess.CompletedProcess[bytes]: git's result, never checked here
    """
    environment = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    environment.update({"GIT_NO_LAZY_FETCH": "1", "GIT_TERMINAL_PROMPT": "0"})
    return subprocess.run(
        ["git", "-C", str(path), *args],
        input = stdin,
        capture_output = True,
        env = environment,
        check = False,
    )


def output(done: subprocess.CompletedProcess[bytes]) -> str:
    """
    Read what git printed, empty when it failed.

    Args:
        done: git's result

    Returns:
        str: its output stripped, or empty
    """
    return done.stdout.decode("utf-8", "replace").strip() if done.returncode == 0 else ""


def closed(path: str) -> bool:
    """
    Say whether a tracked path is one the guard and cicd's tools close, judged from its name alone.

    Args:
        path: the path in the tree

    Returns:
        bool: True for a secret file's name in any case or anything under a keys folder
    """
    # a backslash is a byte of a name git tracks, from a Linux commit, and read as a separator as the guard reads one
    lowered = path.lower().replace("\\", "/")
    if "/keys/" in f"/{lowered}":
        return True
    return any(fnmatch.fnmatchcase(lowered.rpartition("/")[2], glob) for glob in SECRET_GLOBS)


def is_test(path: str) -> bool:
    """
    Say whether a path is a test file.

    Args:
        path: the path in the tree

    Returns:
        bool: True for test_*.py, *_test.py, conftest.py or any file under a folder named tests or ending in _tests
    """
    *folders, filename = path.split("/")
    if filename == "conftest.py" or filename.startswith("test_") or filename.endswith("_test.py"):
        return True
    return any(folder == "tests" or folder.endswith("_tests") for folder in folders)


def module_name(path: str, roots: list[str]) -> tuple[str, bool]:
    """
    Name a file's module from its import root, the clone's top folder unless a deeper root holds it.

    Args:
        path: the path in the tree
        roots: the import roots below the top folder

    Returns:
        tuple[str, bool]: the dotted name, and whether the file is a package's __init__.py
    """
    best    = max((root for root in roots if path.startswith(f"{root}/")), key = len, default = "")
    parts   = path[len(best) + 1 if best else 0:-3].split("/")
    package = parts[-1] == "__init__"
    return ".".join(parts[:-1] if package else parts), package


def age(seconds: float) -> str:
    """
    Say how long ago something happened, in words.

    Args:
        seconds: how many seconds ago

    Returns:
        str: minutes, hours or days ago
    """
    minutes = int(seconds // 60)
    if minutes < 120:
        return f"{minutes} minutes ago"
    if minutes < 48 * 60:
        return f"{minutes // 60} hours ago"
    return f"{minutes // 1440} days ago"


def fence(path: Path, name: str) -> None:
    """
    Refuse a clone with a review open, its marker in its git dir, its common dir or any worktree registered there.

    Args:
        path: the clone
        name: its name as --repo gave it

    Raises:
        Refusal: when a marker stands, or git cannot say where the clone's git dirs are
    """
    places = []
    for option in ("--absolute-git-dir", "--git-common-dir"):
        place = output(git(path, "rev-parse", "--path-format=absolute", option))
        if not place:
            raise Refusal(UNREAD, f"git could not say where the git dir of {name} is")
        places.append(Path(place))
    worktrees = places[1] / "worktrees"
    if worktrees.is_dir():
        places.extend(entry for entry in worktrees.iterdir() if entry.is_dir())
    for place in places:
        marker = place / "kdf-review" / "open"
        if marker.exists():
            message = f"{name} has a review open, {marker.as_posix()}, so none of its files is read"
            raise Refusal(REFUSED, f"{message}. A clone whose review has a read open is never named")


def heading(path: Path, name: str, label: str, commit: str) -> str:
    """
    Write a clone's first line, the commit read, when origin/main last moved, and a checkout that differs.

    Args:
        path: the clone
        name: its name
        label: origin/main, or the --at that named the commit
        commit: the commit read

    Returns:
        str: the line
    """
    parts    = [f"{name} at {label} {commit[:7]}"]
    tracking = output(git(path, "rev-parse", "-q", "--verify", f"{TRACKING_REF}^{{commit}}"))
    if not tracking:
        parts.append("no origin/main")
    else:
        if label != DEFAULT_REF:
            parts.append(f"origin/main at {tracking[:7]}")
        logged = output(git(path, "reflog", "show", "--date=unix", "--format=%gd", "-n", "1", TRACKING_REF))
        stamp  = re.search(r"@\{(\d+)\}", logged)
        moved  = age(time.time() - int(stamp.group(1))) if stamp else "unknown, it has no reflog"
        parts.append(f"origin/main last moved {moved}")
    head = output(git(path, "rev-parse", "-q", "--verify", "HEAD"))
    if head != commit:
        parts.append(f"checkout at {head[:7]}" if head else "no checkout")
    return ", ".join(parts)


def open_clone(root: Path, name: str, rev: str | None) -> Clone:
    """
    Check a named clone, refuse it under an open review, and resolve its commit once.

    Args:
        root: the folder the clones sit in
        name: the clone's folder name
        rev: the --at revision for it, or None for origin/main

    Returns:
        Clone: the clone, its files not yet read

    Raises:
        Refusal: for a name that is no plain folder name, a folder that is no clone's top, or a commit it lacks
    """
    if not REPO_NAME.fullmatch(name) or name in (".", ".."):
        raise Refusal(REFUSED, f"--repo {name} is no folder name, which is letters, digits, ., - and _ alone")
    path = root / name
    if not path.is_dir():
        raise Refusal(UNREAD, f"{name} is no folder under {root.as_posix()}")
    if path.resolve().parent != root.resolve():
        raise Refusal(REFUSED, f"{name} leads outside {root.as_posix()} through a link, which is never followed")
    top = output(git(path, "rev-parse", "--show-toplevel"))
    if not top or Path(top).resolve() != path.resolve():
        raise Refusal(UNREAD, f"{name} is not the top folder of a git clone")
    fence(path, name)
    # the remote ref by its full name, so a tag or branch spelled origin/main is never taken for it
    commit = output(git(path, "rev-parse", "-q", "--verify", f"{rev or TRACKING_REF}^{{commit}}"))
    if not commit:
        raise Refusal(UNREAD, f"{name} has no commit {rev or DEFAULT_REF}")
    return Clone(name, path, commit, heading(path, name, f"--at {rev}" if rev else DEFAULT_REF, commit))


def listing(clone: Clone, skips: list[str]) -> list[tuple[str, str]]:
    """
    List a clone's tracked Python files at its commit, closed paths, vercel_api/ and the skipped folders left out.

    Args:
        clone: the clone
        skips: the folders --skip names

    Returns:
        list[tuple[str, str]]: each file's path and object id

    Raises:
        Refusal: when git cannot read the commit's tree
    """
    done = git(clone.path, "ls-tree", "-r", "-z", "--full-tree", clone.commit)
    if done.returncode:
        raise Refusal(UNREAD, f"the tree of {clone.name} at {clone.commit[:7]} could not be read")
    files = []
    left  = (GENERATED_FOLDER, *skips)
    for entry in done.stdout.split(b"\0"):
        meta, _, raw = entry.partition(b"\t")
        fields = meta.split()
        if len(fields) != 3 or fields[1] != b"blob" or fields[0] not in (b"100644", b"100755"):
            continue
        path = raw.decode("utf-8", "surrogateescape")
        if path.endswith(".py") and not closed(path) and not any(path.startswith(f"{skip}/") for skip in left):
            files.append((path, fields[2].decode()))
    return files


def contents(clone: Clone, oids: list[str]) -> dict[str, bytes]:
    """
    Read blobs in one git cat-file call, with no text conversion or filter, a missing one left out.

    Args:
        clone: the clone
        oids: the object ids

    Returns:
        dict[str, bytes]: each blob read, by its id
    """
    found = {}
    if not oids:
        return found
    data  = git(clone.path, "cat-file", "--batch", stdin = "".join(f"{oid}\n" for oid in oids).encode()).stdout
    start = 0
    for oid in oids:
        end = data.find(b"\n", start)
        if end < 0:
            break
        header = data[start:end].split()
        start  = end + 1
        if len(header) == 3 and header[0].decode() == oid and header[1] == b"blob":
            size = int(header[2])
            found[oid] = data[start:start + size]
            start      += size + 1
    return found


def read(clone: Clone, skips: list[str], package_roots: list[str]) -> None:
    """
    Read and walk every tracked Python file of a clone, naming any it could not read by path and line alone.

    Args:
        clone: the clone
        skips: the folders --skip names
        package_roots: the import roots --package-root names
    """
    files = listing(clone, skips)
    roots = [*package_roots, *(["src"] if any(SRC_PACKAGE.fullmatch(path) for path, _ in files) else [])]
    blobs = contents(clone, [oid for _, oid in files])
    for path, oid in files:
        if oid not in blobs:
            clone.unread.append(f"{path}, its object is missing and was not fetched")
            continue
        name, package = module_name(path, roots)
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                tree = ast.parse(blobs[oid], filename = path)
            module = Module(name, path, package, is_test(path), Scope("module", None, ""))
            Collector(module).visit(tree)
        except SyntaxError as error:
            clone.unread.append(f"{path}:{error.lineno or 0} did not parse")
            continue
        except (ValueError, RecursionError):
            clone.unread.append(f"{path} could not be walked")
            continue
        clone.files.append(module)
        held = clone.modules.get(name)
        # an import takes a package over a module file of the same name, and any other pair is unknown
        if name and (held is None or (package and not held.package)):
            clone.modules[name] = module
        elif name and not (held.package and not package):
            clone.unread.append(f"{path} names module {name} as {held.path} does, which resolves through the first")
    for module in clone.modules.values():
        clone.classes.update({full: (module, scope) for full, scope in module.classes.items()})


def spread(entries: list[tuple[int, str, int, str]], count: int) -> list[tuple[int, str, int, str]]:
    """
    Choose at most CAP lines of a group, taken in turn from each clone so no clone's lines hide another's.

    Args:
        entries: the group's lines, each its clone's index, path, line and words
        count: how many clones were named

    Returns:
        list[tuple[int, str, int, str]]: the lines chosen
    """
    by_clone = [sorted(entry for entry in entries if entry[0] == index) for index in range(count)]
    chosen   = []
    depth    = 0
    while len(chosen) < CAP and any(depth < len(rows) for rows in by_clone):
        chosen.extend(rows[depth] for rows in by_clone if depth < len(rows))
        depth += 1
    return chosen[:CAP]


def render(clones: list[Clone], command: str, groups: list[list], args: argparse.Namespace) -> list[str]:
    """
    Write the answer, each clone's first line, its groups, any file left unread and the floor's warning.

    Args:
        clones: the clones read
        command: the command asked
        groups: the groups' lines, three, or four for callees and test-importers, each its clone's index, path, line
            and words
        args: the parsed arguments, for --tests, --skip and --full

    Returns:
        list[str]: the answer's lines
    """
    lines = [clone.heading for clone in clones]
    left  = [f"{GENERATED_FOLDER}/", *(f"{skip}/" for skip in args.skip)]
    if command in ("imports", "callers") and not args.tests:
        left.append("tests")
    lines.append(f"Left out, {', '.join(left)}.")
    lines.extend(f"{clone.name}, {note}." for clone in clones for note in clone.notes)
    for title, entries in zip(TITLES[command], groups):
        counts = [f"{clone.name} {sum(entry[0] == index for entry in entries)}" for index, clone in enumerate(clones)]
        lines.append(f"{title}, {len(entries)}, {', '.join(counts)}")
        chosen = sorted(entries) if args.full else sorted(spread(entries, len(clones)))
        for index, path, line, words in chosen:
            lines.append(f"{clones[index].name}@{clones[index].commit[:7]} {path}:{line} {words}")
        if len(chosen) < len(entries):
            lines.append(f"{len(entries) - len(chosen)} more, --full prints them")
    lines.extend(f"Incomplete, {clone.name} {note}." for clone in clones for note in clone.unread)
    lines.append(f"{sum(map(len, groups))} in all. A floor, an empty group proves no absence. {NOT_SEEN}")
    lines.append("Read a line at its commit, git -C <clone> show <hash>:<path>, never the checkout.")
    return lines


def folders(values: list[str], flag: str) -> list[str]:
    """
    Check the folders a flag names, each a relative path inside a clone.

    Args:
        values: the folders given
        flag: the flag's name, for the refusal

    Returns:
        list[str]: the folders with no trailing slash

    Raises:
        Refusal: for a path that is absolute, empty or climbs out through a parent folder
    """
    checked = [value.strip("/") for value in values]
    for value in checked:
        if not value or ".." in re.split(r"[/\\]", value) or Path(value).is_absolute() or ":" in value:
            raise Refusal(REFUSED, f"{flag} {value} is no folder inside a clone")
    return checked


def revisions(values: list[str], repos: list[str]) -> dict[str, str]:
    """
    Read the --at values, each <repo>=<rev>, or a bare <rev> with a single --repo.

    Args:
        values: the --at values
        repos: the clones --repo names

    Returns:
        dict[str, str]: each clone's revision

    Raises:
        Refusal: for a bare --at beside several clones, a clone no --repo names, a clone named twice, or a revision
            that is empty or starts with a dash
    """
    found = {}
    for value in values:
        repo, sep, rev = value.partition("=")
        if not sep:
            if len(repos) != 1:
                raise Refusal(REFUSED, f"--at {value} needs a single --repo, else give --at <repo>=<rev>")
            repo, rev = repos[0], value
        if repo not in repos or repo in found:
            raise Refusal(REFUSED, f"--at names {repo}, which no --repo names or another --at named already")
        if not rev or rev.startswith("-"):
            raise Refusal(REFUSED, f"--at {value} is no revision, and one that starts with a dash is refused")
        found[repo] = rev
    return found


def default_root() -> Path:
    """
    Find the workspace, the folder the main checkout of the cicd clone this file sits in belongs to.

    Returns:
        Path: the workspace, from a worktree of the clone too
    """
    checkout = Path(__file__).resolve().parents[2]
    common   = output(git(checkout, "rev-parse", "--path-format=absolute", "--git-common-dir"))
    return Path(common).parent.parent if common else checkout.parent


def run(args: argparse.Namespace) -> int:
    """
    Answer a query whose arguments parsed, every clone checked and fenced before any file of one is read.

    Args:
        args: the parsed arguments

    Returns:
        int: the exit code, 0 an answer, 1 nothing found, 3 an answer left incomplete

    Raises:
        Refusal: for a name, a flag, a clone or a commit refused
    """
    if not DOTTED_NAME.fullmatch(args.name):
        raise Refusal(REFUSED, f"{args.name} is no Python name")
    if args.command in ("callers", "callees") and "." not in args.name:
        message = f"{args.command} takes a dotted name, its module and its name"
        raise Refusal(REFUSED, f"{message}, and defs finds where one lives")
    if len(set(args.repo)) != len(args.repo):
        raise Refusal(REFUSED, "a --repo is named twice")
    skips  = folders(args.skip, "--skip")
    roots  = folders(args.package_root, "--package-root")
    ats    = revisions(args.at, args.repo)
    root   = (args.root or default_root()).resolve()
    clones = [open_clone(root, name, ats.get(name)) for name in args.repo]
    for clone in clones:
        read(clone, skips, roots)
    groups = [[] for _ in TITLES[args.command]]
    for index, clone in enumerate(clones):
        resolver = Resolver(clone, args.name)
        before   = sum(map(len, groups))
        for module in clone.files:
            wanted = module.test if args.command == "test-importers" else not module.test or args.tests
            if args.command in ("defs", "callees") or wanted:
                for group, line, words in resolver.lines(module, args.command):
                    groups[group].append((index, module.path, line, words))
        if args.command == "callees":
            note = resolver.callee_note()
            if note.startswith("the body of ") and sum(map(len, groups)) == before:
                note = f"{note}, which makes no call, use or write the ast sees"
            clone.notes.append(note)
    for line in render(clones, args.command, groups, args):
        print(line)
    if any(clone.unread for clone in clones):
        return UNREAD
    return FOUND if any(groups) else NOTHING


def main(argv: list[str] | None = None) -> int:
    """
    Refuse a reviewer before anything, help included, then parse the arguments and answer.

    Args:
        argv: the arguments, sys.argv's by default

    Returns:
        int: the exit code
    """
    if os.environ.get("KDF_ROLE") == "reviewer":
        message = "a session in the reviewer role never runs the repo map, it reads code whole"
        print(f"kdf-repo-map: {message}", file = sys.stderr)
        return REFUSED
    parser = argparse.ArgumentParser(
        prog = "kdf-repo-map.sh",
        description = "A read only lookup over named Python clones, read from git's objects at one commit.",
        epilog = HELP,
        formatter_class = argparse.RawDescriptionHelpFormatter,
        allow_abbrev = False,
    )
    parser.add_argument("command", choices = COMMANDS)
    parser.add_argument("name", help = "the name asked, dotted for callers")
    parser.add_argument("--repo", action = "append", required = True, help = "a clone under the root, repeated")
    parser.add_argument("--at", action = "append", default = [], help = "<repo>=<rev>, or <rev> with one --repo")
    parser.add_argument("--skip", action = "append", default = [], help = "a folder to leave out besides vercel_api/")
    parser.add_argument("--tests", action = "store_true", help = "keep test files in imports and callers")
    parser.add_argument("--full", action = "store_true", help = "print every line of a group past its 40")
    parser.add_argument("--package-root", action = "append", default = [], help = "an import root inside a clone")
    parser.add_argument("--root", type = Path, help = "the folder the clones sit in, for tests")
    args = parser.parse_args(argv)
    sys.setrecursionlimit(max(sys.getrecursionlimit(), 10000))
    try:
        return run(args)
    except Refusal as refusal:
        print(f"kdf-repo-map: {refusal}", file = sys.stderr)
        return refusal.code


if __name__ == "__main__":
    sys.exit(main())
