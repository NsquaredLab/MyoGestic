"""gRPC client for a renderer's control service.

Three calls, three shapes:

- `RendererClient.capabilities` is the manifest — the whole contract `RendererTarget`
  resolves against, with no separate handshake. Synchronous, and asked once at bind.
- `RendererClient.set_control` is fire-and-forget on a worker thread: it may be
  called from the predict thread and must never block it.
- `RendererClient.sweep` is synchronous and slow — it drives a joint through its
  range. For verification tools, never for a running app.

Continuous per-tick values still go over LSL; this carries the manifest, discrete
state, and verification.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import TYPE_CHECKING, Any

import grpc

from myogestic.renderer._proto import renderer_control_pb2 as pb2
from myogestic.renderer._proto.renderer_control_pb2_grpc import RendererControlStub

if TYPE_CHECKING:
    from collections.abc import Mapping

log = logging.getLogger("myogestic.renderer.control")

_RPC_TIMEOUT_S = 2.0

#: The oldest renderer vocabulary this client can drive.
#:
#: **Load-bearing.** MyoGestic and the renderer are separately installed applications, so
#: "they were released together" does not mean any given pair of them is a matching pair.
#: Vocabulary 2 is one LSL stream per DOF, named for the control's own address and one
#: channel wide; vocabulary 1 was a manifest of ``stream_name``/``channel`` pairs and a
#: renderer listening for one wide pose stream. A version-1 renderer paired with this
#: client fails *silently* — it waits for a stream nobody publishes any more, logs
#: nothing, and the hand simply never moves — which is why the mismatch is refused here,
#: loudly, at the one call every bind makes.
_MIN_VOCABULARY = 2


def _vocabulary(reported: str) -> int:
    """The manifest's vocabulary as an integer, or 0 when it does not state one.

    Leading-integer, so a renderer that versions itself ``"2.1"`` compares as 2 rather
    than as unversioned. Anything with no leading integer at all — including the empty
    string a build predating the field leaves — is 0, and so is older than any minimum.
    """
    try:
        return int(reported.strip().split(".", 1)[0])
    except ValueError:
        return 0

#: How many un-sent control frames to hold before dropping the oldest. `set_control` is fed
#: from the predict thread at ``predict_hz`` while `_send_loop` drains one *blocking* RPC at
#: a time, so a renderer that accepts the connection without answering costs `_RPC_TIMEOUT_S`
#: per frame: measured 0.5 frames/s drained against 50/s produced. Unbounded, that queue grew
#: for as long as the app ran and then replayed every stale frame in order once it answered.
#: At 50 Hz this is about a second of slack.
_QUEUE_DEPTH = 64
#: A sweep drives a joint through its whole range, so its deadline is the sweep's
#: own duration plus room for the renderer to settle and read the rig back.
_SWEEP_SLACK_S = 5.0


class RendererClient:
    """Client for a renderer's control service.

    Parameters
    ----------
    host, port
        Where the renderer's gRPC server is listening.

    Examples
    --------
    >>> from myogestic.renderer._control import RendererClient
    >>> client = RendererClient()
    >>> capabilities = client.capabilities()
    >>> capabilities is None      # None means this renderer is unreachable
    True
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 50051):
        self.host = host
        self.port = port
        self.target = f"{host}:{port}"

        self._channel = grpc.insecure_channel(self.target)
        self._stub = RendererControlStub(self._channel)

        self._commands: queue.Queue[pb2.SetControlRequest | None] = queue.Queue(
            maxsize=_QUEUE_DEPTH
        )
        self._dropped = 0
        self._seen_errors: set[tuple[str, str]] = set()
        self.connected = False

        self._running = True
        self._thread = threading.Thread(
            target=self._send_loop, name="RendererClient", daemon=True
        )
        self._thread.start()

    # --- fire-and-forget -----------------------------------------------------

    def set_control(
        self,
        continuous: Mapping[str, float] | None = None,
        discrete: Mapping[str, str] | None = None,
    ) -> None:
        """Queue one control frame, dropping the oldest if the sender is behind.

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
                        "the renderer is not keeping up — dropped %d stale control frame(s). The "
                        "renderer is answering slower than %s produces them.",
                        self._dropped,
                        type(self).__name__,
                    )

    # --- the target's own vocabulary -----------------------------------------

    def capabilities(self) -> list[Any] | None:
        """Every control this renderer exports, as `myogestic.controls.Capability` values.

        The target-owned half of the contract: a configuration maps *your* aliases onto
        these addresses, and their semantics — number or held state, domain, states —
        come from here rather than from anything hard-coded in MyoGestic.

        Returns
        -------
        list[Capability] or None
            ``None`` when the renderer is unreachable or predates the manifest; the caller
            defers and retries once it is reachable, rather than guessing a vocabulary.

        Raises
        ------
        ValueError
            When the renderer answers with a vocabulary older than `_MIN_VOCABULARY`.
            Deliberately not ``None``: unreachable means "try again", while too old means
            "this pair will never work", and the two must not be handled the same way.
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
        reported = manifest.vocabulary_version
        if _vocabulary(reported) < _MIN_VOCABULARY:
            raise ValueError(
                f"{manifest.target_name or 'this renderer'} speaks control vocabulary "
                f"{reported or '(none)'}, and MyoGestic needs {_MIN_VOCABULARY} or newer. "
                f"Vocabulary {_MIN_VOCABULARY} publishes one LSL stream per control, named "
                f"for that control's own address and one channel wide; vocabulary 1 read a "
                f"single wide pose stream that MyoGestic no longer sends. Paired with this "
                f"client such a renderer would report no error and never move. "
                # Named, not "the renderer": this client speaks to whatever serves the
                # contract, and
                # telling the author of a third-party renderer to update somebody else's
                # program is advice they cannot act on.
                f"Update {manifest.target_name or 'the renderer'}."
            )
        log.info(
            "%s exports %d controls (vocabulary %s)",
            manifest.target_name,
            len(manifest.capabilities),
            reported,
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
                activation_threshold=cap.activation_threshold,
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

        Returns whether the renderer applied it (``False`` when it does not speak v2).
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
        """Drive one DOF across its range and report what the renderer observed on its rig.

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
                    # Keyed by address, because that is what the request was keyed by — the
                    # renderer only ever sees addresses, so it can only refuse one by name.
                    # A reader holding the map that produced this reads the right-hand side.
                    log.warning(
                        "the renderer rejected these control addresses: %s", dict(ack.rejected)
                    )
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


__all__ = ["RendererClient"]
