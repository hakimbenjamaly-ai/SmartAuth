"""تطبيع النصوص العربية وأرقام الهواتف للبحث."""
from __future__ import annotations

import re

_DIACRITICS = re.compile(r"[ؐ-ًؚ-ٰٟۖ-ۭـ]")
_ARABIC_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")


def to_western_digits(s: str) -> str:
    return (s or "").translate(_ARABIC_DIGITS)


def normalize_ar(s: str | None) -> str:
    if not s:
        return ""
    s = _DIACRITICS.sub("", s)
    s = re.sub("[إأآٱ]", "ا", s)
    s = s.replace("ى", "ي").replace("ة", "ه").replace("ؤ", "و").replace("ئ", "ي")
    s = to_western_digits(s)
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def normalize_phone(s: str | None) -> str:
    """يحول الرقم إلى أرقام فقط، ويوحد البادئة الدولية لليبيا (218)."""
    if not s:
        return ""
    d = re.sub(r"\D", "", to_western_digits(s))
    if d.startswith("00"):
        d = d[2:]
    if d.startswith("2180"):
        d = "218" + d[4:]
    if d.startswith("0") and len(d) == 10:  # 09xxxxxxxx محلي ليبي
        d = "218" + d[1:]
    return d


def sql_like_ar(column: str) -> str:
    """تعبير SQL يطبق normalize_ar على العمود (الدالة مسجلة في اتصال SQLite)."""
    return f"norm_ar({column})"
