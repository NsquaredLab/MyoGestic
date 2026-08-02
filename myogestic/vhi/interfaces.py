"""Where the Virtual Hand is, how to start it, and whether this MyoGestic can drive it.

``virtual_hand()`` is a `myogestic.remote.InterfaceSpec` with VHI's numbers filled in
— the Godot path or packaged binary, the nine-channel pose read-back, the gRPC endpoint
— so an application never states any of them:

    from myogestic.controls import connect_controls
    from myogestic.remote import RemoteTarget
    from myogestic.vhi import virtual_hand

    vhi = virtual_hand()
    process_launcher(vhi.launcher())    # the packaged binary or `godot --path`
    client = vhi.control_client()       # gRPC control plane: discover, command, verify
    target = RemoteTarget(client=client, interface=vhi)  # one stream per control driven
    bus = connect_controls(control_map, [target])

Everything past that call is generic — nothing in `myogestic.remote` knows a hand from
a robot arm, and the example still owns *what* to push.

VHI ships in two ways and ``virtual_hand()`` accepts both:

* **Packaged binary** (the default), installed by
  ``python -m myogestic.tools.install_vhi`` or the ``myogestic-install-vhi``
  console script. Launched directly.
* **Godot source project** (for VHI development). Launched via
  ``godot --path <project>``.
"""

from __future__ import annotations

import os
import platform
from functools import partial
from pathlib import Path
from shutil import which

from myogestic.remote import InterfaceSpec

#: Kept in step with `myogestic.tools.install_vhi.MIN_VHI_TAG` (asserted equal by
#: tests/test_install_vhi_version_gate.py). Duplicated rather than imported: the
#: installer pulls in typer, which launching a process should not require.
MIN_VHI_TAG = "v2.0.0"

#: Appended to `myogestic.remote.InterfaceSpec.launcher`'s "not installed" error.
#: How VHI is installed is VHI's business; the generic spec has nothing to say about it.
_INSTALL_HINT = (
    f"\n  Run `python -m myogestic.tools.install_vhi` to fetch a release "
    f"for this platform ({MIN_VHI_TAG} or newer).\n"
    f"  Or set $VHI_PATH to an existing VHI Godot project and "
    f"$GODOT_BIN to a Godot 4.x binary for source-mode."
)


def _version_of(tag: str) -> tuple[int, ...] | None:
    """The numeric part of a release tag, or None if it is not a version at all."""
    cleaned = tag.lstrip("vV").split("-")[0].split("+")[0]
    parts = cleaned.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


def _refuse_an_incompatible_install(install_root: Path | None) -> None:
    """Refuse to launch an installed release this MyoGestic cannot drive.

    The marker `install_vhi` leaves behind is the only way to know what is on disk
    before starting it, so the check happens at launch rather than after VHI
    comes up and every `myogestic.remote.RemoteTarget` refuses it.

    Silent when there is no marker: a source-mode checkout has none, and neither
    does a hand-placed build.

    Parameters
    ----------
    install_root
        Where the release was unpacked, or ``None`` when nothing installed it.

    Raises
    ------
    FileNotFoundError
        When the marker names a release older than `MIN_VHI_TAG`.
    """
    if not install_root:
        return
    marker = Path(install_root) / "vhi-version.txt"
    try:
        text = marker.read_text(encoding="utf-8")
    except OSError:
        return
    tag = ""
    for line in text.splitlines():
        if line.startswith("installed_tag="):
            tag = line.partition("=")[2].strip()
    version = _version_of(tag)
    if version is None or version >= _version_of(MIN_VHI_TAG):
        return
    raise FileNotFoundError(
        f"VHI Hand: the installed release is {tag}, which does not serve the v2 "
        f"control contract.\n"
        f"  MyoGestic 2.x asks the target which controls it exports and refuses "
        f"to guess, so this build cannot be driven at all.\n"
        f"  Upgrade: python -m myogestic.tools.install_vhi --tag {MIN_VHI_TAG} --force\n"
        f"  Or run a checkout from source: set $VHI_PATH and $GODOT_BIN."
    )


# --- Launch resolution -------------------------------------------------------


def _user_data_root() -> Path:
    """Per-user data root for VHI when not in a writable git checkout.

    Uses ``platformdirs`` when available: ``~/Library/Application Support`` on
    macOS, ``%LOCALAPPDATA%`` on Windows, ``$XDG_DATA_HOME`` / ``~/.local/share``
    on Linux. The hand-rolled fallback keeps this importable without the dep.
    """
    try:
        import platformdirs

        return Path(platformdirs.user_data_dir("myogestic"))
    except ImportError:  # pragma: no cover — stripped-down installs
        sysname = platform.system()
        if sysname == "Darwin":
            base = Path.home() / "Library" / "Application Support"
        elif sysname == "Windows":
            base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
        else:
            base = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share"))
        return base / "myogestic"


def _default_install_root() -> Path:
    """Default location to look for / install VHI.

    1. ``<repo>/tools/MyoGestic-VHI`` when running from a writable git
       checkout — keeps the install visible next to the source; gitignored.
    2. ``<user_data>/myogestic/vhi`` otherwise — survives venv churn for
       pip-installed users.
    """
    # this file lives at <repo>/myogestic/vhi/interfaces.py → three parents up
    repo_root = Path(__file__).resolve().parent.parent.parent
    if (repo_root / ".git").exists() and os.access(repo_root, os.W_OK):
        return repo_root / "tools" / "MyoGestic-VHI"
    return _user_data_root() / "vhi"


def _installed_binary(install_root: Path) -> Path | None:
    """Return the platform-appropriate VHI binary inside `install_root`, or None.

    Names match exactly what ``install_vhi`` unpacks for each platform.
    """
    sysname = platform.system()
    if sysname == "Darwin":
        binary = install_root / "VHI.app" / "Contents" / "MacOS" / "Virtual Hand Interface"
    elif sysname == "Linux":
        binary = install_root / "VHI.x86_64"
    elif sysname == "Windows":
        binary = install_root / "VHI.exe"
    else:
        return None
    return binary if binary.exists() else None


def _resolve_godot_bin(godot_bin: str | None) -> str | None:
    """Find a Godot binary for source-mode launch.

    Order: explicit kwarg → ``$GODOT_BIN`` → ``which("godot4")`` /
    ``which("godot")`` → platform-specific GUI default
    (``/Applications/Godot.app`` on macOS).
    """
    if godot_bin:
        return godot_bin
    env = os.environ.get("GODOT_BIN")
    if env:
        return env
    for name in ("godot4", "godot"):
        found = which(name)
        if found:
            return found
    if platform.system() == "Darwin":
        mac_default = "/Applications/Godot.app/Contents/MacOS/Godot"
        if Path(mac_default).exists():
            return mac_default
    return None


def _resolve_vhi_launch(install_root: Path, godot_bin: str | None, mode: str) -> list[str]:
    """Pick (binary or Godot source) launch argv for VHI in ``install_root``.

    Parameters
    ----------
    install_root
        Directory containing either a packaged binary
        (``VHI.app`` / ``VHI.exe`` / ``VHI.x86_64``) or a Godot source
        project (``project.godot``).
    godot_bin
        Explicit override for the Godot binary path. ``None`` means
        "auto-detect via $GODOT_BIN, PATH, then platform default".
    mode
        ``"binary"``, ``"godot"``, or ``"auto"``. In auto, an explicit
        ``godot_bin`` argument or ``$GODOT_BIN`` env var signals "use
        Godot source"; otherwise prefer the packaged binary, falling
        back to source if no binary is installed but a project is.

    Returns
    -------
    argv ready for ``Popen``; empty list when VHI isn't installed.
    """
    binary = _installed_binary(install_root)
    has_project = (install_root / "project.godot").exists()

    if mode == "binary":
        return [str(binary)] if binary else []
    if mode == "godot":
        if not has_project:
            return []
        godot = _resolve_godot_bin(godot_bin)
        return [godot, "--path", str(install_root)] if godot else []

    # auto
    user_signalled_godot = godot_bin is not None or "GODOT_BIN" in os.environ
    if binary and not user_signalled_godot:
        return [str(binary)]
    if has_project:
        godot = _resolve_godot_bin(godot_bin)
        if godot:
            return [godot, "--path", str(install_root)]
    return [str(binary)] if binary else []


# --- The Virtual Hand -------------------------------------------------------


def virtual_hand(
    godot_bin: str | None = None,
    vhi_path: str | None = None,
    grpc_host: str | None = None,
    grpc_port: int | None = None,
    launch_mode: str | None = None,
) -> InterfaceSpec:
    """The MyoGestic Virtual Hand Interface (VHI).

    Parameters
    ----------
    godot_bin
        Path to the Godot binary, for source-mode launch. Falls
        back to ``$GODOT_BIN``, then ``which("godot4")`` /
        ``which("godot")``, then platform GUI defaults.
    vhi_path
        Directory containing VHI (binary install OR Godot project).
        Falls back to ``$VHI_PATH``, then the default install root —
        ``<repo>/tools/MyoGestic-VHI`` in a git checkout, otherwise
        ``<user_data>/myogestic/vhi``.
    grpc_host
        VHI gRPC host. Falls back to ``$VHI_GRPC_HOST`` then
        ``127.0.0.1``.
    grpc_port
        VHI gRPC port. Falls back to ``$VHI_GRPC_PORT`` then
        ``50051``.
    launch_mode
        Launch mode — ``"binary"``, ``"godot"``, or ``"auto"`` (default).
        Also reads ``$VHI_LAUNCH_MODE``. Explicit ``launch_mode`` always wins.

    Returns
    -------
    A `myogestic.remote.InterfaceSpec` with the resolved argv, ready to wire into
    ``process_launcher()``.

    Examples
    --------
    >>> from myogestic.vhi import virtual_hand
    >>> vhi = virtual_hand()
    >>> vhi.n_output_channels
    9
    """
    install_root = Path(vhi_path or os.environ.get("VHI_PATH") or _default_install_root())
    launch_mode = launch_mode or os.environ.get("VHI_LAUNCH_MODE", "auto")
    if launch_mode not in ("auto", "binary", "godot"):
        raise ValueError(f"launch_mode must be 'auto', 'binary', or 'godot'; got {launch_mode!r}")
    grpc_host = grpc_host or os.environ.get("VHI_GRPC_HOST", "127.0.0.1")
    if grpc_port is None:
        grpc_port = int(os.environ.get("VHI_GRPC_PORT", "50051"))

    process = _resolve_vhi_launch(install_root, godot_bin, launch_mode)

    return InterfaceSpec(
        name="VHI Hand",
        process=process,
        n_output_channels=9,
        output_hz=32.0,
        control_stream_name="VHI_Control",
        n_control_channels=9,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        install_root=install_root,
        install_hint=_INSTALL_HINT,
        version_gate=partial(_refuse_an_incompatible_install, install_root),
    )


__all__ = ["virtual_hand"]
