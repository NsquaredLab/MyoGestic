from __future__ import annotations
from typing import TYPE_CHECKING

import logging
from enum import Enum

if TYPE_CHECKING:
    from PySide6.QtWidgets import QWidget


class LoggerLevel(Enum):
    DEBUG = 0
    INFO = 1
    WARNING = 2
    ERROR = 3
    CRITICAL = 4
    NOTSET = 5
    DEFAULT = 6


class CustomLogger(logging.Handler):
    """
    Custom Logger:
        widget (QWidget): TextEdit Widget to display the log
    """

    def __init__(self, widget: QWidget) -> None:
        super().__init__()
        self.widget = widget

        # Log
        self.logger = logging.getLogger("CustomLogger")
        self.logger.addHandler(self)
        self.logger.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter("%(type)s : %(message)s"))

    def get_logger(self) -> logging.Logger:
        return self.logger

    def emit(self, record):
        msg = self.format(record)
        self.widget.append(msg)
        if (
            self.widget.verticalScrollBar().maximum() > 0
            and self.widget.verticalScrollBar().value()
            >= self.widget.verticalScrollBar().maximum() - 50
        ):
            self.scroll_to_bottom()

    def scroll_to_bottom(self):
        self.widget.verticalScrollBar().setValue(
            self.widget.verticalScrollBar().maximum()
        )

    def print(self, msg: str, level: LoggerLevel = LoggerLevel.INFO) -> None:
        """
        Logs information to the console or if provided to a custom logger
        in a PyQt environment.

        Args:
            msg (str):
                Message to be logged.
            level (LoggerLevel, optional):
                Level on which the message should be logged.
                Defaults to "INFO".
        """
        match level:
            case LoggerLevel.INFO:
                self.logger.info(msg, extra={"type": "INFO"})
            case LoggerLevel.DEBUG:
                self.logger.debug(msg, extra={"type": "DEBUG"})
            case LoggerLevel.WARNING:
                self.logger.warning(msg, extra={"type": "WARNING"})
            case LoggerLevel.ERROR:
                self.logger.error(msg, extra={"type": "ERROR"})
            case LoggerLevel.CRITICAL:
                self.logger.critical(msg, extra={"type": "CRITICAL"})
