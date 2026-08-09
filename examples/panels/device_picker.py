"""``device_picker`` in isolation — pick a device, configure it, connect.

The list leads with the two entries that work without hardware:

* **Synthetic — test signal** — the shipped `SYNTHETIC_DEVICE`. Change the
  channel count or rate, press *Connect*, and the stream comes up with exactly
  that geometry. Connect again with different values to watch the source get
  swapped out and the old one closed.
* **Synthetic (scan first)** — the same source in the ``scan=True`` shape used
  for LSL: the target is discovered rather than configured, so *Connect* stays
  disabled until a scan has found something.

The real OTB entries follow. Selecting one shows its setup hint, and *Connect*
genuinely tries to reach the hardware — expect a timeout without it.

Run with:
    uv run python examples/panels/device_picker.py
"""

from functools import partial

from myogestic import App, Stream
from myogestic.sources import SyntheticSource
from myogestic.widgets import OTB_DEVICES, SYNTHETIC_DEVICE, DevicePicker, DeviceSpec

DEMO_DEVICES = (
    SYNTHETIC_DEVICE,
    DeviceSpec(
        "Synthetic (scan first)",
        partial(SyntheticSource, require_target=True),
        scan=True,
        hint="Discovers its target instead of configuring it, the way LSL does.",
    ),
    *OTB_DEVICES,
)

app = App("panel: device_picker")
app.streams(Stream("emg", source=DEMO_DEVICES[0].factory(), window_ms=1000))

picker = DevicePicker("emg", devices=DEMO_DEVICES)


@app.ui
def ui(ctx):
    picker.ui(ctx)


def main() -> None:
    app.run()


if __name__ == "__main__":
    main()
