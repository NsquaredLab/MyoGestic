"""Local-only reference measurements; never write recording samples to the site.

Usage: uv run python website/tests/field-reference.py SESSION [--serve PORT]
The optional loopback server exposes in-memory comparison windows to Playwright.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np

from myogestic.session import open_session_store


def describe(x):
    """Measure normalized tails and signed spatial/temporal correlation."""
    rms = np.sqrt(np.mean(x * x, axis=0))
    z = x / rms
    corr = np.corrcoef(x.T)
    return {
        "rms": float(np.sqrt(np.mean(x * x))),
        "p99_rms": float(np.quantile(np.abs(z), 0.99)),
        "p999_rms": float(np.quantile(np.abs(z), 0.999)),
        "kurtosis": float(np.mean(z**4)),
        "neighbour": float(np.diag(corr, 1).mean()),
        "lag1": float(np.mean([np.corrcoef(z[:-1, c], z[1:, c])[0, 1] for c in range(64)])),
    }


def main():
    """Read the supplied session and report derived, reproducible statistics."""
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("session")
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    session = open_session_store(args.session)
    info = session.stream_info("emg")
    x = np.asarray(session.stores["emg"][:], dtype=np.float64)
    t = np.asarray(session.ts_stores["emg"][:])
    labels = np.full(len(t), -1)
    events = session.label_track
    for i, event in enumerate(events):
        end = events[i + 1].timestamp if i + 1 < len(events) else t[-1] + 1
        # Exclude the first 0.65 s after a cue for stationary statistics.
        labels[(t >= event.timestamp + 0.65) & (t < end)] = event.class_index
    fist = session.class_names.index("Fist")
    rest = session.class_names.index("Rest")
    # Select the block on ALL labelled Fist samples; settling exclusion applies
    # only to stationary statistics, not the channel-selection criterion.
    fist_mask = np.zeros(len(t), dtype=bool)
    for i, event in enumerate(events[:-1]):
        if event.class_index == fist:
            fist_mask |= (t >= event.timestamp) & (t < events[i + 1].timestamp)
    energy = np.mean(x[fist_mask] ** 2, axis=0)
    blocks = np.convolve(energy, np.ones(64), mode="valid")
    start = int(np.argmax(blocks))
    x = x[:, start : start + 64]
    # Remove only the per-channel DC offset, just as a signal viewer centres traces.
    x -= np.median(x, axis=0)
    maps = {}
    for name, code in (("Rest", rest), ("Fist", fist)):
        maps[name] = np.sqrt(np.mean(x[labels == code] ** 2, axis=0))
    scale = np.max(maps["Fist"])
    normalized_maps = {name: np.round(rms / scale, 3).tolist() for name, rms in maps.items()}
    columns = np.floor(np.arange(len(x) * 120 / info.fs) * info.fs / 120).astype(int)
    columns = columns[columns < len(x) - 18]
    ends = np.floor((np.arange(len(columns)) + 1) * info.fs / 120).astype(int)
    sampled = x[columns]
    extrema = np.empty_like(sampled)
    for i, a in enumerate(columns):
        window = x[a : ends[i]]
        extrema[i] = window[np.argmax(np.abs(window), axis=0), np.arange(64)]
    stats = {}
    for name, data, lab in (
        ("sample", sampled, labels[columns]),
        ("minmax", extrema, labels[columns]),
        ("native", x, labels),
    ):
        stats[name] = {
            g: describe(data[lab == code]) for g, code in (("Rest", rest), ("Fist", fist))
        }
        stats[name]["ratio"] = stats[name]["Fist"]["rms"] / stats[name]["Rest"]["rms"]
    onsets = [e.timestamp for e in events if e.class_index == fist]
    offsets = [events[i + 1].timestamp for i, e in enumerate(events[:-1]) if e.class_index == fist]
    # 50 ms RMS; fit the 10--90% transition width / ln(9) after each cue.
    window = round(info.fs * 0.05)
    power = np.mean(x**2, axis=1)
    cs = np.concatenate(([0], np.cumsum(power)))
    env = np.sqrt((cs[window:] - cs[:-window]) / window)
    et = t[window // 2 : window // 2 + len(env)]
    taus = {}
    for name, cues in (("onset", onsets), ("offset", offsets)):
        widths = []
        delays = []
        for cue in cues:
            lo = np.median(env[(et > cue - 1.4) & (et < cue - 0.8)])
            hi = np.median(env[(et > cue + 0.8) & (et < cue + 1.2)])
            a = (env - lo) / (hi - lo)
            times = et[(et > cue - 0.8) & (et < cue + 1.2)]
            curve = a[(et > cue - 0.8) & (et < cue + 1.2)]
            # Both directions are normalized 0 -> 1 above.
            i10 = np.flatnonzero(curve >= 0.1)
            if not len(i10):
                continue
            i90 = np.flatnonzero((curve >= 0.9) & (np.arange(len(curve)) >= i10[0]))
            if len(i90):
                widths.append((times[i90[0]] - times[i10[0]]) / np.log(9))
                delays.append(times[i10[0]] - cue)
        taus[name] = {
            "tau_s": float(np.median(widths)),
            "delay_s": float(np.median(delays)),
            "repeats": len(widths),
        }
    result = {
        "block_zero_based": [start, start + 63],
        "fs": info.fs,
        "stats": stats,
        "maps": normalized_maps,
        "transitions": taus,
    }
    print(json.dumps(result), flush=True)
    if args.serve:
        cue = onsets[1]
        a = np.searchsorted(t, cue - 1.5)
        indices = a + np.floor(np.arange(480) * info.fs / 120).astype(int)
        ends = a + np.floor((np.arange(480) + 1) * info.fs / 120).astype(int)
        native = np.searchsorted(t, cue + 0.8) + np.arange(480)
        windows = {
            "sample": (x[indices] / scale).T.tolist(),
            "native": (x[native] / scale).T.tolist(),
            "min": (
                np.stack([np.min(x[i:j], axis=0) for i, j in zip(indices, ends, strict=True)])
                / scale
            ).T.tolist(),
            "max": (
                np.stack([np.max(x[i:j], axis=0) for i, j in zip(indices, ends, strict=True)])
                / scale
            ).T.tolist(),
        }
        payload = json.dumps({"metrics": result, "windows": windows}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

        HTTPServer(("127.0.0.1", args.serve), Handler).serve_forever()
    session.close()


if __name__ == "__main__":
    main()
