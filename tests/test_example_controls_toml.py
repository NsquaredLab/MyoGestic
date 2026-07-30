"""The shipped mapping file must load, and must keep demonstrating what it claims to.

`examples/controls/hand.toml` is user-facing: people copy it, edit it, and expect it to
work. It is also what `tools/inspect_control.py` loads, so a syntax error or a
rename would break the walkthrough silently.

These assert the properties the file is meant to *teach* — arbitrary aliases, a 1:1
mapping, a fan-out, a weighted fan-out, a target-declared discrete state — not merely
that it parses. Resolution runs against a stand-in for VHI's manifest so the file is
checked without a Virtual Hand; `tests/test_v2_contract.py` covers the live manifest.
"""

from __future__ import annotations

import pathlib
import tomllib

import pytest

from myogestic.controls import Capability, ControlBus, load_control_map, resolve

CONFIG = pathlib.Path(__file__).resolve().parent.parent / "examples" / "controls" / "hand.toml"

FINGERS = ("thumb", "index", "middle", "ring", "little")

#: What VHI's GetControlManifest declares, mirrored. Kept in step by
#: tests/test_v2_contract.py, which asserts the same set against a live build.
VHI_MANIFEST = [
    *(
        Capability(address, "continuous", lo=-1.0, hi=1.0, rest=0.0)
        for digit in FINGERS
        for address in (f"vhi.prediction.{digit}", f"vhi.prediction.{digit}.flexion")
    ),
    Capability("vhi.prediction.thumb.abduction", "continuous", lo=-1.0, hi=1.0, rest=0.0),
    Capability(
        "vhi.control.gesture",
        "discrete",
        states=("Rest", "Fist", "Pointing"),
        rest_state="Rest",
    ),
]


@pytest.fixture(scope="module")
def control_map():
    """The shipped file, loaded exactly as the docs tell a user to load it."""
    with CONFIG.open("rb") as handle:  # "rb" — tomllib requires binary
        return load_control_map(tomllib.load(handle))


@pytest.fixture(scope="module")
def resolved(control_map):
    """...and resolved against what the target says it exports."""
    return resolve(control_map, VHI_MANIFEST)


def test_the_file_exists_where_the_docs_say_it_does():
    assert CONFIG.is_file(), CONFIG


def test_it_loads_through_the_documented_two_liner(control_map):
    assert control_map.bindings, "an empty map would parse but teach nothing"


def test_the_aliases_are_the_users_own(control_map):
    """None of them may look like a target address — that is the whole distinction."""
    for alias in control_map.bindings:
        assert not alias.startswith("vhi."), f"{alias!r} reads as a target address"


def test_every_address_is_exported_by_the_target(resolved, control_map):
    """The file must not reference a control VHI does not actually declare."""
    exported = {cap.address for cap in VHI_MANIFEST}
    for address in control_map.addresses():
        assert address in exported, address


def test_a_one_to_one_mapping_is_demonstrated(resolved):
    single = [a for a, refs in resolved.routes.items() if len(refs) == 1]
    assert single, "the file must show the common 1:1 case"


def test_a_fan_out_is_demonstrated(resolved):
    """One user output reaching several target controls, no whole-hand capability.

    Only a fan-out is asserted, not also an equal-weight one: this hand exports six
    streamed controls and two aliases may not target the same one, so a single file
    cannot show two fan-outs. The plain equal-weight list form is documented in the
    file's header and shown in the other files under ``examples/controls/``.
    """
    fanned = {a: refs for a, refs in resolved.routes.items() if len(refs) > 1}
    assert fanned, "the file must show a fan-out"
    assert any(len(refs) >= 3 for refs in fanned.values()), "and a real one, not a pair"


def test_a_weighted_fan_out_is_demonstrated(resolved):
    weighted = [
        a for a, refs in resolved.routes.items() if any(r.weight != 1.0 for r in refs)
    ]
    assert weighted, "the file must show a per-target weight"
    for alias in weighted:
        for ref in resolved.routes[alias]:
            assert 0.0 < abs(ref.weight) <= 1.0, (alias, ref)


def test_a_target_declared_discrete_state_is_demonstrated(resolved):
    """The kind is the target's declaration, and the file must exercise that path."""
    discrete = [d for d in resolved.dofs.values() if hasattr(d, "states")]
    assert discrete, "the file must map something onto a discrete control"
    for dof in discrete:
        assert dof.states, "states come from the manifest"
        assert dof.rest in dof.states


def test_a_stability_gate_is_demonstrated(resolved):
    """`debounce_s` is declared on this side — it belongs to the control loop."""
    gated = [d for d in resolved.dofs.values() if getattr(d, "debounce_s", 0) > 0]
    assert gated, "the file must show a debounce"


def test_the_resolved_space_actually_drives_a_bus(resolved):
    """Parsing is not enough — the file has to produce a usable control space."""
    seen: list[dict] = []

    class Recorder:
        def bind(self, controls) -> None: ...

        def send(self, values, changed) -> None:
            seen.append(dict(values))

        def stop(self) -> None: ...

    continuous = [d for d in resolved.dofs.values() if hasattr(d, "lo")]
    bus = ControlBus(resolved, targets=[Recorder()], hz=50)
    delivered = bus.push({d.name: d.hi for d in continuous})
    assert seen, "the bus delivered nothing"
    for dof in continuous:
        assert delivered[dof.name] == pytest.approx(dof.hi)
    bus.stop()
    assert seen[-1] == {d.name: d.rest for d in resolved.dofs.values()}


def test_the_walkthrough_points_at_this_file():
    """If the walkthrough's path drifts, this suite is the only thing that would know."""
    walkthrough = CONFIG.parents[2] / "tools" / "inspect_control.py"
    text = walkthrough.read_text()
    assert '"examples"' in text and '"controls"' in text and '"hand.toml"' in text


class TestTheClassificationFileTeachesTheUnifiedPath:
    """`examples/controls/classification.toml` — a classifier through the same mapping.

    The claim the file makes is that classification and regression are the *same*
    connection to the target: the classifier's output is gated to an activation and then
    fanned out and weighted exactly as a regressed value would be, so VHI receives
    continuous per-control values and no separate state command. If that ever regressed
    into a discrete path, the file would still parse and would teach the wrong thing.
    """

    CONFIG = CONFIG.parent / "classification.toml"

    @pytest.fixture(scope="class")
    def resolved(self):
        with self.CONFIG.open("rb") as handle:
            return resolve(load_control_map(tomllib.load(handle)), VHI_MANIFEST)

    def test_the_classifier_drives_continuous_controls_not_a_state(self, resolved):
        assert not any(hasattr(dof, "states") for dof in resolved.dofs.values())

    def test_the_activation_is_gated_and_weighted(self, resolved):
        gated = [d for d in resolved.dofs.values() if d.threshold_fraction is not None]
        assert gated, "the file must show a probability cutoff"
        assert any(
            any(ref.weight != 1.0 for ref in resolved.routes[d.name]) for d in gated
        ), "and one that still fans out with weights, as a regressor's would"

    @pytest.mark.parametrize(("probability", "sent"), [(0.2, 0.0), (0.9, 1.0)])
    def test_a_probability_never_reaches_a_target_as_itself(
        self, resolved, probability, sent
    ):
        """The headline behaviour: 0 to every listed control, or 1 x each weight."""
        bus = ControlBus(resolved, targets=[], hz=50)
        delivered = bus.push({name: probability for name in resolved.dofs})
        assert set(delivered.values()) == {sent}
        bus.stop()

    def test_the_example_pushes_the_probability_it_documents(self):
        """The file and the app that loads it have to agree about who gates."""
        app = self.CONFIG.parents[1] / "synthetic" / "emg_classification.py"
        text = app.read_text()
        assert "classification.toml" in text
        assert "proba[" in text.split("def predict")[1], "it must push the probability"


class TestTheWalkthroughDemonstratesTheClassifierPath:
    """`tools/inspect_control.py` is the one runnable artifact for this design.

    It is what the docs tell a reader to run, so terminology that never appears there is
    terminology they will not meet. `threshold_fraction` was absent from it for exactly
    that reason once already — the rename touched the library, the files and the prose,
    and left the demonstration behind.
    """

    WALKTHROUGH = CONFIG.parents[2] / "tools" / "inspect_control.py"

    @pytest.fixture(scope="class")
    def source(self):
        return self.WALKTHROUGH.read_text()

    def test_it_loads_the_classifier_mapping_file(self, source):
        assert "classification.toml" in source

    def test_it_names_the_cutoff_by_its_real_name(self, source):
        assert "threshold_fraction" in source
        assert ".threshold" not in source.replace(".threshold_fraction", "")

    def test_it_shows_both_sides_of_the_cutoff(self, source):
        """A demonstration that only ever shows the active side proves nothing."""
        assert "substitute_rest" in source, "it must gate real values, not describe gating"
        step = source.split("def step_5_classification")[1].split("\ndef ")[0]
        probabilities = [
            float(p)
            for p in __import__("re").findall(r"\b0\.\d+|\b[01]\.0\b", step)
        ]
        assert any(p < 0.5 for p in probabilities), "no inactive case shown"
        assert any(p >= 0.5 for p in probabilities), "no active case shown"

    def test_the_step_it_lives_in_is_actually_called(self, source):
        """A step defined but never reached would pass every check above."""
        assert "step_5_classification(capabilities)" in source
