# -*- coding: utf-8 -*-
"""
Scalable window implementation for zoom-like UI behavior.

Provides a QMainWindow subclass that scales its content proportionally
when the window is resized, similar to zooming a PDF document.
"""
from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt
from PySide6.QtGui import QPainter, QResizeEvent
from PySide6.QtWidgets import (
    QComboBox,
    QGraphicsProxyWidget,
    QGraphicsScene,
    QGraphicsView,
    QMainWindow,
    QWidget,
)


class ScalableMainWindow(QMainWindow):
    """
    A QMainWindow subclass that scales its content proportionally when resized.

    Provides PDF-viewer-like zoom behavior where the entire UI scales uniformly
    while maintaining aspect ratio. Uses QGraphicsView internally for transforms.

    Usage:
        class MyApp(ScalableMainWindow):
            def __init__(self):
                super().__init__(original_width=1000, original_height=960)

                # Let setupUi run on self (it needs QMainWindow methods)
                self.ui = Ui_MyApp()
                self.ui.setupUi(self)

                # Then enable scaling - this wraps the central widget
                self.enableScaling()
    """

    def __init__(
        self,
        original_width: int = 1000,
        original_height: int = 960,
        allow_upscaling: bool = True,
        letterbox_color: str = "#19232d",
        parent: QWidget | None = None,
    ):
        """
        Initialize scalable window.

        Parameters
        ----------
        original_width : int
            Design width from .ui file (default 1000)
        original_height : int
            Design height from .ui file (default 960)
        allow_upscaling : bool
            If True, allows scaling beyond original size (default True)
        letterbox_color : str
            Background color for letterbox bars, CSS color format (default matches qdarkstyle)
        parent : QWidget | None
            Parent widget
        """
        super().__init__(parent)

        self.original_size = QSize(original_width, original_height)
        self.allow_upscaling = allow_upscaling
        self.letterbox_color = letterbox_color
        self._scale_factor = 1.0
        self._scaling_enabled = False

        # These will be initialized when enableScaling() is called
        self._scene: QGraphicsScene | None = None
        self._view: QGraphicsView | None = None
        self._proxy: QGraphicsProxyWidget | None = None
        self._content_widget: QWidget | None = None

    def enableScaling(self) -> None:
        """
        Enable zoom-like scaling on the current central widget.

        Call this AFTER setupUi() has been called on self. This method:
        1. Takes the current central widget
        2. Unparents it and wraps it in a QGraphicsProxyWidget
        3. Sets up a QGraphicsView as the new central widget
        4. Applies scaling transforms on window resize

        Raises
        ------
        RuntimeError
            If no central widget is set (setupUi not called yet)
        """
        if self._scaling_enabled:
            return  # Already enabled

        # Get the central widget that was set by setupUi
        content = super().centralWidget()
        if content is None:
            raise RuntimeError(
                "No central widget found. Call setupUi() before enableScaling()."
            )

        self._content_widget = content

        # CRITICAL: Unparent the widget first so QGraphicsProxyWidget can adopt it
        # This is required because QGraphicsProxyWidget needs a top-level widget
        content.setParent(None)

        # Remove fixed size constraints from the main window
        self.setMinimumSize(QSize(0, 0))
        self.setMaximumSize(QSize(16777215, 16777215))

        # Create graphics scene and view
        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)

        # Configure view appearance
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setStyleSheet(
            f"background-color: {self.letterbox_color}; border: none;"
        )
        self._view.setFrameShape(QGraphicsView.NoFrame)

        # Configure rendering for quality
        self._view.setRenderHint(QPainter.Antialiasing, True)
        self._view.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._view.setRenderHint(QPainter.TextAntialiasing, True)

        # Optimization settings - use SmartViewportUpdate for real-time content
        self._view.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)

        # Anchor transforms at center
        self._view.setTransformationAnchor(QGraphicsView.AnchorViewCenter)
        self._view.setResizeAnchor(QGraphicsView.AnchorViewCenter)

        # Set fixed size on the content widget to match design
        content.setFixedSize(self.original_size)

        # Wrap in proxy widget - now it works because content has no parent
        self._proxy = self._scene.addWidget(content)

        # Note: NoCache used because the content includes real-time updating
        # widgets (vispy plot) that need immediate redraws
        self._proxy.setCacheMode(QGraphicsProxyWidget.NoCache)

        # Set scene rect to match widget size
        self._scene.setSceneRect(
            QRectF(0, 0, self.original_size.width(), self.original_size.height())
        )

        # Set the view as the new central widget
        super().setCentralWidget(self._view)

        self._scaling_enabled = True

        # Set initial window size to original dimensions
        self.resize(self.original_size)

        # Apply initial scaling
        self._update_scale()

    def resizeEvent(self, event: QResizeEvent) -> None:
        """
        Handle window resize events by updating the scale factor.

        Parameters
        ----------
        event : QResizeEvent
            The resize event
        """
        super().resizeEvent(event)
        if self._scaling_enabled:
            self._update_scale()

    def showEvent(self, event) -> None:
        """
        Handle window show events by updating the scale factor.

        This ensures scaling is properly applied after the window layout is
        fully established, which may not happen until the window is shown.

        Parameters
        ----------
        event : QShowEvent
            The show event
        """
        super().showEvent(event)
        if self._scaling_enabled:
            # Use a single-shot timer to update scale after layout is settled
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, self._update_scale)

    def _update_scale(self) -> None:
        """Calculate and apply the appropriate scale transformation."""
        if self._view is None or self._proxy is None:
            return

        view_size = self._view.size()

        # Calculate scale factors for width and height
        scale_x = view_size.width() / self.original_size.width()
        scale_y = view_size.height() / self.original_size.height()

        # Use minimum to maintain aspect ratio (letterbox if needed)
        scale = min(scale_x, scale_y)

        # Limit to 1.0 if upscaling not allowed
        if not self.allow_upscaling:
            scale = min(scale, 1.0)

        self._scale_factor = scale

        # Reset and apply new transform
        self._view.resetTransform()
        self._view.scale(scale, scale)

        # Align content to top-left by setting scene rect at origin
        self._view.setSceneRect(
            QRectF(0, 0, self.original_size.width(), self.original_size.height())
        )

    def getScaleFactor(self) -> float:
        """
        Get the current scale factor.

        Returns
        -------
        float
            Current scale factor (1.0 = original size)
        """
        return self._scale_factor

    def getContentWidget(self) -> QWidget | None:
        """
        Get the content widget that is being scaled.

        Returns
        -------
        QWidget | None
            The content widget, or None if scaling not enabled
        """
        return self._content_widget

    def isScalingEnabled(self) -> bool:
        """
        Check if scaling is currently enabled.

        Returns
        -------
        bool
            True if scaling is enabled
        """
        return self._scaling_enabled

    def enableHybridScaling(
        self, scalable_widget: QWidget, native_widget: QWidget, scalable_size: QSize
    ) -> None:
        """
        Enable hybrid scaling where one widget scales and another stays native.

        This is useful for OpenGL widgets (like vispy plots) that don't work
        well with QGraphicsProxyWidget. The native widget will resize normally
        while the scalable widget scales proportionally.

        Parameters
        ----------
        scalable_widget : QWidget
            The widget to scale (e.g., the controls tab widget)
        native_widget : QWidget
            The widget to keep as native (not scaled), e.g., an OpenGL plot widget
        scalable_size : QSize
            The original design size of the scalable widget

        Raises
        ------
        RuntimeError
            If no central widget is set (setupUi not called yet)
        """
        from PySide6.QtWidgets import QSplitter, QVBoxLayout, QSizePolicy

        if self._scaling_enabled:
            return  # Already enabled

        # Store references
        self._content_widget = scalable_widget
        self._native_widget = native_widget
        self.original_size = scalable_size

        # Unparent both widgets
        scalable_widget.setParent(None)
        native_widget.setParent(None)

        # Remove fixed size constraints from the main window
        self.setMinimumSize(QSize(0, 0))
        self.setMaximumSize(QSize(16777215, 16777215))

        # Create graphics scene and view for the scalable content
        self._scene = QGraphicsScene()
        self._view = QGraphicsView(self._scene)

        # Set expanding size policy so the view takes its share of the splitter
        self._view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # Configure view appearance
        self._view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self._view.setStyleSheet(
            f"background-color: {self.letterbox_color}; border: none;"
        )
        self._view.setFrameShape(QGraphicsView.NoFrame)

        # Configure rendering for quality
        self._view.setRenderHint(QPainter.Antialiasing, True)
        self._view.setRenderHint(QPainter.SmoothPixmapTransform, True)
        self._view.setRenderHint(QPainter.TextAntialiasing, True)

        # Optimization settings
        self._view.setViewportUpdateMode(QGraphicsView.SmartViewportUpdate)

        # Anchor transforms at top-left (NoAnchor) for proper alignment
        self._view.setTransformationAnchor(QGraphicsView.NoAnchor)
        self._view.setResizeAnchor(QGraphicsView.NoAnchor)

        # Allow rendering outside scene bounds (for popup widgets)
        self._view.setViewportUpdateMode(QGraphicsView.FullViewportUpdate)

        # Set fixed size on the scalable widget
        scalable_widget.setFixedSize(scalable_size)

        # Wrap in proxy widget
        self._proxy = self._scene.addWidget(scalable_widget)
        self._proxy.setCacheMode(QGraphicsProxyWidget.NoCache)

        # Set scene rect larger than widget to allow popups to render above
        # Add 300px above the content for upward-opening popups
        popup_margin = 300
        self._scene.setSceneRect(
            QRectF(0, -popup_margin, scalable_size.width(), scalable_size.height() + popup_margin)
        )
        # Position the proxy at y=0 (which is popup_margin from scene top)
        self._proxy.setPos(0, 0)

        # Create a splitter to hold scaled view and native widget side by side
        splitter = QSplitter(Qt.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.addWidget(self._view)
        splitter.addWidget(native_widget)

        # Use stretch factors to maintain ~48:52 ratio (controls:plot)
        splitter.setStretchFactor(0, 48)  # View (controls)
        splitter.setStretchFactor(1, 52)  # Native widget (plot)

        # Set initial sizes matching original ~48:52 ratio
        splitter.setSizes([480, 520])
        splitter.setStyleSheet(
            f"QSplitter {{ background-color: {self.letterbox_color}; }}"
            f"QSplitter::handle {{ background-color: #3d3d3d; width: 3px; }}"
        )

        # Set the splitter as the new central widget
        super().setCentralWidget(splitter)

        self._scaling_enabled = True

        # Fix combo box popups to extend beyond graphics view bounds
        self._fix_combobox_popups(scalable_widget)

        # Apply initial scaling
        self._update_scale()

    def _fix_combobox_popups(self, widget: QWidget) -> None:
        """
        Fix combo box popups to render as top-level windows outside the graphics scene.

        QGraphicsProxyWidget clips popup widgets to the scene bounds. This method
        installs custom popup handlers on all combo boxes to display their popups
        as true top-level windows that can extend beyond the view.

        Parameters
        ----------
        widget : QWidget
            The widget tree to search for combo boxes
        """
        from PySide6.QtCore import QPoint, QTimer, QEvent, QObject
        from PySide6.QtWidgets import QApplication, QListView, QFrame
        from PySide6.QtGui import QCursor

        main_window = self

        class ComboPopupHelper(QObject):
            """Helper class to show combo box popup as top-level window."""

            def __init__(self, combo: QComboBox, parent=None):
                super().__init__(parent)
                self._combo = combo
                self._popup = None
                self._original_show_popup = combo.showPopup
                combo.showPopup = self._show_popup_toplevel

            def _show_popup_toplevel(self):
                """Show the combo box popup as a top-level window."""
                combo = self._combo

                # Create or reuse popup frame
                if self._popup is None:
                    self._popup = QFrame(None, Qt.Popup | Qt.FramelessWindowHint)
                    self._popup.setStyleSheet("""
                        QFrame {
                            background-color: #19232d;
                            border: 1px solid #455364;
                        }
                        QListView {
                            background-color: #19232d;
                            color: #f0f0f0;
                            border: none;
                            outline: 0;
                        }
                        QListView::item {
                            padding: 4px 8px;
                        }
                        QListView::item:hover {
                            background-color: #37414f;
                        }
                        QListView::item:selected {
                            background-color: #1a72bb;
                        }
                    """)

                    from PySide6.QtWidgets import QVBoxLayout
                    layout = QVBoxLayout(self._popup)
                    layout.setContentsMargins(0, 0, 0, 0)

                    self._list_view = QListView()
                    self._list_view.setModel(combo.model())
                    self._list_view.clicked.connect(self._on_item_clicked)
                    layout.addWidget(self._list_view)

                # Calculate position
                combo_global = combo.mapToGlobal(QPoint(0, combo.height()))
                combo_top = combo.mapToGlobal(QPoint(0, 0))

                # Determine popup height
                item_count = combo.count()
                row_height = self._list_view.sizeHintForRow(0) if item_count > 0 else 24
                popup_height = min(item_count * row_height + 4, 300)
                popup_width = max(combo.width(), 150)

                # Check if popup fits below or needs to go above
                screen = QApplication.screenAt(combo_global)
                if screen:
                    screen_rect = screen.availableGeometry()
                    if combo_global.y() + popup_height > screen_rect.bottom():
                        # Open upward
                        combo_global = QPoint(combo_top.x(), combo_top.y() - popup_height)

                self._popup.setGeometry(
                    combo_global.x(), combo_global.y(),
                    popup_width, popup_height
                )

                # Select current item
                self._list_view.setCurrentIndex(
                    combo.model().index(combo.currentIndex(), 0)
                )

                self._popup.show()
                self._popup.raise_()
                self._list_view.setFocus()

            def _on_item_clicked(self, index):
                """Handle item selection in popup."""
                self._combo.setCurrentIndex(index.row())
                if self._popup:
                    self._popup.hide()

        # Install popup helper on all combo boxes
        for combo_box in widget.findChildren(QComboBox):
            helper = ComboPopupHelper(combo_box, combo_box)
            combo_box._popup_helper = helper  # Keep reference
