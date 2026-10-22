"""
Stand ins for the local code scan's tests (D-085), shared by test_kdf_scan.py, test_kdf_scan_launcher.py and
test_kdf_scan_verify.py.

The wrapper runs each tool by an absolute path with an environment of named variables alone, so a stand in reads its
scenario from the files it is given and from scenario.json beside itself, and logs each call to calls.jsonl beside
itself. The stand in for Opengrep reads the rule files under each --config the way the real one names them, so a
finding's check id comes from the rules the wrapper materialised, and writes a finding for each VULN(<rule id>) it
reads in a scanned file. The stand in for zizmor collects the workflow files under its input, logs each as completed,
flags every unpinned uses and each ZFIND(<audit>) it reads. Each is a Python file run by this interpreter, which plays
an executable whose SHA-256 the test pins.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import types
from dataclasses import dataclass, field
from pathlib import Path

ROOT     = Path(__file__).resolve().parents[2]
COMMON   = ROOT / "scripts" / "common"
GIT      = shutil.which("git")
PYTHON   = Path(sys.executable)
COMMIT   = "c" * 40
EMPTY_GH = {"calls": []}

FAKE_OPENGREP = r'''
import json
import os
import re
import sys
from pathlib import Path

HERE     = Path(__file__).resolve().parent
SCENARIO = HERE / "scenario.json"
scenario = json.loads(SCENARIO.read_text(encoding = "utf-8")) if SCENARIO.exists() else {}
args     = sys.argv[1:]
with open(HERE / "calls.jsonl", "a", encoding = "utf-8") as log:
    log.write(json.dumps({"tool": "opengrep", "args": args, "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")
if scenario.get("opengrep_exit"):
    sys.exit(scenario["opengrep_exit"])
assert args[0] == "scan", args
configs = [args[index + 1] for index, arg in enumerate(args) if arg == "--config"]
output  = args[args.index("--output") + 1]
limit   = int(args[args.index("--max-target-bytes") + 1])
target  = args[-1]
rules   = {}
for config in configs:
    for rule in sorted(Path(config).rglob("*.yaml")):
        text   = rule.read_text(encoding = "utf-8")
        prefix = ".".join(rule.parent.as_posix().split("/"))
        for block in re.split(r"(?m)^\s*-\s+id:", text)[1:]:
            rule_id    = block.split()[0]
            category   = re.search(r"category:\s*(\S+)", block)
            confidence = re.search(r"confidence:\s*(\S+)", block)
            rules[rule_id] = {
                "check": f"{prefix}.{rule_id}",
                "category": category.group(1) if category else "",
                "confidence": confidence.group(1) if confidence else "",
            }
results, errors, scanned = [], [], []
for file in sorted(Path(target).rglob("*")):
    if not file.is_file() or file.name == ".semgrepignore":
        continue
    shown = str(file).replace("/", "\\")
    data  = file.read_bytes()
    if len(data) > limit or b"OPENGREP-SKIPS-ME" in data:
        continue
    scanned.append(shown)
    for number, line in enumerate(data.decode("utf-8", "replace").split("\n"), 1):
        if "PARSE-ERROR" in line:
            spans = [{"path": shown, "start": {"line": number, "col": 1}, "end": {"line": number, "col": 9}}]
            errors.append({"code": 3, "level": "warn", "type": ["PartialParsing", spans], "message": "Syntax error",
                           "path": shown})
        if "RULE-TIMEOUT" in line:
            errors.append({"code": 2, "level": "warn", "type": "Timeout", "message": "Timeout", "path": shown})
        for match in re.finditer(r"VULN\(([\w.-]+)(?:,(\d+))?\)", line):
            rule = rules.get(match.group(1))
            if rule is None:
                continue
            last = number + int(match.group(2) or 1) - 1
            results.append({
                "check_id": rule["check"],
                "path": shown,
                "start": {"line": number, "col": 1, "offset": 0},
                "end": {"line": last, "col": 2, "offset": 1},
                "extra": {
                    "message": f"{match.group(1)} found here",
                    "metadata": {"category": rule["category"], "confidence": rule["confidence"]},
                    "severity": "WARNING",
                    "lines": line,
                },
            })
if scenario.get("opengrep_outside"):
    results.append(dict(results[0], path = "elsewhere\\x.py"))
if scenario.get("opengrep_pathless_error"):
    errors.append({"code": 2, "level": "error", "type": "Rule parse error", "message": "a rule failed"})
if not scenario.get("opengrep_no_json"):
    Path(output).write_text(json.dumps({"version": "1.30.2", "results": results, "errors": errors,
                                        "paths": {"scanned": scanned}}), encoding = "utf-8")
'''

FAKE_ZIZMOR = r'''
import json
import os
import re
import sys
from pathlib import Path

HERE     = Path(__file__).resolve().parent
SCENARIO = HERE / "scenario.json"
scenario = json.loads(SCENARIO.read_text(encoding = "utf-8")) if SCENARIO.exists() else {}
args     = sys.argv[1:]
with open(HERE / "calls.jsonl", "a", encoding = "utf-8") as log:
    log.write(json.dumps({"tool": "zizmor", "args": args, "cwd": os.getcwd(), "env": dict(os.environ)}) + "\n")
if scenario.get("zizmor_exit_error"):
    sys.exit(1)


def workflow(path):
    parts = path.split("/")
    if parts[0] != ".github":
        return False
    if len(parts) == 3 and parts[1] == "workflows" and parts[2].endswith((".yml", ".yaml")):
        return True
    return parts[-1] in ("action.yml", "action.yaml", "dependabot.yml", "dependabot.yaml")


def location(kind, shown, row, feature, feature_kind):
    return {
        "symbolic": {"key": {"Local": {"verbatim_path": shown}}, "annotation": "", "route": {"route": []},
                     "feature_kind": feature_kind, "kind": kind},
        "concrete": {"location": {"start_point": {"row": row, "column": 0}, "end_point": {"row": row, "column": 1}},
                     "feature": feature, "comments": []},
    }


def finding(ident, shown, row, feature, related = None):
    locations = [location("Primary", shown, row, feature, "Normal")]
    if related is not None:
        locations.append(location("Related", shown, related, "run", "KeyOnly"))
    return {"ident": ident, "desc": ident, "ignored": False, "locations": locations,
            "determinations": {"confidence": "High", "severity": "High", "persona": "Regular"}}


found, completed = [], []
for file in sorted(Path(args[-1]).rglob("*")):
    posix = file.as_posix()
    if not file.is_file() or not workflow(posix):
        continue
    text = file.read_text(encoding = "utf-8")
    if "ZIZMOR-SKIPS-ME" in text:
        continue
    shown = ".\\" + posix.replace("/", "\\")
    completed.append(shown)
    lines = text.split("\n")
    for row, line in enumerate(lines):
        uses = re.search(r"uses:\s*([^\s#]+)", line)
        if uses and "@" in uses.group(1) and not re.search(r"@[0-9a-f]{40}$", uses.group(1)):
            found.append(finding("unpinned-uses", shown, row, uses.group(1)))
        for match in re.finditer(r"ZFIND\(([\w-]+)(,run)?\)", line):
            related = None
            if match.group(2):
                related = next(index for index in range(row, -1, -1) if "run:" in lines[index])
            found.append(finding(match.group(1), shown, row, line.strip(), related))
sys.stderr.write(" INFO zizmor: zizmor v1.30.1\n")
for shown in completed:
    sys.stderr.write(f" INFO audit: zizmor: completed {shown}\n")
print(json.dumps(found))
sys.exit(14 if found else 0)
'''

FAKE_GH = r'''
import json
import sys
from pathlib import Path

HERE     = Path(__file__).resolve().parent
scenario = json.loads((HERE / "gh.json").read_text(encoding = "utf-8"))
args     = sys.argv[1:]
with open(HERE / "gh-calls.jsonl", "a", encoding = "utf-8") as log:
    log.write(json.dumps(args) + "\n")
endpoint = next((arg for arg in args if arg.startswith("repos/")), "")
for prefix, answer in scenario["answers"].items():
    if endpoint.startswith(prefix):
        if answer is None:
            sys.stderr.write("HTTP 404\n")
            sys.exit(1)
        print(json.dumps(answer))
        sys.exit(0)
sys.stderr.write(f"no answer for {endpoint}\n")
sys.exit(1)
'''

# the rule files of the rig's rules clone, each id's metadata as Semgrep's rules write it
RULES        = {
    "python/lang/security/audit/eval-detected.yaml": ("eval-detected", "security", "MEDIUM"),
    "python/lang/security/audit/low-python.yaml": ("low-python", "security", "LOW"),
    "python/lang/security/audit/style-only.yaml": ("style-only", "best-practice", "HIGH"),
    "python/lang/security/audit/logging/logger-credential-leak.yaml": (
        "python-logger-credential-disclosure",
        "security",
        "MEDIUM",
    ),
    "python/lang/security/audit/shared-name.yaml": ("shared-name", "security", "HIGH"),
    "python/lang/security/audit/second-rule.yaml": ("second-rule", "security", "HIGH"),
    "javascript/lang/security/audit/shared-name.yaml": ("shared-name", "security", "HIGH"),
    "javascript/lang/security/audit/detect-non-literal-fs-filename.yaml": (
        "detect-non-literal-fs-filename",
        "security",
        "LOW",
    ),
    "javascript/lang/security/audit/path-traversal/path-join-resolve-traversal.yaml": (
        "path-join-resolve-traversal",
        "security",
        "LOW",
    ),
    "typescript/lang/security/audit/low-typescript.yaml": ("low-typescript", "security", "LOW"),
}
RULE_FOLDERS = ("python/lang/security", "javascript/lang/security", "typescript/lang/security")
KDF_RULE     = """rules:
- id: kdf-test-rule
  languages: [python]
  message: a KDF rule
  severity: WARNING
  metadata:
    category: security
    confidence: MEDIUM
  pattern: secret_value($X)
"""

BLOCK = """# >>> kdf-scan, managed by cicd's scripts sync
# The local code scan, Opengrep over the code and zizmor over the workflows (cicd D-085).
SCAN_EXCLUDE ?=
{lines}.PHONY: scan
scan: ## Local code scan, Opengrep and zizmor, before every pull request
\t@D:/KriegerDataForge-scan/python/3.14.7/python.exe -I -S -B D:/KriegerDataForge-scan/kdf-scan.py
# <<< kdf-scan
"""


def rule_text(rule_id: str, category: str, confidence: str) -> str:
    return (
        f"rules:\n- id: {rule_id}\n  languages: [python]\n  message: {rule_id}\n  severity: WARNING\n"
        f"  metadata:\n    category: {category}\n    confidence: {confidence}\n  pattern: {rule_id}($X)\n"
    )


def makefile(*lines: str) -> str:
    return "help:\n\t@echo help\n\n" + BLOCK.format(lines = "".join(f"{line}\n" for line in lines))


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(repo: Path, *args: str, check: bool = True) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        check = check,
        capture_output = True,
        text = True,
    ).stdout.strip()


def init_repo(repo: Path) -> Path:
    repo.mkdir(parents = True, exist_ok = True)
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "dev@example.com")
    git(repo, "config", "user.name", "Dev")
    git(repo, "config", "core.autocrlf", "false")
    git(repo, "config", "commit.gpgsign", "false")
    return repo


def write(repo: Path, files: dict[str, str | bytes]) -> None:
    for name, text in files.items():
        target = repo / name
        target.parent.mkdir(parents = True, exist_ok = True)
        if isinstance(text, bytes):
            target.write_bytes(text)
        else:
            target.write_text(text, encoding = "utf-8", newline = "\n")


def commit(repo: Path, files: dict[str, str | bytes], message: str = "change") -> str:
    write(repo, files)
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


def program(path: Path, text: str) -> Path:
    path.parent.mkdir(parents = True, exist_ok = True)
    path.write_text(text, encoding = "utf-8", newline = "\n")
    return path


def load(name: str, path: Path) -> types.ModuleType:
    """
    Load a module by its path with bytecode off, as test_kdf_repo_map.py loads the repo map.
    """
    spec   = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


@dataclass
class Rig:
    """
    A machine folder of stand ins, a rules clone at a commit, and a repo whose origin/main is its first commit.
    """
    base:      Path
    tools:     Path
    rules:     Path
    commit:    str
    digest:    str
    repo:      Path
    scan:      types.ModuleType
    files:    dict[str, bytes] = field(default_factory = dict)
    cicd:     Path | None = None
    scenario: dict = field(default_factory = dict)


    def machine(self, **changes: object) -> object:
        return self.machine_for(self.scan, **changes)


    def machine_for(self, module: types.ModuleType, **changes: object) -> object:
        """
        The rig's machine built from a given wrapper module, the one a launcher loaded from its bundle among them.
        """
        opengrep = self.tools / "opengrep.py"
        zizmor   = self.tools / "zizmor.py"
        values   = {
            "root": self.base,
            "opengrep": module.Tool("opengrep", "1.30.2", opengrep, sha256(opengrep), (str(PYTHON), str(opengrep))),
            "zizmor": module.Tool("zizmor", "1.30.1", zizmor, sha256(zizmor), (str(PYTHON), str(zizmor))),
            "python": module.Tool("python", "3.14.7", PYTHON, sha256(PYTHON), (str(PYTHON),)),
            "rules": self.rules,
            "rules_commit": self.commit,
            "rules_digest": self.digest,
            "rule_folders": RULE_FOLDERS,
            "git": GIT,
            "bundle": "b" * 40,
            "files": self.files,
            "cicd": self.cicd,
        }
        values.update(changes)
        return module.Machine(**values)


    def set_scenario(self, **values: object) -> None:
        self.scenario.update(values)
        (self.tools / "scenario.json").write_text(json.dumps(self.scenario), encoding = "utf-8")


    def calls(self, tool: str) -> list[dict]:
        log = self.tools / "calls.jsonl"
        if not log.exists():
            return []
        lines = log.read_text(encoding = "utf-8").splitlines()
        return [call for call in (json.loads(line) for line in lines) if call["tool"] == tool]


def bundle_files() -> dict[str, bytes]:
    """
    A bundle's files as this source tree holds them, with the rig's KDF rule in place of KDF's own.
    """
    files = {name: (COMMON / name).read_bytes() for name in ("kdf_scan.py", "kdf_scan_launcher.py", "ci_paths.py")}
    files["kdf_zizmor.yml"] = (COMMON / "kdf_zizmor.yml").read_bytes()
    files["scan_rules/kdf-test-rule.yaml"] = KDF_RULE.encode("utf-8")
    return files


def install_bundle(root: Path, files: dict[str, bytes], commit: str = COMMIT, current: bool = True) -> Path:
    """
    Write a bundle as the install would, its files, its manifest, `current` naming it, and the launcher at the root.
    """
    folder = root / "bundles" / commit
    for name, data in files.items():
        (folder / name).parent.mkdir(parents = True, exist_ok = True)
        (folder / name).write_bytes(data)
    manifest = "".join(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files))
    (folder / "manifest.sha256").write_text(manifest, encoding = "utf-8", newline = "\n")
    if current:
        (root / "current").write_text(f"{commit}\n", encoding = "utf-8", newline = "\n")
        (root / "kdf-scan.py").write_bytes(files["kdf_scan_launcher.py"])
    return folder


def fake_python(root: Path, version: str = "3.14.7") -> Path:
    """
    A stand in for the installed Python's folder, a few files and the manifest the install writes from its archive.
    """
    folder = root / "python" / version
    files  = {"python.exe": b"MZ a stand in\n", "Lib/os.py": b"# os\n", "DLLs/_ssl.pyd": b"pyd\n"}
    for name, data in files.items():
        (folder / name).parent.mkdir(parents = True, exist_ok = True)
        (folder / name).write_bytes(data)
    manifest = "".join(f"{hashlib.sha256(files[name]).hexdigest()}  {name}\n" for name in sorted(files))
    (folder / "manifest.sha256").write_text(manifest, encoding = "utf-8", newline = "\n")
    return folder


def platform(elevated: bool = False, uac: dict | None = None, acl: list[str] | None = None) -> types.SimpleNamespace:
    """
    A stand in for the launcher's Windows checks, an elevated token, UAC's values and the folder's permission.
    """
    return types.SimpleNamespace(
        elevated = lambda: elevated,
        uac = lambda: dict(uac or {}),
        acl = lambda root: list(acl or []),
    )


def make_rig(tmp_path: Path, scan: types.ModuleType, files: dict[str, str | bytes] | None = None) -> Rig:
    """
    Build the rig, its repo's first commit holding the given files and a Makefile with the managed block unless they
    name their own, origin/main set to it.
    """
    tools = tmp_path / "tools"
    program(tools / "opengrep.py", FAKE_OPENGREP)
    program(tools / "zizmor.py", FAKE_ZIZMOR)
    source = init_repo(tmp_path / "rules-src")
    commit(source, {path: rule_text(*meta) for path, meta in RULES.items()} | {"README.md": "rules\n"}, "rules")
    rules = tmp_path / "rules.git"
    subprocess.run(["git", "clone", "-q", "--bare", str(source), str(rules)], check = True, capture_output = True)
    rules_commit = git(source, "rev-parse", "HEAD")
    digest       = scan.rules_digest(scan.rule_files(GIT, rules, rules_commit, RULE_FOLDERS))
    bundle       = {
        "kdf_zizmor.yml": (COMMON / "kdf_zizmor.yml").read_bytes(),
        "scan_rules/kdf-test-rule.yaml": KDF_RULE.encode("utf-8"),
    }
    repo         = init_repo(tmp_path / "repo")
    first        = {"Makefile": makefile(), "README.md": "the repo\n"}
    first.update(files or {})
    commit(repo, first, "first")
    git(repo, "update-ref", "refs/remotes/origin/main", "HEAD")
    return Rig(
        base = tmp_path / "scan-root",
        tools = tools,
        rules = rules,
        commit = rules_commit,
        digest = digest,
        repo = repo,
        scan = scan,
        files = bundle,
    )
