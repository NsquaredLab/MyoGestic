"""Output interface registry — pre-wired (process, output stream, control).

The ``InterfaceSpec`` dataclass and ``virtual_hand()`` constructor hold the VHI
boilerplate — Godot path, outlet name + channel count + sample rate, control
stream names — behind a single call:

    from myogestic.vhi.interfaces import virtual_hand

    vhi = virtual_hand()
    vhi_outlet = vhi.outlet()           # 9-ch LSLOutlet @ 32 Hz
    process_launcher(vhi.launcher())    # the packaged binary or `godot --path`
    client = vhi.control_client()       # gRPC control plane: declare, command, discover

The example still owns *what* to push through the outlet — DOF mapping, sign
flips, smoothing.

VHI ships in two ways and ``virtual_hand()`` accepts both:

* **Packaged binary** (the default), installed by
  ``python -m myogestic.tools.install_vhi`` or the ``myogestic-install-vhi``
  console script. Launched directly.
* **Godot source project** (for VHI development). Launched via
  ``godot --path <project>``.
"""

from __future__ import annotations

import logging
import os
import platform
from dataclasses import dataclass
from pathlib import Path
from shutil import which
from typing import TYPE_CHECKING

from myogestic.outputs import LSLOutlet

if TYPE_CHECKING:
    from myogestic.vhi._control import VhiControlClient
    from myogestic.vhi._recording import VhiRecordingClient

#: Kept in step with `myogestic.tools.install_vhi.MIN_VHI_TAG` (asserted equal by
#: tests/test_install_vhi_version_gate.py). Duplicated rather than imported: the
#: installer pulls in typer, which launching a process should not require.
log = logging.getLogger("myogestic.vhi")

MIN_VHI_TAG = "v2.0.0"


def _version_of(tag: str) -> tuple[int, ...] | None:
    """The numeric part of a release tag, or None if it is not a version at all."""
    cleaned = tag.lstrip("vV").split("-")[0].split("+")[0]
    parts = cleaned.split(".")
    if not parts or not all(part.isdigit() for part in parts):
        return None
    return tuple(int(part) for part in parts)


@dataclass
class InterfaceSpec:
    """Description of an external visual-feedback interface (e.g. VHI).

    Attributes
    ----------
    name
        Human label, used as the process_launcher row title.
    process
        argv to spawn the interface (passed to ``subprocess.Popen``).
        An empty list means "VHI not installed"; ``launcher()`` then raises
        pointing at ``install_vhi``.
    output_stream_name
        LSL outlet name the interface listens on.
    n_output_channels
        Number of channels in the output vector.
    output_hz
        Outlet send rate.
    control_stream_name
        LSL inlet name the interface publishes when the user drives it
        manually (used for regression targets). May be None.
    n_control_channels
        Channel count of the control stream, if known.
    control_pose_stream_name
        LSL *outlet* name for streaming a continuous pose TO the interface's
        control hand — opposite direction to ``control_stream_name``. Consumed
        only when VHI is in STREAM control mode.
    n_control_pose_channels
        Channel count of the control-pose outlet.
    control_pose_hz
        Send rate of the control-pose outlet.
    grpc_host
        VHI gRPC control-server host.
    grpc_port
        VHI gRPC control-server port.
    install_root
        The directory ``process`` was resolved from; quoted in the
        "not installed" error.

    Examples
    --------
    >>> from myogestic.vhi.interfaces import InterfaceSpec
    >>> spec = InterfaceSpec(
    ...     name="Hand",
    ...     process=["vhi"],
    ...     output_stream_name="Pose",
    ...     n_output_channels=9,
    ...     output_hz=32.0,
    ... )
    >>> spec.launcher()
    [('Hand', ['vhi'])]
    """

    name: str
    process: list[str]
    output_stream_name: str
    n_output_channels: int
    output_hz: float
    control_stream_name: str | None = None
    n_control_channels: int | None = None
    control_pose_stream_name: str | None = None
    n_control_pose_channels: int | None = None
    control_pose_hz: float | None = None
    grpc_host: str = "127.0.0.1"
    grpc_port: int = 50051
    install_root: Path | None = None

    def outlet(
        self,
        *,
        n_channels: int | None = None,
    ) -> LSLOutlet:
        """Construct an LSLOutlet matching this interface's output stream.

        Carries a stable ``source_id`` so a consumer can re-resolve this stream
        after a restart. Without one, LSL cannot tell a restarted outlet from a
        new stream and a consumer that resolved the old one keeps a dead inlet.

        Parameters
        ----------
        n_channels
            Override the interface's declared width — e.g. to carry only the
            controls one configuration drives, rather than the renderer's full
            pose layout.

        """
        return LSLOutlet(
            name=self.output_stream_name,
            n_channels=self.n_output_channels if n_channels is None else n_channels,
            hz=self.output_hz,
            source_id=f"myogestic:{self.name}:{self.output_stream_name}",
        )

    def control_client(self) -> VhiControlClient:
        """Construct a client for this interface's control service.

        Hand it to `myogestic.vhi.VhiTarget` and the target asks VHI which named
        DOFs it renders, refusing a configuration it cannot place. Required: without
        one there is nothing to negotiate the control space against.

        Imported lazily — a plain install has no ``[grpc]`` extra, and
        `outlet` / `launcher` must keep working without it.

        Examples
        --------
        >>> from myogestic.controls import ControlBus, Continuous, ControlSet
        >>> from myogestic.vhi import VhiTarget, virtual_hand
        >>>
        >>> vhi = virtual_hand()
        >>> controls = ControlSet(dofs={"my_index": Continuous("my_index")})
        >>> target = VhiTarget(vhi.outlet(), client=vhi.control_client())
        >>> bus = ControlBus(controls, targets=[target])
        >>> target.negotiated          # True once VHI has answered, False until then
        False
        """
        from myogestic.vhi._control import VhiControlClient

        return VhiControlClient(host=self.grpc_host, port=self.grpc_port)

    def recording_client(self) -> VhiRecordingClient:
        """Construct a client for this interface's recording session gate.

        Not a control plane, and nothing it does is a control DOF. It carries the two
        things a *recording session* needs: the gate that stops VHI's local keyboard
        competing as a movement source, and trajectories that cycle the control hand
        so the recorded kinematics sweep a continuous range.

        Imported lazily, like the other gRPC client, so a plain install without the
        ``[grpc]`` extra can still use `outlet` / `launcher`.

        Examples
        --------
        >>> from myogestic.vhi import virtual_hand
        >>> aid = virtual_hand().recording_client()
        >>> aid.set_recording_session(True)     # False when VHI is unreachable
        False
        """
        from myogestic.vhi._recording import VhiRecordingClient

        return VhiRecordingClient(host=self.grpc_host, port=self.grpc_port)

    def control_outlet(
        self,
        *,
        n_channels: int | None = None,
    ) -> LSLOutlet:
        """Construct an [`LSLOutlet`][] for streaming a continuous pose to the control hand.

        Only consumed when VHI is put in STREAM control mode via a declared
        control-pose stream (`control_client().declare(..., control_pose=True)`).
        Raises [`ValueError`][] if this interface has no control-pose stream
        configured.

        `n_channels` means what it means on `outlet`.
        """
        if self.control_pose_stream_name is None:
            raise ValueError(f"{self.name}: no control_pose_stream_name configured")
        default_width = self.n_control_pose_channels or self.n_output_channels
        return LSLOutlet(
            name=self.control_pose_stream_name,
            n_channels=default_width if n_channels is None else n_channels,
            hz=self.control_pose_hz or self.output_hz,
            source_id=f"myogestic:{self.name}:{self.control_pose_stream_name}",
        )

    def launcher(self) -> list[tuple[str, list[str]]]:
        """Return the (name, argv) tuple list expected by `process_launcher`.

        Raises ``FileNotFoundError`` with an ``install_vhi`` hint when VHI
        is not installed at the resolved location.
        """
        if not self.process:
            location = f" at {self.install_root}" if self.install_root else ""
            raise FileNotFoundError(
                f"{self.name}: not installed{location}.\n"
                f"  Run `python -m myogestic.tools.install_vhi` to fetch a release "
                f"for this platform ({MIN_VHI_TAG} or newer).\n"
                f"  Or set $VHI_PATH to an existing VHI Godot project and "
                f"$GODOT_BIN to a Godot 4.x binary for source-mode."
            )
        self._refuse_an_incompatible_install()
        return [(self.name, list(self.process))]

    def launchable(self) -> list[tuple[str, list[str]]]:
        """Like `launcher`, but empty instead of raising when nothing can be launched.

        For a `myogestic.widgets.ProcessLauncher` in an application's own UI, where an
        in-app Launch button is a *convenience*: `launcher` raising there takes the whole
        app down at import, even when a renderer is already running. This returns no rows
        and logs why instead. `launcher` stays strict for a caller whose entire job is to
        start the thing (`tools/launch_vhi.py`).

        Examples
        --------
        >>> from myogestic.vhi import virtual_hand
        >>> processes = virtual_hand().launchable()   # [] rather than an exception
        """
        try:
            return self.launcher()
        except FileNotFoundError as exc:
            log.info("%s cannot be launched from this app: %s", self.name, exc)
            return []

    def _refuse_an_incompatible_install(self) -> None:
        """Refuse to launch an installed release this MyoGestic cannot drive.

        The marker `install_vhi` leaves behind is the only way to know what is on disk
        before starting it, so the check happens here rather than after the renderer
        comes up and every `VhiTarget` refuses it.

        Silent when there is no marker: a source-mode checkout has none, and neither
        does a hand-placed build.
        """
        if not self.install_root:
            return
        marker = Path(self.install_root) / "vhi-version.txt"
        try:
            text = marker.read_text()
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
            f"{self.name}: the installed release is {tag}, which does not serve the v2 "
            f"control contract.\n"
            f"  MyoGestic 2.x asks the renderer which controls it exports and refuses "
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


# --- Concrete interfaces ----------------------------------------------------


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
    An ``InterfaceSpec`` with the resolved argv, ready to wire into
    ``process_launcher()``.

    Examples
    --------
    >>> from myogestic.vhi.interfaces import virtual_hand
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
        output_stream_name="MyoGestic_Output",
        n_output_channels=9,
        output_hz=32.0,
        control_stream_name="VHI_Control",
        n_control_channels=9,
        control_pose_stream_name="MyoGestic_ControlPose",
        n_control_pose_channels=9,
        control_pose_hz=32.0,
        grpc_host=grpc_host,
        grpc_port=grpc_port,
        install_root=install_root,
    )


__all__ = ["InterfaceSpec", "virtual_hand"]
