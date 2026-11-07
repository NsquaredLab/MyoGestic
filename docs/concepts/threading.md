---
title: "Threading"
---
On desktop, acquisition, prediction and sending use stdlib `threading`; the hot path uses no multiprocessing. The browser playground schedules those steps on the GUI frame loop instead of creating OS threads. Subprocess isolation is reserved for "bridges" - heavy-data sources like webcams or ultrasound that would otherwise saturate a thread.

## What runs where

```mermaid
flowchart LR
    subgraph MAIN["Main thread"]
        UI["GUI event loop<br/>ImGui render, button clicks<br/>display snapshots"]
    end

    subgraph DAEMONS["Daemon threads (desktop)"]
        direction TB
        AT["Acquisition thread (per Stream)<br/>source.read → ring buffer<br/>→ optional Zarr append"]
        PT["Predict thread (only with Pipeline)<br/>get_window → extract → predict<br/>→ pipeline.predictions"]
        TT["Training thread (one run)<br/>train → pipeline.model"]
        OT["Output thread (per Outlet)<br/>latest-value slot → transport @ hz"]
    end

    subgraph BRIDGE["Subprocess (optional)"]
        BR["Bridge process<br/>webcam → Zarr<br/>+ LSL clock timestamps"]
    end

    AT --> CTX["ctx.streams[name]<br/>(threading.Lock)"]
    CTX --> PT
    CTX --> UI
    PT -.->|push| OT
    BR -.->|LSL clock| AT
```


| Thread | Owner | Job |
|--------|-------|-----|
| Main | OS | GUI event loop, ImGui render, button clicks |
| Acquisition (one per `Stream`) | `Stream` | source.read → ring buffer → optional Zarr append |
| Predict | `Pipeline` | extract → predict → write to `pipeline.predictions` |
| Training (transient) | `Pipeline` | train → assign to `pipeline.model` |
| Output (one per `Outlet`) | user-owned `Outlet` | drain `_latest` to its destination at `hz` |
| Bridge subprocess (optional) | `Bridge` | webcam decode → Zarr → publish LSL clock |

The framework's acquisition, prediction, training and output threads are daemons. App cleanup stops an open recording inline and waits up to 30 seconds for pending saves before stopping streams. The predict thread is started via `app.before_run_hooks` (at `app.run()`, not on first Predict click) and joined with a short timeout via a `threading.Event` flag on cleanup. Acquisition and output threads are daemons that exit when the process does; their `stop()` methods set a sentinel but don't `join()`.

## Why the GIL does not serialise these threads

Python's Global Interpreter Lock would be a problem if any of these threads spent CPU time in pure Python. They don't:

- **NumPy** releases the GIL inside C extensions (`np.copy`, `np.fft.rfft`, `np.dot`). The ring buffer copy in `get_window` is GIL-released.
- **PyTorch CUDA** runs on the GPU; the Python thread is mostly waiting for the kernel.
- **LSL** (`pylsl` and `mne_lsl`) is a C library; `pull_chunk` releases the GIL.
- **ImGui / ImPlot** are C++; the render thread spends its time in C++ frame building.
- **OpenCV** (used by `WebCamBridge`) releases the GIL in `cv2.VideoCapture.read`.

The Python interpreter is mostly orchestrating - handing buffers between threads. The actual compute happens in GIL-released code, so the threads run in parallel on multi-core machines.

## Synchronisation

`Context`, `Pipeline` and stream/session objects share state using these conventions:

1. **Reference assignment is atomic in CPython.** `pipeline.model = trained` doesn't tear; readers either see the old reference or the new one. Same for `pipeline.predictions = {...}`.
2. **Ring buffer reads/writes hold a `threading.Lock`.** ~1–5 µs overhead per access - invisible against the µs–ms latencies of real workloads.
3. **`ctx.state` transitions go through the App and Pipeline start/stop methods.** Callers don't poke `ctx.state = "..."` directly. State changes are point-in-time; there's no "stop in progress" intermediate state.

Stream buffers, attached sessions, event buffers and connection attempts have their own locks. Prediction shutdown uses a `threading.Event`; following runs also have cancellation events. Outputs pass values through a latest-value slot rather than a per-sample queue.

## The GPU contention rule

**Predicting pauses while training runs.** This is a hard rule, not a soft hint:

```text
ctx.state ∈ {"idle", "recording", "training", "predicting"}
                                    │           │
                                    └─ exclusive ┘
```

Train is disabled while predicting. Stop prediction and any open recording first, then train. When training completes, click Predict to resume.

Why: PyTorch CUDA streams can be juggled, but the engineering complexity isn't worth it for a single-user experiment app. Predict throughput drops to zero during training, which lasts seconds-to-minutes; that's acceptable for the use case. The state machine refuses parallel attempts so you can't accidentally OOM the GPU.

## Bridge subprocesses

Heavy-data sources break the GIL-release assumption - webcam decoding, even with OpenCV, can saturate the Python thread enough to disrupt the predict thread. For heavy-data sources that break that assumption, use a subprocess:

```python
cam = WebCamBridge("cam", device=0, zarr_path="session/cam.zarr")
app.bridges(cam)
```

The bridge process:

- Owns its own Python interpreter (no GIL contention with the main app).
- Writes frames directly to a Zarr array - that's the persistence step.
- Publishes one LSL clock timestamp per captured frame for alignment.

The main app never touches the camera frames; it reads per-frame LSL clock timestamps and can look up the corresponding frames in Zarr if the experiment needs them. Registering a bridge does not start it — call `cam.start()` when you want it up; `app.run()` stops it on cleanup. Nothing renders a bridge for you: `bridge.status` and `bridge.alive` are there if you want to show them, and a stop that does not land is logged.

## Common mistakes

See also: full **[Troubleshooting](../troubleshooting.md)** index, organised by symptom across every subsystem.

- **`time.sleep` in `@pipeline.predict`.** It blocks the predict thread. The framework already paces ticks at `predict_hz`; if you need rate-limiting, change `predict_hz` or use a state machine that returns the previous prediction on stale ticks.
- **Touching ImGui from a non-main thread.** ImGui is not thread-safe. Widgets only run inside `@app.ui`, which is the render thread. Predict-thread code must NOT call `imgui.*`.
- **Long blocking I/O inside a Source's `read`.** It pauses the acquisition thread, which pauses ring-buffer updates, which delays prediction. Sources should poll non-blockingly (e.g. `pylsl.pull_chunk(timeout=0.0)`).
- **Holding the ring buffer lock during compute.** The lock is taken inside `get_window` for the copy; release happens before the function returns. User code holds no buffer lock.
