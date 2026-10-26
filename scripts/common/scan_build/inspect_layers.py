"""
The scan image's layer inspection (D-085, design 5.1, Round Table 66's L7), run by the image's build on the OCI
archive it is about to publish, so Semgrep's rules never reach a public image.

It reads every layer the archive's manifest names, not only the finished filesystem, so a rules file added in one layer
and deleted in a later one is still found, and fails on any path naming semgrep-rules and on any file holding the
address Semgrep's rules carry in their metadata. KDF's own rules carry neither. Standard library only.
"""

from __future__ import annotations

# standard imports
import io
import json
import sys
import tarfile
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

# what marks a file as one of Semgrep's rules, by its path or by the rule page address every rule's metadata names
PATH_MARKS    = ("semgrep-rules", "semgrep_rules")
CONTENT_MARKS = (b"semgrep.dev/r/", b"semgrep.dev/playground")
# files larger than this are programs and libraries, never a rule file, and are left unread
LARGEST_RULE = 2 * 1024 * 1024

# ======================================================================================================================
# The inspection
# ======================================================================================================================

def blob(archive: tarfile.TarFile, digest: str) -> bytes:
    """
    One blob of the OCI archive by its digest.

    Args:
        archive: the archive
        digest: the blob's sha256 digest

    Returns:
        bytes: the blob

    Raises:
        ValueError: when the archive holds no such blob
    """
    algorithm, _, value = digest.partition(":")
    member = archive.extractfile(f"blobs/{algorithm}/{value}")
    if member is None:
        raise ValueError(f"the archive holds no blob {digest}")
    return member.read()


def layers(archive: tarfile.TarFile) -> list[str]:
    """
    Every layer digest of the archive's one image, through its index and manifest.

    Args:
        archive: the archive

    Returns:
        list[str]: each layer's digest

    Raises:
        ValueError: when the archive holds no single image manifest
    """
    index = json.loads(archive.extractfile("index.json").read())
    found = index.get("manifests", [])
    if len(found) != 1:
        raise ValueError(f"the archive's index names {len(found)} manifests, not one")
    manifest = json.loads(blob(archive, found[0]["digest"]))
    if "manifests" in manifest:
        images = manifest["manifests"]
        if len(images) != 1:
            raise ValueError(f"the image index names {len(images)} images, not one")
        manifest = json.loads(blob(archive, images[0]["digest"]))
    return [layer["digest"] for layer in manifest.get("layers", [])]


def findings(path: Path) -> list[str]:
    """
    Every file of every layer that names or holds one of Semgrep's rules.

    Args:
        path: the OCI archive

    Returns:
        list[str]: each finding, the layer and the file
    """
    found = []
    with tarfile.open(path) as archive:
        for digest in layers(archive):
            with tarfile.open(fileobj = io.BytesIO(blob(archive, digest))) as layer:
                for member in layer:
                    name = member.name.lower()
                    if any(mark in name for mark in PATH_MARKS):
                        found.append(f"{digest[:19]} {member.name}, its path names Semgrep's rules")
                        continue
                    if not member.isfile() or member.size > LARGEST_RULE:
                        continue
                    data = layer.extractfile(member).read()
                    if any(mark in data for mark in CONTENT_MARKS):
                        found.append(f"{digest[:19]} {member.name}, it holds a Semgrep rule's address")
    return found


def main(argv: list[str] | None = None) -> int:
    """
    Inspect one OCI archive, printing each finding.

    Args:
        argv: the archive's path, sys.argv when None

    Returns:
        int: 0 when no layer holds a rule, 1 when one does or the archive cannot be read
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("inspect   usage, inspect_layers.py <oci archive>")
        return 1
    try:
        found = findings(Path(args[0]))
    except (OSError, ValueError, KeyError, tarfile.TarError) as error:
        print(f"inspect   refused, the archive cannot be read, {error}")
        return 1
    for line in found:
        print(f"inspect   FAIL {line}")
    print(f"inspect   {'FAIL' if found else 'ok'}, {len(found)} files of Semgrep's rules in the image's layers")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main())
