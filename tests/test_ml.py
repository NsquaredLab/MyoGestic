"""Tests for myogestic.ml — Pipeline composition, decorators, training lifecycle."""

import threading
import time

import numpy as np
from mne_lsl.lsl import StreamInfo, StreamOutlet

from myogestic.contracts import TrainingData
from myogestic.core import App
from myogestic.ml import Pipeline, PipelineState
from myogestic.sources.lsl import LSLSource
from myogestic.stream import Stream


def start_synthetic_stream(name="MLTestEMG", n_channels=4, fs=128):
    info = StreamInfo(name, "EMG", n_channels, fs, "float32", "")
    outlet = StreamOutlet(info)
    running = [True]

    def _push():
        chunk_size = 32
        interval = chunk_size / fs
        while running[0]:
            chunk = np.random.randn(chunk_size, n_channels).astype(np.float32)
            for sample in chunk:
                outlet.push_sample(sample)
            time.sleep(interval)

    threading.Thread(target=_push, daemon=True).start()
    return lambda: running.__setitem__(0, False)


def test_pipeline_constructor_registers_hooks():
    """Pipeline(app) adds before_run + cleanup hooks to the App."""
    app = App("MLTest")
    n_before = len(app.before_run_hooks)
    n_cleanup = len(app.cleanup_hooks)
    p = Pipeline(app)
    assert isinstance(p, Pipeline)
    assert p.app is app
    assert len(app.before_run_hooks) == n_before + 1
    assert len(app.cleanup_hooks) == n_cleanup + 1


def test_decorators_set_callbacks():
    """@pipeline.extract / @pipeline.train / @pipeline.predict populate the Pipeline."""
    app = App("MLDecorators")
    pipeline = Pipeline(app)

    @pipeline.extract
    def my_extract(windows):
        return np.zeros(1)

    @pipeline.train
    def my_train(data):
        return "model"

    @pipeline.predict
    def my_predict(model, features):
        return {"x": 1}

    assert pipeline.on_extract is my_extract
    assert pipeline.on_train is my_train
    assert pipeline.on_predict is my_predict


def test_training_lifecycle():
    """idle → training → idle, model stored on pipeline. train() receives TrainingData."""
    stop_lsl = start_synthetic_stream("MLTrainEMG", n_channels=2, fs=64)
    time.sleep(0.3)

    stream = Stream("emg", source=LSLSource("MLTrainEMG"), window_seconds=0.1)
    app = App("MLTrain")
    app.streams(stream)
    pipeline = Pipeline(app)
    pipeline.training_data = TrainingData(paths=["/tmp/fake_session"])

    train_entered = threading.Event()
    proceed = threading.Event()
    received_data: list[object] = []

    @pipeline.train
    def fake_train(data):
        received_data.append(data)
        train_entered.set()
        proceed.wait(timeout=5.0)
        return {"type": "fake_model"}

    stream.start()
    time.sleep(0.3)

    pipeline.start_training()
    assert train_entered.wait(timeout=5.0)
    assert app.ctx.state == PipelineState.TRAINING
    # train() received the TrainingData we set on the pipeline
    assert isinstance(received_data[0], TrainingData)
    assert received_data[0].paths == ["/tmp/fake_session"]

    proceed.set()
    time.sleep(0.2)
    assert app.ctx.state == "idle"
    assert pipeline.model == {"type": "fake_model"}
    assert app.ctx.status_message == "Training complete"

    stream.stop()
    stop_lsl()


def test_training_without_callback_is_noop():
    """start_training with no @pipeline.train set: error status, stays idle."""
    app = App("MLNoTrain")
    pipeline = Pipeline(app)
    pipeline.start_training()
    assert app.ctx.state == "idle"
    assert "No train callback" in app.ctx.status_message


def test_predicting_without_model_is_noop():
    """start_predicting with no model: error status, stays idle."""
    app = App("MLNoModel")
    pipeline = Pipeline(app)
    pipeline.start_predicting()
    assert app.ctx.state == "idle"
    assert "No model" in app.ctx.status_message


def test_stop_predicting_from_wrong_state_sets_message():
    """stop_predicting while already idle: status_message names the actual state."""
    app = App("MLStopWrong")
    pipeline = Pipeline(app)
    assert app.ctx.state == "idle"
    pipeline.stop_predicting()
    assert "Cannot stop predicting" in app.ctx.status_message
    assert "'idle'" in app.ctx.status_message


def test_multiple_pipelines_stack_hooks():
    """Two Pipeline(app) calls stack hooks (don't collide). Responsibility is
    on the user not to double-attach — no automatic protection."""
    app = App("MultiPipe")
    n0 = len(app.before_run_hooks)
    Pipeline(app)
    Pipeline(app)
    assert len(app.before_run_hooks) == n0 + 2


def test_ml_widgets_import_registers_state_colors():
    """Importing myogestic.ml.widgets must populate STATE_COLORS with 'training'
    and 'predicting' entries (inverts coupling: core doesn't know ml states)."""
    import myogestic.ml.widgets  # noqa: F401, I001 -- triggers registration
    from myogestic.widgets.panels.recording import STATE_COLORS

    assert PipelineState.TRAINING in STATE_COLORS
    assert PipelineState.PREDICTING in STATE_COLORS


def test_pipeline_cleanup_stops_predict_thread():
    """_cleanup must set _stop and join the thread within the timeout."""
    app = App("MLCleanup")
    pipeline = Pipeline(app)
    # Manually invoke the startup hook (normally App.run does this)
    pipeline._start_predict_thread(app)
    assert pipeline._thread is not None
    assert pipeline._thread.is_alive()

    pipeline._cleanup(app)
    time.sleep(0.05)  # let OS schedule the join
    assert pipeline._stop.is_set()
    assert pipeline._thread is not None
    assert not pipeline._thread.is_alive()


def test_pipeline_predict_hz_caps_loop_rate():
    """predict_hz limits how fast the loop iterates when actively predicting.

    Set hz=20 → period 0.05s. Run for 0.5s → expect ~10 iterations (±tolerance).
    Without the cap the loop spins as fast as the CPU allows.
    """
    app = App("MLHzCap")
    pipeline = Pipeline(app, predict_hz=20.0)

    iterations = [0]

    @pipeline.extract
    def extract(windows):
        return np.zeros(1)

    @pipeline.predict
    def predict(model, features):
        iterations[0] += 1
        return {"x": iterations[0]}

    pipeline.model = "fake"
    app.ctx.state = PipelineState.PREDICTING
    # Add a fake stream so the loop has windows to read
    from myogestic.sources.lsl import LSLSource
    from myogestic.stream import Stream
    # Use a stream that won't actually connect, but make get_window return data
    stream = Stream("emg", source=LSLSource("DoesNotExist"), window_seconds=0.01)
    # Skip stream setup — just inject get_window-compatible data via monkeypatch
    fake_data = np.ones((1, 1), dtype=np.float32)   # channels-first (1 ch, 1 sample)
    fake_ts = np.array([0.0])
    stream.get_window = lambda: (fake_data, fake_ts)  # type: ignore[method-assign]
    app.streams(stream)

    pipeline._start_predict_thread(app)
    time.sleep(0.5)
    pipeline._cleanup(app)

    # At 20 Hz over 0.5s, expect ~10 iterations. Tight bounds catch a broken
    # cap (a 30 Hz "cap" would yield ~15 — outside this window).
    assert 7 <= iterations[0] <= 13, f"got {iterations[0]} iterations, expected ~10"


def test_pipeline_predict_thread_can_restart():
    """_stop.clear() on restart: a second run() must not see the previous
    session's stop signal."""
    app = App("MLRestart")
    pipeline = Pipeline(app)

    # First run
    pipeline._start_predict_thread(app)
    first = pipeline._thread
    pipeline._cleanup(app)
    assert pipeline._stop.is_set()

    # Restart
    pipeline._start_predict_thread(app)
    assert not pipeline._stop.is_set(), "_stop must be cleared before new thread starts"
    assert pipeline._thread is not first
    assert pipeline._thread is not None and pipeline._thread.is_alive()

    pipeline._cleanup(app)


def test_pipeline_train_failure_sets_idle_and_logs():
    """If on_train raises, state returns to idle and the traceback is logged."""
    app = App("MLTrainFail")
    pipeline = Pipeline(app)
    pipeline.training_data = TrainingData(paths=["/tmp/fake_session"])

    @pipeline.train
    def bad_train(data):
        raise ValueError("training exploded")

    pipeline.start_training()
    # Give worker thread time
    time.sleep(0.3)
    assert app.ctx.state == "idle"
    assert "Training failed" in app.ctx.status_message
    assert any("FAILED" in line for line in pipeline.train_log)
    assert any("ValueError" in line or "training exploded" in line for line in pipeline.train_log)


def test_start_training_refuses_without_data():
    """No pipeline.training_data and no ctx.session → status_message refusal."""
    app = App("MLNoData")
    pipeline = Pipeline(app)

    @pipeline.train
    def _t(_data):  # never reached
        return "model"

    pipeline.start_training()
    assert app.ctx.state == "idle"
    assert pipeline.model is None
    assert "No training data" in app.ctx.status_message


