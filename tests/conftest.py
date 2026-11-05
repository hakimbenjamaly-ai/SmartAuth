"""عند استخدام Qt الحقيقي: إنهاء العملية مباشرة بعد الاختبارات بنفس رمز النتيجة،
لتجنب انهيار معروف في PySide6 أثناء تفكيك المفسّر (يحدث بعد نجاح كل الاختبارات)."""
import os
import sys

_status = {"code": None}


def pytest_sessionfinish(session, exitstatus):
    _status["code"] = int(exitstatus)


def pytest_unconfigure(config):
    if _status["code"] is not None and "PySide6.QtWidgets" in sys.modules and "fake_qt" not in sys.modules:
        sys.stdout.flush(); sys.stderr.flush()
        os._exit(_status["code"])
