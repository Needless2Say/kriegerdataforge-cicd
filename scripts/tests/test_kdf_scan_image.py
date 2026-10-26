"""
Tests for the local code scan's image and gate (D-085, design 5.1 and 5.3), the files a build session cannot run
here, held to their contract by reading them, and the build's two helpers run on archives and pins made here.

The gate's reusable workflow and SCAN_IMAGE name one active set, unpinned until the first activation, the canonical
caller's SHA-256 is the caller's, every action is pinned by its commit, the gate refuses any event but a dispatch of
main, reads with contents and pull-requests alone and writes the five ids, and the image's build holds no permission
while its publish job alone writes packages, attestations and its token. The Dockerfile takes its base by digest in
both stages and runs the wrapper as a user that is not root, and its context is an allowlist. The layer inspection
finds a rule in a layer a later one deletes, and the fetch refuses an empty pin and a hash that differs.
"""

from __future__ import annotations

import gzip
import hashlib
import io
import json
import re
import tarfile
import types
import zipfile
from pathlib import Path

import distribute_scripts as ds
import pytest
from tests.scan_fakes import COMMON, ROOT, load

SCAN      = load("kdf_scan", COMMON / "kdf_scan.py")
INSPECT   = load("kdf_scan_inspect_layers", COMMON / "scan_build" / "inspect_layers.py")
FETCH     = load("kdf_scan_fetch", COMMON / "scan_build" / "fetch.py")
WORKFLOWS = ROOT / ".github" / "workflows"
GATE      = (WORKFLOWS / "kdf-scan-gate-reusable.yml").read_text(encoding = "utf-8")
PUBLISH   = (WORKFLOWS / "publish-scan-image.yml").read_text(encoding = "utf-8")
BUILD     = COMMON / "scan_build"
DIGEST    = re.compile(r"@sha256:[0-9a-f]{64}\b")


def env_value(text: str, name: str) -> str:
    found = re.findall(rf"^  {name}: (\S+)$", text, re.MULTILINE)
    assert len(found) == 1, name
    return found[0]


def uncommented(text: str) -> str:
    return "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))


def job(text: str, name: str) -> str:
    start = text.index(f"\n  {name}:\n")
    after = re.search(r"\n  [a-z][a-z0-9-]*:\n", text[start + 1:])
    return text[start:start + 1 + after.start()] if after else text[start:]

# ======================================================================================================================
# the active set and the caller
# ======================================================================================================================

def test_the_gates_set_and_scan_image_are_one_set_unpinned_together_until_activated() -> None:
    active = SCAN.parse_scan_image(ds.SCAN_IMAGE_FILE.read_text(encoding = "utf-8"))
    if not active:
        for name in ("KDF_SCAN_DIGEST", "KDF_SCAN_RULES_COMMIT", "KDF_SCAN_CONTRACT"):
            assert env_value(GATE, name) == SCAN.UNPINNED, name
        return
    assert env_value(GATE, "KDF_SCAN_IMAGE") == active["image"]
    assert env_value(GATE, "KDF_SCAN_DIGEST") == active["digest"]
    assert env_value(GATE, "KDF_SCAN_RULES_COMMIT") == active["rules_commit"]
    assert env_value(GATE, "KDF_SCAN_CONTRACT") == active["contract"]


def test_the_gates_canonical_caller_hash_is_the_callers_own() -> None:
    expected = hashlib.sha256(ds.caller_text().encode("utf-8")).hexdigest()
    assert env_value(GATE, "KDF_SCAN_CALLER_SHA") == expected


def test_the_caller_names_the_reusable_workflow_by_its_own_name_apart_from_its_own_path() -> None:
    assert SCAN.CALLER_PATH.endswith(
        "/kdf-scan-gate.yml",
    ) and SCAN.REUSABLE_PATH.endswith("/kdf-scan-gate-reusable.yml")
    assert f"kriegerdataforge-cicd/{SCAN.REUSABLE_PATH}@main" in ds.caller_text()

# ======================================================================================================================
# the gate
# ======================================================================================================================

def test_every_action_of_both_workflows_is_pinned_by_its_commit() -> None:
    for text in (GATE, PUBLISH):
        for used in re.findall(r"uses: (\S+)", text):
            assert re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", used), used


def test_the_gate_is_a_reusable_workflow_that_refuses_any_event_but_a_dispatch_of_main() -> None:
    assert "  workflow_call:\n" in GATE and "pull_request" not in GATE and "push:" not in GATE
    assert '"$EVENT" != "workflow_dispatch"' in GATE and '"$REF" != "refs/heads/main"' in GATE
    assert "the pull request's base is $base" in GATE


def test_the_gate_reads_with_contents_and_pull_requests_alone_and_inherits_no_secret() -> None:
    assert "permissions: {}\n" in GATE
    assert "    permissions:\n      contents: read\n      pull-requests: read\n" in GATE
    assert "secrets" not in GATE.replace("secret's", "") and "write" not in re.sub(r"#.*", "", GATE).replace(
        "--no-write-fetch-head",
        "",
    )


def test_the_gate_scans_offline_read_only_as_no_root_with_the_repository_and_rules_mounted_read_only() -> None:
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--user 65532:65532",
        "/repo:ro",
        "/rules:ro",
        'pr-tree --head "$HEAD_SHA"',
        "--caller-sha",
    ):
        assert flag in GATE, flag
    assert "GH_TOKEN" not in GATE[GATE.index("Scan the head in the pinned image"):GATE.index("Ask GitHub again")]


def test_the_gate_pulls_and_runs_the_scan_image_by_its_digest_alone() -> None:
    scan = GATE[GATE.index("Scan the head in the pinned image"):GATE.index("Ask GitHub again")]
    assert 'docker pull --quiet "$KDF_SCAN_IMAGE@$KDF_SCAN_DIGEST"' in scan
    assert 'image="$KDF_SCAN_IMAGE@$KDF_SCAN_DIGEST"' in scan and '"$image" \\\n' in scan
    assert len(re.findall(r"docker (?:pull|run)\b", GATE)) == 2


def test_the_gate_checks_gits_ids_against_githubs_and_asks_again_before_it_ends() -> None:
    assert "the fetched head is not GitHub's" in GATE and "the fetch does not reach GitHub's merge base" in GATE
    again = GATE[GATE.index("Ask GitHub again"):]
    assert "the head moved" in again and "main moved" in again and "cicd's pin moved" in again


def test_the_gate_writes_the_five_ids_for_the_owners_reading() -> None:
    summary = GATE[GATE.index("Write the five ids"):]
    for row in (
        "| Head |",
        "| Base's main, the policy |",
        "| Image |",
        "| Scanner's cicd commit |",
        "| Rules' commit",
        "| Caller workflow |",
    ):
        assert row in summary, row

# ======================================================================================================================
# the image's build
# ======================================================================================================================

def test_the_publish_runs_on_main_alone_its_build_holding_no_permission() -> None:
    assert "    branches: [main]\n" in PUBLISH and "pull_request" not in PUBLISH
    assert PUBLISH.count("if: github.ref == 'refs/heads/main'") == 2
    build = job(PUBLISH, "build")
    assert "    permissions: {}\n" in build and "persist-credentials: false" in build
    assert "inspect_layers.py" in build and "image_fixtures.py" in build and "--provenance=false" in build


def test_the_publish_job_alone_writes_and_pushes_the_tested_archive_by_its_digest() -> None:
    publish = job(PUBLISH, "publish")
    assert "      packages: write\n      attestations: write\n      id-token: write\n" in publish
    assert "skopeo copy --quiet --preserve-digests" in publish and '"$pushed" != "$expected"' in publish
    assert "actions/attest-build-provenance@" in publish and "skopeo inspect --no-creds" in publish
    assert "delete" not in uncommented(PUBLISH).lower()


def test_the_dockerfile_takes_its_base_by_digest_and_runs_the_wrapper_as_no_root() -> None:
    text  = (BUILD / "Dockerfile").read_text(encoding = "utf-8")
    bases = re.findall(r"^FROM (\S+)", text, re.MULTILINE)
    assert len(bases) == 2 and all(DIGEST.search(base) for base in bases), bases
    assert all(base.startswith("ghcr.io/needless2say/") for base in bases)
    assert "\nUSER 65532:65532\n" in text and '"-I", "-S", "-B", "/opt/kdf-scan/kdf_scan.py"' in text
    assert "semgrep" not in uncommented(text).lower()
    assert not text.startswith("# syntax")


def test_the_build_context_is_an_allowlist() -> None:
    lines = [line for line in (BUILD / "Dockerfile.dockerignore").read_text(encoding = "utf-8").splitlines()
             if line and not line.startswith("#")]
    assert lines[0] == "*" and all(line.startswith("!") for line in lines[1:])
    assert "!scan_build/fetch.py" in lines and "!kdf_scan.py" in lines

# ======================================================================================================================
# the layer inspection
# ======================================================================================================================

def layer(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj = buffer, mode = "w") as archive:
        for name, data in files.items():
            info      = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return gzip.compress(buffer.getvalue())


def oci(path: Path, layers: list[bytes]) -> Path:
    blobs = {}
    for data in layers:
        blobs["sha256:" + hashlib.sha256(data).hexdigest()] = data
    manifest = json.dumps({"layers": [{"digest": digest} for digest in blobs]}).encode()
    blobs["sha256:" + hashlib.sha256(manifest).hexdigest()] = manifest
    index = json.dumps({"manifests": [{"digest": "sha256:" + hashlib.sha256(manifest).hexdigest()}]}).encode()
    with tarfile.open(path, "w") as archive:
        for name, data in [("index.json", index), *((f"blobs/sha256/{d[7:]}", b) for d, b in blobs.items())]:
            info      = tarfile.TarInfo(name)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return path


def test_a_clean_archive_passes_the_layer_inspection(tmp_path: Path) -> None:
    archive = oci(tmp_path / "clean.tar", [layer({"opt/kdf-scan/kdf_scan.py": b"print(1)\n"})])
    assert INSPECT.findings(archive) == [] and INSPECT.main([str(archive)]) == 0


def test_a_rule_in_a_layer_a_later_one_deletes_is_still_found(tmp_path: Path) -> None:
    rule    = b"rules:\n- id: x\n  metadata:\n    source: https://semgrep.dev/r/python.x\n"
    archive = oci(tmp_path / "hidden.tar", [
        layer({"tmp/rules/x.yaml": rule}),
        layer({"tmp/rules/.wh.x.yaml": b""}),
    ])
    assert len(INSPECT.findings(archive)) == 1 and INSPECT.main([str(archive)]) == 1


def test_a_path_naming_semgreps_rules_is_found(tmp_path: Path) -> None:
    archive = oci(tmp_path / "named.tar", [layer({"cache/semgrep-rules.git/HEAD": b"ref: refs/heads/main\n"})])
    assert INSPECT.findings(archive) and INSPECT.main([str(archive)]) == 1

# ======================================================================================================================
# the fetch
# ======================================================================================================================

def test_the_fetch_finds_the_wrapper_one_folder_up_in_cicds_tree() -> None:
    assert FETCH.load_pins().RULES_COMMIT == SCAN.RULES_COMMIT


def test_the_fetch_refuses_while_owner_step_3_leaves_a_pin_empty(tmp_path: Path, capsys) -> None:
    pins                 = types.SimpleNamespace(**{name: "x" for name in FETCH.NEEDED})
    pins.OPENGREP_SHA256 = ""
    assert FETCH.main([str(tmp_path / "out")], pins) == 1
    assert "owner step 3 has not filled OPENGREP_SHA256" in capsys.readouterr().out


def test_the_fetch_refuses_an_address_that_is_not_https(tmp_path: Path) -> None:
    with pytest.raises(FETCH.FetchError, match = "not an https address"):
        FETCH.download("http://example.com/x", tmp_path / "x", "0" * 64)


def test_zizmor_is_taken_from_its_wheel_and_held_to_its_own_pin(tmp_path: Path) -> None:
    pins  = types.SimpleNamespace(ZIZMOR_VERSION = "1.30.1", ZIZMOR_SHA256 = hashlib.sha256(b"a program").hexdigest())
    wheel = tmp_path / "zizmor.whl"
    with zipfile.ZipFile(wheel, "w") as archive:
        archive.writestr(FETCH.zizmor_member(pins), b"a program")
    assert FETCH.take_zizmor(pins, wheel, tmp_path / "zizmor").read_bytes() == b"a program"
    pins.ZIZMOR_SHA256 = "0" * 64
    with pytest.raises(FETCH.FetchError, match = "not its pinned"):
        FETCH.take_zizmor(pins, wheel, tmp_path / "zizmor")
    pins.ZIZMOR_SHA256 = ""
    with pytest.raises(FETCH.FetchError, match = "pin it and build again"):
        FETCH.take_zizmor(pins, wheel, tmp_path / "zizmor")
