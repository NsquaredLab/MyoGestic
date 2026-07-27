"""Execute the *runnable* docstring Examples so the reference stays honest.

Most public symbols are GUI/hardware, so their `Examples` are illustrative and
not run. The pure-computation ones below are real doctests: this collects each
object's own docstring example and runs it, failing if the shown output drifts
from what the code actually returns. Object-level (``recurse=False``) so the
GUI examples living in the same modules are never collected — no ``+SKIP``
clutter needed on the illustrative ones.
"""

from __future__ import annotations

import doctest

import pytest

from myogestic import EdgeTrigger, Fr, Grid, Px, StreamInfo, TrainingData
from myogestic import controls as _controls
from myogestic.outputs import filters
from myogestic.recipes import estimators, features
from myogestic.vhi import legacy as _legacy

# Objects whose docstring Examples are deterministic and dependency-free.
RUNNABLE = [
    _legacy.decode_pose,
    _legacy.encode_pose,
    _controls.Continuous,
    _controls.Discrete,
    _controls.ControlSet,
    _controls.load_dofs,
    _controls.substitute_rest,
    _controls.clip,
    _controls.encode,
    _controls.decode,
    StreamInfo,
    TrainingData,
    Grid,
    Px,
    Fr,
    EdgeTrigger,
    features.rms,
    features.mav,
    features.wl,
    features.var,
    features.zc,
    filters.VectorFilter,
    filters.OneEuroFilter,
    filters.GaussianFilter,
    filters.IdentityFilter,
    filters.make_filter,
    filters.chain,
    estimators.constant_classifier,
    estimators.mean_regressor,
]


@pytest.mark.parametrize("obj", RUNNABLE, ids=lambda o: getattr(o, "__name__", str(o)))
def test_docstring_example_runs(obj):
    """The object's docstring must carry an Examples block that executes cleanly."""
    finder = doctest.DocTestFinder(recurse=False)
    tests = finder.find(obj, globs={})
    assert tests, f"{getattr(obj, '__name__', obj)} has no docstring to test"
    example_tests = [t for t in tests if t.examples]
    assert example_tests, f"{getattr(obj, '__name__', obj)} has no `>>>` Examples section"

    runner = doctest.DocTestRunner(optionflags=doctest.NORMALIZE_WHITESPACE)
    for t in example_tests:
        runner.run(t)
    result = runner.summarize(verbose=False)
    assert result.failed == 0, f"docstring example failed for {getattr(obj, '__name__', obj)}"
