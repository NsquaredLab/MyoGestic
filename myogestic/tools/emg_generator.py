"""Controllable EMG signal generator.

Outputs fake EMG via LSL. Reads a control stream to switch between class
patterns. Default behavior is binary (rest / fist) — pass ``--classes N``
to generate ``N`` deterministic class-specific channel-group activations.

Usage:
    # Binary (default — rest=0, fist=1):
    python -m myogestic.tools.emg_generator --name TestEMG1 --channels 8 --fs 256
    # 4-class (rest, fist, pinch, open):
    python -m myogestic.tools.emg_generator --name TestEMG32 --channels 32 \\
        --classes 4 --fs 256 --control EMG_Control
"""

from __future__ import annotations

import argparse
import sys
import time

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamInlet, StreamOutlet, resolve_streams

# liblsl prints multicast-bind WARN/INFO lines to stderr whenever a second
# LSL process joins the same multicast group on the box (e.g. GUI + this
# generator). They're harmless — the streams still flow — but mne-lsl's
# bundled liblsl doesn't honour LSL_LOG_LEVEL so there's no clean way to
# suppress them from Python. Ignore them in the terminal.


def _class_pattern(class_idx: int, n_classes: int, channels: int) -> np.ndarray:
    """Deterministic per-class channel-activation envelope of shape ``(channels,)``.

    Class 0 is "rest" — all-zeros, so callers can short-circuit to a low-noise
    floor. Classes 1..n_classes-1 each activate a contiguous channel group via
    a smooth bump centred on a different fraction of the channel axis. Same
    inputs always give the same array (no RNG, no global state) so trials
    across runs are reproducible.
    """
    if class_idx <= 0 or n_classes <= 1 or channels <= 0:
        return np.zeros(channels, dtype=np.float32)
    n_active = max(1, n_classes - 1)
    centre = (class_idx - 1 + 0.5) / n_active
    width = 1.0 / max(1, n_active * 1.5)
    x = np.linspace(0.0, 1.0, channels, dtype=np.float32)
    pattern = np.exp(-((x - centre) ** 2) / (2.0 * width * width))
    pattern *= 1.0 / float(np.max(pattern))
    return pattern.astype(np.float32)


def _read_mode(inlet: StreamInlet | None, n_classes: int, mode_idx: int) -> int:
    """Pull latest control sample (if any) and clamp to a class index."""
    if inlet is None:
        return mode_idx
    try:
        data, ts = inlet.pull_chunk(timeout=0.0)
    except Exception:
        return mode_idx
    if ts is None or len(ts) == 0:
        return mode_idx
    raw = float(np.asarray(data)[-1, 0])
    idx = int(round(raw))
    return max(0, min(n_classes - 1, idx))


def _read_bitmask(inlet: StreamInlet | None, n_dofs: int, mask: int) -> int:
    """Pull latest control sample and return it as a DoF bitmask (n_dofs bits).

    Used by --multi-dof mode. Inverse of `_read_mode`; the same control-stream
    sample value is interpreted as ``int(round(value))`` and masked to keep
    only the low ``n_dofs`` bits.
    """
    if inlet is None:
        return mask
    try:
        data, ts = inlet.pull_chunk(timeout=0.0)
    except Exception:
        return mask
    if ts is None or len(ts) == 0:
        return mask
    raw = float(np.asarray(data)[-1, 0])
    return max(0, int(round(raw))) & ((1 << n_dofs) - 1)


DEFAULT_CONTROL_STREAM = "EMG_Control"


def control_outlet(name: str = DEFAULT_CONTROL_STREAM) -> StreamOutlet:
    """LSL outlet for steering the EMG generator from another script.

    The generator listens on a stream named ``name`` for a single float
    (channel = 1) that selects the next gesture amplitude — typically
    ``0.0`` (rest) … ``1.0`` (full). Push samples like::

        from myogestic.tools.emg_generator import control_outlet
        out = control_outlet()
        out.push_sample(np.array([0.0], dtype=np.float32))  # rest
        out.push_sample(np.array([1.0], dtype=np.float32))  # fist

    Matches the protocol the ``--control`` flag on
    ``python -m myogestic.tools.emg_generator`` listens for.
    """
    return StreamOutlet(
        sinfo=StreamInfo(
            name=name,
            stype="Control",
            n_channels=1,
            sfreq=0,
            dtype="float32",
            source_id="ctrl",
        )
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Controllable EMG generator")
    parser.add_argument("--name", default="TestEMG1", help="Output stream name")
    parser.add_argument("--channels", type=int, default=8)
    parser.add_argument("--fs", type=float, default=256)
    parser.add_argument("--chunk", type=int, default=32)
    parser.add_argument(
        "--classes",
        type=int,
        default=2,
        help="Number of distinct classes (default 2 = rest/fist).",
    )
    parser.add_argument(
        "--control",
        default="EMG_Control",
        help="Control stream name (1ch float; sample value = class index).",
    )
    parser.add_argument(
        "--multi-dof",
        action="store_true",
        help=(
            "Interpret control-stream value as a *bitmask* over DoFs: bit i "
            "set ⇒ DoF i active. Each active DoF contributes its class-1+i "
            "Gaussian pattern additively, so control=5 (0b101) activates "
            "DoFs 0 and 2 simultaneously. Number of DoFs = `--classes - 1` "
            "(class 0 is rest)."
        ),
    )
    args = parser.parse_args()

    n_classes = max(2, int(args.classes))

    # Refuse to double-publish: if a stream with the same name is already
    # alive on the network, exit before constructing a second outlet.
    # liblsl will happily let you publish two outlets with the same name —
    # subscribers latch onto whichever they discover first, so the new
    # process's data silently goes nowhere. Cheap probe (200 ms) that
    # avoids surprising the user when they click "EMG Generator" twice
    # or forget to stop a previous run.
    existing = resolve_streams(timeout=0.2, name=args.name)
    if existing:
        print(
            f"[emg_generator] stream '{args.name}' is already published; "
            f"exiting. Stop the other instance (or pass --name OTHER) to start "
            f"a second generator.",
            file=sys.stderr,
        )
        return

    out_info = StreamInfo(args.name, "EMG", args.channels, args.fs, "float32", "emg_gen")
    outlet = StreamOutlet(out_info)

    patterns = np.stack(
        [_class_pattern(i, n_classes, args.channels) for i in range(n_classes)],
        axis=0,
    )

    inlet: StreamInlet | None = None
    mode_idx = 0  # legacy single-class mode
    mask = 0  # multi-DoF mode (bitmask over `n_classes - 1` DoFs)
    n_dofs = max(1, n_classes - 1)  # only used when --multi-dof is set

    interval = args.chunk / args.fs
    mode_label = "multi-DoF bitmask" if args.multi_dof else "class index"
    print(
        f"EMG generator: {args.name} · {args.channels} ch · {args.fs} Hz · "
        f"{n_classes} classes ({mode_label})"
    )
    print(f"Listening for control on '{args.control}' (sample value = {mode_label})")
    print("Generating rest signal...")

    rng = np.random.default_rng()
    try:
        while True:
            t0 = time.perf_counter()

            if inlet is None:
                streams = resolve_streams(timeout=0.1, name=args.control)
                if streams:
                    inlet = StreamInlet(streams[0])
                    print(f"Connected to control stream '{args.control}'")
            else:
                try:
                    if args.multi_dof:
                        mask = _read_bitmask(inlet, n_dofs, mask)
                    else:
                        mode_idx = _read_mode(inlet, n_classes, mode_idx)
                except Exception:
                    inlet = None

            noise = rng.standard_normal((args.chunk, args.channels)).astype(np.float32)
            if args.multi_dof:
                # Sum patterns of all set bits. Each active DoF i contributes
                # the class-(i+1) Gaussian (class 0 reserved for rest).
                if mask == 0:
                    chunk = noise * np.float32(0.02)
                else:
                    summed_pattern = np.zeros(args.channels, dtype=np.float32)
                    for i in range(n_dofs):
                        if mask & (1 << i):
                            summed_pattern += patterns[i + 1]
                    base = noise * np.float32(0.15)
                    burst = (
                        rng.standard_normal((args.chunk, args.channels)).astype(np.float32)
                        * summed_pattern
                    )
                    chunk = base + burst + np.float32(0.15) * summed_pattern
            elif mode_idx == 0:
                chunk = noise * np.float32(0.02)
            else:
                pattern = patterns[mode_idx]
                base = noise * np.float32(0.15)
                burst = (
                    rng.standard_normal((args.chunk, args.channels)).astype(np.float32)
                    * pattern
                )
                chunk = base + burst + np.float32(0.15) * pattern

            for sample in chunk:
                outlet.push_sample(sample)

            elapsed = time.perf_counter() - t0
            if elapsed < interval:
                time.sleep(interval - elapsed)

    except KeyboardInterrupt:
        print("EMG generator stopped")


if __name__ == "__main__":
    main()
