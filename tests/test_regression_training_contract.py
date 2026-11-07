"""Regression examples train and predict with the same selected inputs."""

from __future__ import annotations

import runpy
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from myogestic import StreamInfo, TrainingData
from myogestic.session import Session

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(params=["emg_regression", "emg_regression_raulnet"])
def regression_example(request, monkeypatch, tmp_path):
    """Wire each real example without launching external processes."""
    pytest.importorskip("torch")
    pytest.importorskip("myoverse")
    if request.param.endswith("raulnet"):
        pytest.importorskip("lightning")
    from myogestic.remote import InterfaceSpec
    from myogestic.tools import emg_generator

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(InterfaceSpec, "launchable", lambda self: [])
    monkeypatch.setattr(
        emg_generator, "control_outlet", lambda: SimpleNamespace(push_sample=lambda values: None)
    )
    ns = runpy.run_path(str(ROOT / "examples/synthetic" / f"{request.param}.py"))
    try:
        yield ns
    finally:
        ns["link"].stop()
        ns["recording_aid"].stop()
        ns["vhi_control"].stop()
        for stream in ns["app"].ctx.streams.values():
            stream.stop()


@pytest.fixture(params=["labels", "kinematics"])
def regression_take(request, tmp_path):
    """Two seconds of eight-channel EMG with either recorded poses or labels."""
    fs = 2048
    emg = np.random.default_rng(23).normal(size=(2 * fs, 8)).astype(np.float32)
    ts = np.arange(len(emg)) / fs
    info = StreamInfo(n_channels=8, fs=fs)
    session = Session(base_path=tmp_path / "takes")
    session.init_stream("emg", info)
    session.append("emg", emg, ts)
    if request.param == "kinematics":
        session.init_stream("vhi_control", StreamInfo(n_channels=9, fs=fs))
        session.append("vhi_control", np.zeros((len(ts), 9), dtype=np.float32), ts)
    session.add_label(1, timestamp=ts[0])
    session.save_meta("Regression contract", class_names=["Rest", "Fist"])
    path = str(session.pack_to_zip())
    return path, info, emg, ts


def test_live_feature_shape_matches_trained_input(regression_example, regression_take, monkeypatch):
    """Both training paths fit the feature layout delivered by the live stream."""
    ns = regression_example
    path, info, emg, ts = regression_take
    trained = []
    globals_ = ns["train"].__globals__
    if "catboost_regressor" in ns:
        estimator = SimpleNamespace(fit=lambda X, y: trained.append(X.copy()))
        monkeypatch.setitem(globals_, "catboost_regressor", lambda **kwargs: estimator)
    else:
        trainer = SimpleNamespace(
            fit=lambda model, train_dataloaders: trained.append(
                train_dataloaders.dataset.tensors[0].numpy()[:, 0].copy()
            )
        )
        monkeypatch.setattr(ns["L"], "Trainer", lambda **kwargs: trainer)

    ns["train"](TrainingData(paths=[path], class_names=ns["CLASSES"], classes={1}))
    stream = ns["app"].ctx.streams["emg"]
    stream.info = info
    stream._allocate_buffers()
    stream._data.extend(emg)
    stream._timestamps.extend(ts)
    live_window, _ = stream.get_window()
    live_features = ns["pipeline"].on_extract({"emg": live_window})

    assert len(trained) == 1 and len(trained[0]) >= 16
    assert live_features.shape == trained[0].shape[1:]
    assert live_features.size == trained[0][0].size


def test_empty_class_selection_refuses_training(regression_example, regression_take, monkeypatch):
    """Unticking every class refuses both callbacks before reading or fitting data."""
    ns = regression_example
    path, *_ = regression_take

    def read_sessions(*args):
        pytest.fail("An empty class selection must be refused before reading sessions")

    monkeypatch.setitem(ns["train"].__globals__, "split_sessions_by_stream", read_sessions)
    data = TrainingData(paths=[path], class_names=ns["CLASSES"], classes=set())
    with pytest.raises(ValueError, match="No classes selected.*select at least one class"):
        ns["train"](data)

    # The pipeline's existing refusal path publishes the same reason and keeps the model.
    from myogestic.ml import pipeline as pipeline_module

    monkeypatch.setattr(
        pipeline_module.threading,
        "Thread",
        lambda *, target, **kwargs: SimpleNamespace(start=target),
    )
    pipeline, ctx = ns["pipeline"], ns["app"].ctx
    previous_model = object()
    pipeline.model = previous_model
    pipeline.training_data = data
    pipeline.start_training()
    assert pipeline.model is previous_model
    assert ctx.state == "idle"
    assert ctx.status_message.startswith("Training failed: No classes selected")
    assert any("select at least one class" in line for line in pipeline.train_log)
