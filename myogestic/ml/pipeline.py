"""Opt-in ML pipeline layer for myogestic.

Core `App` knows only idle ↔ recording. Create a `Pipeline(app)` to add
training/predicting lifecycle + a predict daemon thread:

    from myogestic import App, Stream, TrainingData
    from myogestic.ml import Pipeline

    app = App("EMG Demo")
    app.streams(Stream(...))
    pipeline = Pipeline(app)

    @pipeline.extract
    def extract(windows: dict[str, np.ndarray]):  ...   # channels-first

    @pipeline.train
    def train(data: TrainingData):                ...   # data.paths / .classes

    @pipeline.predict
    def predict(model, features) -> dict:         ...

    @app.ui
    def ui(ctx):
        pipeline.training_data = session_manager(...)   # publishes selection

    app.run()

ML widgets (`myogestic.ml.widgets`) take `pipeline`, not `app`.

See also: `myogestic.recipes` for estimator constructor recipes (CatBoost/sklearn)
and feature recipes. Model persistence lives here: `save_pickle` / `load_pickle`.
"""

from __future__ import annotations

import json
import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable, Mapping
from enum import StrEnum
from typing import TYPE_CHECKING, Any

import numpy as np

from myogestic.contracts import TrainingData
from myogestic.core import RECORDABLE_STATES, AppState

if TYPE_CHECKING:
    from myogestic.core import App
    from myogestic.session import Session

log = logging.getLogger("myogestic.ml")

# Pyodide reports sys.platform == "emscripten" and forbids OS threads.
# When detected, the predict loop runs as an asyncio task instead.
_IS_BROWSER = sys.platform == "emscripten"


def _event_row(value: Any) -> np.ndarray | None:
    """One float32 row for a recordable value, or ``None`` for one that is not.

    Recordable: a bool, a number, or an array-like of numbers with at most one dimension.
    Not recordable: text, ``None``, nested mappings, and anything 2-D or wider — a raw window
    is already the recorded stream, and a CNN history is rebuilt from consecutive frames.
    """
    if isinstance(value, (str, bytes, Mapping)) or value is None:
        return None
    if isinstance(value, (bool, int, float, np.number)):
        return np.asarray([value], dtype=np.float32)
    try:
        arr = np.asarray(value)
    except Exception:  # noqa: BLE001 - anything numpy cannot read is simply not recorded
        return None
    if arr.ndim > 1 or arr.size == 0:
        return None
    if arr.dtype != bool and not np.issubdtype(arr.dtype, np.number):
        return None
    return arr.astype(np.float32).ravel()


class PipelineState(StrEnum):
    """ML-side extension of [`AppState`][myogestic.AppState].

    The core app only knows about ``"idle"`` and ``"recording"``;
    attaching a [`Pipeline`][] (via ``Pipeline(app)``) adds two more
    states for the ML lifecycle. Mutually exclusive with each other and
    with the core states.

    The enum is a ``StrEnum`` so it compares cleanly against the raw
    string written to ``app.ctx.state`` by the transition methods.

    Attributes
    ----------
    TRAINING
        ``train()`` is running on a background thread.
        Predict ticks short-circuit so they don't fight for GPU.
    PREDICTING
        The predict thread is calling ``extract`` +
        ``predict`` each tick at ``predict_hz`` and writing the
        result to ``pipeline.predictions``.

    Examples
    --------
    >>> from myogestic.ml import PipelineState
    >>> PipelineState.PREDICTING.value
    'predicting'
    """

    TRAINING = "training"
    PREDICTING = "predicting"


class Pipeline:
    """ML lifecycle + state for an App.

    Constructor registers the predict thread + cleanup on the App's hook
    lists; they fire on `app.run()` start/exit. Decorators set the
    callbacks. Transition methods flip `app.ctx.state`.

    Parameters
    ----------
    app
        The myogestic App.
    predict_hz
        Maximum predict-loop tick rate. Set to 0 or negative to remove
        the cap (run at full speed).

    Examples
    --------
    >>> from myogestic import App
    >>> from myogestic.ml import Pipeline
    >>> pipeline = Pipeline(App("EMG demo"), predict_hz=20)
    >>> @pipeline.extract
    ... def extract(windows):
    ...     return windows["emg"].mean(axis=1)
    """

    def __init__(self, app: App, predict_hz: float = 50.0):
        self.app = app
        self.predict_hz = predict_hz
        self.model: Any = None
        self.predictions: dict[str, Any] = {}
        self.train_log: list[str] = []
        self.on_extract: Callable | None = None
        self.on_train: Callable | None = None
        self.on_predict: Callable | None = None
        # Set if you want save/load buttons to do anything; the joblib helpers
        # `myogestic.ml.save_pickle` / `load_pickle` are the default.
        self.save_model: Callable | None = None
        self.load_model: Callable | None = None
        # Set this from inside `@app.ui` to publish what the user picked
        # in `session_manager(...)` to `@pipeline.train`.
        self.training_data: TrainingData | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        # Recording state: which session the skip list belongs to, and what was skipped in
        # it (name -> reason), so each skip is logged once and lands in meta.json.
        self._recorded_session: Any = None
        self._skipped: dict[str, str] = {}

        RECORDABLE_STATES.add(PipelineState.PREDICTING)
        app.finalize_hooks.append(self._on_finalize)

        app.before_run_hooks.append(self._start_predict_thread)
        app.cleanup_hooks.append(self._cleanup)

    # --- Decorators (set callback, return fn unchanged) ---

    def extract(self, fn: Callable) -> Callable:
        """Decorator: register the feature-extraction callback.

        The wrapped function receives ``windows: dict[str, np.ndarray]``
        keyed by stream name — each array is **channels-first**
        ``(n_channels, n_samples)``. Return whatever shape your model
        wants to consume. The same function is invoked from inside
        ``train()`` (over recorded windows) and on the predict thread
        (over live windows), so keep its return type stable.
        """
        self.on_extract = fn
        return fn

    def train(self, fn: Callable) -> Callable:
        """Decorator: register the training callback.

        The wrapped function receives one [`TrainingData`][] and
        must return any object — it's stored on ``pipeline.model`` and
        forwarded to every subsequent ``predict()`` call. If
        ``pipeline.save_model`` is set, the **Save Model** button calls
        it as ``save_model(pipeline.model, path)``.
        """
        self.on_train = fn
        return fn

    def predict(self, fn: Callable) -> Callable:
        """Decorator: register the predict callback.

        The wrapped function is called every ``1/predict_hz`` seconds
        with ``(model, features)`` where ``features`` is the return
        value of the ``extract`` callback. **Must return a
        ``dict[str, Any]``** — non-dict returns are silently dropped
        (the previous prediction stays in ``pipeline.predictions``).
        """
        self.on_predict = fn
        return fn

    # --- Transitions ---

    def start_training(self) -> None:
        """Run the ``@pipeline.train`` callback on a worker thread.

        No-op (sets ``ctx.status_message``) unless the state is ``idle``,
        a train callback is registered, and non-empty
        `training_data` is set. Flips the state to ``training`` for
        the duration and stores the returned object on `model`.
        """
        ctx = self.app.ctx
        if ctx.state != "idle":
            ctx.status_message = f"Cannot start training: state is {ctx.state!r}, expected 'idle'."
            return
        if self.on_train is None:
            ctx.status_message = "No train callback set (use @pipeline.train)"
            return
        data = self.training_data
        if data is None or data.is_empty:
            ctx.status_message = (
                "No training data — set "
                "pipeline.training_data = session_manager(...) inside @app.ui."
            )
            return

        ctx.state = PipelineState.TRAINING
        ctx.status_message = "Training..."
        ctx.log("Training started")
        on_train = self.on_train

        def _worker() -> None:
            try:
                self.model = on_train(data)
                ctx.status_message = "Training complete"
                self.train_log.append("Training complete")
                ctx.log("Training complete")
            except Exception as e:
                tb = traceback.format_exc()
                ctx.status_message = f"Training failed: {e}"
                self.train_log.append(f"FAILED: {e}")
                self.train_log.append(tb)
                ctx.log(f"Training failed: {e}")
            finally:
                ctx.state = "idle"

        if _IS_BROWSER:
            # Pyodide: no threads. Run synchronously on the UI frame that
            # triggered the click, blocking it for the duration of training.
            _worker()
        else:
            threading.Thread(target=_worker, daemon=True).start()

    def start_predicting(self) -> None:
        """Flip the state to ``predicting`` so the predict thread runs.

        No-op (sets ``ctx.status_message``) unless the state is ``idle`` or ``recording``
        and a `model` is loaded. A take that is open keeps recording; the pipeline writes
        into it.
        """
        ctx = self.app.ctx
        if ctx.state not in ("idle", AppState.RECORDING):
            ctx.status_message = (
                f"Cannot start predicting: state is {ctx.state!r}, expected 'idle' or 'recording'."
            )
            return
        if self.model is None:
            ctx.status_message = "No model loaded — train one first or load from disk."
            return
        ctx.state = PipelineState.PREDICTING
        ctx.status_message = "Predicting..."

    def stop_predicting(self) -> None:
        """Return to ``idle`` — or to ``recording`` when a take is open — pausing the predict loop.

        No-op (sets ``ctx.status_message``) unless the state is currently
        ``predicting``.
        """
        ctx = self.app.ctx
        if ctx.state != PipelineState.PREDICTING:
            ctx.status_message = (
                f"Cannot stop predicting: state is {ctx.state!r}, expected 'predicting'."
            )
            return
        ctx.state = AppState.RECORDING if ctx.recording else "idle"
        ctx.status_message = "Prediction stopped"

    # --- Hooks registered with App.run() ---

    def _predict_step(self, app: App) -> float:
        """One iteration of the predict loop. Returns seconds-to-sleep.

        Shared between threaded and async variants.
        """
        period = 1.0 / self.predict_hz if self.predict_hz > 0 else 0.0
        t_start = time.perf_counter()
        if app.ctx.state == PipelineState.PREDICTING and self.model is not None:
            try:
                windows: dict[str, Any] = {}
                latest: float | None = None
                for name, stream in app.ctx.streams.items():
                    data, ts = stream.get_window()
                    if data.size > 0:
                        windows[name] = data
                        if len(ts):
                            end = float(ts[-1])
                            latest = end if latest is None else max(latest, end)
                if windows and self.on_extract and self.on_predict:
                    features = self.on_extract(windows)
                    result = self.on_predict(self.model, features)
                    if isinstance(result, dict):
                        self.predictions = result
                    self._record_tick(app, features, result, latest)
            except Exception as e:
                tb = traceback.format_exc()
                app.ctx.status_message = f"Predict error: {e}"
                app.ctx.log(f"Predict error: {e}\n{tb}")
            if period > 0:
                return max(0.0, period - (time.perf_counter() - t_start))
            return 0.0
        # Not predicting - poll at 100 Hz so the state flip is picked up
        # within ~10ms, without burning CPU.
        return 0.01

    # --- Recording -----------------------------------------------------------

    def _record_tick(self, app: App, features: Any, result: Any, latest: float | None) -> None:
        """Write this tick's input and output into the open session, if there is one.

        Rows are stamped with the newest sample the tick consumed, so they align with the
        raw arrays; ``pipeline.tick`` carries the decision clock, so latency is one
        subtraction. Never raises: a value that cannot be recorded is skipped, once, with a
        log line, and the loop goes on.
        """
        ctx = app.ctx
        session = ctx.session
        if not ctx.recording or session is None or latest is None:
            return
        if session is not self._recorded_session:
            self._recorded_session = session
            self._skipped = {}
        if "*" in self._skipped:
            return
        try:
            from mne_lsl.lsl import local_clock

            tick = local_clock()
            fs = self.predict_hz if self.predict_hz > 0 else 1.0
            self._record(ctx, session, "features", features, latest, fs)
            self._record(ctx, session, "prediction", result, latest, fs)
            session.append_event("pipeline.tick", [tick], latest, fs=fs, dtype=np.float64)
        except Exception as e:  # noqa: BLE001 - recording must never stop the predict loop
            self._skip(ctx, "*", f"recording stopped for this take: {e!r}")

    def _record(self, ctx: Any, session: Any, prefix: str, obj: Any, t: float, fs: float) -> None:
        items = obj.items() if isinstance(obj, Mapping) else ((None, obj),)
        for key, value in items:
            name = prefix if key is None else f"{prefix}.{key}"
            if name in self._skipped:
                continue
            row = _event_row(value)
            if row is None:
                self._skip(ctx, name, "not a number or a 1-D array")
                continue
            try:
                session.append_event(name, row, t, fs=fs)
            except ValueError as e:
                self._skip(ctx, name, str(e))

    def _skip(self, ctx: Any, name: str, reason: str) -> None:
        self._skipped[name] = reason
        ctx.log(f"Recording: skipped {name} ({reason})")

    def _on_finalize(self, session: Session) -> None:
        """Save the running model beside the take and describe what was recorded.

        Runs on the finalize thread after `Session.freeze`, so ``event_streams`` is
        complete. A model that cannot be saved is a recorded fact, not a missing file.
        """
        info: dict[str, Any] = {
            "predict_hz": self.predict_hz,
            "event_streams": list(session.event_streams),
            "skipped": dict(self._skipped) if session is self._recorded_session else {},
            "model": None,
            "model_type": None,
        }
        model = self.model
        if model is not None:
            info["model_type"] = type(model).__qualname__
            if self.save_model is None:
                info["model_note"] = "not saved: pipeline.save_model is unset"
            else:
                path = session.path / "model.joblib"
                try:
                    self.save_model(model, str(path))
                    info["model"] = path.name
                except Exception as e:  # noqa: BLE001 - a failed save is recorded, never fatal
                    info["model_note"] = f"not saved: {e!r}"
            report = getattr(model, "report", None)
            if isinstance(report, Mapping):
                try:
                    json.dumps(report)
                    info["report"] = dict(report)
                except (TypeError, ValueError):
                    info["report_note"] = "model.report is not JSON-serialisable"
        session.extras["pipeline"] = info

    def _start_predict_thread(self, app: App) -> None:
        # Clear stop event so a second App.run() restarts the loop cleanly.
        self._stop.clear()

        if _IS_BROWSER:
            # Pyodide: no threads, and asyncio tasks don't dispatch
            # while immapp.run blocks Python. Register one step with
            # the per-frame scheduler the App's GUI callback ticks.
            from myogestic._browser import register

            register(lambda: self._predict_step(app) if not self._stop.is_set() else 1.0)
            log.info("predict step registered with browser scheduler")
            return

        def _loop() -> None:
            while not self._stop.is_set():
                delay = self._predict_step(app)
                if delay > 0:
                    time.sleep(delay)

        self._thread = threading.Thread(target=_loop, daemon=True, name="myogestic.ml.predict")
        self._thread.start()
        log.info("predict thread started")

    def _cleanup(self, app: App) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            log.info("predict thread stopped")
