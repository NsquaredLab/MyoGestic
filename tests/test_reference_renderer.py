"""The reference renderer is the claim 'the contract is small', made executable."""

from __future__ import annotations

import importlib.util
import pathlib
import time

import pytest

RENDERER = (
    pathlib.Path(__file__).parent.parent
    / "examples" / "synthetic" / "reference_renderer.py"
)


@pytest.fixture(scope="module")
def renderer_module():
    pytest.importorskip("grpc")
    spec = importlib.util.spec_from_file_location("reference_renderer", RENDERER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.lsl_contention
def test_a_control_bus_drives_the_reference_renderer(renderer_module):
    """Serve a manifest, read a stream, get driven. No Declare in the path.

    Deselected from the default run (see the `lsl_contention` marker registered in
    pyproject.toml): a bounded 3-attempt retry with a fresh outlet/renderer/inlet per
    attempt (see git history for the tried-and-reverted version) still failed outright
    in 2 of 3 full-suite runs on this dev machine, so retrying does not make this a
    signal the default suite can carry. It passes reliably every time run alone —
    `uv run --extra grpc --extra dev pytest -m lsl_contention -q`. See CLAUDE.md.
    """
    from myogestic.controls import connect_controls, load_control_map
    from myogestic.vhi import VhiTarget, virtual_hand

    renderer = renderer_module.ReferenceRenderer(port=50099)
    renderer.serve()
    try:
        vhi = virtual_hand(grpc_port=50099)
        client = vhi.control_client()
        # Two addresses, and on this renderer that is two streams — one per control,
        # named for the control.
        control_map = load_control_map(
            {"dofs": {"close": "vhi.prediction.index", "spread": "vhi.prediction.little"}}
        )
        # No stream is named on this side and there is no field that could name one: a
        # control's stream is its address, and the target publishes under exactly that —
        # which is the whole reason this end-to-end can find the other end at all.
        target = VhiTarget(client=client, interface=vhi)
        bus = connect_controls(control_map, [target], hz=32)
        assert bus is not None, "the renderer's manifest did not resolve"

        # Opposite signs, because a renderer applying each address as it arrives has to be
        # caught writing one value onto both streams — which a matching pair would hide.
        index, little = "vhi.prediction.index", "vhi.prediction.little"
        deadline = time.time() + 10.0
        while time.time() < deadline and renderer.pose[index] < 0.9:
            bus.push({"close": 1.0, "spread": -1.0})
            time.sleep(0.1)
        assert renderer.pose[index] == pytest.approx(1.0, abs=0.05), renderer.pose
        assert renderer.pose[little] == pytest.approx(-1.0, abs=0.05), renderer.pose
        bus.stop()
        client.stop()
    finally:
        renderer.stop()


def test_a_renderer_reporting_an_older_vocabulary_is_refused_by_name(renderer_module):
    """The gate that makes a version-skewed pair say so instead of just not moving.

    MyoGestic and the renderer are installed separately, so an upgrade on one side is not
    an upgrade on both. A vocabulary-1 renderer listens for a wide pose stream nothing
    publishes any more and reports nothing at all — the hand simply never moves. This is
    the one place that turns that into a sentence.

    No LSL here: the refusal is on the manifest, so this is a gRPC round trip and nothing
    else, and it runs in the default suite.
    """
    from myogestic.vhi import virtual_hand

    class Antique(renderer_module.ReferenceRenderer):
        """The same renderer, still claiming the vocabulary it served before the split."""

        def GetControlManifest(self, request, context):   # noqa: N802 - gRPC's spelling
            manifest = super().GetControlManifest(request, context)
            manifest.vocabulary_version = "1"
            return manifest

    renderer = Antique(port=50098)
    renderer.serve()
    try:
        client = virtual_hand(grpc_port=50098).control_client()
        try:
            with pytest.raises(ValueError) as excinfo:
                client.capabilities()
        finally:
            client.stop()
    finally:
        renderer.stop()

    message = str(excinfo.value)
    # Both versions by name, and the remedy: a refusal that says only "incompatible"
    # leaves the reader to guess which side is behind.
    assert "vocabulary 1" in message, message
    assert "needs 2 or newer" in message, message
    assert message.endswith("Update VHI."), message


def test_the_reference_renderer_reports_the_vocabulary_this_client_needs(renderer_module):
    """The example renderers ship must be one a current MyoGestic will actually drive."""
    from myogestic.vhi._control import _MIN_VOCABULARY, _vocabulary

    manifest = renderer_module.ReferenceRenderer(port=0).GetControlManifest(None, None)
    assert _vocabulary(manifest.vocabulary_version) >= _MIN_VOCABULARY
