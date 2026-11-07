---
title: "Pick a device from the UI"
---
`DevicePicker` puts device choice in the running app instead of the source
file. Pick hardware from a dropdown, set the few knobs it has, press
Connect. Nothing attaches on its own, and nothing changes until you press
that button.

`examples/start_here/force_ramps.py` combines a picker with a tabbed signal /
force-tracking viewer, log, recording and sessions:

```python
from myogestic import App, Stream
from myogestic.widgets import DEFAULT_DEVICES, DevicePicker

app = App("pick a device")
# A Stream needs *a* source to exist; the picker replaces it on Connect.
app.streams(Stream("emg", source=DEFAULT_DEVICES[0].factory(), window_ms=200))

device = DevicePicker("emg")


@app.ui
def ui(ctx):
    device.ui(ctx)
```

`DEFAULT_DEVICES` covers Muovi, Muovi+, Sessantaquattro(+) and Quattrocento
from OT Bioelettronica. It also offers network LSL outlets and a synthetic test signal. Each amplifier
still needs its physical setup first: the ⓘ button beside the dropdown opens
the numbered setup procedure, and
[Connect OTB devices](connect-otb-devices.md) has the detail behind it.

The panel header dot shows connection state. It is grey until you connect,
green once connected, red if the attempt failed. Hover it for the
reason. The action area shows connection progress or live geometry; a failed
attempt leaves its error below Connect.

On a Sessantaquattro, `Bipolar` halves the channel count.
Picking `64` and `Bipolar` gives you 32. The status
line shows the real number once connected.

## Try it without hardware

The last entry in the list, Synthetic (no hardware), is a fake amplifier
that runs in-process: sine waves, a 50 Hz mains hum so the notch filter has
something to remove, and paced to whatever rate you pick. Connect it and every
panel supports plotting and recording, including naming and saving takes.

Use it to learn the app or reproduce bugs without an amplifier. It is labelled
as a test signal and listed last so real hardware leads. Use real recordings for experimental data.

Five sliders appear once connected. Activation, Direction, Noise, Hum and
Hum (Hz) retune the live signal without reconnecting. The plot keeps its history
and a recording keeps its geometry.

Activation scales the synthetic contraction. At `0` the channels contain noise
and mains hum; at `1` the carrier has full amplitude. Vary it between gestures
to produce distinct training signals. At a fixed amplitude every gesture has
the same waveform, so a classifier cannot separate them and a prediction demo
provides no evidence of discrimination.

Direction ranges from `-1` to `+1` and splits Activation between the channel halves,
like an agonist/antagonist pair on opposite sides of a limb.
At `-1` only the first half carries the signal; at `+1` only the second does.
At the default `0`, both carry it and preserve the original signal exactly. Record "down" and "up" as distinct takes
to train a regressor without hardware. Direction only attenuates; neither half
exceeds the amplitude set by Activation.

Noise and hum deliberately do *not* scale with either: an electrode picks those
up whether or not the muscle is contracting, and scaling them would hand a
classifier a signal-to-noise cue that no real recording has.

Raise Hum and set the viewer's Notch to 50 Hz to remove it. Then move Hum (Hz)
away from 50. The hum returns outside the notch's bandwidth.

The source is public, so a script can use it directly with no picker involved:

```python
from myogestic import Stream
from myogestic.sources import SyntheticSource

stream = Stream("emg", source=SyntheticSource(n_channels=8), window_ms=1000)
stream.reconnect()
```

The default carrier is sine. Pass `SyntheticSource(n_channels=8, waveform="emg")`
for band-limited stochastic EMG-like signals. The picker's built-in synthetic
entry uses the default sine carrier.

## Knobs you can turn while it streams

A `DeviceOption` sets a constructor argument when Connect builds the source;
changing it requires reconnecting. A `DeviceParam` slider writes an attribute
of the running source:

```python
from myogestic.widgets import DeviceSpec, DeviceParam
from myogestic.sources import SyntheticSource

TUNABLE = DeviceSpec(
    "Synthetic",
    SyntheticSource,
    live=(DeviceParam("noise", "Noise", 0.0, 1.0),),
)
```

The next chunk picks the new value up. Nothing reconnects, the plot does not
reset, and a recording in progress keeps its channel count and rate.

For that to work the source must expose the attribute publicly and read it fresh
each chunk. Float assignment is atomic under the GIL, so no lock is needed
between the UI thread and the acquire thread. The sliders are shown only while
that device is the connected one: they write to the live source, so
rendering them for a device you have merely selected would retune something
else. Disconnecting or removing the stream hides the sliders.

On a `selectable` picker they survive pointing the panel at another stream and
back. Every field the panel shows is keyed by the stream it describes, so a
stream you return to is as you left it: same device, same options, same scan
results, and still attached.

## Offer only the hardware you support

The list is data. Pass a narrower one and the dropdown shrinks:

```python
from myogestic.widgets import OTB_DEVICES, DevicePicker

picker = DevicePicker("emg", devices=OTB_DEVICES)
```

## Add your own device

A `DeviceSpec` is a label, a factory, and the `DeviceOption` rows that factory takes:

```python
from functools import partial

from myogestic.sources.otb import MuoviSource
from myogestic.widgets import DeviceSpec, DeviceOption

MUOVI_EEG = DeviceSpec(
    "Muovi+ (EEG)",
    partial(MuoviSource, plus=True, emg=False),
    (DeviceOption("include_aux", "Channels", {"Biosignal": False, "With IMU": True}),),
    hint="This PC is the server; the probe connects in over Wi-Fi.",
    steps=(
        "Hold the probe's button for about 5 seconds.",
        "Join its MVxxx-ID network from this PC.",
        "Press Connect.",
    ),
)
```

Each `DeviceOption` binds a constructor keyword to a labelled row of choices, and
the chosen values are passed to the factory as keyword arguments. Rows are
drawn in the order you write them.

`hint` and `steps` appear behind the ⓘ button beside the dropdown.
Use one hint line describing the device and a numbered setup procedure.
Setup is a sequence of physical actions; list them in order so the reader
does not have to recover the sequence from a paragraph. The button is hidden
when both are empty.

Two things to get right:

- Use a descriptive `label` with the unit spelled out, such as `"Sample rate"`
  or `"Channels"`. Never display constructor keywords such as `"fs_mode"`.
  Only the device entry knows what those keywords mean.
- Keep choices short. `"2048"` fits better than `"2048 Hz"`. When every choice
  fits on the row it is drawn as a segmented control, so all the alternatives
  stay visible and picking one is a single click. Wordy choices, or a narrow
  panel, fall back to a dropdown automatically.

You do not write down defaults. Each row starts on whichever choice matches the
factory's *own* default, so an untouched panel reproduces `factory()` exactly
and the source constructors stay the single source of truth.

## Devices that are discovered, not configured

An LSL outlet has no device settings to choose. Scan available streams
and select the outlet to subscribe to.
Set `scan=True` and the picker draws a Scan button and a list of what
`discover()` found, instead of option dropdowns, then hands the choice to
`Stream.reconnect`:

```python
from myogestic.sources import LSLSource
from myogestic.widgets import DeviceSpec

LSL = DeviceSpec(
    "LSL stream",
    lambda: LSLSource(""),
    scan=True,
    hint="Scan for outlets advertised on this network.",
)
```

Set the flag explicitly; a source with `discover()` can also use static configuration.

## Watch the buffer at high channel counts

Ring-buffer memory scales with rate × channels, and the dropdowns put the
extremes one click apart. A `Stream` allocates roughly
`4 × fs × buffer_s × channels × 4` bytes for float32 samples, plus timestamps
and display workspaces. The Quattrocento's top setting (384 ch @ 10240 Hz)
needs at least ~630 MB at the default 10 s buffer and ~3.8 GB at 60 s.

The default is 10 s. Raise `buffer_ms` for a specific recording, not by habit.

## One Connect per app

`SignalViewer` offers Connect while detached. Use it in an app with
`App`, `Stream` and a viewer.
Once you add a picker, turn it off:

```python
viewer = SignalViewer("emg", show_connect=False)
```

The two buttons are not the same action. The viewer's attaches whatever source
the stream already holds; the picker's builds a new one from the dropdown. They
agree right up until somebody changes the dropdown, and then one of them
silently connects a device nobody chose.

## Streams that come and go

Declare as many streams as needed with `app.streams(Stream("emg", ...))`
or let the operator add them while the app runs.

```python
from myogestic import Stream
from myogestic.widgets import StreamManager

streams = StreamManager(
    on_add=lambda name: app.add_stream(Stream(name, source=..., window_ms=200)),
    on_remove=app.remove_stream,
)
```

`StreamManager` shows sorted mono stream chips with status dots. Select a chip to
reveal its × removal action; the last stream is kept. The trailing + opens
an inline name field, Add, and × to cancel. During recording the chips are
dimmed and a caption says to stop recording before adding or removing streams.

The manager names the stream; the app builds it with its window and buffer lengths. Pair it with
`DevicePicker(selectable=True)` to choose each source. The picker has its own
chip selection and keeps each stream's chosen device, options, and connection
state intact when switching between them.

For sources already configured in code, `StreamPanel` shows one compact row per
stream: name, sample rate, channels, sample age, and a reconnect icon. Detached
streams offer Connect, connection attempts show elapsed time with Abort,
and failures show their error with Retry. With `selectable=True` (the default),
Connect opens a popover of discovered outlets when the source supports discovery;
its rescan icon refreshes the choices. The Streams header also offers rescan and
summarizes connection state with a dot. Give panels distinct `widget_id` values
when displaying more than one; connection attempts belong to each instance.

For one compact card, put those callbacks directly on the picker instead of
rendering a separate manager:

```python
from myogestic.widgets import DEFAULT_DEVICES, DevicePicker

picker = DevicePicker(
    "emg",
    selectable=True,
    on_add=lambda name: app.add_stream(
        Stream(name, source=DEFAULT_DEVICES[0].factory(), window_ms=200)
    ),
    on_remove=app.remove_stream,
)
```

The trailing + chip opens a name field, Add, and × to cancel. Names use
`StreamManager`'s rules: lowercase ASCII letters, digits, hyphens, and underscores,
up to 32 characters. Empty names and duplicates cannot be added. Only the selected
chip offers × removal; the last offered stream cannot be removed, and removing
the selected stream points the picker at a remaining one. `exclude=("target",)`
keeps widget-owned streams out of these chips.

Options have captions above their controls in two columns, falling back to one
column when the controls need more room. Each uses segments when all choices fit,
or a dropdown otherwise. Scanned devices show an Outlet chooser and rescan
button. Connect fills the action row while detached; during connection it
becomes an elapsed-time readout with Abort. Once connected, sample rate,
channel count and sample age share a tinted row with Reconnect and Disconnect
icons; attached-device live sliders stay below.

Both are refused while a recording is running. A session sizes one Zarr array
per stream when recording starts, so a stream that appears afterwards has
nowhere to write, and one that vanishes mid-take keeps the session attached and
is never finalized. `App.add_stream` and `App.remove_stream` return `False` and
put the reason in `ctx.status_message`.

`App.run` starts each registered stream once. `add_stream` starts its stream
only while the app is running; during setup it behaves like `app.streams(...)`.

## Recording

Connect, Reconnect, and Disconnect are disabled while a recording is running,
with the reason in each action's tooltip. Reconnecting does not
detach the session, so the acquire loop would keep appending to the same key at
the new channel width and corrupt what you recorded. Stop, switch, start again.
