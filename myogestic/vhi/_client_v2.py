"""gRPC client for VHI's canonical control service (v2).

The v2 counterpart to `myogestic.vhi._client`. Three calls, three shapes:

- `VhiCanonicalClient.declare` is a **synchronous handshake**. It runs once at bind
  time and its answer decides how everything afterwards is encoded, so a caller has
  to wait for it. It returns ``None`` rather than raising when VHI does not speak v2
  (an older build answers ``UNIMPLEMENTED``).
- `VhiCanonicalClient.set_control` is fire-and-forget on a worker thread, like every
  v1 command: it may be called from the predict thread and must never block it.
- `VhiCanonicalClient.sweep` is synchronous and slow — it drives a joint through its
  range. For verification tools, never for a running app.

Continuous per-tick values still go over LSL. This carries the negotiation, discrete
state, and verification.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Any

import grpc

from myogestic._controls_core import Continuous, Discrete
from myogestic.vhi._proto import myogestic_vhi_v2_pb2 as pb2
from myogestic.vhi._proto.myogestic_vhi_v2_pb2_grpc import VhiCanonicalControlStub

if TYPE_CHECKING:
    from collections.abc import Mapping

    from myogestic.controls import ControlSet

log = logging.getLogger("myogestic.vhi_client_v2")

_RPC_TIMEOUT_S = 2.0

#: How many un-sent control frames to hold before dropping the oldest. `set_control` is fed
#: from the predict thread at ``predict_hz`` while `_send_loop` drains one *blocking* RPC at
#: a time, so a VHI that accepts the connection without answering costs `_RPC_TIMEOUT_S` per
#: frame: measured 0.5 frames/s drained against 50/s produced. Unbounded, that queue grew for
#: as long as the app ran and then replayed every stale frame in order once VHI answered.
#: At 50 Hz this is about a second of slack.
_QUEUE_DEPTH = 64
#: A sweep drives a joint through its whole range, so its deadline is the sweep's
#: own duration plus room for VHI to settle and read the rig back.
_SWEEP_SLACK_S = 5.0


def declare_request(
    controls: ControlSet, client_name: str = "", *, control_pose: str = ""
) -> pb2.DeclareRequest:
    """A `DeclareRequest` describing ``controls``, in declaration order.

    Order is the canonical wire order: VHI echoes it back as the channel layout it
    expects, so a reordered configuration must rename channels rather than silently
    remap them.

    Parameters
    ----------
    control_pose
        Opt in to driving the renderer's *second* pose stream, and say which convention
        you will send on it: ``"canonical"`` or ``"legacy"``. Empty (the default) does
        not declare that stream at all, leaving an existing renderer-unit producer
        working as before.
    """
    if not hasattr(controls, "dofs"):
        # A ControlMap is the *unresolved* form and cannot be declared: a declaration
        # carries each control's kind and range, and only the target can supply those.
        # Raised, not swallowed — None here would read as "this target does not speak v2".
        raise TypeError(
            f"declare() needs a resolved ControlSet, got {type(controls).__name__}. "
            f"Resolve first: resolve(control_map, client.capabilities())."
        )

    encodings = {
        "": pb2.ENCODING_UNSPECIFIED,
        "canonical": pb2.CANONICAL,
        "legacy": pb2.LEGACY_NEGATED,
    }
    if control_pose not in encodings:
        raise ValueError(
            f"control_pose must be one of {sorted(encodings)!r}, got {control_pose!r}"
        )
    request = pb2.DeclareRequest(
        standard_version=controls.standard_version,
        client_name=client_name,
        control_pose_encoding=encodings[control_pose],
    )
    routes = getattr(controls, "routes", {}) or {}
    for dof in controls.dofs.values():
        # One declaration per (alias, address) pair: a grouped mapping fans out, so it
        # declares each address separately with that address's own weight. An unresolved
        # set has no routes and sends the alias as the address.
        refs = routes.get(dof.name) or [None]
        for ref in refs:
            address = getattr(ref, "address", "") if ref is not None else ""
            weight = getattr(ref, "weight", 1.0) if ref is not None else 1.0
            if isinstance(dof, Continuous):
                request.dofs.add(
                    name=dof.name,
                    kind=pb2.CONTINUOUS,
                    lo=dof.lo,
                    hi=dof.hi,
                    rest=dof.rest,
                    address=address,
                    weight=weight,
                )
            elif isinstance(dof, Discrete):
                request.dofs.add(
                    name=dof.name,
                    kind=pb2.DISCRETE,
                    states=list(dof.states),
                    rest_state=dof.rest,
                    address=address,
                    weight=weight,
                )
    return request


class VhiCanonicalClient:
    """Client for VHI's v2 canonical control service.

    Parameters
    ----------
    host, port
        Where VHI's gRPC server is listening. The same server as v1 — v2 is an
        additional service on it, not a second port.

    Examples
    --------
    >>> from myogestic.controls import Continuous, ControlSet
    >>> from myogestic.vhi._client_v2 import VhiCanonicalClient
    >>> client = VhiCanonicalClient()
    >>> reply = client.declare(ControlSet(dofs={"my_index": Continuous("my_index")}))
    >>> reply is None      # None means this VHI does not speak v2
    True
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 50051):
        self.host = host
        self.port = port
        self.target = f"{host}:{port}"

        self._channel = grpc.insecure_channel(self.target)
        self._stub = VhiCanonicalControlStub(self._channel)

        self._commands: queue.Queue[pb2.SetControlRequest | None] = queue.Queue(
            maxsize=_QUEUE_DEPTH
        )
        self._dropped = 0
        self._seen_errors: set[tuple[str, str]] = set()
        self.connected = False
        #: True once a server has answered `Declare` with ``UNIMPLEMENTED``, i.e. it is
        #: reachable but predates v2. Distinguishing that from "nothing is listening"
        #: lets a caller stop retrying a build that will never answer differently.
        self.unimplemented = False

        self._running = True
        self._thread = threading.Thread(
            target=self._send_loop, name="VhiCanonicalClient", daemon=True
        )
        self._thread.start()

    # --- the handshake -------------------------------------------------------

    def declare(
        self,
        controls: ControlSet,
        *,
        client_name: str = "",
        control_pose: str = "",
    ) -> pb2.DeclareReply | None:
        """Negotiate ``controls`` with VHI, or return ``None`` if it cannot.

        Returns
        -------
        DeclareReply or None
            ``None`` when VHI does not implement v2, is unreachable, or errors; the
            caller falls back to the legacy encoding.

            A reply with ``accepted == False`` is **not** ``None``: VHI answered,
            and its per-DOF verdicts say what it refused and why.

        Other Parameters
        ----------------
        control_pose
            Declare the renderer's second pose stream too — see `declare_request`.
            Omitted by default.
        """
        request = declare_request(controls, client_name, control_pose=control_pose)
        try:
            reply = self._stub.Declare(request, timeout=_RPC_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - absence is an answer here
            self.connected = False
            # UNIMPLEMENTED means a server *is* there and does not serve v2 — settled.
            # Anything else (UNAVAILABLE, a deadline) just means not reached yet, so
            # it is worth retrying.
            code = e.code().name if isinstance(e, grpc.Call) else ""
            self.unimplemented = code == "UNIMPLEMENTED"
            self._log_failure("declare", e, level=logging.DEBUG)
            return None
        self.connected = True
        self.unimplemented = False
        self._seen_errors.clear()
        return reply

    # --- fire-and-forget -----------------------------------------------------

    def set_control(
        self,
        continuous: Mapping[str, float] | None = None,
        discrete: Mapping[str, str] | None = None,
    ) -> None:
        """Queue one canonical frame, dropping the oldest if the sender is behind.

        Safe to call from the predict thread: never blocks, never raises. A control frame
        is latest-wins — a held state and a pose both mean "be this now" — so when the
        renderer cannot keep up, the *old* frame is the one to lose. Delivering it late
        moves the hand to somewhere the model asked for minutes ago.
        """
        if not self._running:
            return
        request = pb2.SetControlRequest(
            continuous=dict(continuous or {}), discrete=dict(discrete or {})
        )
        while True:
            try:
                self._commands.put_nowait(request)
                return
            except queue.Full:
                try:
                    self._commands.get_nowait()
                except queue.Empty:  # pragma: no cover - drained by the sender first
                    pass
                self._dropped += 1
                if self._dropped == 1 or self._dropped % 1000 == 0:
                    log.warning(
                        "VHI is not keeping up — dropped %d stale control frame(s). The "
                        "renderer is answering slower than %s produces them.",
                        self._dropped,
                        type(self).__name__,
                    )

    # --- the target's own vocabulary -----------------------------------------

    def capabilities(self) -> list[Any] | None:
        """Every control this VHI exports, as `myogestic.controls.Capability` values.

        The target-owned half of the contract: a configuration maps *your* aliases onto
        these addresses, and their semantics — number or held state, domain, states —
        come from here rather than from anything hard-coded in MyoGestic.

        Returns
        -------
        list[Capability] or None
            ``None`` when VHI is unreachable or predates the manifest; the caller
            falls back rather than guessing a vocabulary.
        """
        from myogestic.controls import Capability

        try:
            manifest = self._stub.GetControlManifest(
                pb2.GetControlManifestRequest(), timeout=_RPC_TIMEOUT_S
            )
        except Exception as e:  # noqa: BLE001 - absence is an answer during migration
            self.connected = False
            self._log_failure("capabilities", e, level=logging.DEBUG)
            return None
        self.connected = True
        self._seen_errors.clear()
        log.info(
            "VHI %s exports %d controls (vocabulary %s)",
            manifest.target_name,
            len(manifest.capabilities),
            manifest.vocabulary_version,
        )
        return [
            Capability(
                address=cap.address,
                kind="discrete" if cap.kind == pb2.DISCRETE else "continuous",
                lo=cap.lo,
                hi=cap.hi,
                rest=cap.rest,
                states=tuple(cap.states),
                rest_state=cap.rest_state,
                channel=cap.channel,
                stream_name=cap.stream_name,
                activation_threshold=cap.activation_threshold,
                encoding=int(cap.encoding),
                description=cap.description,
            )
            for cap in manifest.capabilities
        ]

    # --- presentation --------------------------------------------------------

    def set_presentation(self, *, blend: bool, blend_speed: float = 0.0) -> bool:
        """Configure how the renderer *looks* while reaching a commanded value.

        The third of three separate layers:

        1. **Continuous smoothing** — `myogestic.controls.ControlBus`'s ``smoothing``,
           applied in MyoGestic before any target sees a frame. It decides what value
           is actually *commanded*.
        2. **Discrete debounce and hysteresis** — declared on the DOF
           (`myogestic.controls.Discrete.debounce_s`) and applied by the same bus. A
           discrete control is never numerically low-pass filtered like an axis; that
           would interpolate through states nobody selected.
        3. **This** — purely visual interpolation inside the renderer, so the hand does
           not snap between poses.

        Layer 3 is not a substitute for layer 2: with blending on but no debounce the
        hand still jumps between states, just smoothly.

        Returns whether VHI applied it (``False`` when it does not speak v2).
        """
        try:
            ack = self._stub.SetPresentation(
                pb2.SetPresentationRequest(blend=blend, blend_speed=blend_speed),
                timeout=_RPC_TIMEOUT_S,
            )
        except Exception as e:  # noqa: BLE001 - absence is an answer during migration
            self._log_failure("set_presentation", e, level=logging.DEBUG)
            return False
        return ack.applied

    # --- verification --------------------------------------------------------

    def sweep(
        self, name: str, *, duration_s: float = 2.0, both_directions: bool = True
    ) -> pb2.SweepControlReply | None:
        """Drive one DOF across its range and report what VHI observed on its rig.

        Synchronous and slow — it animates a joint. For a verification tool, never
        for a running app. ``None`` on any failure.
        """
        try:
            return self._stub.SweepControl(
                pb2.SweepControlRequest(
                    name=name, duration_s=duration_s, both_directions=both_directions
                ),
                timeout=duration_s + _SWEEP_SLACK_S,
            )
        except Exception as e:  # noqa: BLE001 - a verification tool reports, not raises
            self._log_failure("sweep", e)
            return None

    # --- lifecycle -----------------------------------------------------------

    def stop(self) -> None:
        """Stop the worker thread and close the channel. Idempotent."""
        if not self._running:
            return
        self._running = False
        # Drop the backlog, but keep the newest frame. Two reasons, and they pull the same
        # way: the sentinel would otherwise sit behind up to `_QUEUE_DEPTH` stale frames,
        # each costing an RPC timeout before the worker reached it — and the newest frame is
        # the one `ControlBus.stop` just queued to put the hand back at rest. Dropping that
        # would leave the renderer holding whatever it was doing.
        while self._commands.qsize() > 1:
            try:
                self._commands.get_nowait()
            except queue.Empty:  # pragma: no cover - the sender drained it first
                break
        self._commands.put_nowait(None)
        if threading.current_thread() is not self._thread:
            self._thread.join()
        self.connected = False
        self._channel.close()

    # --- internals -----------------------------------------------------------

    def _send_loop(self) -> None:
        while True:
            request = self._commands.get()
            if request is None:
                return
            try:
                ack = self._stub.SetControl(request, timeout=_RPC_TIMEOUT_S)
                self.connected = True
                self._seen_errors.clear()
                if not ack.applied:
                    log.warning("VHI rejected control values: %s", dict(ack.rejected))
            except Exception as e:  # noqa: BLE001 - the worker must survive
                self.connected = False
                self._log_failure("set_control", e)

    def _log_failure(self, operation: str, error: Exception, *, level: int = logging.WARNING) -> None:
        # Keyed on the gRPC status code, not str(error): grpc varies the field order
        # of debug_error_string between calls, so a string key would never dedup.
        call = error if isinstance(error, grpc.Call) else None
        key = (operation, call.code().name if call is not None else type(error).__name__)
        if key in self._seen_errors:
            return
        self._seen_errors.add(key)
        detail = f"{call.code().name}: {call.details()}" if call is not None else repr(error)
        log.log(level, "%s.%s failed — %s", type(self).__name__, operation, detail)


__all__ = ["VhiCanonicalClient", "declare_request"]
