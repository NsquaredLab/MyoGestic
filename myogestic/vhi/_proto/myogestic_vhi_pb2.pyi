from google.protobuf.internal import containers as _containers
from google.protobuf.internal import enum_type_wrapper as _enum_type_wrapper
from google.protobuf import descriptor as _descriptor
from google.protobuf import message as _message
from collections.abc import Iterable as _Iterable
from typing import ClassVar as _ClassVar, Optional as _Optional, Union as _Union

DESCRIPTOR: _descriptor.FileDescriptor

class ControlMode(int, metaclass=_enum_type_wrapper.EnumTypeWrapper):
    __slots__ = ()
    MOVEMENT: _ClassVar[ControlMode]
    STREAM: _ClassVar[ControlMode]
    IDLE: _ClassVar[ControlMode]
MOVEMENT: ControlMode
STREAM: ControlMode
IDLE: ControlMode

class SetMovementRequest(_message.Message):
    __slots__ = ("movement_name", "cycle")
    MOVEMENT_NAME_FIELD_NUMBER: _ClassVar[int]
    CYCLE_FIELD_NUMBER: _ClassVar[int]
    movement_name: str
    cycle: bool
    def __init__(self, movement_name: _Optional[str] = ..., cycle: bool = ...) -> None: ...

class FreezeRequest(_message.Message):
    __slots__ = ("frozen",)
    FROZEN_FIELD_NUMBER: _ClassVar[int]
    frozen: bool
    def __init__(self, frozen: bool = ...) -> None: ...

class SetSpeedRequest(_message.Message):
    __slots__ = ("frequency_hz", "hold_time_s", "rest_time_s")
    FREQUENCY_HZ_FIELD_NUMBER: _ClassVar[int]
    HOLD_TIME_S_FIELD_NUMBER: _ClassVar[int]
    REST_TIME_S_FIELD_NUMBER: _ClassVar[int]
    frequency_hz: float
    hold_time_s: float
    rest_time_s: float
    def __init__(self, frequency_hz: _Optional[float] = ..., hold_time_s: _Optional[float] = ..., rest_time_s: _Optional[float] = ...) -> None: ...

class SetSmoothingRequest(_message.Message):
    __slots__ = ("enabled", "smoothing_speed")
    ENABLED_FIELD_NUMBER: _ClassVar[int]
    SMOOTHING_SPEED_FIELD_NUMBER: _ClassVar[int]
    enabled: bool
    smoothing_speed: float
    def __init__(self, enabled: bool = ..., smoothing_speed: _Optional[float] = ...) -> None: ...

class SetChiralityRequest(_message.Message):
    __slots__ = ("right_hand",)
    RIGHT_HAND_FIELD_NUMBER: _ClassVar[int]
    right_hand: bool
    def __init__(self, right_hand: bool = ...) -> None: ...

class SetSessionActiveRequest(_message.Message):
    __slots__ = ("active",)
    ACTIVE_FIELD_NUMBER: _ClassVar[int]
    active: bool
    def __init__(self, active: bool = ...) -> None: ...

class SetControlModeRequest(_message.Message):
    __slots__ = ("mode",)
    MODE_FIELD_NUMBER: _ClassVar[int]
    mode: ControlMode
    def __init__(self, mode: _Optional[_Union[ControlMode, str]] = ...) -> None: ...

class GetStateRequest(_message.Message):
    __slots__ = ()
    def __init__(self) -> None: ...

class CommandAck(_message.Message):
    __slots__ = ("applied", "current_state", "current_movement", "message")
    APPLIED_FIELD_NUMBER: _ClassVar[int]
    CURRENT_STATE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_MOVEMENT_FIELD_NUMBER: _ClassVar[int]
    MESSAGE_FIELD_NUMBER: _ClassVar[int]
    applied: bool
    current_state: str
    current_movement: str
    message: str
    def __init__(self, applied: bool = ..., current_state: _Optional[str] = ..., current_movement: _Optional[str] = ..., message: _Optional[str] = ...) -> None: ...

class StateReply(_message.Message):
    __slots__ = ("current_state", "current_movement", "session_active", "available_movements", "mode", "control_mode")
    CURRENT_STATE_FIELD_NUMBER: _ClassVar[int]
    CURRENT_MOVEMENT_FIELD_NUMBER: _ClassVar[int]
    SESSION_ACTIVE_FIELD_NUMBER: _ClassVar[int]
    AVAILABLE_MOVEMENTS_FIELD_NUMBER: _ClassVar[int]
    MODE_FIELD_NUMBER: _ClassVar[int]
    CONTROL_MODE_FIELD_NUMBER: _ClassVar[int]
    current_state: str
    current_movement: str
    session_active: bool
    available_movements: _containers.RepeatedScalarFieldContainer[str]
    mode: str
    control_mode: ControlMode
    def __init__(self, current_state: _Optional[str] = ..., current_movement: _Optional[str] = ..., session_active: bool = ..., available_movements: _Optional[_Iterable[str]] = ..., mode: _Optional[str] = ..., control_mode: _Optional[_Union[ControlMode, str]] = ...) -> None: ...
