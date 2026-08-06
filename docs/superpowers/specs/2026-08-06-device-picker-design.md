# Design: `DevicePicker` — pick, configure, and connect a device from the UI

**Status:** design, pending review

## Context / problem

Every acquisition example hardcodes its source at import time:

```python
source = SessantaquattroSource(nch_mode=3, fs_mode=2, mode="monopolar")
app.streams(Stream("emg", source=source, window_ms=200))
```

A novice who owns a Muovi instead of a Sessantaquattro, or wants 1000 Hz instead of
2000 Hz, has to edit Python. `StreamPanel` does not help: it shows status and offers a
Connect button, but the *source object* is fixed. Its inline target buttons come from
`source.discover()`, which only `LSLSource` and `SerialSource` implement — none of the
three OTB sources do, because an OTB device is not discoverable on a network, it is
configured by constructor arguments.

So the gap is: **choosing which source class to instantiate, and with what arguments,
from the running UI.**

## Goals / non-goals

**Goals**
- One panel that selects a device, exposes that device's own relevant knobs, shows the
  physical setup hint, and connects — replacing `StreamPanel` in the example app.
- The device list is **passed in code**, so an app can ship OTB-only, LSL-only, or a
  custom list. Default is OTB + LSL.
- Per-device configuration is **declared by the device entry**, not imposed by the
  widget. Sessantaquattro shows channels/rate/mode; Muovi shows EMG-or-EEG; LSL shows
  a discovered-stream list.

**Non-goals**
- Every constructor argument. Gain, `hpf`/`lpf`, `include_aux`, IP, port and timeouts
  stay at their library defaults; a user who needs them writes Python.
- Saved presets, auto-reconnect-on-drop, per-device validation UI.
- Making OTB sources implement `discover()`. They are not discoverable.

## Data model

```python
@dataclass(frozen=True)
class Device:
    label: str                      # "Sessantaquattro — 64 ch"
    factory: Callable[..., object]  # called with the chosen kwargs
    # kwarg -> {shown label: value}; insertion order is the combo order
    options: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    hint: str = ""                  # physical setup instruction
```

`options` is the whole configuration mechanism: an ordered mapping from constructor
keyword to the choices offered for it. The widget renders one combo per key and calls
`factory(**chosen)`. No schema, no base class, no registration — a device that wants no
knobs passes no options.

Shipped entries (module constants, composable):

```python
OTB_DEVICES = [
    Device("Muovi — 32 ch", MuoviSource,
           {"emg": {"EMG · 2000 Hz": True, "EEG · 500 Hz": False}},
           hint="Hold the power button ~5 s, join the MVxxx WiFi network, then Connect."),
    Device("Muovi+ — 64 ch", partial(MuoviSource, plus=True),
           {"emg": {"EMG · 2000 Hz": True, "EEG · 500 Hz": False}},
           hint="Hold the power button ~5 s, join the MVxxx WiFi network, then Connect."),
    Device("Quattrocento", QuattrocentoSource, {
        "nch_mode":  {"96 ch": 0, "192 ch": 1, "288 ch": 2, "384 ch": 3},
        "fs_mode":   {"512 Hz": 0, "2048 Hz": 1, "5120 Hz": 2, "10240 Hz": 3},
        "detection": {"Monopolar": "monopolar", "Differential": "differential",
                      "Bipolar": "bipolar"},
    }, hint="Connect over Ethernet and give this PC a 169.254.x.x address."),
    Device("Sessantaquattro", SessantaquattroSource, {
        "nch_mode": {"8 ch": 0, "16 ch": 1, "32 ch": 2, "64 ch": 3},
        "fs_mode":  {"500 Hz": 0, "1000 Hz": 1, "2000 Hz": 2, "4000 Hz": 3},
        "mode":     {"Monopolar": "monopolar", "Bipolar": "bipolar",
                     "Differential": "differential"},
    }, hint="Join the device's WiFi AP (or set this PC's IP on its web page), "
            "then power it on and Connect."),
]
LSL_DEVICE = Device("LSL stream", lambda: LSLSource(""),
                    hint="Scan for outlets advertised on this network.")
DEFAULT_DEVICES = [*OTB_DEVICES, LSL_DEVICE]
```

Channel counts in the labels are the **biosignal** counts (`QUATTRO_BIO_BY_MODE`,
`SESSANTAQUATTRO_BIO_BY_NCH`), not the wire totals — that is what the user sees plotted.

## Widget

```python
class DevicePicker:
    def __init__(self, stream: str, *, devices: Sequence[Device] = DEFAULT_DEVICES,
                 show_header: bool = True) -> None: ...
    def ui(self, ctx: Context) -> None: ...
```

State is keyed by widget identity (the instance), per the design-principles contract:
the selected device index and the per-device chosen-option indices live on the
instance, not in a module dict keyed by stream name.

Render order each frame:

1. `panel_header("Device", fa.ICON_FA_MICROCHIP)`
2. Device combo.
3. **Config**, branching on the *selected device's* source kind:
   - has `discover()` → delegate to the existing `_scan_panel(stream_name, stream)` in
     `signals/_scan.py`: Scan button, discovered-outlet combo, Connect. Already written,
     already shared with the viewers.
   - otherwise → one combo per `options` key, then a Connect button.
4. Muted `hint` line.
5. Status line: dot (`SUCCESS`/`DANGER`), `fs · n_channels · last-sample age`, or
   `stream.last_error` when detached.

The two config paths exist because the two source kinds genuinely differ: an LSL target
is discovered at runtime and applied via `stream.reconnect(target)`; an OTB
configuration is fixed at construction. Collapsing them would mean either faking
`discover()` on OTB or reimplementing scanning here.

## Connect flow

```python
stream._source = dev.factory(**chosen)   # swap the source object
threading.Thread(target=stream.reconnect, daemon=True).start()
```

`Stream.reconnect()` already takes `self._lock` for the whole swap and calls
`_allocate_buffers()` from the returned `StreamInfo`, so changing device *and* geometry
in one click (64 ch @ 2 kHz → 384 ch @ 512 Hz) is handled by existing code. Connecting
must be off-thread: `accept_timeout` on the OTB sources defaults to 30 s and would
freeze the UI.

Assigning `stream._source` reaches past a private name. The alternative — adding a
public `Stream.set_source()` — is a public API addition for one caller; noted as the
upgrade path in a `ponytail:` comment rather than built now.

Guards: the Connect button is disabled while a connect is in flight; a device combo
change while connected does nothing until Connect is pressed (so the plot does not
silently swap under a running recording).

## Error handling

`stream.reconnect()` returns `False` and sets `last_error` rather than raising; the
status line renders it. A factory that raises (bad kwarg combination) is caught in the
worker thread and logged via `ctx.log`, same as `StreamPanel._connect` does today.

## Testing

`tests/test_device_picker.py` — the non-trivial logic is factory-kwargs assembly, not
rendering:

- Each shipped `Device` constructs successfully with its **default** option choices.
- Each shipped `Device` constructs successfully with **every** option value (cartesian
  product is small: max 4×4×3 = 48 for Sessantaquattro).
- The resulting source reports the geometry the label promises — e.g. selecting
  "384 ch" on Quattrocento yields a source whose `nch_mode` maps to
  `QUATTRO_BIO_BY_MODE[3] == 384`.
- `DEFAULT_DEVICES` labels are unique (they are ImGui combo entries).

The ImGui rendering is not unit-testable and is covered by the standalone example.

## Files

| file | change |
|---|---|
| `myogestic/widgets/signals/device_picker.py` | new — `Device`, `DevicePicker`, `OTB_DEVICES`, `LSL_DEVICE`, `DEFAULT_DEVICES` |
| `myogestic/widgets/signals/__init__.py` | re-export |
| `myogestic/widgets/__init__.py` | re-export (public API) |
| `examples/panels/device_picker.py` | new — standalone widget demo, per the per-widget convention |
| `examples/devices_app.py` | new — device-agnostic app: picker + viewer + log + recording + sessions |
| `docs/how-to/pick-a-device.md` | new — novice how-to, added to `properdocs.yml` and the how-to `index.md` |
| `tests/test_device_picker.py` | new |

The three `examples/otb/*_emg.py` scripts and `sessantaquattro_app.py` stay as focused
per-device references.
