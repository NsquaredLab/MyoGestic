"""What a remote target is, to MyoGestic: a process, some streams, and a control endpoint.

``InterfaceSpec`` is the whole description. It says how to start the target (or that
nothing starts it, when someone else does), how to build a stream for one of its
controls, and where its gRPC control plane listens. Nothing in it is device-specific:

    from myogestic.controls import connect_controls
    from myogestic.remote import InterfaceSpec, RemoteTarget

    rig = InterfaceSpec(name="rig", process=[], n_output_channels=1, output_hz=32.0)
    client = rig.control_client()       # gRPC control plane: discover, command, verify
    target = RemoteTarget(client=client, interface=rig)  # one stream per control driven
    bus = connect_controls(control_map, [target])

What it does *not* hold is a stream name: which controls the target has comes from the
manifest a running target answers with, and each control's stream is named for that
control's own address.

`myogestic.vhi.virtual_hand` is one of these with the Virtual Hand's numbers filled in
and a Godot path resolved — the same object every other remote target builds by hand.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from myogestic.outputs import LSLOutlet

if TYPE_CHECKING:
    from collections.abc import Callable

    from myogestic.remote._control import RemoteClient
    from myogestic.remote._recording import RecordingClient

log = logging.getLogger("myogestic.remote")


@dataclass
class InterfaceSpec:
    """Description of a remote target — a separate process MyoGestic drives.

    Attributes
    ----------
    name
        Human label, used as the process_launcher row title.
    process
        argv to spawn the target (passed to ``subprocess.Popen``).
        An empty list means "nothing here launches it": either it is not installed,
        or you start it yourself. ``launcher()`` then raises, quoting `install_hint`.
    n_output_channels
        Number of channels in the target's full pose vector — the width of the
        whole-pose read-back a recording consumes, not of a control's own stream.
    output_hz
        Outlet send rate.
    control_stream_name
        LSL inlet name the target publishes when the user drives it manually
        (used for regression targets). May be None.
    n_control_channels
        Channel count of the control stream, if known.
    grpc_host
        Host the target's gRPC control server listens on.
    grpc_port
        Port the target's gRPC control server listens on.
    install_root
        The directory ``process`` was resolved from; quoted in the
        "not installed" error.
    install_hint
        Appended to that error. How *this* target is installed is the target's
        own business — an installer command, an environment variable — and a generic
        spec has nothing useful to say about it.
    version_gate
        Called by `launcher` just before returning argv, to refuse an installed build
        this MyoGestic cannot drive. Whatever the check is, it is the target's: it
        reads a marker only that target leaves behind. ``None`` means there is
        nothing on disk to check, which is the honest default for a target MyoGestic
        did not install.
    min_target_version
        Oldest build of this target known to behave, checked against the
        ``target_version`` a *running* target reports in its manifest — so it covers
        what `version_gate` cannot: a build launched by hand, unpacked without a
        marker, or run from source. A build reporting an older version is refused on
        the same path as a vocabulary mismatch; one reporting nothing (builds
        predating the field, third-party targets) is warned about once and driven
        anyway. ``None`` means no opinion, the honest default for a target whose
        release history this spec does not know.

    Examples
    --------
    >>> from myogestic.remote import InterfaceSpec
    >>> spec = InterfaceSpec(
    ...     name="Hand",
    ...     process=["vhi"],
    ...     n_output_channels=9,
    ...     output_hz=32.0,
    ... )
    >>> spec.launcher()
    [('Hand', ['vhi'])]
    """

    name: str
    process: list[str]
    n_output_channels: int
    output_hz: float
    control_stream_name: str | None = None
    n_control_channels: int | None = None
    grpc_host: str = "127.0.0.1"
    grpc_port: int = 50051
    install_root: Path | None = None
    install_hint: str = ""
    version_gate: Callable[[], None] | None = None
    min_target_version: str | None = None

    def stream_outlet(self, name: str, *, n_channels: int | None = None) -> LSLOutlet:
        """Construct an LSLOutlet publishing the target's stream called `name`.

        **The name is the target's, not this spec's.** Which controls exist is in the
        manifest a running target answers with, and a streamed control's stream is
        named for that control's own address — so a stream is named where that answer is
        read (`myogestic.remote.RemoteTarget`, which calls this once per address it
        drives, after negotiation has settled), never guessed here.

        Carries a stable ``source_id`` so a consumer can re-resolve this stream after a
        restart. Without one, LSL cannot tell a restarted outlet from a new stream and a
        consumer that resolved the old one keeps a dead inlet.

        Parameters
        ----------
        name
            The stream's name, as the target's manifest reports it.
        n_channels
            Width. `~myogestic.remote.RemoteTarget` passes ``1``: one control per
            stream. The default is the target's full pose layout, for the whole-pose
            read-back a recording consumes.

        Raises
        ------
        ValueError
            If `name` is empty. An unnamed LSL stream cannot be resolved, so a nameless
            control could never be found by the target that exports it.
        """
        if not name:
            raise ValueError(
                f"{self.name}: cannot publish an unnamed stream. A stream carrying one "
                f"control is named for that control's address, so an empty name means "
                f"the manifest reported a capability with no address at all."
            )
        return LSLOutlet(
            name=name,
            n_channels=self.n_output_channels if n_channels is None else n_channels,
            hz=self.output_hz,
            source_id=f"myogestic:{self.name}:{name}",
        )

    def control_client(self) -> RemoteClient:
        """Construct a client for this target's control service.

        Hand it to `myogestic.remote.RemoteTarget` and it asks the remote target which
        named DOFs it drives, refusing a configuration it cannot place. Required:
        without one there is nothing to negotiate the control space against.

        Imported lazily — a plain install has no ``[grpc]`` extra, and
        `stream_outlet` / `launcher` must keep working without it.

        Examples
        --------
        >>> from myogestic.controls import ControlBus, Continuous, ControlSet
        >>> from myogestic.remote import RemoteTarget
        >>> from myogestic.vhi import virtual_hand
        >>>
        >>> vhi = virtual_hand()
        >>> controls = ControlSet(dofs={"my_index": Continuous("my_index")})
        >>> target = RemoteTarget(client=vhi.control_client(), interface=vhi)
        >>> bus = ControlBus(controls, targets=[target])
        >>> target.negotiated     # True once the remote end has answered, False until then
        False
        """
        from myogestic.remote._control import RemoteClient

        return RemoteClient(host=self.grpc_host, port=self.grpc_port)

    def recording_client(self) -> RecordingClient:
        """Construct a client for this target's recording session gate.

        Not a control plane, and nothing it does is a control DOF. It carries the two
        things a *recording session* needs: the gate that stops the target's own local
        input competing as a movement source, and trajectories that cycle its control rig
        so the recorded kinematics sweep a continuous range.

        Imported lazily, like the other gRPC client, so a plain install without the
        ``[grpc]`` extra can still use `stream_outlet` / `launcher`.

        Examples
        --------
        >>> from myogestic.vhi import virtual_hand
        >>> aid = virtual_hand().recording_client()
        >>> aid.set_recording_session(True)   # False when the target is unreachable
        False
        """
        from myogestic.remote._recording import RecordingClient

        return RecordingClient(host=self.grpc_host, port=self.grpc_port)

    def launcher(self) -> list[tuple[str, list[str]]]:
        """Return the (name, argv) tuple list expected by `process_launcher`.

        Raises ``FileNotFoundError``, quoting `install_hint`, when nothing can be
        launched from the resolved location. `version_gate` runs last, so an install
        this MyoGestic cannot drive is refused before the process starts rather than
        by every target at bind.
        """
        if not self.process:
            location = f" at {self.install_root}" if self.install_root else ""
            raise FileNotFoundError(f"{self.name}: not installed{location}.{self.install_hint}")
        if self.version_gate is not None:
            self.version_gate()
        return [(self.name, list(self.process))]

    def launchable(self) -> list[tuple[str, list[str]]]:
        """Like `launcher`, but empty instead of raising when nothing can be launched.

        For a `myogestic.widgets.ProcessLauncher` in an application's own UI, where an
        in-app Launch button is a *convenience*: `launcher` raising there takes the whole
        app down at import, even when a target is already running. This returns no rows
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


__all__ = ["InterfaceSpec"]
