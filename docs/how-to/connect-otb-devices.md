# Connect OT Bioelettronica devices

MyoGestic talks to OTB Muovi/Muovi+ and Quattrocento natively — no Qt, no
external bridge. Each device is a `Source` you drop into a `Stream`.

## Muovi / Muovi+ (Wi-Fi)

The PC is the TCP **server**; the probe connects to it.

1. Hold the probe button ~5 s → it becomes a Wi-Fi access point `MVxxx-ID`.
2. Join that network from the PC.
3. ```python
   from myogestic import Stream
   from myogestic.sources.otb import MuoviSource
   stream = Stream("emg", source=MuoviSource(plus=False, emg=True, mode=0),
                   window_ms=1000)
   stream.start()
   ```

Defaults: 32-ch (Muovi) monopolar gain-8 EMG @ 2000 Hz, biosignal-only
(286.1 nV/LSB → mV). Pass `plus=True` for 64-ch Muovi+, `emg=False` for EEG
(500 Hz, 24-bit), `include_aux=True` to also stream IMU/buffer/counter.

## Quattrocento (Ethernet)

The PC is the TCP **client** to the amplifier (default `169.254.1.10:23456`).
Give the PC NIC a `169.254.x.x` address on that segment.

```python
from myogestic.sources.otb import QuattrocentoSource
stream = Stream("emg", source=QuattrocentoSource(fs_mode=1, nch_mode=1),
                window_ms=1000)  # 2048 Hz, 216 streamed ch
stream.start()
```

`nch_mode` 0..3 → 120/216/312/408 streamed channels; `fs_mode` 0..3 →
512/2048/5120/10240 Hz. Biosignal-only by default exposes the grid channels
(96/192/288/384 for nch_mode 0..3) scaled to mV; `include_aux=True` also appends
the 16 AUX IN (analog, scaled to V) and the 8 accessory channels (counter /
trigger / buffer, raw). Always stop the stream before reconnecting.

> Protocol references: `docs/reference/otb/`.
