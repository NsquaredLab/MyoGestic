from __future__ import annotations

import logging
from enum import Enum
from queue import Queue
from threading import Thread
from typing import TYPE_CHECKING

from PySide6.QtCore import Signal, QObject

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


class LoggerSignal(QObject):
    log_message = Signal(str)


class CustomLogger(logging.Handler):
    """
    Custom Logger:
        widget (QWidget): TextEdit Widget to display the log
    """

    def __init__(self, widget: QWidget) -> None:
        super().__init__()
        self.widget = widget
        self.signal = LoggerSignal()
        self.signal.log_message.connect(self.append_log)

        # Log
        self.logger = logging.getLogger("CustomLogger")
        self.logger.addHandler(self)
        self.logger.setLevel(logging.INFO)
        self.setFormatter(logging.Formatter("%(type)s : %(message)s"))

        self.queue = Queue()
        self.thread = Thread(target=self.process_queue)
        self.thread.daemon = True
        self.thread.start()

    def get_logger(self) -> logging.Logger:
        return self.logger

    def emit(self, record):
        msg = self.format(record)
        self.queue.put(msg)

    def process_queue(self):
        while True:
            msg = self.queue.get()
            self.signal.log_message.emit(msg)
            self.queue.task_done()

    def append_log(self, msg: str) -> None:
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
