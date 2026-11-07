"""Derive a field fit from local groups of 8-channel forearm bracelet recordings.

Supply one --group followed by its takes for each recording set. Only derived
maps and scalar statistics are printed. --serve exposes comparison arrays only
in memory on loopback; never save that response or publish the bridge.
"""

import argparse
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

import numpy as np
from scipy.signal import butter, filtfilt, iirnotch, sosfiltfilt, welch

from myogestic.session import open_session_store

GESTURES = ("Rest", "Fist", "Pinch", "Index")


def spread(x, channels=64):
    """Interpolate signed electrode signals on a closed bracelet, including 7→0."""
    position = np.arange(channels) * 8 / channels
    lo = position.astype(int)
    mix = position - lo
    return x[:, lo] * (1 - mix) + x[:, (lo + 1) % 8] * mix


def describe(x):
    """Stationary signed correlations and per-channel RMS-normalized tails."""
    rms = np.sqrt(np.mean(x * x, axis=0))
    z = x / rms
    n = x.shape[1]
    return {
        "rms": float(np.sqrt(np.mean(x * x))),
        "p99": float(np.quantile(np.abs(z), 0.99)),
        "p999": float(np.quantile(np.abs(z), 0.999)),
        "kurtosis": float(np.mean(z**4)),
        "neighbour": float(np.mean([
            np.corrcoef(x[:, c], x[:, (c + 1) % n])[0, 1] for c in range(n)
        ])),
        "lag1": float(np.mean([
            np.corrcoef(x[:-1, c], x[1:, c])[0, 1] for c in range(n)
        ])),
    }


def spectrum(x, fs):
    """Measure the pooled stationary spectrum in the EMG passband."""
    frequencies, power = welch(x, fs=fs, nperseg=min(1024, len(x)), axis=0)
    keep = (frequencies >= 20) & (frequencies <= 450)
    power = power[keep].mean(axis=1)
    return {
        "peak_hz": float(frequencies[keep][np.argmax(power)]),
        "flatness": float(np.exp(np.mean(np.log(np.maximum(power, 1e-30)))) / np.mean(power)),
    }


def read_group(paths):
    """Read one bracelet placement, rejecting incomplete gesture sets."""
    takes = {gesture: [] for gesture in GESTURES}
    for path in paths:
        session = open_session_store(path)
        try:
            info = session.stream_info("emg")
            if info.n_channels != 8 or info.fs != 1000:
                raise ValueError("Expected eight electrodes sampled at 1000 Hz")
            events = session.label_track
            names = {
                session.class_names[e.class_index].replace("Index Flex", "Index")
                for e in events if 0 <= e.class_index < len(session.class_names)
            }
            if len(names) != 1 or not names.issubset(GESTURES):
                continue
            gesture = names.pop()
            raw = np.asarray(session.stores["emg"][:], dtype=np.float64)
            timestamps = np.asarray(session.ts_stores["emg"][:])
            x = sosfiltfilt(butter(4, [20, 450], fs=info.fs, btype="bandpass", output="sos"), raw, axis=0)
            for frequency in range(50, 451, 50):
                b, a = iirnotch(frequency, 30, info.fs)
                x = filtfilt(b, a, x, axis=0)
            # The single label identifies the take, not a rest→active transition.
            # Trim 650 ms at the start and 100 ms at the end before statistics.
            first = max(timestamps[0], min(e.timestamp for e in events)) + 0.65
            keep = (timestamps >= first) & (timestamps < timestamps[-1] - 0.1)
            takes[gesture].append((x[keep], raw[keep]))
        finally:
            session.close()
    if any(not rows for rows in takes.values()):
        return None
    rows = {g: np.concatenate([x for x, _ in takes[g]]) for g in GESTURES}
    maps = {g: np.sqrt(np.mean(x * x, axis=0)) for g, x in rows.items()}
    scale = max(maps["Fist"])
    maps = {g: x / scale for g, x in maps.items()}
    separation = min(
        np.sqrt(np.mean((maps[a] - maps[b]) ** 2))
        for i, a in enumerate(GESTURES) for b in GESTURES[i + 1:]
    )
    stats = {}
    for gesture in GESTURES:
        # Reset the point-sampling clock at each take boundary. No anti-aliasing:
        # this is the existing 480 columns / four seconds display policy.
        sampled = []
        for x, _ in takes[gesture]:
            indices = np.floor(np.arange(int(len(x) * 120 / 1000)) * 1000 / 120).astype(int)
            sampled.append(x[indices] / scale)
        y = np.concatenate(sampled)
        stats[gesture] = {
            "native": describe(rows[gesture] / scale),
            "electrodes": describe(y),
            "lanes": describe(spread(y)),
            "raw_spectrum": spectrum(np.concatenate([raw for _, raw in takes[gesture]]), 1000),
            "filtered_spectrum": spectrum(rows[gesture], 1000),
            "takes": len(takes[gesture]),
            "stationary_seconds": len(rows[gesture]) / 1000,
        }
    for domain in ("native", "electrodes", "lanes"):
        for gesture in GESTURES:
            stats[gesture][domain]["active_rest_ratio"] = (
                stats[gesture][domain]["rms"] / stats["Rest"][domain]["rms"]
            )
    metrics = {
        "maps": {g: np.round(x, 4).tolist() for g, x in maps.items()},
        "min_map_distance": float(separation), "stats": stats,
        "transitions": {"estimable": False, "onset_tau_s": 0.018, "offset_tau_s": 0.018},
    }
    # One second per gesture, same time scale and circular interpolation on both
    # sides of the comparison. These excerpts stay in process memory only.
    windows = []
    for gesture in GESTURES:
        x = takes[gesture][0][0]
        indices = np.floor(np.arange(120) * 1000 / 120).astype(int)
        if indices[-1] >= len(x):
            raise ValueError("Comparison needs one stationary second per gesture")
        windows.append(spread(x[indices] / scale))
    return metrics, np.concatenate(windows).T.tolist()


def main():
    """Select the most distinct complete map set and optionally serve a view."""
    parser = argparse.ArgumentParser(__doc__)
    parser.add_argument("--group", nargs="+", action="append", required=True)
    parser.add_argument("--serve", type=int)
    args = parser.parse_args()
    groups = [read_group(paths) for paths in args.group]
    complete = [(i, row) for i, row in enumerate(groups) if row is not None]
    if not complete:
        parser.error("No recording set contains all four gestures")
    selected, (metrics, window) = max(complete, key=lambda item: item[1][0]["min_map_distance"])
    metrics["selection"] = {
        "group_index": selected, "complete_groups": len(complete),
        "criterion": "largest minimum pairwise distance between Fist-normalized RMS maps",
        "candidate_distances": [round(row[0]["min_map_distance"], 4) for _, row in complete],
    }
    print(json.dumps(metrics), flush=True)
    if args.serve:
        payload = json.dumps({"metrics": metrics, "window": window}).encode()

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, *_):
                pass

        HTTPServer(("127.0.0.1", args.serve), Handler).serve_forever()


if __name__ == "__main__":
    main()
