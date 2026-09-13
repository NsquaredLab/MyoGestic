"""Event streams: buffered per-tick rows declared on first use, closed by freeze()."""

from __future__ import annotations

import json
import tempfile
import zipfile

import numpy as np
import pytest

from myogestic.session import Session, _core, open_session_store
from myogestic.sources.replay import ReplaySource
from myogestic.stream import StreamInfo


def _session(tmp) -> Session:
    session = Session(base_path=tmp)
    session.init_stream("emg", StreamInfo(n_channels=2, fs=100.0))
    session.append("emg", np.zeros((10, 2), np.float32), np.arange(10.0))
    return session


def test_first_row_declares_the_stream_and_stays_buffered():
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        s.append_event(
            "prediction.pose", [0.5, -0.25, 1.0], 12.5, channel_names=["a", "b", "c"], fs=32.0
        )
        info = s.stream_info("prediction.pose")
        assert (info.n_channels, info.fs, info.channel_names) == (3, 32.0, ["a", "b", "c"])
        assert s.event_streams == ("prediction.pose",)
        assert s.stores["prediction.pose"].shape == (0, 3)  # buffered, not yet written
        assert s.stores["prediction.pose"].chunks == (_core.EVENT_CHUNK_ROWS, 3)
        s.freeze()
        assert np.array(s.stores["prediction.pose"]).tolist() == [[0.5, -0.25, 1.0]]
        assert np.array(s.ts_stores["prediction.pose"]).tolist() == [12.5]
        assert s.ts_stores["prediction.pose"].dtype == np.float64


def test_dtype_is_fixed_by_the_declaring_call():
    """`dtype=` on the first call to a name sets the stream's dtype for good; a value
    that is itself a clock needs float64, or it quantises the way ``pipeline.tick``
    used to before this was added — see C1.
    """
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        s.append_event("clock", [123456.789012], 0.0, dtype=np.float64)
        s.freeze()
        assert np.array(s.stores["clock"]).tolist() == [[123456.789012]]
        assert s.stream_info("clock").dtype == np.float64

        s2 = _session(tmp)
        s2.append_event("x", [1.0], 0.0)  # declares float32 (the default)
        s2.append_event("x", [2.0], 1.0, dtype=np.float64)  # ignored: already declared
        assert s2.stream_info("x").dtype == np.float32
        assert s2.stores["x"].dtype == np.float32


def test_a_row_of_another_width_is_refused():
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        s.append_event("x", [1.0, 2.0], 0.0)
        with pytest.raises(ValueError, match="2 wide"):
            s.append_event("x", [1.0], 1.0)
        with pytest.raises(ValueError, match="sampled stream"):
            s.append_event("emg", [1.0, 2.0], 1.0)


def test_the_buffer_flushes_at_the_chunk_size():
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        for i in range(_core.EVENT_CHUNK_ROWS):
            s.append_event("x", [float(i)], float(i))
        assert s.stores["x"].shape == (_core.EVENT_CHUNK_ROWS, 1)  # written without freeze
        s.append_event("x", [9.0], 9.0)
        assert s.stores["x"].shape == (_core.EVENT_CHUNK_ROWS, 1)  # the new row is buffered


def test_the_buffer_flushes_after_one_second(monkeypatch):
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        clock = [100.0]
        monkeypatch.setattr(_core.time, "monotonic", lambda: clock[0])
        s.append_event("x", [1.0], 0.0)
        clock[0] += 0.5
        s.append_event("x", [2.0], 0.5)
        assert s.stores["x"].shape == (0, 1)
        clock[0] += 0.6  # oldest buffered row is now 1.1 s old
        s.append_event("x", [3.0], 1.1)
        assert s.stores["x"].shape == (3, 1)


def test_after_freeze_rows_are_dropped_and_no_stream_can_be_declared():
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        s.append_event("x", [1.0], 0.0)
        s.freeze()
        s.append_event("x", [2.0], 1.0)
        s.append_event("late", [1.0], 1.0)
        s.append("emg", np.ones((5, 2), np.float32), np.arange(5.0))
        assert s.stores["x"].shape == (1, 1)
        assert "late" not in s.stores and s.event_streams == ("x",)
        assert s.stores["emg"].shape == (10, 2)
        s.freeze()  # idempotent


def test_event_streams_survive_pack_and_replay():
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        for i in range(70):
            s.append_event(
                "controls", [i / 70, 1.0], 100.0 + i / 32, channel_names=["a", "g"], fs=32.0
            )
        s.save_meta("EventsTest")
        zip_path = s.pack_to_zip()  # freezes, flushes, packs
        with zipfile.ZipFile(zip_path) as zf:
            meta = json.loads(zf.read("meta.json"))
        assert meta["event_streams"] == ["controls"]
        assert meta["streams"]["controls"]["fs"] == 32.0
        with open_session_store(zip_path) as loaded:
            assert loaded.event_streams == ("controls",)
            assert loaded.stream_info("controls").fs == 32.0
            assert np.array(loaded.stores["controls"]).shape == (70, 2)
            loaded.freeze()  # a loaded session is read-only; freeze must be a no-op, not an error
        source = ReplaySource(str(zip_path), "controls")
        info = source.connect()
        data, ts = source.read()  # first read hands over the initial chunk immediately
        source.disconnect()
        assert info.fs == 32.0 and data.shape[1] == 2 and len(ts) > 0


def test_flush_failure_drops_the_buffer_instead_of_raising(caplog):
    """A failed flush logs once, marks the buffer dead, drops rows, and does not propagate."""
    caplog.set_level("WARNING")
    with tempfile.TemporaryDirectory() as tmp:
        s = _session(tmp)
        # Declare stream x
        s.append_event("x", [1.0], 0.0)
        buf_x = s._event_buffers["x"]

        # Monkeypatch zarr append to fail on any call
        def failing_append(data):
            raise OSError("disk full")

        s.stores["x"].append = failing_append
        s.ts_stores["x"].append = failing_append

        # Fill the buffer to trigger a flush (at EVENT_CHUNK_ROWS rows total)
        for i in range(_core.EVENT_CHUNK_ROWS):
            s.append_event("x", [float(i)], float(i))

        # Flush failed: buffer should be marked dead and emptied
        assert buf_x.dead, "buffer should be marked dead after flush failure"
        assert len(buf_x.rows) == 0, "rows should be cleared after flush failure"
        assert s.stores["x"].shape == (0, 1), "no data should be written"

        # Later appends to x are silent no-ops
        s.append_event("x", [99.0], 99.0)
        assert len(buf_x.rows) == 0, "dead buffer should remain empty"

        # A second stream in the same session still works
        for i in range(5):
            s.append_event("y", [float(i)], float(i))
        s.freeze()
        assert s.stores["y"].shape == (5, 1), "second stream should flush successfully"

        # Exactly one warning logged for the failed stream x
        warnings = [
            rec for rec in caplog.records if "event stream 'x': flush failed" in rec.message
        ]
        assert len(warnings) == 1, f"expected 1 warning for stream x, got {len(warnings)}"
