from PySide6.QtCore import QObject
from abc import ABCMeta


class MetaQObjectABC(type(QObject), ABCMeta):
    pass
