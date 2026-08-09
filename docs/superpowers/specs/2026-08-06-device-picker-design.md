# Design: `DevicePicker` — pick, configure, and connect a device from the UI

**Status:** implemented. Three things changed during the build and are corrected
below: the connect flow does **not** stop/start the stream, `scan` is a declared flag
rather than a detected `discover()`, and the pre-connect memory estimate was dropped in
favour of documenting the scaling.

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
class DeviceOption:
    kwarg: str                    # constructor keyword
    label: str                    # row label: "Channels", "Rate (Hz)"
    choices: Mapping[str, Any]    # {shown: value}, in display order

@dataclass(frozen=True)
class DeviceSpec:
    label: str                              # "Sessantaquattro / +"
    factory: Callable[..., Any]             # called with the chosen kwargs
    options: Sequence[DeviceOption] = ()
    scan: bool = False                      # target is discovered, not configured
    hint: str = ""                          # physical setup instruction
```

`DeviceOption` is the whole configuration mechanism. No schema, no base class, no
registration — a device that wants no knobs passes no options.

**Why a record and not a `{kwarg: {shown: value}}` dict.** The first build used the
dict, and drew the rows with no labels on the theory that every choice states its own
unit ("192 ch", "2048 Hz"). Rendered, that is four identical full-width dropdowns
reading as four unrelated facts — and the visual contract's Units section requires a
spelled-out label anyway. The label has to come from somewhere, and a module-level
`{"nch_mode": "Channels", ...}` table is magic keyed on a parameter name that only the
device entry can interpret. `DeviceOption` puts it where the knowledge is.

**`scan` is declared, not detected.** The earlier draft branched on
`hasattr(source, "discover")`. That is wrong: `SyntheticSource` implements `discover()`
unconditionally, yet the panel example needs it configured statically — and a real
source may reasonably offer both. Detection would also require constructing a probe
every frame just to ask. One bool settles it.

**No defaults table.** Each combo opens at the index whose value matches the factory's
*own* default, read once via `inspect.signature(dev.factory)` — which resolves through
`functools.partial`, so `partial(MuoviSource, plus=True)` reports `plus=True`. An
untouched panel therefore reproduces `factory()` exactly, and the source constructors
stay the single source of truth. Type is compared before value, since `True == 1` would
otherwise let a bool default select an int option. Unresolvable → first choice.

Shipped entries (module constants, composable):

```python
_DETECTION = {"Monopolar": "monopolar", "Differential": "differential", "Bipolar": "bipolar"}
_SIGNAL = DeviceOption("emg", "Signal", {"EMG": True, "EEG": False})

OTB_DEVICES = (
    DeviceSpec("Muovi — 32 ch",  MuoviSource,                        (_SIGNAL,), hint=...),
    DeviceSpec("Muovi+ — 64 ch", partial(MuoviSource, plus=True),    (_SIGNAL,), hint=...),
    DeviceSpec("Sessantaquattro / +", SessantaquattroSource, (
        DeviceOption("nch_mode", "Channels",  {"8": 0, "16": 1, "32": 2, "64": 3}),
        DeviceOption("fs_mode",  "Rate (Hz)", {"500": 0, "1000": 1, "2000": 2, "4000": 3}),
        DeviceOption("mode",     "Detection", _DETECTION),
    ), hint=...),
    DeviceSpec("Quattrocento", QuattrocentoSource, (
        DeviceOption("nch_mode",  "Channels",  {"96": 0, "192": 1, "288": 2, "384": 3}),
        DeviceOption("fs_mode",   "Rate (Hz)", {"512": 0, "2048": 1, "5120": 2, "10240": 3}),
        DeviceOption("detection", "Detection", _DETECTION),
    ), hint=...),
)
LSL_DEVICE = DeviceSpec("LSL stream", lambda: LSLSource(""), scan=True, hint=...)
DEFAULT_DEVICES = (*OTB_DEVICES, LSL_DEVICE)
```

Channel counts in the labels are the **biosignal** counts (`QUATTRO_BIO_BY_MODE`,
`SESSANTAQUATTRO_BIO_BY_NCH`), not the wire totals — that is what the user sees plotted,
and a test asserts each label against the constant it selects.

Choice text is bare numbers — the row label carries the unit — so a segmented control
fits at realistic panel widths. Verified rendered at 620 px (segmented) and 250 px
(dropdown fallback).

One Sessantaquattro entry, not the two the earlier draft listed: the accessory-channel
count is **probed** from the ramp counter rather than configured, so a Sessantaquattro
and a Sessantaquattro+ are identical to set up. That `"Bipolar"` halves the channel
count — making the `Channels` row overstate the result — does not fit in a segment
label, so it is stated in the how-to and the status line shows the true count once
connected.

## Widget

```python
class DevicePicker:
    def __init__(self, stream: str, *, devices: Sequence[DeviceSpec] = DEFAULT_DEVICES,
                 show_header: bool = True) -> None: ...
    def ui(self, ctx: Context) -> None: ...
```

State is keyed by widget identity (the instance), per the design-principles contract:
the selected device index and the per-device chosen-option indices live on the
instance, not in a module dict keyed by stream name.

Render order each frame:

1. `panel_header("DeviceSpec", ICON_FA_MICROCHIP, status=tone)` — the state dot lives in
   the header, so the panel does not spend a row on it, with a `set_item_tooltip`
   carrying the detail (the contract: colour must never be the only channel).
2. `DeviceSpec` row.
3. **Config**, branching on `dev.scan`:
   - `False` → one labelled row per `DeviceOption`, `segmented()` when every choice fits the
     row and a dropdown when it does not.
   - `True` → a labelled `Stream` row of what `discover()` found plus an
     `ARROWS_ROTATE` rescan button, auto-fired once per selection so the list is there
     without the user knowing to press Scan. Discovery runs off-thread against a
     **throwaway** source built from the same options; it is a network query, never a
     session, so it needs no teardown and cannot disturb whatever the stream is
     currently running.
4. Muted `hint` line.
5. Full-width action — `PLUG  Connect`, or `ARROWS_ROTATE  Reconnect` once attached,
   since the glyph shows what clicking will do. Disabled with the reason in its tooltip.
6. Detail line: `fs · n_channels · last-sample age`, or `last_error` in `DANGER`.

Every row goes through `label_column(label, among)` with the same `among`, so one
column width serves the whole panel and the fields line up as a block. `label_column`
stacks the label above a full-width field when the panel is too narrow for a column.

**`IDLE`, not `DANGER`, for a stream nobody has connected yet.** Never having been asked
to attach is not a failure, and a panel that opens red reads as a broken app. `DANGER`
is reserved for a `last_error`. (`StreamPanel` still opens red; not changed here.)

The two config paths exist because the two source kinds genuinely differ: an LSL target
is discovered at runtime and applied via `stream.reconnect(target)`; an OTB
configuration is fixed at construction. Collapsing them would mean either faking
`discover()` on OTB or reimplementing scanning here.

`_scan_panel()` in `signals/_scan.py` was going to be reused for step 3. It is not: it
draws its own Connect button (a second one), and it keys its state by *stream name* in a
module-level dict, which the design-principles contract forbids — widget state is keyed
by widget identity. The replacement is ~15 lines storing state on the instance.

`segmented()` is the contract's idiom for a one-of-N choice with every option visible;
it cannot wrap or truncate, so `_fits_segmented` measures the row first and falls back
to a combo. Both paths were checked rendered, not reasoned about.

## Connect flow

On a daemon thread (`accept_timeout` defaults to 30 s and would freeze the UI):

```python
source = dev.factory(**chosen)   # build FIRST: a bad combination raises here,
old = stream._source             # with the stream still on what was working
stream._source = source
old.disconnect()                 # load-bearing — see below
ok = stream.reconnect(target)    # target is None for a statically configured device
```

**Disconnecting the old source is load-bearing, not tidiness.** `Stream.reconnect()`
only ever calls `reconnect()`/`connect()` on `self._source`, which by then is the *new*
object — the replaced source is never disconnected. For Muovi and Sessantaquattro that
leaks the **listening** server socket, which only their `disconnect()` override closes;
the next Connect to the same device then fails `EADDRINUSE` on the fixed port
(54321 / 45454). `SO_REUSEADDR` is set on both but does not permit binding over a live
listener.

**An earlier draft wrapped this in `stream.stop()` / `stream.start()`. That is wrong.**
`App.run()` starts the acquire thread and owns it (`core.py:485`), so calling `start()`
again spawns a *second* one. It is also unnecessary: `_base.read()` returns
`(None, None)` when `_sock is None`, and `LSLSource.read()` does the same with no inlet,
so the acquire loop reading a freshly-constructed source is a no-op. `Stream.reconnect`
clears `_connected` under the stream lock immediately afterwards, closing the window.

`reconnect()` then holds `self._lock` for the whole swap and calls `_allocate_buffers()`
from the returned `StreamInfo`, so changing device *and* geometry in one click
(64 ch @ 2 kHz → 384 ch @ 512 Hz) needs no new code.

Assigning `stream._source` reaches past a private name. The alternative — a public
`Stream.set_source()` — is public API for one caller; noted as the upgrade path in a
`ponytail:` comment rather than built now.

**Guards**
- Connect disabled while a connect is in flight.
- Connect disabled while `ctx.state == "recording"`, with the reason in the tooltip.
  `reconnect()` does not detach the session, so the acquire loop would keep appending
  to the same zarr key at the new channel width and corrupt the recording.
- Changing the device combo does nothing until Connect is pressed.

## Memory footprint

`_allocate_buffers` sets `_cap = fs * buffer_seconds` and allocates a `RingBuffer` plus
`_display_d` plus `_win_d` — roughly **3 × cap × n_channels × itemsize**. The combos
make the worst case one click away: Quattrocento at "384 ch" + "10240 Hz" against a
60 s buffer is ~940 MB per array, ~2.8 GB total.

**The live estimate under the combos was cut.** Predicting `fs` and `n_channels` from
the chosen options *before* connecting needs per-source geometry knowledge the sources
do not expose uniformly: `MuoviSource` computes `_geo` in `__init__`, `QuattrocentoSource`
stores an output `_select` but not `fs`, and `SessantaquattroSource` leaves `_geo = None`
until the accessory width is probed at connect time. That is a per-device predictor
function — real machinery for a hint.

What ships instead is the mitigation that actually removes the hazard, plus the number
written down where it is read:

- `examples/devices_app.py` uses the default **10 s** buffer, not the 60 s that
  `sessantaquattro_app.py` hardcodes. Worst case drops from ~2.8 GB to ~470 MB, which
  is the honest cost of 384 channels at 10 kHz rather than a footgun.
- `docs/how-to/pick-a-device.md` states the `3 × fs × buffer_s × channels × 4` scaling
  and both worked examples.

Revisit if someone actually runs out of memory.

## Error handling

`stream.reconnect()` returns `False` and sets `last_error` rather than raising; the
status line renders it. A factory that raises (bad kwarg combination) is caught in the
worker thread and logged via `ctx.log`, same as `StreamPanel._connect` does today.

## Testing

`tests/test_device_picker.py` — the non-trivial logic is factory-kwargs assembly, not
rendering:

- Each shipped `DeviceSpec` constructs successfully with its **default** option choices.
- Each shipped `DeviceSpec` constructs successfully with **every** option value (cartesian
  product is small: max 4×4×3 = 48 for Sessantaquattro).
- The resulting source reports the geometry the label promises — e.g. selecting
  "384 ch" on Quattrocento yields a source whose `nch_mode` maps to
  `QUATTRO_BIO_BY_MODE[3] == 384`.
- `DEFAULT_DEVICES` labels are unique (they are ImGui combo entries).
- Untouched choices reproduce `factory()` exactly — `seeded.__dict__ == factory().__dict__`
  — which is what lets the entries carry no defaults of their own.
- A bool option is not selected by an int default (the `True == 1` trap).
- Swapping the source on a `Stream` closes the previous source: connect a fake source,
  swap to a second, assert the first saw `disconnect()`. This is the regression test for
  the leaked-listener bug above, and it needs no hardware.
- Re-attaching the *same* source does not double-disconnect it (retry, not swap).
- A failed swap leaves the error in `last_error` and the stream detached.
- Pressing Connect end to end: `_connect` off-thread against a fake source builds the
  selected configuration and the stream ends up running it.
- An unbuildable configuration is logged and leaves the previous source attached —
  pinning the build-before-swap ordering.

24 tests, all hardware-free. The ImGui rendering is not unit-testable; the panel example
was run and the rendered output checked before shipping.

## Files

| file | change |
|---|---|
| `myogestic/widgets/signals/device_picker.py` | new — `DeviceSpec`, `DevicePicker`, `OTB_DEVICES`, `LSL_DEVICE`, `DEFAULT_DEVICES` |
| `myogestic/widgets/signals/__init__.py` | re-export |
| `myogestic/widgets/__init__.py` | re-export (public API) |
| `examples/panels/device_picker.py` | new — standalone widget demo, per the per-widget convention |
| `examples/devices_app.py` | new — device-agnostic app: picker + viewer + log + recording + sessions |
| `docs/how-to/pick-a-device.md` | new — novice how-to |
| `properdocs.yml`, `docs/how-to/index.md` | new "Connecting hardware" section. It also picks up `connect-otb-devices.md`, which was in neither and so was unreachable from the docs site |
| `examples/panels/README.md` | table row for the new panel script |
| `tests/test_device_picker.py` | new |

The three `examples/otb/*_emg.py` scripts and `sessantaquattro_app.py` stay as focused
per-device references.
