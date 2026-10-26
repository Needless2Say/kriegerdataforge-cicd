"""
The local code scan's image fetch (D-085, design 5.1), run in the image's first build stage alone, the only step with
the network.

It reads every pin from the wrapper beside it, refuses an empty one, which owner step 3 fills, downloads cosign,
Opengrep's Linux asset with its .cert and .sig, and zizmor's Linux wheel, each by its pinned address and checked by its
pinned SHA-256 before anything runs it, verifies Opengrep with that cosign against OPENGREP_IDENTITY exactly and the
issuer GitHub's token service, and takes zizmor's program out of its wheel, checked against its own pin. A program
whose pin is still empty has its measured SHA-256 printed and the build refused, so a first build reads it for the pin
and never ships it unpinned. Standard library only.
"""

from __future__ import annotations

# standard imports
import hashlib
import importlib.util
import stat
import subprocess
import sys
import types
import urllib.request
import zipfile
from pathlib import Path

# ======================================================================================================================
# Configuration
# ======================================================================================================================

# the pins each download needs, each of which must be filled before the build goes on
NEEDED = (
    "OPENGREP_ASSET",
    "OPENGREP_SHA256",
    "ZIZMOR_WHEEL_URL",
    "ZIZMOR_WHEEL_SHA256",
    "COSIGN_URL",
    "COSIGN_SHA256",
)
# where the wrapper sits, beside this file in the build stage, or one folder up in cicd's tree
WRAPPER_PLACES = ("kdf_scan.py", "../kdf_scan.py")
CHUNK          = 1 << 20

# ======================================================================================================================
# The fetch
# ======================================================================================================================

class FetchError(Exception):
    """
    A download, a hash or a signature that refuses the build.
    """


def load_pins(here: Path | None = None) -> types.ModuleType:
    """
    The wrapper, whose constants are every pin, loaded by its path with bytecode off.

    Args:
        here: the folder to look from, this file's when None

    Returns:
        types.ModuleType: the wrapper

    Raises:
        FetchError: when no wrapper sits beside this file or one folder up
    """
    base  = here or Path(__file__).resolve().parent
    found = next((base / place for place in WRAPPER_PLACES if (base / place).is_file()), None)
    if found is None:
        raise FetchError(f"no kdf_scan.py beside {base}")
    spec   = importlib.util.spec_from_file_location("kdf_scan_pins", found)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.dont_write_bytecode = True
    # registered before it runs, since its dataclasses find their module there
    spec.loader.exec_module(module)
    return module


def zizmor_member(pins: types.ModuleType) -> str:
    """
    The wheel's program, by its path inside the wheel's data folder.

    Args:
        pins: the wrapper's pins

    Returns:
        str: the member's path
    """
    return f"zizmor-{pins.ZIZMOR_VERSION}.data/scripts/zizmor"


def sha256_of(path: Path) -> str:
    """
    A file's SHA-256, read in chunks.

    Args:
        path: the file

    Returns:
        str: its hex digest
    """
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download(url: str, target: Path, pinned: str | None) -> Path:
    """
    One download by its pinned address over https alone, checked by its pinned SHA-256 when it has one.

    Args:
        url: the address
        target: where it lands
        pinned: its SHA-256, None for a .cert or .sig, which cosign's check vouches for

    Returns:
        Path: the file

    Raises:
        FetchError: when the address is not https or the hash differs
    """
    if not url.startswith("https://"):
        raise FetchError(f"{url} is not an https address")
    with urllib.request.urlopen(url, timeout = 120) as answer, open(target, "wb") as handle:  # noqa: S310 https alone
        for chunk in iter(lambda: answer.read(CHUNK), b""):
            handle.write(chunk)
    found = sha256_of(target)
    if pinned is not None and found != pinned:
        raise FetchError(f"{target.name} is {found}, not its pinned {pinned}")
    print(f"fetch     {target.name} sha256 {found}" + (" ok" if pinned else ""))
    return target


def executable(path: Path) -> None:
    """
    Make a fetched program runnable, by root's build alone.

    Args:
        path: the program
    """
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def verify_opengrep(pins: types.ModuleType, cosign: Path, asset: Path, out: Path) -> None:
    """
    Verify Opengrep's signature with cosign against the exact identity of the workflow that signed its release.

    Args:
        pins: the wrapper's pins
        cosign: the fetched cosign
        asset: the fetched asset
        out: the folder its .cert and .sig land in

    Raises:
        FetchError: when the signature does not verify
    """
    cert = download(f"{pins.OPENGREP_URL}.cert", out / "opengrep.cert", None)
    sig  = download(f"{pins.OPENGREP_URL}.sig", out / "opengrep.sig", None)
    done = subprocess.run(
        [
            str(cosign),
            "verify-blob",
            "--certificate",
            str(cert),
            "--signature",
            str(sig),
            "--certificate-identity",
            pins.OPENGREP_IDENTITY,
            "--certificate-oidc-issuer",
            pins.OPENGREP_ISSUER,
            str(asset),
        ],
        capture_output = True,
        text = True,
        check = False,
    )
    if done.returncode != 0:
        raise FetchError(f"cosign refused Opengrep's signature, {done.stderr.strip()[-300:]}")
    print(f"fetch     opengrep signature ok, {pins.OPENGREP_IDENTITY}")


def take_zizmor(pins: types.ModuleType, wheel: Path, target: Path) -> Path:
    """
    zizmor's program out of its wheel, checked against its own pin.

    Args:
        pins: the wrapper's pins
        wheel: the fetched wheel
        target: where the program lands

    Returns:
        Path: the program

    Raises:
        FetchError: when the wheel holds no program, its hash differs, or its pin is still empty
    """
    member = zizmor_member(pins)
    with zipfile.ZipFile(wheel) as archive:
        if member not in archive.namelist():
            raise FetchError(f"the wheel holds no {member}")
        target.write_bytes(archive.read(member))
    found = sha256_of(target)
    if not pins.ZIZMOR_SHA256:
        raise FetchError(f"ZIZMOR_SHA256 is empty, the program measured {found}, pin it and build again")
    if found != pins.ZIZMOR_SHA256:
        raise FetchError(f"zizmor is {found}, not its pinned {pins.ZIZMOR_SHA256}")
    print(f"fetch     zizmor {pins.ZIZMOR_VERSION} sha256 {found} ok")
    return target


def main(argv: list[str] | None = None, pins: types.ModuleType | None = None) -> int:
    """
    Fetch and check every tool into one folder, which the image's last stage copies.

    Args:
        argv: the folder, sys.argv when None
        pins: the wrapper's pins, loaded from beside this file when None

    Returns:
        int: 0 when every check passed, 1 when one refused the build
    """
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("fetch     usage, fetch.py <out folder>")
        return 1
    out = Path(args[0])
    out.mkdir(parents = True, exist_ok = True)
    try:
        pins = pins or load_pins()
    except FetchError as error:
        print(f"fetch     refused, {error}")
        return 1
    empty = [name for name in NEEDED if not getattr(pins, name)]
    if empty:
        print(f"fetch     refused, owner step 3 has not filled {', '.join(empty)}")
        return 1
    try:
        cosign = download(pins.COSIGN_URL, out / "cosign", pins.COSIGN_SHA256)
        executable(cosign)
        asset = download(pins.OPENGREP_URL, out / "opengrep", pins.OPENGREP_SHA256)
        verify_opengrep(pins, cosign, asset, out)
        executable(asset)
        wheel = download(pins.ZIZMOR_WHEEL_URL, out / "zizmor.whl", pins.ZIZMOR_WHEEL_SHA256)
        executable(take_zizmor(pins, wheel, out / "zizmor"))
    except (FetchError, OSError) as error:
        print(f"fetch     refused, {error}")
        return 1
    for name in ("cosign", "opengrep.cert", "opengrep.sig", "zizmor.whl"):
        (out / name).unlink()
    return 0


if __name__ == "__main__":
    sys.exit(main())
