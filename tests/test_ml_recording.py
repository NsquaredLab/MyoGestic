"""The pipeline writes its tick into an open session, and saves the model on finalize."""

from __future__ import annotations

import json
import time
import zipfile
from pathlib import Path

import numpy as np

from myogestic.core import RECORDABLE_STATES, App
from myogestic.ml import Pipeline, PipelineState, save_pickle
from myogestic.stream import Stream, StreamInfo


class _TickSource:
    """Hands over four samples per read with rising timestamps, so the ring has a window."""

    def __init__(self) -> None:
        self._n = 0

    def connect(self) -> StreamInfo:
        return StreamInfo(n_channels=2, fs=100.0)

    def read(self):
        time.sleep(0.04)  # paced at 4 samples / 100 Hz, so the acquire loop doesn't hot-loop
        data = np.full((4, 2), float(self._n), np.float32)
        ts = 1000.0 + (self._n * 4 + np.arange(4)) / 100.0
        self._n += 1
        return data, ts

    def disconnect(self) -> None:
        pass


def _running_app(tmp_path: Path, *, save_model=None):
    app = App("ml-rec")
    stream = Stream("emg", source=_TickSource(), window_ms=100)
    app.streams(stream)
    pipeline = Pipeline(app, predict_hz=32.0)
    pipeline.save_model = save_model

    @pipeline.extract
    def extract(windows):
        return {
            "vec": windows["emg"].mean(axis=1),  # 1-D: recorded
            "img": windows["emg"],  # 2-D: skipped
            "why": "text",  # str: skipped
            "ok": True,  # bool: recorded as one channel
        }

    @pipeline.predict
    def predict(model, features):
        return {"pose": np.array([0.5, -0.5, 0.0]), "label": 2, "name": "fist"}

    pipeline.model = _Model()
    stream.reconnect()
    stream.start()
    time.sleep(0.2)  # let the acquire loop fill a window
    app.ctx.state = PipelineState.PREDICTING
    return app, pipeline, stream


def _zip(folder: Path) -> Path:
    (zip_path,) = folder.glob("*.session.zip")
    return zip_path


class _Model:
    """Module-level so joblib can pickle it; a class defined inside a function cannot be."""

    report = {"decoder": "test"}


def _raise_disk_full(model, path):
    raise OSError("disk full")


def test_a_pipeline_registers_predicting_as_recordable():
    Pipeline(App("reg"))
    assert PipelineState.PREDICTING in RECORDABLE_STATES


def test_each_tick_lands_in_the_session_with_the_window_timestamp(tmp_path):
    app, pipeline, stream = _running_app(tmp_path, save_model=save_pickle)
    try:
        app.start_recording(str(tmp_path))
        assert app.ctx.recording and app.ctx.state == "predicting"
        pipeline._predict_step(app)
        pipeline._predict_step(app)
        _, ts = stream.get_window()
        app.stop_recording(wait=True)
    finally:
        stream.stop()
    with zipfile.ZipFile(_zip(tmp_path)) as zf:
        meta = json.loads(zf.read("meta.json"))
        names = set(zf.namelist())
    recorded = set(meta["event_streams"])
    assert {
        "features.vec",
        "features.ok",
        "prediction.pose",
        "prediction.label",
        "pipeline.tick",
    } <= recorded
    assert not {"features.img", "features.why", "prediction.name"} & recorded
    assert meta["streams"]["prediction.pose"]["n_channels"] == 3
    assert meta["streams"]["prediction.pose"]["fs"] == 32.0
    info = meta["extras"]["pipeline"]
    assert info["model"] == "model.joblib" and "model.joblib" in names
    assert info["report"] == {"decoder": "test"}
    assert set(info["skipped"]) == {"features.img", "features.why", "prediction.name"}
    from myogestic.session import open_session_store

    with open_session_store(_zip(tmp_path)) as s:
        pose = np.array(s.stores["prediction.pose"])
        t = np.array(s.ts_stores["prediction.pose"])
        tick = np.array(s.stores["pipeline.tick"])
        tick_dtype = s.stores["pipeline.tick"].dtype
    assert pose.shape == (2, 3) and pose[0].tolist() == [0.5, -0.5, 0.0]
    assert t[-1] <= float(ts[-1]) and t[-1] > 1000.0  # stamped with a window sample time
    # pipeline.tick is liblsl's local_clock(): seconds since boot, unrelated to the fake data
    # clock, so compare it with itself and with the clock now, not with `t`.
    from mne_lsl.lsl import local_clock

    assert tick_dtype == np.float64  # float32 would quantise the latency it exists to measure
    assert tick.shape == (2, 1) and np.isfinite(tick).all()
    assert tick[1, 0] >= tick[0, 0] and abs(local_clock() - tick[-1, 0]) < 1.0


def test_skips_are_logged_once_per_session(tmp_path):
    app, pipeline, stream = _running_app(tmp_path)
    try:
        app.start_recording(str(tmp_path))
        for _ in range(3):
            pipeline._predict_step(app)
        app.stop_recording(wait=True)
    finally:
        stream.stop()
    skipped_lines = [line for line in app.ctx.logs if "skipped features.img" in line]
    assert len(skipped_lines) == 1
    with zipfile.ZipFile(_zip(tmp_path)) as zf:
        info = json.loads(zf.read("meta.json"))["extras"]["pipeline"]
    assert info["model"] is None and "save_model" in info["model_note"]


def test_a_failing_model_save_still_records_the_pipeline_extras(tmp_path):
    app, pipeline, stream = _running_app(tmp_path, save_model=_raise_disk_full)
    try:
        app.start_recording(str(tmp_path))
        pipeline._predict_step(app)
        app.stop_recording(wait=True)
    finally:
        stream.stop()
    with zipfile.ZipFile(_zip(tmp_path)) as zf:
        info = json.loads(zf.read("meta.json"))["extras"]["pipeline"]
    assert info["model"] is None
    assert "disk full" in info["model_note"]
    assert "prediction.pose" in info["event_streams"]
    assert not any("Finalize hook failed" in line for line in app.ctx.logs)


def test_a_width_change_skips_that_stream_and_keeps_predicting(tmp_path):
    app, pipeline, stream = _running_app(tmp_path)
    widths = iter([3, 5, 5])

    @pipeline.predict
    def predict(model, features):
        return {"pose": np.zeros(next(widths))}

    try:
        app.start_recording(str(tmp_path))
        for _ in range(3):
            pipeline._predict_step(app)
        assert pipeline.predictions["pose"].shape == (5,)  # the loop kept running
        app.stop_recording(wait=True)
    finally:
        stream.stop()
    with zipfile.ZipFile(_zip(tmp_path)) as zf:
        info = json.loads(zf.read("meta.json"))["extras"]["pipeline"]
    assert "prediction.pose" in info["skipped"] and "wide" in info["skipped"]["prediction.pose"]


def test_stop_predicting_returns_to_recording_when_a_take_is_open(tmp_path):
    app, pipeline, stream = _running_app(tmp_path)
    try:
        app.start_recording(str(tmp_path))
        pipeline.stop_predicting()
        assert app.ctx.state == "recording" and app.ctx.recording
        pipeline.start_predicting()  # allowed from recording
        assert app.ctx.state == "predicting" and app.ctx.recording
        pipeline.stop_predicting()
        app.stop_recording(wait=True)
        assert app.ctx.state == "idle"
    finally:
        stream.stop()


def test_model_is_not_saved_for_a_take_the_pipeline_never_wrote_into(tmp_path):
    """An idle calibration take (predict thread never ticked into it) should not carry a
    pickled model, even though a model is loaded — the model belongs beside the take that
    actually produced its predictions.
    """
    app = App("ml-rec-idle")
    pipeline = Pipeline(app)
    pipeline.save_model = save_pickle
    pipeline.model = _Model()
    app.start_recording(str(tmp_path))
    assert app.ctx.state == "recording"  # never set to predicting: the pipeline never ticked
    app.stop_recording(wait=True)
    with zipfile.ZipFile(_zip(tmp_path)) as zf:
        meta = json.loads(zf.read("meta.json"))
        names = set(zf.namelist())
    assert "model.joblib" not in names
    info = meta["extras"]["pipeline"]
    assert info["model"] is None
    assert "did not predict" in info["model_note"]
