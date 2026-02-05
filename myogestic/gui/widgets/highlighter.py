"""Widget highlighter utility for visual workflow guidance.

Provides glow/highlight effects to draw user attention to specific UI elements
during the training workflow.
"""

from PySide6.QtCore import QObject, QTimer, QEvent
from PySide6.QtWidgets import QWidget, QTabWidget, QTabBar, QGraphicsDropShadowEffect, QAbstractButton
from PySide6.QtGui import QColor


class WidgetHighlighter(QObject):
    """Applies temporary highlight/glow effects to widgets to guide user attention."""

    # Highlight color (blue glow)
    DEFAULT_COLOR = "#4a90d9"

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._widget_flashers: dict[int, tuple[QTimer, QGraphicsDropShadowEffect | None, QWidget]] = {}
        self._tab_flashers: dict[tuple[int, int], tuple[QTimer, QColor, list]] = {}

    def highlight(
        self,
        widget: QWidget,
        flash_interval_ms: int = 1000,
        color: str = DEFAULT_COLOR,
        blur_radius: float = 30.0,
    ) -> None:
        """Apply a flashing glow effect to a widget until it is clicked.

        Args:
            widget: The widget to highlight
            flash_interval_ms: Interval between flash toggles in milliseconds (default 1000ms)
            color: Hex color string for the glow
            blur_radius: Size of the glow effect
        """
        if widget is None:
            return

        widget_id = id(widget)

        # Stop any existing flasher for this widget
        if widget_id in self._widget_flashers:
            self._stop_widget_flash(widget)

        # Store original effect if any
        original_effect = widget.graphicsEffect()

        # Create the glow effect
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(blur_radius)
        effect.setColor(QColor(color))
        effect.setOffset(0, 0)

        # State: starts with highlight on
        is_highlighted = [True]
        widget.setGraphicsEffect(effect)

        # Create timer for flashing
        timer = QTimer(self)

        def toggle_flash():
            if widget:
                is_highlighted[0] = not is_highlighted[0]
                if is_highlighted[0]:
                    new_effect = QGraphicsDropShadowEffect(widget)
                    new_effect.setBlurRadius(blur_radius)
                    new_effect.setColor(QColor(color))
                    new_effect.setOffset(0, 0)
                    widget.setGraphicsEffect(new_effect)
                else:
                    widget.setGraphicsEffect(None)

        timer.timeout.connect(toggle_flash)
        timer.start(flash_interval_ms)

        # Store flasher state
        self._widget_flashers[widget_id] = (timer, original_effect, widget)

        # Connect to clicked signal if it's a button
        if isinstance(widget, QAbstractButton):
            def on_clicked():
                self._stop_widget_flash(widget)
                try:
                    widget.clicked.disconnect(on_clicked)
                except RuntimeError:
                    pass
            widget.clicked.connect(on_clicked)
        else:
            # Use event filter for other widgets
            widget.installEventFilter(self)

    def eventFilter(self, obj: QObject, event: QEvent) -> bool:
        """Stop flashing when widget is clicked."""
        if event.type() == QEvent.Type.MouseButtonPress:
            widget_id = id(obj)
            if widget_id in self._widget_flashers:
                self._stop_widget_flash(obj)
                obj.removeEventFilter(self)
        return False  # Don't consume the event

    def _stop_widget_flash(self, widget: QWidget) -> None:
        """Stop flashing a widget and restore its original effect."""
        widget_id = id(widget)

        if widget_id not in self._widget_flashers:
            return

        timer, original_effect, _ = self._widget_flashers[widget_id]
        timer.stop()
        del self._widget_flashers[widget_id]

        # Restore original effect (or None)
        if widget:
            widget.setGraphicsEffect(original_effect)

    def highlight_tab(
        self,
        tab_widget: QTabWidget,
        tab_index: int,
        flash_interval_ms: int = 1000,
        color: str = DEFAULT_COLOR,
    ) -> None:
        """Highlight a specific tab header with a flashing effect until clicked.

        Uses QTabBar.setTabTextColor() which is a native Qt method that:
        - Works reliably across all Qt versions
        - Doesn't interfere with tab switching
        - Can be easily reverted

        The tab will flash until the user clicks on it.

        Args:
            tab_widget: The tab widget containing the tab
            tab_index: Index of the tab to highlight
            flash_interval_ms: Interval between flash toggles (milliseconds)
            color: Hex color string for the highlight
        """
        if tab_widget is None or tab_index < 0:
            return

        tab_bar = tab_widget.tabBar()
        if tab_bar is None:
            return

        widget_id = id(tab_widget)
        key = (widget_id, tab_index)

        # Stop any existing flasher for this tab
        if key in self._tab_flashers:
            self._stop_tab_flash(tab_widget, tab_index)

        # Store original color
        original_color = tab_bar.tabTextColor(tab_index)
        highlight_color = QColor(color)

        # State: starts with highlight on
        is_highlighted = [True]  # Use list to allow mutation in closure
        tab_bar.setTabTextColor(tab_index, highlight_color)

        # Create timer for flashing
        timer = QTimer(self)

        def toggle_flash():
            if tab_bar:
                is_highlighted[0] = not is_highlighted[0]
                if is_highlighted[0]:
                    tab_bar.setTabTextColor(tab_index, highlight_color)
                else:
                    tab_bar.setTabTextColor(tab_index, original_color)

        timer.timeout.connect(toggle_flash)
        timer.start(flash_interval_ms)

        # Store flasher state
        self._tab_flashers[key] = (timer, original_color, is_highlighted)

        # Connect to tab change to stop flashing when tab is selected
        def on_tab_changed(new_index):
            if new_index == tab_index:
                self._stop_tab_flash(tab_widget, tab_index)
                # Disconnect this handler
                try:
                    tab_widget.currentChanged.disconnect(on_tab_changed)
                except RuntimeError:
                    pass  # Already disconnected

        tab_widget.currentChanged.connect(on_tab_changed)

    def _stop_tab_flash(self, tab_widget: QTabWidget, tab_index: int) -> None:
        """Stop flashing a tab and restore its original color."""
        widget_id = id(tab_widget)
        key = (widget_id, tab_index)

        if key not in self._tab_flashers:
            return

        timer, original_color, _ = self._tab_flashers[key]
        timer.stop()
        del self._tab_flashers[key]

        # Restore original color
        tab_bar = tab_widget.tabBar()
        if tab_bar:
            tab_bar.setTabTextColor(tab_index, original_color)

    def clear_all(self) -> None:
        """Remove all active highlight effects immediately."""
        # Stop all widget flashers
        for widget_id, (timer, original_effect, widget) in list(self._widget_flashers.items()):
            timer.stop()
            if widget:
                widget.setGraphicsEffect(original_effect)
        self._widget_flashers.clear()

        # Stop all tab flashers
        for key, (timer, _, _) in list(self._tab_flashers.items()):
            timer.stop()
        self._tab_flashers.clear()
