"""Training completion, persistence, and failure feedback."""

import re
import time
from pathlib import Path

from myogestic import App, TrainingData
from myogestic.ml import Pipeline, load_pickle, save_pickle


def _pipeline(tmp_path):
    pipeline = Pipeline(App("Auto-save"))
    pipeline.app.ctx.participant = "P-014"
    pipeline.training_data = TrainingData(paths=[str(tmp_path / "take.session.zip")])

    @pipeline.train
    def train(data):
        return {"classes": [0, 1]}

    return pipeline


def _train_and_wait(pipeline):
    pipeline.start_training()
    deadline = time.monotonic() + 5.0
    while pipeline.app.ctx.state != "idle" and time.monotonic() < deadline:
        time.sleep(0.01)
    assert pipeline.app.ctx.state == "idle"


def test_autosave_writes_labelled_model(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.save_model = save_pickle
    pipeline.autosave_dir = str(tmp_path)

    _train_and_wait(pipeline)

    files = list((tmp_path / "P-014").glob("P-014_*_model.joblib"))
    assert len(files) == 1
    assert pipeline.last_saved_model == str(files[0])
    assert load_pickle(files[0]) == pipeline.model == {"classes": [0, 1]}
    notice = pipeline.app.ctx.notifications[-1]
    assert (notice.title, notice.detail, notice.kind) == (
        "Training finished",
        files[0].name,
        "success",
    )
    assert pipeline.app.ctx.logs[-1].endswith(f"Training finished — {files[0].name}")


def test_no_autosave_without_dir(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.save_model = save_pickle
    assert pipeline.autosave_dir is None

    _train_and_wait(pipeline)

    assert list(tmp_path.iterdir()) == []
    assert pipeline.last_saved_model is None
    notice = pipeline.app.ctx.notifications[-1]
    assert (notice.title, notice.kind) == ("Training finished", "success")
    assert re.fullmatch(r"in \d+\.\d s", notice.detail)


def test_no_autosave_without_save_callback(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.autosave_dir = str(tmp_path)

    _train_and_wait(pipeline)

    assert list(tmp_path.iterdir()) == []
    assert pipeline.last_saved_model is None
    assert pipeline.app.ctx.notifications[-1].kind == "success"


def test_autosave_failure_keeps_model(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.autosave_dir = str(tmp_path)

    def fail_save(model, path):
        raise OSError("disk full")

    pipeline.save_model = fail_save
    _train_and_wait(pipeline)

    assert pipeline.model == {"classes": [0, 1]}
    assert pipeline.last_saved_model is None
    notices = pipeline.app.ctx.notifications
    assert any(n.kind == "danger" and "disk full" in n.detail for n in notices)
    assert not any(n.title == "Training failed" for n in notices)
    assert any("disk full" in line for line in pipeline.app.ctx.logs)
    pipeline.start_predicting()
    assert pipeline.app.ctx.state == "predicting"
    pipeline.stop_predicting()


def test_training_failure_notifies_danger(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.autosave_dir = str(tmp_path)
    pipeline.save_model = save_pickle

    @pipeline.train
    def train(data):
        raise ValueError("no usable windows")

    _train_and_wait(pipeline)

    assert pipeline.model is None
    assert list(tmp_path.iterdir()) == []
    notice = pipeline.app.ctx.notifications[-1]
    assert (notice.title, notice.detail, notice.kind) == (
        "Training failed",
        "no usable windows",
        "danger",
    )


def test_autosave_without_participant_uses_base_folder(tmp_path):
    pipeline = _pipeline(tmp_path)
    pipeline.app.ctx.participant = ""
    pipeline.autosave_dir = str(tmp_path)
    pipeline.save_model = save_pickle

    _train_and_wait(pipeline)

    files = list(tmp_path.glob("*_model.joblib"))
    assert len(files) == 1
    assert Path(pipeline.last_saved_model) == files[0]
