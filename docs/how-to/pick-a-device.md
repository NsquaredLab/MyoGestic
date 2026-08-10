# Pick a device from the UI

`DevicePicker` puts device choice in the running app instead of the source
file. Pick hardware from a dropdown, set the few knobs it has, press
**Connect**. Nothing attaches on its own, and nothing changes until you press
that button.

`examples/start_here/force_ramps.py` is the whole thing — a tabbed signal /
force-tracking viewer, log, recording and sessions around one picker:

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

`DEFAULT_DEVICES` covers the OT Bioelettronica family — Muovi, Muovi+,
Sessantaquattro(+), Quattrocento — plus any LSL outlet on the network, plus a
synthetic test signal for when you have no hardware to hand. Each amplifier
still needs its physical setup first: the **ⓘ** button beside the dropdown opens
the numbered procedure — which button to hold, which network to join — and
[Connect OTB devices](connect-otb-devices.md) has the detail behind it.

The dot in the panel header is the connection state — grey until you connect,
green once samples are arriving, red if the attempt failed. Hover it for the
reason. The line under the button repeats it in words.

One thing the labels cannot tell you: on a Sessantaquattro, **`Bipolar` halves
the channel count**, so picking `64` and `Bipolar` gives you 32. The status
line shows the real number once connected.

## Try it without hardware

The last entry in the list, **Synthetic (no hardware)**, is a fake amplifier
that runs in-process: sine waves, a 50 Hz mains hum so the notch filter has
something to remove, and paced to whatever rate you pick. Connect it and every
panel behaves exactly as it would against a real device — plot, record, name,
save.

It is there so you can learn the app before the hardware arrives, and so a bug
can be reproduced by someone who does not own the amplifier. It is *not* data:
the label says so, and it is listed last so real hardware leads.

Five of its knobs — **Activation**, **Direction**, **Noise**, **Hum** and
**Hum (Hz)** — appear as sliders once it is connected, and they retune the
running signal *live*: no reconnect, so the plot never resets and a recording in
progress keeps its geometry.

**Activation** is the one that makes it a subject rather than a signal
generator. At `0` the channels are noise and mains hum; at `1` the muscle is
working. Without it every gesture is the same waveform, so a model trained on
synthetic EMG separates nothing — which makes a prediction demo meaningless.

**Direction**, `-1` to `+1`, is the same idea for a *two-way* gesture. It splits
Activation between the first half of the channels and the second, the way an
agonist and its antagonist sit on opposite sides of a limb: at `-1` only the
first half carries the signal, at `+1` only the second, at `0` — the default —
both do and the source is exactly what it was before the knob existed. This is
what lets you record "down" and "up" as measurably different takes and train a
regressor on them with no hardware in the room. It only ever attenuates, so
steering never makes a channel louder than Activation alone would.

Noise and hum deliberately do *not* scale with either: an electrode picks those
up whether or not the muscle is contracting, and scaling them would hand a
classifier a signal-to-noise cue that no real recording has.

Two things worth trying with them. Drag **Hum** up and switch the viewer's Notch
to 50 Hz to watch it disappear. Then drag **Hum (Hz)** off 50 while the notch
stays there — the hum comes back, which is that filter's bandwidth made visible.

The source is public, so a script can use it directly with no picker involved:

```python
from myogestic import Stream
from myogestic.sources import SyntheticSource

stream = Stream("emg", source=SyntheticSource(n_channels=8), window_ms=1000)
stream.reconnect()
```

## Knobs you can turn while it streams

An `DeviceOption` is a constructor argument: it is applied when Connect builds the
source, so changing one means reconnecting. A `DeviceParam` is the other kind —
a slider wired straight to an attribute of the source that is *already running*:

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
each chunk — assigning a float is atomic under the GIL, so no lock is needed
between the UI thread and the acquire thread. The sliders are shown only while
that device is the **connected** one: they write to the live source, so
rendering them for a device you have merely selected would retune something
else. Detaching the stream from anywhere — this panel's Disconnect, a
`StreamManager` removing it — takes them away with it.

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

Each `DeviceOption` binds a **constructor keyword** to a labelled row of choices, and
the chosen values are passed to the factory as keyword arguments. Rows are
drawn in the order you write them.

`hint` and `steps` sit behind the **ⓘ** button next to the dropdown: one line on
what the device is, then the setup procedure as a numbered list. Setup is a
sequence of physical acts, so it is written as one — a paragraph makes the
reader re-derive the order every time they come back to it. A device with
neither gets no button.

Two things to get right:

- **The row `label` carries the unit, spelled out** — `"Sample rate"`,
  `"Channels"`, never `"fs_mode"`. Only your entry knows what the keyword means.
- **Keep the choice text short** — `"2048"`, not `"2048 Hz"`. When every choice
  fits on the row it is drawn as a segmented control, so all the alternatives
  stay visible and picking one is a single click. Wordy choices, or a narrow
  panel, fall back to a dropdown automatically.

You do not write down defaults. Each row starts on whichever choice matches the
factory's *own* default, so an untouched panel reproduces `factory()` exactly
and the source constructors stay the single source of truth.

## Devices that are discovered, not configured

An LSL outlet has no settings to pick — you choose which one to subscribe to.
Set `scan=True` and the picker draws a Scan button and a list of what
`discover()` found, instead of option dropdowns, then hands the choice to
`Stream.reconnect`:

```python
from myogestic.sources import LSLSource
from myogestic.widgets import DeviceSpec

LSL = DeviceSpec("LSL stream", lambda: LSLSource(""), scan=True,
             hint="Scan for outlets advertised on this network.")
```

This is declared, not detected. A source can implement `discover()` and still
be worth configuring statically, so the flag is yours to set.

## Watch the buffer at high channel counts

Ring-buffer memory scales with rate × channels, and the dropdowns put the
extremes one click apart. A `Stream` allocates roughly
`3 × fs × buffer_s × channels × 4` bytes, so the Quattrocento's top setting
(384 ch @ 10240 Hz) needs ~470 MB at the default 10 s buffer and ~2.8 GB at 60 s.

The default is 10 s. Raise `buffer_ms` for a specific recording, not by habit.

## One Connect per app

`SignalViewer` offers its own Connect button while a stream is detached — for an
app that is just `App` + `Stream` + a viewer, that is the only way to attach.
Once you add a picker, **turn it off**:

```python
viewer = SignalViewer("emg", show_connect=False)
```

The two buttons are not the same action. The viewer's attaches whatever source
the stream already holds; the picker's builds a new one from the dropdown. They
agree right up until somebody changes the dropdown, and then one of them
silently connects a device nobody chose.

## Streams that come and go

An app can declare its streams up front — `app.streams(Stream("emg", ...))` has
always taken as many as you like — or let the operator add them while it runs:

```python
from myogestic import Stream
from myogestic.widgets import StreamManager

streams = StreamManager(
    on_add=lambda name: app.add_stream(Stream(name, source=..., window_ms=200)),
    on_remove=app.remove_stream,
)
```

`StreamManager` only names the stream; the app builds it, because the geometry —
window and buffer length — is the app's decision, not the panel's. Pair it with
`DevicePicker(selectable=True)`, which gains a **Stream** row so one picker
follows whichever stream you are setting up instead of needing one panel each.

**Both are refused while a recording is running.** A session sizes one Zarr array
per stream when recording starts, so a stream that appears afterwards has
nowhere to write, and one that vanishes mid-take keeps the session attached and
is never finalised. `App.add_stream` and `App.remove_stream` return `False` and
put the reason in `ctx.status_message`.

One asymmetry worth knowing: `App.run` starts every registered stream once on
the way in, so `add_stream` starts the stream itself *only* when the app is
already running. Called during setup it behaves exactly like `app.streams(...)`.

## Recording

**Connect** is disabled while a recording is running. Reconnecting does not
detach the session, so the acquire loop would keep appending to the same key at
the new channel width and corrupt what you recorded. Stop, switch, start again.
