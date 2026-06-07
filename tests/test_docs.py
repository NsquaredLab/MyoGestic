"""Keep the documentation's code examples honest.

Two layers, because most doc snippets are illustrative GUI/pipeline *fragments*
(they call ``app.run()`` or reference an undefined ``pipeline``/``data``) and
cannot run standalone:

1. **Parse** — every ```` ```python ```` block in ``docs/`` + ``README.md`` must
   compile. Catches syntax / indentation rot in *all* blocks for free.
2. **Run** — a block tagged with an HTML comment ``<!--docs:run-->`` immediately
   above its fence is *executed* against a synthetic session in a per-file shared
   namespace. This catches the bugs reviews keep finding by hand — wrong kwargs,
   wrong attribute (``sw.data``), wrong tuple unpack — that a parse check can't.
   Tag the self-contained, non-GUI data-API blocks. ``<!--docs:skip-->`` drops a
   block from *both* layers (shell snippets, intentionally-broken examples).

The seeded ``pipeline`` is a stand-in whose ``@pipeline.train`` decorator runs
the function *immediately* against the synthetic ``data``, so a tagged
``@pipeline.train`` block actually drives ``iter_*_windows`` rather than just
defining a function that never runs.

Run locally: ``uv run pytest tests/test_docs.py``  (``-k run`` for just layer 2).
"""

from __future__ import annotations

import ast
import re
import shutil
import tempfile
import textwrap
from pathlib import Path

import numpy as np
import pytest

from myogestic.contracts import TrainingData
from myogestic.recipes.features import mav, rms
from myogestic.session import (
    Session,
    iter_aligned_windows,
    iter_labeled_windows,
    open_session_store,
)
from myogestic.stream import StreamInfo

ROOT = Path(__file__).resolve().parent.parent
MD_FILES = sorted(
    p
    for p in [*(ROOT / "docs").rglob("*.md"), ROOT / "README.md"]
    if p.exists() and "superpowers" not in p.parts and "playground" not in p.parts
)

# Optional `<!--docs:run-->` / `<!--docs:skip-->` directive on the line above a fence.
_BLOCK = re.compile(
    # The closing fence may be indented (code block nested in a list item), so
    # allow leading whitespace before it; textwrap.dedent then cleans the body.
    r"(?:<!--\s*docs:(run|skip)\s*-->[ \t]*\n)?```python\n(.*?)\n[ \t]*```",
    re.DOTALL,
)


def _blocks(path: Path):
    """Yield ``(directive, code, line_number)`` for each python block in a file."""
    text = path.read_text(encoding="utf-8")
    for m in _BLOCK.finditer(text):
        directive, code = m.group(1), m.group(2)
        # Dedent: code blocks nested in a list item (e.g. "3. ```python") carry
        # the list's indentation, which mkdocs strips on render but ast.parse
        # would choke on.
        code = textwrap.dedent(code)
        # `--8<--` snippet includes pull real code from examples/ (the example is
        # import/wire-tested by tests/test_examples.py) — they aren't literal
        # python here, so skip both layers.
        if directive is None and any(ln.lstrip().startswith("--8<--") for ln in code.splitlines()):
            directive = "skip"
        yield directive, code, text[: m.start()].count("\n") + 1


_ALL = [(p, d, code, ln) for p in MD_FILES for d, code, ln in _blocks(p)]


# --- Layer 1: every non-skipped block must parse -----------------------------

_PARSE = [
    pytest.param(code, id=f"{p.relative_to(ROOT)}:{ln}")
    for p, d, code, ln in _ALL
    if d != "skip"
]


@pytest.mark.parametrize("code", _PARSE)
def test_doc_block_parses(code):
    ast.parse(code)


# --- Layer 2: execute `docs:run` blocks against a synthetic session ----------


class _DocPipeline:
    """Stand-in pipeline: ``@train`` runs the function now, so the iterator runs."""

    def __init__(self, data: TrainingData) -> None:
        self._data = data
        self.model = None
        self.predictions: dict = {}
        self.predict_hz = 50.0
        self.training_data: TrainingData | None = None

    def extract(self, fn):  # noqa: D102
        self.on_extract = fn
        return fn

    def train(self, fn):  # noqa: D102
        self.model = fn(self._data)  # invoke immediately to exercise the body
        return fn

    def predict(self, fn):  # noqa: D102
        self.on_predict = fn
        return fn


class _StubEstimator:
    """Minimal fit/predict so doc training examples run without sklearn."""

    def fit(self, X, y):  # noqa: D102
        self.classes_ = np.unique(y) if len(y) else np.array([0])
        return self

    def predict(self, X):  # noqa: D102
        return np.zeros(len(X), dtype=int)

    def predict_proba(self, X):  # noqa: D102
        return np.tile([1.0, 0.0], (len(X), 1))


@pytest.fixture(scope="module")
def doc_session():
    """A small on-disk session: emg + aligned vhi_guide stream + 3 labelled classes."""
    tmp = tempfile.mkdtemp()
    rng = np.random.default_rng(0)
    s = Session(base_path=tmp)
    fs, n = 2000.0, 6000  # 3 s of EMG
    s.init_stream("emg", StreamInfo(n_channels=8, fs=fs, dtype=np.dtype("float32")))
    s.append("emg", rng.normal(size=(n, 8)).astype(np.float32), np.arange(n) / fs)
    fsg, ng = 60.0, 180  # aligned guide stream over the same span
    s.init_stream("vhi_guide", StreamInfo(n_channels=5, fs=fsg, dtype=np.dtype("float32")))
    s.append("vhi_guide", rng.normal(size=(ng, 5)).astype(np.float32), np.arange(ng) / fsg)
    for t, c in [(0.2, 0), (1.0, 1), (2.0, 2)]:
        s.add_label(c, timestamp=t)
    s.save_meta("DocTest", class_names=["a", "b", "c"])
    yield s
    shutil.rmtree(tmp, ignore_errors=True)


_RUN_FILES = sorted({p for p, d, _, _ in _ALL if d == "run"})


@pytest.mark.parametrize("path", [pytest.param(p, id=str(p.relative_to(ROOT))) for p in _RUN_FILES])
def test_doc_page_runs(path, doc_session):
    """Execute every `docs:run` block of a page in order, sharing one namespace."""
    data = TrainingData(paths=[str(doc_session.path)], class_names=["a", "b", "c"], classes={0, 1, 2})
    ns: dict = {
        "np": np,
        "data": data,
        "sess": doc_session,
        "pipeline": _DocPipeline(data),
        "rms": rms,
        "mav": mav,
        "rms_features": rms,
        "extract": lambda windows: rms(windows["emg"]),
        "LogisticRegression": _StubEstimator,
        "MultiOutputRegressor": lambda *a, **k: _StubEstimator(),
        "TrainingData": TrainingData,
        "iter_labeled_windows": iter_labeled_windows,
        "iter_aligned_windows": iter_aligned_windows,
        "open_session_store": open_session_store,
        "StreamInfo": StreamInfo,
    }
    for d, code, ln in _blocks(path):
        if d != "run":
            continue
        try:
            exec(compile(code, f"{path}:{ln}", "exec"), ns)  # noqa: S102
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{path.relative_to(ROOT)}:{ln} doc block raised {type(e).__name__}: {e}")
