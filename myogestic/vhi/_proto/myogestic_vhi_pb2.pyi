from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable, Mapping as _Mapping
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class Kind(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    KIND_UNSPECIFIED: _ClassVar[Kind]
    CONTINUOUS: _ClassVar[Kind]
    DISCRETE: _ClassVar[Kind]
KIND_UNSPECIFIED: Kind
CONTINUOUS: Kind
DISCRETE: Kind

class GetControlManifestRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class ControlCapability(_message.Message):
    __slots__ = ("address", "kind", "lo", "hi", "rest", "states", "rest_state", "description", "stream_name", "activation_threshold", "channel")
    ADDRESS_FIELD_NUMBER: _ClassVar[int]
    KIND_FIELD_NUMBER: _ClassVar[int]
    LO_FIELD_NUMBER: _ClassVar[int]
    HI_FIELD_NUMBER: _ClassVar[int]
    REST_FIELD_NUMBER: _ClassVar[int]
    STATES_FIELD_NUMBER: _ClassVar[int]
    REST_STATE_FIELD_NUMBER: _ClassVar[int]
    DESCRIPTION_FIELD_NUMBER: _ClassVar[int]
    STREAM_NAME_FIELD_NUMBER: _ClassVar[int]
    ACTIVATION_THRESHOLD_FIELD_NUMBER: _ClassVar[int]
    CHANNEL_FIELD_NUMBER: _ClassVar[int]
    address: str
    kind: Kind
    lo: float
    hi: float
    rest: float
    states: _containers.RepeatedScalarFieldContainer[str]
    rest_state: str
    description: str
    stream_name: str
    activation_threshold: float
    channel: int
    def __init__(self, address: _Optional[str] = ..., kind: _Optional[_Union[Kind, str]] = ..., lo: _Optional[float] = ..., hi: _Optional[float] = ..., rest: _Optional[float] = ..., states: _Optional[_Iterable[str]] = ..., rest_state: _Optional[str] = ..., description: _Optional[str] = ..., stream_name: _Optional[str] = ..., activation_threshold: _Optional[float] = ..., channel: _Optional[int] = ...) -> None: ...

class ControlManifest(_message.Message):
    __slots__ = ("target_name", "vocabulary_version", "capabilities")
    TARGET_NAME_FIELD_NUMBER: _ClassVar[int]
    VOCABULARY_VERSION_FIELD_NUMBER: _ClassVar[int]
    CAPABILITIES_FIELD_NUMBER: _ClassVar[int]
    target_name: str
    vocabulary_version: str
    capabilities: _containers.RepeatedCompositeFieldContainer[ControlCapability]
    def __init__(self, target_name: _Optional[str] = ..., vocabulary_version: _Optional[str] = ..., capabilities: _Optional[_Iterable[_Union[ControlCapability, _Mapping]]] = ...) -> None: ...

class SetPresentationRequest(_message.Message):
    __slots__ = ("blend", "blend_speed")
    BLEND_FIELD_NUMBER: _ClassVar[int]
    BLEND_SPEED_FIELD_NUMBER: _ClassVar[int]
    blend: bool
    blend_speed: float
    def __init__(self, blend: bool = ..., blend_speed: _Optional[float] = ...) -> None: ...

class SetControlRequest(_message.Message):
    __slots__ = ("continuous", "discrete")
    class ContinuousEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: float
        def __init__(self, key: _Optional[str] = ..., value: _Optional[float] = ...) -> None: ...
    class DiscreteEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    CONTINUOUS_FIELD_NUMBER: _ClassVar[int]
    DISCRETE_FIELD_NUMBER: _ClassVar[int]
    continuous: _containers.ScalarMap[str, float]
    discrete: _containers.ScalarMap[str, str]
    def __init__(self, continuous: _Optional[_Mapping[str, float]] = ..., discrete: _Optional[_Mapping[str, str]] = ...) -> None: ...

class ControlAck(_message.Message):
    __slots__ = ("applied", "rejected")
    class RejectedEntry(_message.Message):
        __slots__ = ("key", "value")
        KEY_FIELD_NUMBER: _ClassVar[int]
        VALUE_FIELD_NUMBER: _ClassVar[int]
        key: str
        value: str
        def __init__(self, key: _Optional[str] = ..., value: _Optional[str] = ...) -> None: ...
    APPLIED_FIELD_NUMBER: _ClassVar[int]
    REJECTED_FIELD_NUMBER: _ClassVar[int]
    applied: bool
    rejected: _containers.ScalarMap[str, str]
    def __init__(self, applied: bool = ..., rejected: _Optional[_Mapping[str, str]] = ...) -> None: ...

class SweepControlRequest(_message.Message):
    __slots__ = ("name", "duration_s", "both_directions")
    NAME_FIELD_NUMBER: _ClassVar[int]
    DURATION_S_FIELD_NUMBER: _ClassVar[int]
    BOTH_DIRECTIONS_FIELD_NUMBER: _ClassVar[int]
    name: str
    duration_s: float
    both_directions: bool
    def __init__(self, name: _Optional[str] = ..., duration_s: _Optional[float] = ..., both_directions: bool = ...) -> None: ...

class SweepObservation(_message.Message):
    __slots__ = ("element", "degrees_at_hi", "degrees_at_lo")
    ELEMENT_FIELD_NUMBER: _ClassVar[int]
    DEGREES_AT_HI_FIELD_NUMBER: _ClassVar[int]
    DEGREES_AT_LO_FIELD_NUMBER: _ClassVar[int]
    element: str
    degrees_at_hi: float
    degrees_at_lo: float
    def __init__(self, element: _Optional[str] = ..., degrees_at_hi: _Optional[float] = ..., degrees_at_lo: _Optional[float] = ...) -> None: ...

class SweepControlReply(_message.Message):
    __slots__ = ("completed", "message", "observed", "matched_expectation")
    COMPLETED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    OBSERVED_FIELD_NUMBER: _ClassVar[int]
    MATCHED_EXPECTATION_FIELD_NUMBER: _ClassVar[int]
    completed: bool
    message: str
    observed: _containers.RepeatedCompositeFieldContainer[SweepObservation]
    matched_expectation: bool
    def __init__(self, completed: bool = ..., message: _Optional[str] = ..., observed: _Optional[_Iterable[_Union[SweepObservation, _Mapping]]] = ..., matched_expectation: bool = ...) -> None: ...

class SetRecordingSessionRequest(_message.Message):
    __slots__ = ("active",)
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    active: bool
    def __init__(self, active: bool = ...) -> None: ...

class StartRecordingTrajectoryRequest(_message.Message):
    __slots__ = ("movement", "frequency_hz", "hold_time_s", "rest_time_s")
    MOVEMENT_FIELD_NUMBER: _ClassVar[int]
    FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    HOLD_TIME_S_FIELD_NUMBER: _ClassVar[int]
    REST_TIME_S_FIELD_NUMBER: _ClassVar[int]
    movement: str
    frequency_hz: float
    hold_time_s: float
    rest_time_s: float
    def __init__(self, movement: _Optional[str] = ..., frequency_hz: _Optional[float] = ..., hold_time_s: _Optional[float] = ..., rest_time_s: _Optional[float] = ...) -> None: ...

class StopRecordingTrajectoryRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class GetRecordingSessionStateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class RecordingAck(_message.Message):
    __slots__ = ("applied", "message")
    APPLIED_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    applied: bool
    message: str
    def __init__(self, applied: bool = ..., message: _Optional[str] = ...) -> None: ...

class RecordingSessionState(_message.Message):
    __slots__ = ("recording_session_active", "trajectory_running", "trajectory_movement", "animation_state", "available_movements", "current_movement")
    RECORDING_SESSION_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_RUNNING_FIELD_NUMBER: _ClassVar[int]
    TRAJECTORY_MOVEMENT_FIELD_NUMBER: _ClassVar[int]
    ANIMATION_STATE_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_MOVEMENTS_FIELD_NUMBER: _ClassVar[int]
    CURRENT_MOVEMENT_FIELD_NUMBER: _ClassVar[int]
    recording_session_active: bool
    trajectory_running: bool
    trajectory_movement: str
    animation_state: str
    available_movements: _containers.RepeatedScalarFieldContainer[str]
    current_movement: str
    def __init__(self, recording_session_active: bool = ..., trajectory_running: bool = ..., trajectory_movement: _Optional[str] = ..., animation_state: _Optional[str] = ..., available_movements: _Optional[_Iterable[str]] = ..., current_movement: _Optional[str] = ...) -> None: ...
