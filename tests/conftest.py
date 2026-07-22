"""Shared test fixtures."""

import pytest


@pytest.fixture
def imgui_frame():
    """A minimal offscreen ImGui context so a widget's ``.ui()`` runs headless.

    Sets the dynamic-texture backend flag so no GL renderer / built font atlas
    is required — we only run the layout pass, which is enough to trip
    missing-API or bad-argument errors in a widget's render code that the
    pure-logic tests never reach.

    Yields a ``frame(draw)`` callable that wraps ``draw`` in one new_frame /
    begin / end / render cycle.
    """
    from imgui_bundle import imgui

    imgui.create_context()
    io = imgui.get_io()
    io.display_size = imgui.ImVec2(700, 500)
    io.fonts.add_font_default()
    io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
    io.fonts.tex_is_built = True

    def frame(draw):
        imgui.new_frame()
        # Force a deterministic window width so width-dependent tests (e.g.
        # panel-header truncation) don't hinge on a stray imgui.ini — which is
        # wide on a dev box but absent on fresh CI, flipping "does it fit".
        imgui.set_next_window_size(imgui.ImVec2(680.0, 480.0))
        imgui.begin("t")
        draw()
        imgui.end()
        imgui.end_frame()
        imgui.render()

    try:
        yield frame
    finally:
        imgui.destroy_context()


@pytest.fixture
def implot_frame(imgui_frame):
    """Like :func:`imgui_frame`, but with an ImPlot context too (plot widgets)."""
    from imgui_bundle import implot

    implot.create_context()
    try:
        yield imgui_frame
    finally:
        implot.destroy_context()
