"""gRPC control client for the Virtual Hand Interface (VHI).

MyoGestic is the gRPC *client*; VHI hosts the server. Commands are
fire-and-forget: the public methods enqueue onto a daemon worker thread so GUI
handlers never block the 60 fps render loop. The worker issues the unary RPC
with a short deadline and logs the ack; failures are deduped per (error class,
message) like ``myogestic.outputs.Output`` so a noisy disconnect logs once.

``get_state()`` is the one synchronous call — a query the GUI makes rarely
(startup / explicit refresh), never inside the frame loop.
"""

from __future__ import annotations

import logging
import queue
import threading
from dataclasses import dataclass

import grpc
from google.protobuf.message import Message

from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2
from myogestic.vhi._proto.myogestic_vhi_pb2_grpc import VhiControlStub

log = logging.getLogger("myogestic.vhi_client")

_RPC_TIMEOUT_S = 2.0


@dataclass(frozen=True)
class _QueuedCommand:
    rpc_name: str
    request: Message


class VhiControlClient:
    """Fire-and-forget gRPC control client for the Virtual Hand Interface."""

    def __init__(self, host: str = "127.0.0.1", port: int = 50051):
        self.host = host
        self.port = port
        self.target = f"{host}:{port}"

        self._channel = grpc.insecure_channel(self.target)
        self._stub = VhiControlStub(self._channel)

        self._commands: queue.Queue[_QueuedCommand | None] = queue.Queue()
        self._seen_send_errors: set[tuple[str, str]] = set()

        self.last_ack: pb2.CommandAck | None = None
        self.connected = False

        self._running = True
        self._thread = threading.Thread(
            target=self._send_loop,
            name="VhiControlClient",
            daemon=True,
        )
        self._thread.start()

    # --- fire-and-forget public API ------------------------------------------

    def set_movement(self, name: str, cycle: bool = False) -> None:
        """Queue a movement command (``"Rest"`` returns the hand to rest).

        ``cycle=False`` (default): VHI snaps the control hand to the movement's
        end pose and holds it — for a classifier output or a manual command.
        ``cycle=True``: VHI plays the open/close movement cycle — for recording
        regression data, so the control-hand kinematics sweep a continuous range.
        """
        self._enqueue("SetMovement", pb2.SetMovementRequest(movement_name=name, cycle=cycle))

    def freeze(self, frozen: bool) -> None:
        """Queue a freeze/unfreeze command."""
        self._enqueue("Freeze", pb2.FreezeRequest(frozen=frozen))

    def set_speed(
        self,
        frequency_hz: float,
        hold_time_s: float,
        rest_time_s: float,
    ) -> None:
        """Queue a control-hand animation timing command."""
        self._enqueue(
            "SetSpeed",
            pb2.SetSpeedRequest(
                frequency_hz=frequency_hz,
                hold_time_s=hold_time_s,
                rest_time_s=rest_time_s,
            ),
        )

    def set_smoothing(self, enabled: bool, smoothing_speed: float) -> None:
        """Queue a predicted-hand smoothing command."""
        self._enqueue(
            "SetSmoothing",
            pb2.SetSmoothingRequest(enabled=enabled, smoothing_speed=smoothing_speed),
        )

    def set_chirality(self, right_hand: bool) -> None:
        """Queue a control-hand chirality command."""
        self._enqueue("SetChirality", pb2.SetChiralityRequest(right_hand=right_hand))

    def set_session_active(self, active: bool) -> None:
        """Queue a session-active command (gates VHI's local keyboard control)."""
        self._enqueue("SetSessionActive", pb2.SetSessionActiveRequest(active=active))

    def set_control_mode(self, mode: str) -> None:
        """Queue a control-hand driver-mode change: "MOVEMENT", "STREAM" or "IDLE".

        MOVEMENT (default): predefined-movement commands + keyboard drive the
        control hand. STREAM: a continuous pose streamed to ``control_outlet()``
        drives it instead (SetMovement / Freeze / SetSpeed are then rejected).
        IDLE: the hand holds its rest pose. Raises ValueError on an unknown mode.
        """
        try:
            value = pb2.ControlMode.Value(mode.upper())
        except ValueError:
            raise ValueError(
                f"unknown control mode {mode!r} — expected MOVEMENT, STREAM or IDLE"
            ) from None
        self._enqueue("SetControlMode", pb2.SetControlModeRequest(mode=value))

    # --- synchronous query ---------------------------------------------------

    def get_state(self) -> pb2.StateReply | None:
        """Synchronously query VHI state.

        Intentionally blocking (short deadline): call on startup, on an explicit
        GUI refresh, or for low-frequency connection checks — never inside the
        60 fps frame loop. Returns None on any RPC failure.
        """
        try:
            reply = self._stub.GetState(pb2.GetStateRequest(), timeout=_RPC_TIMEOUT_S)
        except Exception as e:
            self.connected = False
            self._log_failure("get_state", e)
            return None

        self.connected = True
        return reply

    # --- lifecycle -----------------------------------------------------------

    def stop(self) -> None:
        """Stop the worker thread and close the gRPC channel."""
        if not self._running:
            return
        self._running = False
        self._commands.put_nowait(None)  # sentinel to unblock the loop
        if threading.current_thread() is not self._thread:
            self._thread.join()
        self.connected = False
        self._channel.close()

    # --- internals -----------------------------------------------------------

    def _enqueue(self, rpc_name: str, request: Message) -> None:
        if not self._running:
            return
        self._commands.put_nowait(_QueuedCommand(rpc_name=rpc_name, request=request))

    def _send_loop(self) -> None:
        while True:
            command = self._commands.get()
            if command is None:  # stop() sentinel
                return
            try:
                self._send(command)
            except Exception as e:
                self.connected = False
                self._log_failure("send", e)

    def _send(self, command: _QueuedCommand) -> None:
        rpc = getattr(self._stub, command.rpc_name)
        ack: pb2.CommandAck = rpc(command.request, timeout=_RPC_TIMEOUT_S)
        self.last_ack = ack
        self.connected = True
        log.info(
            "VHI %s ack: applied=%s state=%r movement=%r message=%r",
            command.rpc_name,
            ack.applied,
            ack.current_state,
            ack.current_movement,
            ack.message,
        )

    def _log_failure(self, operation: str, error: Exception) -> None:
        # Log once per (error class, message) pair — a noisy disconnect must not
        # flood the log, and the worker thread must never crash.
        key = (type(error).__name__, str(error))
        if key in self._seen_send_errors:
            return
        self._seen_send_errors.add(key)
        log.warning(
            "%s.%s failed: %s: %s",
            type(self).__name__,
            operation,
            type(error).__name__,
            error,
        )


__all__ = ["VhiControlClient"]
