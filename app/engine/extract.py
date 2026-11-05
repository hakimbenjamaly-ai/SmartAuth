"""استخراج الحقول من نص المستند: الأسماء، الصفات الوظيفية، الجهات، التواريخ، الهواتف، البريد."""
from __future__ import annotations

import re
from dataclasses import dataclass

from ..core.textnorm import normalize_phone, to_western_digits


@dataclass
class Field:
    field: str
    value: str
    confidence: float
    page: int | None = None


FIELD_LABELS = {
    "full_name": "الاسم",
    "full_name_en": "الاسم (إنجليزي)",
    "job_title": "الصفة الوظيفية",
    "entity": "الجهة",
    "country": "الدولة",
    "date": "التاريخ",
    "auth_start": "بداية التفويض",
    "auth_end": "نهاية التفويض",
    "phone": "رقم الهاتف",
    "email": "البريد الإلكتروني",
    "reference_no": "الرقم الإشاري",
}

EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_RE = re.compile(r"(?<!\d)(?:\+|00)?\d[\d\s\-()/.]{6,17}\d(?!\d)")
DATE_RES = [
    (re.compile(r"(?<!\d)(\d{4})[/\-.](\d{1,2})[/\-.](\d{1,2})(?!\d)"), "ymd"),
    (re.compile(r"(?<!\d)(\d{1,2})[/\-.](\d{1,2})[/\-.](\d{4})(?!\d)"), "dmy"),
]
AR_MONTHS = {
    "يناير": 1, "فبراير": 2, "مارس": 3, "أبريل": 4, "ابريل": 4, "مايو": 5, "يونيو": 6, "يوليو": 7,
    "أغسطس": 8, "اغسطس": 8, "سبتمبر": 9, "أكتوبر": 10, "اكتوبر": 10, "نوفمبر": 11, "ديسمبر": 12,
    "أي النار": 1, "النوار": 2, "الربيع": 3, "الطير": 4, "الماء": 5, "الصيف": 6, "ناصر": 7,
    "هانيبال": 8, "الفاتح": 9, "التمور": 10, "الحرث": 11, "الكانون": 12,
}
EN_MONTHS = {m: i for i, m in enumerate(
    ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"], 1)}

LABELS = {
    "full_name": [r"الاسم(?:\s+الكامل|\s+الثلاثي|\s+الرباعي)?", r"اسم\s+المخول(?:\s+بالتوقيع)?",
                  r"المخول\s+بالتوقيع", r"السيد(?:ة)?", r"Name", r"Full\s+Name"],
    "job_title": [r"الصفة(?:\s+الوظيفية)?", r"الوظيفة", r"المسمى\s+الوظيفي", r"المنصب",
                  r"Title", r"Position", r"Designation", r"Job\s+Title"],
    "entity": [r"الجهة", r"اسم\s+الجهة", r"السفارة", r"القنصلية", r"الشركة", r"الوزارة", r"الهيئة",
               r"المؤسسة", r"Organization", r"Entity", r"Embassy", r"Company", r"Ministry"],
    "country": [r"الدولة", r"البلد", r"Country"],
    "reference_no": [r"الرقم\s+الإشاري", r"الرقم\s+الاشاري", r"رقم\s+المرجع", r"Ref(?:erence)?\.?\s*No\.?"],
    "auth_start": [r"تاريخ\s+بداية\s+التفويض", r"يسري\s+من", r"اعتباراً\s+من", r"اعتبارا\s+من", r"Valid\s+from"],
    "auth_end": [r"تاريخ\s+(?:انتهاء|نهاية)\s+التفويض", r"حتى\s+تاريخ", r"ينتهي\s+في", r"Valid\s+(?:until|to)",
                 r"Expiry\s+Date"],
}
SEP = r"\s*[:：\-–]\s*"

TITLE_WORDS = ["سفير", "قنصل", "وزير", "مدير", "رئيس", "نائب", "مستشار", "سكرتير", "ملحق", "مفوض",
               "وكيل", "أمين", "المكلف", "القائم بالأعمال", "Ambassador", "Consul", "Minister", "Director",
               "Manager", "Chairman", "Secretary", "Attaché", "Counsellor", "Chargé"]


def _iso(y: int, m: int, d: int) -> str | None:
    if 1 <= m <= 12 and 1 <= d <= 31 and 1900 <= y <= 2100:
        return f"{y:04d}-{m:02d}-{d:02d}"
    return None


def parse_date(s: str) -> str | None:
    s = to_western_digits(s)
    for rx, kind in DATE_RES:
        m = rx.search(s)
        if m:
            a, b, c = map(int, m.groups())
            return _iso(a, b, c) if kind == "ymd" else _iso(c, b, a)
    m = re.search(r"(\d{1,2})\s+([^\d\s]+(?:\s[^\d\s]+)?)\s+(\d{4})", s)
    if m:
        mon = AR_MONTHS.get(m.group(2).strip()) or EN_MONTHS.get(m.group(2).strip()[:3].lower())
        if mon:
            return _iso(int(m.group(3)), mon, int(m.group(1)))
    return None


def find_dates(text: str) -> list[str]:
    t = to_western_digits(text)
    out = []
    for rx, kind in DATE_RES:
        for m in rx.finditer(t):
            a, b, c = map(int, m.groups())
            iso = _iso(a, b, c) if kind == "ymd" else _iso(c, b, a)
            if iso and iso not in out:
                out.append(iso)
    return out


def find_phones(text: str) -> list[str]:
    t = to_western_digits(text)
    out = []
    for m in PHONE_RE.finditer(t):
        raw = m.group(0)
        if re.fullmatch(r"\d{1,4}[/\-.]\d{1,2}[/\-.]\d{1,4}", raw.strip()):
            continue  # تاريخ وليس هاتفاً
        digits = re.sub(r"\D", "", raw)
        if 7 <= len(digits) <= 15:
            n = normalize_phone(raw)
            if n not in [normalize_phone(x) for x in out]:
                out.append(raw.strip())
    return out


def _labeled(text: str, key: str) -> list[str]:
    vals = []
    for lab in LABELS[key]:
        for m in re.finditer(rf"(?im)(?:^|[\s\(])(?:{lab}){SEP}([^\n\r|]+)", text):
            v = re.split(r"\s{3,}|\t", m.group(1).strip())[0].strip(" .،,")
            if v and len(v) <= 120:
                vals.append(v)
    return vals


def extract_fields(text: str, page: int | None = None) -> list[Field]:
    text = to_western_digits(text or "")
    fields: list[Field] = []

    def add(f, v, c):
        v = (v or "").strip()
        if v and not any(x.field == f and x.value == v for x in fields):
            fields.append(Field(f, v, c, page))

    for key in ("full_name", "job_title", "entity", "country", "reference_no"):
        for v in _labeled(text, key):
            if key == "full_name" and re.search(r"[A-Za-z]", v) and not re.search(r"[؀-ۿ]", v):
                add("full_name_en", v, 0.85)
            else:
                add(key, v, 0.85)
    for key in ("auth_start", "auth_end"):
        for v in _labeled(text, key):
            d = parse_date(v)
            if d:
                add(key, d, 0.8)
    # الصفة الوظيفية بدون عنوان صريح
    if not any(f.field == "job_title" for f in fields):
        for line in text.splitlines():
            ls = line.strip()
            if 2 < len(ls) < 60 and any(re.search(rf"(?:^|\s){re.escape(w)}", ls) for w in TITLE_WORDS):
                add("job_title", ls, 0.5)
                break
    for e in EMAIL_RE.findall(text):
        add("email", e, 0.95)
    for p in find_phones(text):
        add("phone", p, 0.8)
    for d in find_dates(text):
        if not any(f.value == d for f in fields if f.field in ("auth_start", "auth_end")):
            add("date", d, 0.75)
    return fields
