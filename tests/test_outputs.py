"""Test the Output base class send-thread pattern and LSLOutlet."""

import threading
import time

import numpy as np
from mne_lsl.lsl import StreamInlet, resolve_streams

from myogestic.outputs import Output
from myogestic.outputs.lsl import LSLOutlet


class RecordingOutput(Output):
    """Test double that records every _send call."""

    def __init__(self, hz: float = 50):
        self.sent: list[np.ndarray] = []
        self._send_event = threading.Event()
        super().__init__(hz=hz)

    def _send(self, data: np.ndarray) -> None:
        self.sent.append(data.copy())
        self._send_event.set()


def test_output_send_loop_calls_send():
    """push() stores data, send thread picks it up and calls _send()."""
    out = RecordingOutput(hz=100)
    assert out._latest is None
    assert len(out.sent) == 0

    data = np.array([1.0, 2.0, 3.0])
    out.push(data)

    # Wait for at least one _send call
    assert out._send_event.wait(timeout=2.0), "_send was never called"
    assert len(out.sent) >= 1
    np.testing.assert_array_equal(out.sent[0], data)

    out.stop()


def test_output_send_loop_runs_at_hz():
    """Verify the send thread fires roughly at the requested rate."""
    out = RecordingOutput(hz=50)
    out.push(np.array([1.0]))
    time.sleep(0.2)  # 50 Hz => ~10 calls in 200ms

    count = len(out.sent)
    assert count >= 5, f"Expected >=5 sends in 200ms at 50Hz, got {count}"
    assert count <= 20, f"Expected <=20 sends in 200ms at 50Hz, got {count}"

    out.stop()


def test_output_push_overwrites():
    """Later push() replaces earlier data atomically."""
    out = RecordingOutput(hz=20)
    out.push(np.array([1.0]))
    time.sleep(0.15)
    out.push(np.array([99.0]))
    time.sleep(0.15)

    # The last few sends should contain 99.0
    last = out.sent[-1]
    np.testing.assert_array_equal(last, np.array([99.0]))

    out.stop()


def test_output_no_send_without_push():
    """If nothing is pushed, _send is never called."""
    out = RecordingOutput(hz=100)
    time.sleep(0.1)
    assert len(out.sent) == 0
    out.stop()


def test_output_send_exception_does_not_crash():
    """An exception in _send must not kill the send thread."""

    class FailOnceOutput(Output):
        def __init__(self):
            self.call_count = 0
            self._survived = threading.Event()
            super().__init__(hz=100)

        def _send(self, data):
            self.call_count += 1
            if self.call_count == 1:
                raise ValueError("boom")
            self._survived.set()

    out = FailOnceOutput()
    out.push(np.array([1.0]))
    assert out._survived.wait(timeout=2.0), "Send thread died after exception"
    assert out.call_count >= 2
    out.stop()


def test_output_logs_first_error_per_kind(caplog):
    """First send-loop exception of a given (class, message) is logged at
    WARNING; subsequent identical errors are suppressed so a noisy
    disconnect does not flood the log."""
    import logging

    class AlwaysFails(Output):
        def __init__(self):
            self.call_count = 0
            super().__init__(hz=200)

        def _send(self, data):
            self.call_count += 1
            raise ValueError("device unplugged")

    out = AlwaysFails()
    with caplog.at_level(logging.WARNING, logger="myogestic.outputs"):
        out.push(np.array([1.0]))
        time.sleep(0.2)  # enough for many _send attempts
    out.stop()

    assert out.call_count >= 2, "send loop did not retry after first failure"
    matching = [r for r in caplog.records if "device unplugged" in r.getMessage()]
    assert len(matching) == 1, f"expected exactly one WARNING per error kind, got {len(matching)}"


def test_lsl_outlet_rejects_wrong_shape(caplog):
    """A wrong-shape push surfaces ValueError via the dedup logger
    (instead of silently dropping the sample)."""
    import logging

    out = LSLOutlet("TestControl_BadShape", n_channels=3, hz=200)
    with caplog.at_level(logging.WARNING, logger="myogestic.outputs"):
        out.push(np.array([1.0, 2.0]))  # wrong: 2 != n_channels=3
        time.sleep(0.2)
    out.stop()

    matching = [r for r in caplog.records if "expected 1-D vector of length 3" in r.getMessage()]
    assert matching, "wrong-shape push did not produce the expected warning"


def test_lsl_outlet_roundtrip():
    """LSLOutlet push -> LSL network -> StreamInlet receive."""
    out = LSLOutlet("TestControl", n_channels=3, hz=50)

    # Receive side
    streams = resolve_streams(timeout=5.0, name="TestControl")
    assert len(streams) > 0, "LSLOutlet stream not found"
    inlet = StreamInlet(streams[0])

    out.push(np.array([1.0, 2.0, 3.0]))
    time.sleep(0.2)

    samples, _ = inlet.pull_chunk(timeout=1.0)
    assert len(samples) > 0, "No samples received from LSLOutlet"
    # Last sample should match pushed data
    np.testing.assert_allclose(samples[-1], [1.0, 2.0, 3.0], atol=1e-6)

    inlet.close_stream()
    out.stop()
