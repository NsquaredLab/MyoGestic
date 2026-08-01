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
    from myogestic.vhi import vhi_targets, virtual_hand

    renderer = renderer_module.ReferenceRenderer(port=50099)
    renderer.serve()
    try:
        vhi = virtual_hand(grpc_port=50099)
        client = vhi.control_client()
        # Two addresses, and on this renderer that is two streams — so this also pins the
        # thing `vhi_targets` exists for: the map is grouped by the `stream_name` the
        # manifest reports, and each group gets the target that drives it.
        control_map = load_control_map(
            {"dofs": {"close": "vhi.prediction.index", "spread": "vhi.prediction.little"}}
        )
        # No stream is named on this side: the renderer's manifest says which one carries
        # each address, and each target publishes under exactly that name — which is the
        # whole reason this end-to-end can find the other end at all.
        targets = vhi_targets(control_map, vhi, client=client)
        assert targets is not None, "the renderer did not answer GetControlManifest"
        assert len(targets) == 2, "one target per stream the map names"
        bus = connect_controls(control_map, targets, hz=32)
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
