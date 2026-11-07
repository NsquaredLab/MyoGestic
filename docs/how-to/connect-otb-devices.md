---
title: "Connect OT Bioelettronica devices"
---
Use OTB Muovi/Muovi+ and Quattrocento directly as a `Source` in a `Stream`.

## Muovi / Muovi+ (Wi-Fi)

The PC is the TCP server; the probe connects to it.

1. Hold the probe button ~5 s → it becomes a Wi-Fi access point `MVxxx-ID`.
2. Join that network from the PC.
3. ```python
   from myogestic import Stream
   from myogestic.sources.otb import MuoviSource
   stream = Stream("emg", source=MuoviSource(plus=False, emg=True, mode=0),
                   window_ms=1000)
   if not stream.reconnect():
       raise RuntimeError(stream.last_error)
   stream.start()
   ```

Defaults: 32-ch (Muovi) monopolar gain-8 EMG @ 2000 Hz, biosignal-only
(286.1 nV/LSB → mV). Pass `plus=True` for 64-ch Muovi+, `emg=False` for EEG
(500 Hz, 24-bit), `include_aux=True` to also stream IMU/buffer/counter.

## Sessantaquattro / Sessantaquattro+ (Wi-Fi)

The PC is the TCP server on port 45454; the device connects in.

1. Join the device's access point, or set the PC's IP as "Server IP address" on
   the sessantaquattro's internal web page.
2. ```python
   from myogestic import Stream
   from myogestic.sources.otb import SessantaquattroSource
   stream = Stream("emg", source=SessantaquattroSource(nch_mode=3, fs_mode=2),
                   window_ms=1000)
   if not stream.reconnect():
       raise RuntimeError(stream.last_error)
   stream.start()
   ```

Defaults: 64-ch monopolar gain-8 EMG @ 2000 Hz, 16-bit, biosignal-only
(286.1 nV/LSB → mV). `nch_mode` 0..3 → 8/16/32/64 bioelectrical channels;
`fs_mode` 0..3 → 500/1000/2000/4000 Hz. `mode="bipolar"` halves the channel
count, `mode="differential"` does not, and `mode="accelerometer"` pins it to 8
at four times the rate. `high_res=True` switches to 24-bit. `include_aux=True`
appends 2 AUX channels, the IMU quaternion, buffer/trigger and sample counter.
Divide quaternion values by 16384 for a unit quaternion.

The source probes the accessory-channel count. Both protocol
documents state "2 AUX + 2 accessory" for every NCH value, but a
Sessantaquattro+ transmits eight. Since the frame is a flat run of words, a
wrong count silently de-interleaves samples into the wrong channels. The last accessory channel is a ramp counter, so the source tries
each candidate width on the first 32 samples and keeps the one that yields a
clean ramp, raising if none does.

The counter also detects loss. `source.dropped_samples` and
`source.dropout_events` report samples the device produced that never arrived.
The first gap is logged as a warning. Check both counters after a session;
sample loss may be invisible in the traces.

## Quattrocento (Ethernet)

The PC is the TCP client to the amplifier (default `169.254.1.10:23456`).
Give the PC NIC a `169.254.x.x` address on that segment.

```python
from myogestic import Stream
from myogestic.sources.otb import QuattrocentoSource

stream = Stream(
    "emg", source=QuattrocentoSource(fs_mode=1, nch_mode=1), window_ms=1000
)  # 2048 Hz, 192 biosignal channels (216 on the wire)
if not stream.reconnect():
    raise RuntimeError(stream.last_error)
stream.start()
```

`nch_mode` 0..3 → 120/216/312/408 streamed channels; `fs_mode` 0..3 →
512/2048/5120/10240 Hz. Biosignal-only by default exposes the grid channels
(96/192/288/384 for nch_mode 0..3) scaled to mV; `include_aux=True` also appends
the 16 AUX IN (analog, scaled to V) and the 8 accessory channels (counter /
trigger / buffer, raw). Always stop the stream before reconnecting.

> Protocol references: `docs/reference/otb/`.
