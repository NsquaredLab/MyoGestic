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
"""

from __future__ import annotations

import asyncio
import logging
import sys
import threading
import time
import traceback
from collections.abc import Callable
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from myogestic.contracts import TrainingData
from myogestic.ml.persistence import load_pickle as load_pickle
from myogestic.ml.persistence import save_pickle as save_pickle

if TYPE_CHECKING:
    from myogestic.core import App

log = logging.getLogger("myogestic.ml")

# Pyodide reports sys.platform == "emscripten" and forbids OS threads.
# When detected, the predict loop runs as an asyncio task instead.
_IS_BROWSER = sys.platform == "emscripten"


class PipelineState(StrEnum):
    """ML-side extension of :class:`~myogestic.AppState`.

    The core app only knows about ``"idle"`` and ``"recording"``;
    attaching a :class:`Pipeline` (via ``Pipeline(app)``) adds two more
    states for the ML lifecycle. Mutually exclusive with each other and
    with the core states: a Pipeline cannot be predicting and training
    at the same time, by design (the train pause exists so the GPU
    isn't fought over).

    The enum is a ``StrEnum`` so it compares cleanly against the raw
    string written to ``app.ctx.state`` by the transition methods.

    Members:
        TRAINING: ``train()`` is running on a background thread.
            Predict ticks short-circuit so they don't fight for GPU.
        PREDICTING: The predict thread is calling ``extract`` +
            ``predict`` each tick at ``predict_hz`` and writing the
            result to ``pipeline.predictions``.
    """

    TRAINING = "training"
    PREDICTING = "predicting"


class Pipeline:
    """ML lifecycle + state for an App.

    Constructor registers the predict thread + cleanup on the App's hook
    lists; they fire on `app.run()` start/exit. Decorators set the
    callbacks. Transition methods flip `app.ctx.state`.
    """

    def __init__(self, app: App, predict_hz: float = 50.0):
        """
        Args:
            app: The myogestic App.
            predict_hz: Maximum predict-loop tick rate. Set to 0 or
                negative to remove the cap (run at full speed).
        """
        self.app = app
        self.predict_hz = predict_hz
        self.model: Any = None
        self.predictions: dict[str, Any] = {}
        self.train_log: list[str] = []
        self.on_extract: Callable | None = None
        self.on_train: Callable | None = None
        self.on_predict: Callable | None = None
        # Set if you want save/load buttons to do anything; the
        # `myogestic.models.{save,load}_model` joblib helpers are the
        # obvious default but the library doesn't force them.
        self.save_model: Callable | None = None
        self.load_model: Callable | None = None
        # Set this from inside `@app.ui` to publish what the user picked
        # in `session_manager(...)` to `@pipeline.train`.
        self.training_data: TrainingData | None = None
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

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

        The wrapped function receives one :class:`TrainingData` and
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
        ctx = self.app.ctx
        if ctx.state != "idle":
            ctx.status_message = (
                f"Cannot start training: state is {ctx.state!r}, expected 'idle'."
            )
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
            # Pyodide: no threads. Run synchronously on the UI frame
            # that triggered the click. Blocks that frame for the
            # duration of training - acceptable for the small models
            # the playground demos. Heavy models would need an explicit
            # split-step trainer, out of scope here.
            _worker()
        else:
            threading.Thread(target=_worker, daemon=True).start()

    def start_predicting(self) -> None:
        ctx = self.app.ctx
        if ctx.state != "idle":
            ctx.status_message = (
                f"Cannot start predicting: state is {ctx.state!r}, expected 'idle'."
            )
            return
        if self.model is None:
            ctx.status_message = "No model loaded — train one first or load from disk."
            return
        ctx.state = PipelineState.PREDICTING
        ctx.status_message = "Predicting..."

    def stop_predicting(self) -> None:
        ctx = self.app.ctx
        if ctx.state != PipelineState.PREDICTING:
            ctx.status_message = (
                f"Cannot stop predicting: state is {ctx.state!r}, expected 'predicting'."
            )
            return
        ctx.state = "idle"
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
                for name, stream in app.ctx.streams.items():
                    data, _ts = stream.get_window()
                    if data.size > 0:
                        windows[name] = data
                if windows and self.on_extract and self.on_predict:
                    features = self.on_extract(windows)
                    result = self.on_predict(self.model, features)
                    if isinstance(result, dict):
                        self.predictions = result
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

    def _start_predict_thread(self, app: App) -> None:
        # Clear stop event so a second App.run() restarts the loop cleanly.
        self._stop.clear()

        if _IS_BROWSER:
            # Pyodide: no threads, and asyncio tasks don't dispatch
            # while immapp.run blocks Python. Register one step with
            # the per-frame scheduler the App's GUI callback ticks.
            from myogestic._browser import register
            register(
                lambda: self._predict_step(app) if not self._stop.is_set() else 1.0
            )
            log.info("predict step registered with browser scheduler")
            return

        def _loop() -> None:
            while not self._stop.is_set():
                delay = self._predict_step(app)
                if delay > 0:
                    time.sleep(delay)

        self._thread = threading.Thread(
            target=_loop, daemon=True, name="myogestic.ml.predict"
        )
        self._thread.start()
        log.info("predict thread started")

    async def _predict_loop_async(self, app: App) -> None:
        """Browser predict loop. Same step body; asyncio pacing."""
        while not self._stop.is_set():
            delay = self._predict_step(app)
            await asyncio.sleep(delay)

    def _cleanup(self, app: App) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
            log.info("predict thread stopped")
