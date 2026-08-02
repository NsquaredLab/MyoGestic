"""Collapsing GLFW's per-frame monitor warning without hiding it.

GLFW's Cocoa backend logs `Cannot query workarea without screen` once or twice **per
frame** — ~90 lines a second, which buries everything the application prints.

The cause is a mirrored display: GLFW builds its monitor list from CoreGraphics' *online*
displays, which includes a mirror slave, and macOS gives a mirror slave no `NSScreen`. So
GLFW holds a monitor it can never resolve. Measured: 3 online displays to CoreGraphics, 2
screens to AppKit, the missing one being the built-in mirroring an external. It reproduces
in a bare imgui_bundle app with multi-viewport on (497 lines) or off (522), so neither this
package nor the viewports are involved.

It cannot be fixed here: it is GLFW via hello_imgui, and its error callback is unreachable
because imgui_bundle links GLFW statically and exposes no setter. It also does not affect
rendering. So the noise is collapsed — shown once, the rest counted — and these tests pin
that the collapsing neither loses the first warning nor swallows anything else.
"""

from __future__ import annotations

import os
import sys

from myogestic.core import _collapse_glfw_monitor_spam

SPAM = b"Glfw Error 65544: Cocoa: Cannot query workarea without screen\n"


def _run_with_stderr_captured(body) -> str:
    """Run `body` with fd 2 on a pipe, and return everything it received."""
    read_fd, write_fd = os.pipe()
    saved = os.dup(2)
    os.dup2(write_fd, 2)
    os.close(write_fd)
    try:
        body()
        sys.stderr.flush()
    finally:
        os.dup2(saved, 2)
        os.close(saved)
    with os.fdopen(read_fd, "rb") as pipe:
        return pipe.read().decode()


def test_the_warning_is_shown_once_and_the_rest_counted():
    def body():
        with _collapse_glfw_monitor_spam():
            for _ in range(200):
                os.write(2, SPAM)

    out = _run_with_stderr_captured(body)
    assert out.count("Cannot query workarea") == 1, "shown exactly once"
    assert "199 more identical GLFW monitor warnings suppressed" in out
        # And it says how to stop it at the source, not just that it happened.
    assert "Extended" in out


def test_nothing_else_is_swallowed():
    """The risk of touching fd 2: losing output that mattered."""

    def body():
        with _collapse_glfw_monitor_spam():
            os.write(2, b"a real error\n")
            os.write(2, SPAM)
            os.write(2, b"another real error\n")

    out = _run_with_stderr_captured(body)
    assert "a real error" in out
    assert "another real error" in out


def test_a_lookalike_line_is_not_suppressed():
    """Only that exact GLFW message; anything else mentioning a screen passes."""

    def body():
        with _collapse_glfw_monitor_spam():
            os.write(2, b"Glfw Error 65544: Cocoa: something else entirely\n")
            os.write(2, b"cannot query workarea without screen (lowercase, different)\n")

    out = _run_with_stderr_captured(body)
    assert "something else entirely" in out
    assert "lowercase, different" in out


def test_no_summary_when_there_was_nothing_to_suppress():
    def body():
        with _collapse_glfw_monitor_spam():
            os.write(2, b"quiet\n")

    out = _run_with_stderr_captured(body)
    assert "suppressed" not in out
    assert "quiet" in out


def test_stderr_is_restored_afterwards():
    """A leaked redirection would silence the rest of the process."""

    def body():
        with _collapse_glfw_monitor_spam():
            os.write(2, SPAM)
        os.write(2, b"after the block\n")

    assert "after the block" in _run_with_stderr_captured(body)


def test_an_exception_inside_still_restores_stderr():
    def body():
        try:
            with _collapse_glfw_monitor_spam():
                os.write(2, SPAM)
                raise RuntimeError("boom")
        except RuntimeError:
            pass
        os.write(2, b"still here\n")

    assert "still here" in _run_with_stderr_captured(body)
