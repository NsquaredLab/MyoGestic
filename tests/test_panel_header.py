"""Ellipsis / icon-only truncation of the shared ``panel_header``."""

from imgui_bundle import imgui

from myogestic.widgets.common import _fit_header


def test_full_title_when_it_fits(imgui_frame):
    def check():
        assert _fit_header("POST-PROCESSING", "X", 0.0) == "X  POST-PROCESSING"

    imgui_frame(check)


def test_ellipsis_when_narrow(imgui_frame):
    def check():
        avail = imgui.get_content_region_avail().x
        s = _fit_header("POST-PROCESSING", "X", avail - 70)  # ~70px to draw in
        assert s.startswith("X  ") and s.endswith("…") and s != "X  POST-PROCESSING"

    imgui_frame(check)


def test_icon_only_when_tiny(imgui_frame):
    def check():
        avail = imgui.get_content_region_avail().x
        assert _fit_header("POST-PROCESSING", "X", avail - 14) == "X"  # no room for a label

    imgui_frame(check)


def test_truncates_without_an_icon(imgui_frame):
    def check():
        avail = imgui.get_content_region_avail().x
        assert _fit_header("POST-PROCESSING", None, avail - 60).endswith("…")

    imgui_frame(check)
