"""PySide6 وهمي لاختبار بناء الصفحات وربطها بالخدمات في بيئة بدون Qt (اختبار دخان فقط)."""
import sys
import types

SPECIAL = {"text": "", "currentData": None, "currentRow": -1, "count": 0, "isChecked": False, "value": 0,
           "exec": 0, "currentIndex": 0, "findData": -1, "toPlainText": "", "currentText": "", "currentItem": None,
           "property": None, "rowCount": 0, "isNull": True, "item": None, "widget": None, "takeAt": None,
           "currentWidget": None, "tabText": "", "data": None}


class _Meta(type):
    def __getattr__(cls, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in SPECIAL:
            v = SPECIAL[name]
            return lambda *a, **k: v
        return _Q()

    def __or__(cls, o):
        return cls

    __ror__ = __or__


class _Q(metaclass=_Meta):
    def __init__(self, *a, **k):
        pass

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        if name in SPECIAL:
            v = SPECIAL[name]
            return lambda *a, **k: v
        return _Q()

    def __call__(self, *a, **k):
        return _Q()

    def __or__(self, o):
        return self

    __ror__ = __and__ = __add__ = __radd__ = __or__

    def __bool__(self):
        return True

    def __int__(self):
        return 0

    def __iter__(self):
        return iter(())


class _Mod(types.ModuleType):
    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        cls = type(name, (_Q,), {})
        setattr(self, name, cls)
        return cls


def install():
    root = _Mod("PySide6")
    for sub in ("QtCore", "QtGui", "QtWidgets"):
        m = _Mod(f"PySide6.{sub}")
        setattr(root, sub, m)
        sys.modules[f"PySide6.{sub}"] = m
    sys.modules["PySide6"] = root
