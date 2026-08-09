"""The stream-age read-out must hold still while it updates.

It changes every frame — at 2048 Hz with 64-sample chunks the age sweeps
0→31 ms and back, several times a second. Any width change is visible as jitter,
and in a tooltip it resizes the whole box.
"""

import pytest
from imgui_bundle import imgui

from myogestic.widgets.common import format_age

_MONO = "myogestic/assets/fonts/IBMPlexMono-Regular.ttf"
_ALL_BANDS = [None, 0.0, 0.009, 0.026, 0.111, 0.999, 1.0, 1.4, 99.9, 500.0, 86_400.0]


@pytest.mark.parametrize("seconds", _ALL_BANDS)
def test_every_band_is_the_same_length(seconds):
    assert len(format_age(seconds)) == len(format_age(0.026))


def test_the_bands_read_in_the_unit_the_operator_thinks_in():
    assert format_age(0.026).strip() == "last  26 ms"
    assert format_age(1.4).strip() == "last  1.4 s"
    assert format_age(None).strip() == "last   — ms"
    # Beyond a minute the exact figure is noise; the stream is simply gone.
    assert format_age(500.0).strip() == "last  >99 s"


def test_the_readout_is_pixel_stable_in_the_mono_face():
    """The real assertion. Fixed *character count* alone does not do it.

    The UI face is proportional and its digits are not tabular — SF Pro draws
    ``1`` at 6 px and ``9`` at 9 px — so ``last 111 ms`` and ``last 999 ms``
    differ in width however they are padded. Only the mono face holds them
    identical, which is why `mono_text` exists.
    """
    imgui.create_context()
    try:
        io = imgui.get_io()
        io.display_size = imgui.ImVec2(700, 500)
        io.backend_flags |= imgui.BackendFlags_.renderer_has_textures
        font = io.fonts.add_font_from_file_ttf(_MONO, 13.0)
        io.fonts.tex_is_built = True

        imgui.new_frame()
        imgui.begin("t")
        imgui.push_font(font, 13.0)
        widths = {imgui.calc_text_size(format_age(s)).x for s in _ALL_BANDS}
        imgui.pop_font()
        imgui.end()
        imgui.end_frame()
        imgui.render()
    finally:
        imgui.destroy_context()

    assert len(widths) == 1, f"the read-out changes width across bands: {sorted(widths)}"
