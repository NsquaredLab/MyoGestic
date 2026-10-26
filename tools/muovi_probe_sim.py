"""Fake Muovi / Muovi+ probe, to reproduce device bugs without the hardware.

`MuoviSource` is the TCP *server* (the real probe dials in), so this sim can
drive any unmodified example: run the app, pick "Muovi+ — 64 ch" in the
DevicePicker, press Connect, then start this in a second terminal:

    uv run python tools/muovi_probe_sim.py            # Muovi+: 200 pkt/s x 10 samples
    uv run python tools/muovi_probe_sim.py --device muovi   # 111 pkt/s x 18 samples

Wire format matches the real device: big-endian int16, bio+6 aux channels
interleaved per sample instant, 2000 Hz EMG. Packet cadence matches what the
hardware actually sends (Muovi+ = 10 samples every 5 ms; Muovi = 18 every 9 ms).
`--rate-scale 1.02` runs the simulated crystal 2% fast — real probes drift.

The sim keeps re-dialling, so start order doesn't matter, and it survives the
app's Disconnect/Connect buttons. If the app stops draining the socket the
send schedule slips; the sim prints a BACKPRESSURE line when that happens —
that line appearing at the moment the hand freezes is itself a diagnosis.

`--self-check` runs an in-process MuoviSource against the sim for ~2 s and
asserts the delivered sample rate, so a pacing bug can't produce a repro of
nothing.
"""

from __future__ import annotations

import argparse
import socket
import time

import numpy as np

from myogestic.sources.otb import _constants as C

RNG = np.random.default_rng(0)


def _packet(geo, n_samples: int, counter_start: int, t0: float) -> bytes:
    """One wire packet: (n_samples, n_total) BE int16, bio noise + aux counter.

    Bio channels are gaussian noise (~100 LSB ≈ 29 µV RMS) under a slow 0.5 Hz
    envelope, so viewers visibly scroll and features visibly vary — a frozen
    hand must be distinguishable from a merely boring one.
    """
    env = 0.6 + 0.4 * np.sin(2 * np.pi * 0.5 * t0)
    raw = np.zeros((n_samples, geo.n_total), dtype=np.int16)
    bio = RNG.normal(0.0, 100.0 * env, size=(n_samples, geo.n_bio))
    raw[:, : geo.n_bio] = np.clip(bio, -32000, 32000).astype(np.int16)
    counters = (counter_start + np.arange(n_samples)) % 65536
    raw[:, -1] = counters.astype(np.uint16).view(np.int16)  # sample counter aux
    return raw.astype(">i2").tobytes()


def stream_once(host: str, port: int, *, plus: bool, rate_scale: float) -> None:
    """Dial in, wait for GO, then stream packets until the socket dies."""
    samples_per_packet = 10 if plus else 18
    geo = C.muovi_geometry(plus=plus, emg=True, mode=0)
    interval = samples_per_packet / (geo.fs * rate_scale)

    sock = socket.create_connection((host, port), timeout=5.0)
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    print(f"[sim] connected to {host}:{port}, waiting for GO byte...")
    sock.settimeout(60.0)
    go = sock.recv(1)
    if not go:
        raise OSError("server closed before GO")
    print(f"[sim] got control byte 0x{go[0]:02x}, streaming "
          f"{geo.n_total} ch x {samples_per_packet} samples every {interval * 1000:.1f} ms")

    sock.settimeout(None)
    counter = 0
    sent_packets = 0
    start = time.perf_counter()
    next_t = start
    last_report = start
    warned_backpressure = False
    while True:
        now = time.perf_counter()
        if next_t > now:
            time.sleep(next_t - now)
        elif now - next_t > 1.0:
            # sendall blocked: the app is not draining the socket. This is the
            # device's-eye view of a freeze — worth shouting about.
            if not warned_backpressure:
                print(f"[sim] BACKPRESSURE: send schedule slipped {now - next_t:.1f}s "
                      f"behind at t={now - start:.1f}s — the app has stopped reading")
                warned_backpressure = True
            next_t = now  # re-anchor rather than burst-flood after a stall
        else:
            warned_backpressure = False  # schedule recovered; report the next stall too
        t0 = counter / geo.fs
        sock.sendall(_packet(geo, samples_per_packet, counter, t0))
        counter += samples_per_packet
        sent_packets += 1
        next_t += interval
        if now - last_report >= 5.0:
            print(f"[sim] t={now - start:5.1f}s  {sent_packets / (now - start):5.1f} pkt/s  "
                  f"{counter} samples sent")
            last_report = now


def run(host: str, port: int, *, plus: bool, rate_scale: float) -> None:
    """Keep dialling forever, like a probe in AP mode: start order never matters."""
    while True:
        try:
            stream_once(host, port, plus=plus, rate_scale=rate_scale)
        except (OSError, ConnectionError) as e:
            print(f"[sim] connection ended ({e.__class__.__name__}: {e}); redialling in 0.5s")
            time.sleep(0.5)


def self_check(*, plus: bool, rate_scale: float) -> None:
    """Loop the sim through a real MuoviSource and assert the delivered rate."""
    import threading

    from myogestic.sources.otb import MuoviSource

    src = MuoviSource(host_ip="127.0.0.1", port=0, plus=plus, emg=True, mode=0)
    src.connect_listen()
    port = src._server.getsockname()[1]
    t = threading.Thread(
        target=run, args=("127.0.0.1", port), kwargs={"plus": plus, "rate_scale": rate_scale},
        daemon=True,
    )
    t.start()
    info = src.accept_and_start()
    expected_ch = 64 if plus else 32
    assert info.n_channels == expected_ch, (info.n_channels, expected_ch)

    n = 0
    t_start = time.perf_counter()
    while time.perf_counter() - t_start < 2.0:
        data, _ts = src.read()
        if data is not None:
            n += data.shape[0]
        time.sleep(0.002)
    elapsed = time.perf_counter() - t_start
    src.disconnect()
    rate = n / elapsed
    expected = 2000.0 * rate_scale
    print(f"[self-check] {n} samples in {elapsed:.2f}s = {rate:.0f} samp/s "
          f"(expected ~{expected:.0f})")
    assert abs(rate - expected) < expected * 0.03, f"rate off: {rate:.0f} vs {expected:.0f}"
    print("[self-check] OK")


def main() -> None:
    """Parse args and run the sim (or its self-check)."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=C.MUOVI_PORT)
    p.add_argument("--device", choices=["muovi+", "muovi"], default="muovi+",
                   help="muovi+ = 64 bio ch, 10 samp/pkt; muovi = 32 bio ch, 18 samp/pkt")
    p.add_argument("--rate-scale", type=float, default=1.0,
                   help="clock skew: 1.02 = device crystal 2%% fast")
    p.add_argument("--self-check", action="store_true")
    args = p.parse_args()
    plus = args.device == "muovi+"
    if args.self_check:
        self_check(plus=plus, rate_scale=args.rate_scale)
        return
    try:
        run(args.host, args.port, plus=plus, rate_scale=args.rate_scale)
    except KeyboardInterrupt:
        print("\n[sim] stopped")


if __name__ == "__main__":
    main()
