from PySide6.QtCore import QObject
from abc import ABCMeta

import _abc


class MetaQObjectABC(type(QObject), ABCMeta):
    def __new__(mcls, name, bases, namespace, **kwargs):
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        # Shiboken's metaclass may not chain to ABCMeta.__new__, so
        # _abc_impl (needed for isinstance checks) is never set.
        # Initialize it explicitly when missing.
        if not hasattr(cls, "_abc_impl"):
            _abc._abc_init(cls)
        return cls
