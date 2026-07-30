"""Client for VHI's recording session gate and trajectories.

Separate from `myogestic.vhi._control` for the same reason the RPCs are grouped
apart on the service: **none of this is control**. A DOF is something an
application commands; these are properties of a recording *session*.

The distinction earns its keep in one specific way. Collecting regression training
data wants a control hand that keeps *moving*, so the recorded kinematics sweep a
continuous range for EMG windows to align against. A discrete DOF wants the
opposite — ask for a grip, hold a grip. Expressing the first through the second would
have made a held state mean "held, unless someone is recording", so recording gets its
own vocabulary and the control one stays honest.

Every call here is **synchronous**. They are all setup and teardown around a recording
— a button click, not a per-tick command — and a caller needs to know whether the
session actually opened before it starts writing samples.
"""

from __future__ import annotations

import logging

import grpc

from myogestic.vhi._proto import myogestic_vhi_pb2 as pb2
from myogestic.vhi._proto.myogestic_vhi_pb2_grpc import VhiControlStub

log = logging.getLogger("myogestic.vhi_recording")

_RPC_TIMEOUT_S = 3.0


class VhiRecordingClient:
    """Drive VHI's recording session: the session gate and trajectories.

    Parameters
    ----------
    host, port
        VHI's gRPC server — the same one `myogestic.vhi._control.VhiControlClient`
        uses. There is one service now, not a second port.

    Examples
    --------
    >>> from myogestic.vhi import virtual_hand
    >>> aid = virtual_hand().recording_client()
    >>> aid.available_movements()          # discover, don't hard-code
    []
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 50051):
        self.target = f"{host}:{port}"
        self._channel = grpc.insecure_channel(self.target)
        self._stub = VhiControlStub(self._channel)
        self._seen_errors: set[tuple[str, str]] = set()
        self.available = False

    # --- the session gate ----------------------------------------------------

    def set_recording_session(self, active: bool) -> bool:
        """Open or close a recording session. Returns whether VHI applied it.

        While active, VHI ignores its local keyboard, so a recording has a single
        movement source. Returns ``False`` rather than raising when the aid is absent
        — a caller can then decide whether an ungated recording is acceptable, which
        is a judgement about experiment integrity and not this client's to make.
        """
        return self._call(
            "SetRecordingSession", pb2.SetRecordingSessionRequest(active=active)
        )

    # --- trajectories ----------------------------------------------------------

    def start_trajectory(
        self,
        movement: str,
        *,
        frequency_hz: float = 0.0,
        hold_time_s: float = -1.0,
        rest_time_s: float = -1.0,
    ) -> bool:
        """Start cycling ``movement`` so the control hand sweeps a range.

        This is the recording aid, not a control command: it deliberately keeps the
        hand moving. The defaults leave VHI's own timing alone — a non-positive
        frequency and negative hold/rest times mean "don't change it".

        Refused while another trajectory is running: a recording is being aligned
        against the current one, and swapping it underneath would corrupt the labels
        for everything already captured.
        """
        return self._call(
            "StartRecordingTrajectory",
            pb2.StartRecordingTrajectoryRequest(
                movement=movement,
                frequency_hz=frequency_hz,
                hold_time_s=hold_time_s,
                rest_time_s=rest_time_s,
            ),
        )

    def stop_trajectory(self) -> bool:
        """Stop any running trajectory and rest the hand. Safe to call unconditionally."""
        return self._call(
            "StopRecordingTrajectory", pb2.StopRecordingTrajectoryRequest()
        )

    # --- state ---------------------------------------------------------------

    def state(self) -> pb2.RecordingSessionState | None:
        """The session's state, or ``None`` when VHI does not offer it."""
        try:
            reply = self._stub.GetRecordingSessionState(
                pb2.GetRecordingSessionStateRequest(), timeout=_RPC_TIMEOUT_S
            )
        except Exception as e:  # noqa: BLE001 - absence is an answer during migration
            self.available = False
            self._log_failure("state", e, level=logging.DEBUG)
            return None
        self.available = True
        self._seen_errors.clear()
        return reply

    def available_movements(self) -> list[str]:
        """Movement names a trajectory may use. Empty when the aid is unavailable."""
        state = self.state()
        return list(state.available_movements) if state is not None else []

    def stop(self) -> None:
        """Close the channel. Does **not** stop a running trajectory.

        Deliberately separate: closing a client is not the same act as ending a
        recording, and a teardown path that silently ended someone's session would be
        surprising. Call `stop_trajectory` explicitly.
        """
        self._channel.close()

    # --- internals -----------------------------------------------------------

    def _call(self, rpc_name: str, request) -> bool:
        try:
            ack = getattr(self._stub, rpc_name)(request, timeout=_RPC_TIMEOUT_S)
        except Exception as e:  # noqa: BLE001 - the caller decides what absence means
            self.available = False
            self._log_failure(rpc_name, e, level=logging.DEBUG)
            return False
        self.available = True
        self._seen_errors.clear()
        if not ack.applied:
            log.warning("VHI refused %s: %s", rpc_name, ack.message)
        return ack.applied

    def _log_failure(self, operation: str, error: Exception, *, level: int = logging.WARNING) -> None:
        # Keyed on the gRPC status code, not str(error): grpc varies the field order of
        # debug_error_string between calls, so a string key would never dedup.
        call = error if isinstance(error, grpc.Call) else None
        key = (operation, call.code().name if call is not None else type(error).__name__)
        if key in self._seen_errors:
            return
        self._seen_errors.add(key)
        detail = f"{call.code().name}: {call.details()}" if call is not None else repr(error)
        log.log(level, "%s.%s failed — %s", type(self).__name__, operation, detail)


__all__ = ["VhiRecordingClient"]
