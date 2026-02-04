from abc import ABCMeta

import _abc
from PySide6.QtCore import QObject

# When PySide6 is mocked (e.g. by Sphinx autodoc_mock_imports),
# type(QObject) returns a Sphinx mock class whose __new__ does not
# produce real types.  Detect this by checking whether an instance of
# type(QObject) is itself a type (i.e. a proper metaclass).  If not,
# fall back to ABCMeta alone so that documentation builds succeed
# while runtime behaviour with real PySide6 is unchanged.
_qobject_meta = type(QObject)
if not issubclass(_qobject_meta, type):
    _bases = (ABCMeta,)
else:
    _bases = (_qobject_meta, ABCMeta)


class MetaQObjectABC(*_bases):
    def __new__(mcls, name, bases, namespace, **kwargs):
        cls = super().__new__(mcls, name, bases, namespace, **kwargs)
        # Shiboken's metaclass may not chain to ABCMeta.__new__, so
        # _abc_impl (needed for isinstance checks) is never set.
        # Initialize it explicitly when missing.
        if not hasattr(cls, "_abc_impl"):
            _abc._abc_init(cls)
        return cls
