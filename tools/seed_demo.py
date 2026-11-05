"""إدخال بيانات تجريبية لتجربة المنظومة (جهات، أشخاص، تفويضات، توقيعات اصطناعية، مستندات نموذجية).

الاستخدام (بعد إنشاء حساب المشغل الرئيسي):
    python tools/seed_demo.py --user admin --password <كلمة المرور> [--home <مجلد البيانات>]
يُنشئ أيضاً مجلد demo_documents بمستندات وصور توقيعات لتجربة القراءة والبحث بالتوقيع.
لا تستخدمه على قاعدة بيانات العمل الفعلية.
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tests")]

from app.core.context import AppContext  # noqa: E402
from app.engine.imaging import imwrite_any  # noqa: E402
from synth import make_person_template, render_signature  # noqa: E402

DATA = [
    ("LY_EMB_ABROAD", "سفارة دولة ليبيا لدى تونس", "تونس", "Tunisia",
     [("محمد سالم الورفلي", "السفير", "0912223344"), ("علي أحمد بن عمران", "المستشار", "0923334455")]),
    ("LY_CONS_ABROAD", "القنصلية العامة الليبية في الإسكندرية", "مصر", "Egypt",
     [("خالد عمر الزوي", "القنصل العام", "0915556677")]),
    ("FOREIGN_EMB_LY", "سفارة الجمهورية الإيطالية في طرابلس", "إيطاليا", "Italy",
     [("Marco Rossi", "Consul", "+218217778899")]),
    ("PUBLIC_CO", "الشركة العامة للكهرباء", "ليبيا", "Libya",
     [("فاطمة الهادي الترهوني", "مديرة الشؤون الإدارية", "0918889900")]),
    ("MINISTRY", "وزارة الخارجية والتعاون الدولي", "ليبيا", "Libya",
     [("إبراهيم مصطفى الطاهر", "مدير إدارة التصديقات", "0910001122"),
      ("سعاد عبدالله الفيتوري", "رئيس قسم التوثيق", "0921112233")]),
    ("AUTHORITY", "هيئة الرقابة الإدارية", "ليبيا", "Libya",
     [("عمر الصادق المنفي", "مدير مكتب الرئيس", "0914445566")]),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", required=True)
    ap.add_argument("--password", required=True)
    ap.add_argument("--home")
    a = ap.parse_args()
    ctx = AppContext(a.home)
    sv = ctx.services
    sv.auth.login(a.user, a.password)
    demo = ROOT / "demo_documents"
    (demo / "signatures_to_scan").mkdir(parents=True, exist_ok=True)
    seed = 500
    for code, ename, country, country_en, people in DATA:
        cat = ctx.db.scalar("SELECT id FROM categories WHERE code=?", (code,))
        cid = ctx.db.scalar("SELECT id FROM countries WHERE name_ar=?", (country,)) or \
            sv.catalog.add_country(country, country_en)
        eid = sv.catalog.find_or_create_entity(ename, cat, cid)
        for name, title, phone in people:
            pid = sv.persons.add(full_name=name, job_title=title, phone=phone, entity_id=eid)
            start = date.today() - timedelta(days=400)
            end = date.today() + timedelta(days=(365 if seed % 3 else -20))
            sv.persons.add_authorization(pid, start.isoformat(), end.isoformat())
            sv.persons.add_certification(pid, (date.today() - timedelta(days=seed % 90)).isoformat(),
                                         f"REF-{seed}")
            tpl = make_person_template(seed)
            ref = demo / f"_ref_{seed}.png"
            imwrite_any(ref, render_signature(tpl, seed=1))
            sv.signatures.enroll(pid, ref)
            ref.unlink()
            # نسخة "ممسوحة" مختلفة قليلاً لتجربة البحث بالتوقيع
            imwrite_any(demo / "signatures_to_scan" / f"{name}.png",
                        render_signature(tpl, seed=42, jitter=3, angle=3, scale=0.92, noise=8))
            seed += 1
    print(f"تم: {ctx.db.scalar('SELECT COUNT(*) FROM persons')} شخص، "
          f"{ctx.db.scalar('SELECT COUNT(*) FROM signatures')} توقيع.")
    print("صور للتجربة في:", demo / "signatures_to_scan")
    ctx.close()


if __name__ == "__main__":
    main()
