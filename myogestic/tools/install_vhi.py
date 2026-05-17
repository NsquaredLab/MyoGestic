"""Install the Virtual Hand Interface release binary for this platform.

VHI ships pre-built artifacts on every release at
https://github.com/NsquaredLab/MyoGestic-VHI/releases. This CLI picks the
right asset for the host OS/arch, downloads it, unpacks it into the location
``virtual_hand()`` looks at, and drops a ``vhi-version.txt`` marker so a
later install knows what's already there.

Usage:
    python -m myogestic.tools.install_vhi                # latest, default dest
    python -m myogestic.tools.install_vhi --tag v1.0.0   # pinned version
    python -m myogestic.tools.install_vhi --dest /custom/path
    python -m myogestic.tools.install_vhi --force        # reinstall over existing

Or after ``pip install myogestic``:
    myogestic-install-vhi

Pin ``--tag`` in production: ``latest`` is convenient for a fresh checkout but
not reproducible — a downstream rebuild months later may pick up a different
VHI version with subtly different behaviour.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

REPO = "NsquaredLab/MyoGestic-VHI"

# (system, machine) → release asset. Darwin/x86_64 is deliberately absent:
# only an arm64 macOS build is shipped, and Rosetta translates x86_64 → arm64,
# NOT the reverse, so the arm64 binary cannot run on Intel Macs. See
# https://support.apple.com/en-ie/guide/security/secebb113be1/web
ASSETS = {
    ("Darwin", "arm64"): "VHI-macos-arm64.zip",
    ("Linux", "x86_64"): "VHI-linux-x64.tar.gz",
    ("Windows", "AMD64"): "VHI-windows-x64.zip",
    ("Windows", "x86_64"): "VHI-windows-x64.zip",
}

# Top-level entries that mark a successful install. After unpack we look for
# at least one of these in the staging dir — protects against malformed
# archives that extract to an unexpected layout.
INSTALL_MARKERS = ("VHI.app", "VHI.exe", "VHI.x86_64")

# Paths inside the install whose executable bit must be set. ZIP archives
# don't preserve POSIX permission bits reliably, so we restore +x explicitly
# after extraction. (tar archives preserve them — this is a no-op for Linux.)
EXEC_PATHS = {
    "Darwin": ["VHI.app/Contents/MacOS/Virtual Hand Interface"],
    "Linux": ["VHI.x86_64"],
    "Windows": [],
}


def _default_dest() -> Path:
    """Mirror ``myogestic.interfaces._default_install_root()`` so both agree."""
    from myogestic.interfaces import _default_install_root

    return _default_install_root()


def _resolve_asset() -> str:
    """Choose the release asset for this host. Refuses unsupported combos."""
    sysname = platform.system()
    machine = platform.machine()
    name = ASSETS.get((sysname, machine))
    if name:
        return name
    msg = f"No VHI release artifact for {sysname}/{machine}."
    if sysname == "Darwin" and machine in ("x86_64", "i386"):
        msg += (
            " VHI ships an Apple Silicon (arm64) build only; Rosetta cannot "
            "run arm64 binaries on Intel Macs. Use a different machine, or "
            "run VHI from the Godot source project (set $VHI_PATH + $GODOT_BIN)."
        )
    elif sysname == "Linux" and machine in ("aarch64", "arm64"):
        msg += " VHI ships x86_64 Linux only — no aarch64 build available."
    raise SystemExit(msg)


def _download_url(tag: str, asset: str) -> str:
    if tag == "latest":
        return f"https://github.com/{REPO}/releases/latest/download/{asset}"
    return f"https://github.com/{REPO}/releases/download/{tag}/{asset}"


def _fetch_release_digest(tag: str, asset: str) -> str | None:
    """Fetch the SHA-256 hex digest for ``asset`` at ``tag`` from the GitHub API.

    GitHub publishes ``assets[].digest`` (``"sha256:<hex>"``) in every release
    payload — used by ``install_vhi`` to integrity-check the downloaded zip
    against the value GitHub computed at upload time. No coordination with
    VHI's release pipeline required.

    Returns the hex digest (no ``sha256:`` prefix), or ``None`` if the API is
    unreachable, the tag doesn't exist, or the asset has no digest.
    """
    if tag == "latest":
        url = f"https://api.github.com/repos/{REPO}/releases/latest"
    else:
        url = f"https://api.github.com/repos/{REPO}/releases/tags/{tag}"
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json"},
    )
    try:
        with urllib.request.urlopen(req) as response:
            data = json.load(response)
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        print(
            f"  WARNING: could not fetch release metadata ({exc}). "
            f"Skipping checksum verification.",
            file=sys.stderr,
        )
        return None
    for entry in data.get("assets", []):
        if entry.get("name") != asset:
            continue
        digest = entry.get("digest", "")
        if digest.startswith("sha256:"):
            return digest.removeprefix("sha256:")
    return None


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _verify(archive: Path, expected: str | None) -> None:
    """Compare the on-disk archive's SHA-256 against the expected digest.

    Aborts the install on mismatch — a tampered or corrupted artifact must
    never reach the unpack step. ``expected=None`` (digest unavailable from
    the API) downgrades to a warning instead of an error; the warning is
    intentional so it isn't silently masked.
    """
    if expected is None:
        print(
            "  WARNING: no SHA-256 digest published for this release — "
            "downloaded archive was NOT integrity-checked.",
            file=sys.stderr,
        )
        return
    print(f"  verifying SHA-256...")
    actual = _sha256(archive)
    if actual != expected:
        raise SystemExit(
            f"Checksum mismatch — refusing to install.\n"
            f"  expected: sha256:{expected}\n"
            f"  got:      sha256:{actual}\n"
            f"  archive:  {archive}\n"
            f"This could indicate a corrupted download or a tampered asset. "
            f"Try again; if the mismatch persists, file an issue."
        )
    print(f"    ✓ sha256:{expected[:16]}...")


def _download(url: str, dest_archive: Path) -> None:
    print(f"  ↓ {url}")
    with urllib.request.urlopen(url) as response:
        total = int(response.headers.get("Content-Length") or 0)
        chunk = 1024 * 1024  # 1 MiB
        downloaded = 0
        with open(dest_archive, "wb") as out:
            while True:
                buf = response.read(chunk)
                if not buf:
                    break
                out.write(buf)
                downloaded += len(buf)
                if total:
                    pct = downloaded * 100 / total
                    print(
                        f"\r    {downloaded / 1_048_576:.1f}/"
                        f"{total / 1_048_576:.1f} MiB ({pct:.0f}%)",
                        end="",
                        flush=True,
                    )
        if total:
            print()


def _unpack(archive: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(target)
    elif archive.name.endswith(".tar.gz") or archive.name.endswith(".tgz"):
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(target)
    else:
        raise SystemExit(f"Unknown archive type: {archive.name}")


def _validate(target: Path) -> None:
    for marker in INSTALL_MARKERS:
        if (target / marker).exists():
            return
    raise SystemExit(
        f"Extracted archive does not contain any of {INSTALL_MARKERS} at "
        f"top level of {target}. The release asset may be malformed."
    )


def _restore_exec_bits(target: Path) -> None:
    """ZIPs lose Unix +x — restore it on the launched binary."""
    for rel in EXEC_PATHS.get(platform.system(), []):
        path = target / rel
        if path.exists():
            mode = path.stat().st_mode
            path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def _strip_quarantine(target: Path) -> None:
    """Remove macOS Gatekeeper's `com.apple.quarantine` xattr so the .app launches.

    Loud on purpose: this is security-sensitive (we're trusting the
    GitHub-hosted artifact), and the user should see it happen rather than
    have it done silently.
    """
    if platform.system() != "Darwin":
        return
    app = target / "VHI.app"
    if not app.exists():
        return
    print(f"  removing com.apple.quarantine xattr from {app}")
    subprocess.run(
        ["xattr", "-rd", "com.apple.quarantine", str(app)], check=False
    )


def _macos_gatekeeper_note(target: Path) -> None:
    """Print the macOS-specific "what to do when Gatekeeper blocks it" notice.

    VHI's .app is ad-hoc signed (no Apple Developer ID, no notarization), so
    macOS will block it when launched via Finder / `open`. The block does NOT
    fire when MyoGestic launches it via process_launcher (subprocess.Popen
    bypasses LaunchServices) - so for the integrated workflow this is a
    non-issue. The note is for users who try to double-click the app.
    """
    if platform.system() != "Darwin":
        return
    app = target / "VHI.app"
    if not app.exists():
        return
    print()
    print(
        "macOS note: VHI is ad-hoc signed (not Apple-notarised). Launching via\n"
        "MyoGestic's process_launcher works directly. To launch manually from\n"
        "Finder / `open`, do this once:\n"
        "  1. Double-click VHI.app — macOS will refuse to open it.\n"
        "  2. System Settings → Privacy & Security → 'Open Anyway' under the\n"
        "     blocked-app notice. (On macOS 14 and earlier: right-click → Open\n"
        "     also works.)\n"
        "  3. Subsequent launches via Finder will succeed."
    )


def _write_marker(target: Path, tag: str, asset: str) -> None:
    (target / "vhi-version.txt").write_text(
        f"installed_tag={tag}\n"
        f"asset={asset}\n"
        f"platform={platform.system()}/{platform.machine()}\n"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="myogestic-install-vhi",
        description="Install a MyoGestic-VHI release binary for this platform.",
    )
    parser.add_argument(
        "--tag",
        default="latest",
        help="Release tag, e.g. 'v1.0.0' (default: 'latest'). Pin in "
        "production for reproducible installs.",
    )
    parser.add_argument(
        "--dest",
        type=Path,
        default=None,
        help="Install directory (default: matches `virtual_hand()`'s install "
        "root — repo `tools/MyoGestic-VHI` in a git checkout, else a per-user "
        "data dir).",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Reinstall over an existing VHI install. Refuses by default to "
        "avoid clobbering an unrelated directory.",
    )
    parser.add_argument(
        "--no-verify",
        action="store_true",
        help="Skip SHA-256 verification against the GitHub release digest. "
        "Default is to verify; disable only if you know what you're doing.",
    )
    args = parser.parse_args(argv)

    dest = args.dest or _default_dest()
    asset = _resolve_asset()
    url = _download_url(args.tag, asset)

    print(f"Installing VHI {args.tag} → {dest}")

    if dest.exists() and any(dest.iterdir()):
        looks_like_previous_install = any(
            (dest / m).exists() for m in INSTALL_MARKERS
        )
        if not args.force:
            hint = (
                "Use --force to reinstall."
                if looks_like_previous_install
                else "It does not look like a previous VHI install; refusing "
                "to clobber. Use --force or pass --dest to a fresh directory."
            )
            print(f"{dest} is non-empty. {hint}", file=sys.stderr)
            return 1
        if not looks_like_previous_install:
            print(
                f"WARNING: --force on a directory that does not look like a "
                f"previous VHI install ({dest}).",
                file=sys.stderr,
            )

    # Fetch the expected digest before download so a missing-tag-on-API error
    # surfaces immediately, not after a 150 MB download.
    expected_digest = None if args.no_verify else _fetch_release_digest(args.tag, asset)

    # Atomic install: stage in a temp dir, validate, then swap with dest.
    # A failed download or malformed archive never leaves a half-installed
    # dest behind. Checksum verification happens before unpack — a tampered
    # archive never reaches the file extraction step.
    with tempfile.TemporaryDirectory(prefix="myogestic-vhi-") as tmp:
        tmp_path = Path(tmp)
        archive = tmp_path / asset
        _download(url, archive)
        if not args.no_verify:
            _verify(archive, expected_digest)
        staging = tmp_path / "staging"
        _unpack(archive, staging)
        _validate(staging)
        _restore_exec_bits(staging)
        _write_marker(staging, args.tag, asset)

        if dest.exists():
            shutil.rmtree(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # `shutil.move` falls back to copy+rmtree across filesystems where
        # plain rename() fails with EXDEV — temp dirs are often on a
        # different mount than the install target.
        shutil.move(str(staging), str(dest))

    _strip_quarantine(dest)
    print(f"✓ VHI {args.tag} installed at {dest}")
    _macos_gatekeeper_note(dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
