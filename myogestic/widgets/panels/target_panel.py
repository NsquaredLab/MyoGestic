"""One card for the separate processes an app drives: launch each, or connect to it.

Usage:
    from myogestic.widgets import TargetPanel

    hands = TargetPanel([vhi, kappa], connectors={vhi.name: connector}, title="Hands")

    @app.ui
    def ui(ctx):
        hands.ui(details={kappa.name: "board /dev/cu.usbmodem1101"})
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from imgui_bundle import icons_fontawesome_6 as fa
from imgui_bundle import imgui

from myogestic.widgets.common import (
    DANGER,
    IDLE,
    SUCCESS,
    WARNING,
    destructive_button,
    fit_text,
    mono_text,
    muted,
    panel_header,
    primary_button,
    tinted_row,
    ui_px,
)
from myogestic.widgets.panels import process_launcher
from myogestic.widgets.panels._target_state import Row, View, view
from myogestic.widgets.panels.log_box import render_log_popout

if TYPE_CHECKING:
    from myogestic.controls import ControlLinkConnector


class _Launchable(Protocol):
    """`myogestic.remote.InterfaceSpec`'s shape: a name, and how to start it."""

    name: str

    def launcher(self) -> list[tuple[str, list[str]]]: ...


class TargetPanel:
    """Launch the processes an app drives, or connect to ones already running.

    One card, one row per target: a dot and tint for its state, its name, the state in
    words with PID and elapsed time beside it, the one action that moves it on, and its
    output. A target with a connector is **connected first and launched only if none
    answers**, so a target someone already started is never started twice; one without
    is launched and stopped. Stop appears only for a process this card started. Processes
    are killed on exit, like `ProcessLauncher`'s.

    Parameters
    ----------
    targets
        Anything shaped like `myogestic.remote.InterfaceSpec`: a ``name`` and a
        ``launcher()`` returning ``[(name, argv)]``, or raising `FileNotFoundError` when
        it cannot be launched here (not installed, or a build this MyoGestic refuses).
        It is asked again on every press, so an install made meanwhile is picked up.
    connectors
        A `myogestic.controls.ControlLinkConnector` per target name, for the targets
        the app binds controls to. The app keeps it and reads ``link.bus`` as before.
    title, icon
        The card's `panel_header`.
    widget_id
        Scope for this card's processes and popouts. Defaults to ``title``.

    Examples
    --------
    >>> from myogestic.vhi import virtual_hand
    >>> from myogestic.widgets import TargetPanel
    >>> hands = TargetPanel([virtual_hand()], title="Hands")
    >>> hands.ui()
    """

    def __init__(
        self,
        targets: Sequence[_Launchable],
        *,
        connectors: Mapping[str, ControlLinkConnector] | None = None,
        title: str = "Targets",
        icon: str | None = fa.ICON_FA_PLUG,
        widget_id: str = "",
    ) -> None:
        self._targets = {target.name: target for target in targets}
        if len(self._targets) != len(targets):
            raise ValueError("targets: two share a name; give each target its own name.")
        self._connectors = dict(connectors or {})
        if unknown := sorted(set(self._connectors) - set(self._targets)):
            raise ValueError(f"connectors: no target named {unknown}; key each by its name.")
        self._title, self._icon = title, icon
        self._widget_id = widget_id or title
        self._rows = {name: Row() for name in self._targets}
        self._popped: dict[str, bool] = {}
        for name in self._targets:
            self._argv(name)  # so an idle row can already say it cannot launch

    def start(self, name: str) -> None:
        """Do what the row's forward action does: connect, or launch.

        Raises
        ------
        ValueError
            If no target is called ``name``.
        """
        row = self._row(name)
        row.unlaunched = False
        connector = self._connectors.get(name)
        if connector is None:
            self._launch(name)
            return
        row.pending = True
        connector.poll(force=True)

    def stop(self, name: str) -> None:
        """Stop the process this card started for ``name``, and drop its controls."""
        row = self._row(name)
        row.pending = False
        process = process_launcher._procs.get((self._widget_id, name))
        if process is not None:
            process.stop()
        if name in self._connectors:
            row.disconnect = True
            self._update(name)

    def running(self, name: str) -> bool:
        """Whether ``name`` is alive **because this card started it**."""
        self._row(name)
        process = process_launcher._procs.get((self._widget_id, name))
        return process is not None and process.alive

    def ui(self, *, details: Mapping[str, str] | None = None) -> None:
        """Render the card. Call once per frame inside ``@app.ui``.

        Parameters
        ----------
        details
            Per target name, values only the app knows, shown after the row's own,
            such as the serial port a hand also drives.
        """
        details = details or {}
        views: dict[str, View] = {}
        for name in self._targets:
            self._update(name)
            views[name] = self._view(name)
        # The header's dot is the most urgent row: a failure, then a wait, then anything
        # working. A target nobody started is not a problem with the ones that are up.
        tones = [v.tone for v in views.values()]
        status = next(
            (tone for tone in (DANGER, WARNING, SUCCESS) if any(t is tone for t in tones)), IDLE
        )
        panel_header(self._title, self._icon, status=status)
        imgui.set_item_tooltip("\n".join(f"{n}: {v.words}" for n, v in views.items()))
        imgui.push_id(self._widget_id)
        for name, row_view in views.items():
            self._row_ui(name, row_view, details.get(name, ""))
        imgui.pop_id()
        for name, popped in list(self._popped.items()):
            process = process_launcher._procs.get((self._widget_id, name))
            if popped and process is not None:
                self._popped[name] = render_log_popout(
                    f"{self._widget_id}_{name}", process.log, title=f"{name} output"
                )

    # --- state ----------------------------------------------------------------

    def _row(self, name: str) -> Row:
        if name not in self._rows:
            raise ValueError(f"No target named {name!r}; use one of {sorted(self._rows)}.")
        return self._rows[name]

    def _argv(self, name: str) -> list[str] | None:
        """The argv to launch ``name``, or ``None`` with the refusal remembered."""
        row = self._rows[name]
        try:
            rows = self._targets[name].launcher()
        except FileNotFoundError as error:
            row.refusal = str(error)
            return None
        row.refusal = "" if rows else f"{name}: nothing to launch."
        return list(rows[0][1]) if rows else None

    def _launch(self, name: str) -> None:
        argv = self._argv(name)
        if argv is None:
            self._rows[name].unlaunched = True
            return
        key = (self._widget_id, name)
        process = process_launcher._procs.setdefault(key, process_launcher._ProcState(name, argv))
        process.command = argv
        try:
            process.start()
        except Exception:  # noqa: BLE001 - start records the error; the row shows it
            pass

    def _update(self, name: str) -> None:
        """Advance a connector row: drop a bus whose process went, launch if nothing answered."""
        connector = self._connectors.get(name)
        if connector is None:
            return
        row = self._rows[name]
        process = process_launcher._procs.get((self._widget_id, name))
        alive = process is not None and process.alive
        gone = None if process is None or alive else process.process
        if gone is not None and gone is not row.dropped and connector.connected:
            row.dropped, row.disconnect = gone, True  # what this card started has exited
        if row.disconnect and not connector.busy:
            connector.disconnect()
            row.disconnect = False
        if alive and not connector.connected:
            connector.poll()  # rate-limited: binds the target once it listens
        if row.pending and connector.finished:
            row.pending = False
            if not (connector.connected or connector.last_error or alive):
                self._launch(name)

    def _view(self, name: str) -> View:
        connector = self._connectors.get(name)
        return view(
            self._rows[name],
            process_launcher._procs.get((self._widget_id, name)),
            bindable=connector is not None,
            connected=connector is not None and connector.connected,
            error=connector.last_error if connector is not None else None,
        )

    # --- drawing --------------------------------------------------------------

    def _row_ui(self, name: str, row_view: View, extra: str) -> None:
        style = imgui.get_style()
        line, frame, gap, pad = (
            imgui.get_text_line_height(),
            imgui.get_frame_height(),
            ui_px(2),
            ui_px(4),
        )
        height = max(2 * line + gap, frame) + 2 * ui_px(10)
        first = row_view.detail.splitlines()[0] if row_view.detail else ""
        values = " · ".join(part for part in (first, extra) if part)
        process = process_launcher._procs.get((self._widget_id, name))
        with tinted_row(row_view.tone, height=height) as width:
            left, top = imgui.get_cursor_pos_x(), imgui.get_cursor_pos_y()
            mid, right = top + (height - 2 * pad) / 2, left + width
            output_w = imgui.calc_text_size(fa.ICON_FA_TERMINAL).x + 2 * style.frame_padding.x
            action_w = 0.0
            if row_view.action:
                action_w = imgui.calc_text_size(row_view.action).x + 2 * style.frame_padding.x
                action_w += style.item_spacing.x
            text_x = left + pad + imgui.calc_text_size(fa.ICON_FA_CIRCLE).x + style.item_spacing.x
            end = right - output_w - action_w - style.item_spacing.x
            budget = max(0.0, end - text_x)

            imgui.set_cursor_pos(imgui.ImVec2(left + pad, mid - line / 2))
            imgui.text_colored(row_view.tone, fa.ICON_FA_CIRCLE)
            imgui.set_cursor_pos(imgui.ImVec2(text_x, mid - line - gap / 2))
            imgui.begin_group()
            imgui.text_unformatted(fit_text(name, budget))
            imgui.set_cursor_pos(imgui.ImVec2(text_x, mid + gap / 2))
            imgui.text_colored(muted(), fit_text(row_view.words, budget))
            if values:
                imgui.same_line()
                room = end - imgui.get_cursor_pos_x()
                if room > ui_px(24):
                    mono_text(values, muted(), width=room)
            imgui.end_group()
            refusal = self._rows[name].refusal if row_view.tone is not SUCCESS else ""
            tip = [f"{row_view.words}{' · ' + extra if extra else ''}", row_view.detail, refusal]
            imgui.set_item_tooltip("\n\n".join(part.strip() for part in tip if part))

            top_y = mid - frame / 2
            if row_view.action:
                imgui.set_cursor_pos(imgui.ImVec2(end + style.item_spacing.x, top_y))
                imgui.begin_disabled(not row_view.enabled)
                if row_view.action == "Stop":
                    if destructive_button(f"Stop##{name}", tooltip=f"Stop {name} (SIGKILL)."):
                        self.stop(name)
                elif primary_button(f"{row_view.action}##{name}"):
                    self.start(name)
                imgui.end_disabled()
            imgui.set_cursor_pos(imgui.ImVec2(right - output_w, top_y))
            imgui.begin_disabled(process is None or not process.log)
            if imgui.button(f"{fa.ICON_FA_TERMINAL}##{name}_output"):
                self._popped[name] = not self._popped.get(name, False)
            imgui.end_disabled()
            imgui.set_item_tooltip(f"{name} output")


__all__ = ["TargetPanel"]
