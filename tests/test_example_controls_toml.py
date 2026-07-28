"""The shipped TOML config must load, and must keep demonstrating what it claims to.

`examples/controls/hand.toml` is a user-facing file: people copy it, edit it, and expect
it to work. It is also what `tools/inspect_canonical_control.py` loads, so a syntax error
or a rename would break the walkthrough silently — a doc example that is never executed
rots, which is why this exists rather than a prose promise that the file is valid.

These assert the *properties the file is meant to teach*, not merely that it parses:
the mapping-first short forms, a signed continuous DOF, a one-way DOF, and a discrete
state with a stability gate.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from myogestic.controls import Continuous, ControlBus, Discrete, load_dofs

CONFIG = pathlib.Path(__file__).resolve().parent.parent / "examples" / "controls" / "hand.toml"


@pytest.fixture(scope="module")
def controls():
    """The shipped file, loaded exactly as the docs tell a user to load it."""
    with CONFIG.open("rb") as handle:  # "rb" — tomllib requires binary
        return load_dofs(tomllib.load(handle))


def test_the_file_exists_where_the_docs_say_it_does():
    """A moved file breaks the walkthrough and every doc snippet pointing at it."""
    assert CONFIG.is_file(), CONFIG


def test_it_loads_through_the_documented_two_liner(controls):
    assert controls.dofs, "an empty control space would parse but teach nothing"


def test_the_mapping_first_short_forms_are_demonstrated(controls):
    """A bare string is continuous; a bare array is discrete. The smallest syntax."""
    raw = tomllib.loads(CONFIG.read_text())["dofs"]
    assert any(isinstance(v, str) for v in raw.values()), "no short-form continuous DOF"
    assert any(isinstance(v, list) for v in raw.values()), "no short-form discrete DOF"
    assert any(isinstance(v, dict) for v in raw.values()), "no explicit table form"


def test_a_signed_continuous_dof_is_demonstrated(controls):
    """The canonical domain is signed: +1 is the direction the name denotes."""
    signed = [d for d in controls.continuous if d.lo < 0 < d.hi]
    assert signed, "the file must show a signed DOF — that is the canonical default"
    for dof in signed:
        assert dof.rest == 0.0, f"{dof.name}: rest must be 0 for a signed DOF"


def test_a_one_way_dof_is_demonstrated(controls):
    """Declaring [0, 1] is how a model is prevented from commanding a direction."""
    one_way = [d for d in controls.continuous if d.lo == 0.0]
    assert one_way, "the file must show a one-way range"
    for dof in one_way:
        assert dof.lo <= dof.rest <= dof.hi


def test_a_grasp_state_is_demonstrated(controls):
    """The product requirement: a discrete grasp/fist state, declared in the file."""
    discrete = controls.discrete
    assert discrete, "the file must declare a discrete DOF"
    states = {s.lower() for dof in discrete for s in dof.states}
    assert "fist" in states, f"expected a fist state, got {sorted(states)}"
    assert "rest" in states, "a discrete DOF needs a neutral state"
    for dof in discrete:
        assert dof.rest in dof.states


def test_a_stability_gate_is_demonstrated(controls):
    """`debounce_s` on the DOF is what protects a classifier from its own chatter."""
    gated = [d for d in controls.discrete if d.debounce_s > 0]
    assert gated, "the file must show a debounce — it is the discrete protection"


def test_every_dof_is_the_kind_its_shape_implies(controls):
    for dof in controls.dofs.values():
        assert isinstance(dof, (Continuous, Discrete)), dof


def test_the_loaded_space_actually_drives_a_bus(controls):
    """Parsing is not enough — the file has to produce a usable control space."""
    seen: list[dict] = []

    class Recorder:
        def bind(self, controls) -> None: ...

        def send(self, values, changed) -> None:
            seen.append(dict(values))

        def stop(self) -> None: ...

    bus = ControlBus(controls, targets=[Recorder()], hz=50)
    delivered = bus.push({d.name: d.hi for d in controls.continuous})
    assert seen, "the bus delivered nothing"
    for dof in controls.continuous:
        assert delivered[dof.name] == pytest.approx(dof.hi)
    bus.stop()
    # stop() must leave every DOF at its declared rest, from the file's own values.
    assert seen[-1] == {d.name: d.rest for d in controls.dofs.values()}


def test_the_walkthrough_points_at_this_file():
    """If the walkthrough's path drifts, this suite is the only thing that would know."""
    walkthrough = CONFIG.parents[2] / "tools" / "inspect_canonical_control.py"
    text = walkthrough.read_text()
    assert '"examples"' in text and '"controls"' in text and '"hand.toml"' in text
