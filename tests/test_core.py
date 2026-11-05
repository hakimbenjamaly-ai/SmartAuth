"""اختبارات شاملة لطبقة الخدمات وقاعدة البيانات والمحركات (دون واجهة)."""
from __future__ import annotations

import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tests"))

from app.core.context import AppContext  # noqa: E402
from app.core.db import PermissionDenied  # noqa: E402
from app.core.security import sha256_file  # noqa: E402
from app.engine.extract import extract_fields, find_phones, parse_date  # noqa: E402
from app.engine.imaging import imwrite_any  # noqa: E402
from app.services.auth import AuthError  # noqa: E402
from synth import make_person_template, render_signature  # noqa: E402

FONT = next((f for f in ("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf", r"C:\Windows\Fonts\arial.ttf",
                          r"C:\Windows\Fonts\tahoma.ttf") if Path(f).exists()), None)
try:
    from PIL import features as _pf
    HAS_RAQM = bool(_pf.check("raqm"))
except Exception:
    HAS_RAQM = False


@pytest.fixture()
def ctx(tmp_path):
    c = AppContext(tmp_path / "home")
    c.services.auth.create_initial_admin("admin", "Admin@123", "مدير النظام")
    c.services.auth.login("admin", "Admin@123")
    yield c
    c.close()


def _cat(ctx, code):
    return ctx.db.scalar("SELECT id FROM categories WHERE code=?", (code,))


# --------------------------------------------------------------- auth/perms
def test_seed_categories(ctx):
    names = [r["name"] for r in ctx.services.catalog.categories()]
    assert len(names) == 9 and names[0] == "السفارات الليبية بالخارج" and names[-1] == "جهات أخرى"


def test_login_and_lockout(ctx):
    a = ctx.services.auth
    a.create_user("user1", "User@123", "standard", "موظف")
    a.logout()
    with pytest.raises(AuthError):
        a.login("user1", "wrong-pass")
    for _ in range(4):
        with pytest.raises(AuthError):
            a.login("user1", "wrong-pass")
    with pytest.raises(AuthError, match="قفل"):
        a.login("user1", "User@123")
    with pytest.raises(PermissionDenied):
        a.create_initial_admin("x", "123456")


def test_standard_user_permissions_service_and_db(ctx):
    sv = ctx.services
    eid = sv.catalog.add_entity(name="سفارة ليبيا في تونس", category_id=_cat(ctx, "LY_EMB_ABROAD"))
    sv.persons.add(full_name="أحمد علي", entity_id=eid)
    sv.auth.create_user("user1", "User@123", "standard")
    sv.auth.logout()
    s = sv.auth.login("user1", "User@123")
    assert s.role == "standard"
    # مسموح
    assert sv.persons.search(name="احمد")
    assert sv.catalog.entities()
    # ممنوع في طبقة الخدمات
    for fn in (lambda: sv.persons.add(full_name="x"),
               lambda: sv.catalog.add_entity(name="x", category_id=1),
               lambda: sv.excel.list_files(),
               lambda: sv.backup.create(),
               lambda: sv.auth.list_users(),
               lambda: sv.sources.list(),
               lambda: sv.persons.delete(1)):
        with pytest.raises(PermissionDenied):
            fn()
    # ممنوع في طبقة قاعدة البيانات حتى لو تم تجاوز الخدمات
    for sql in ("INSERT INTO persons(full_name) VALUES ('hack')",
                "UPDATE persons SET full_name='hack'",
                "DELETE FROM persons",
                "UPDATE users SET role='admin'",
                "DROP TABLE persons"):
        with pytest.raises(PermissionDenied):
            ctx.db.execute(sql)
    assert ctx.db.scalar("SELECT password_hash FROM users LIMIT 1") is None
    assert ctx.db.scalar("SELECT COUNT(*) FROM persons") == 1


def test_last_admin_protected(ctx):
    with pytest.raises(ValueError):
        ctx.services.auth.update_user(ctx.session.user_id, role="standard")


# ------------------------------------------------------------ catalog/persons
def test_entities_and_person_search(ctx):
    sv = ctx.services
    tn = sv.catalog.add_country("تونس", "Tunisia", "TN")
    sv.catalog.add_city(tn, "تونس العاصمة")
    e1 = sv.catalog.add_entity(name="سفارة دولة ليبيا لدى تونس", category_id=_cat(ctx, "LY_EMB_ABROAD"),
                               country_id=tn)
    e2 = sv.catalog.add_entity(name="الشركة العامة للكهرباء", category_id=_cat(ctx, "PUBLIC_CO"))
    p1 = sv.persons.add(full_name="إبراهيم مصطفى الطاهر", job_title="القنصل العام",
                        phone="091-234-5678", entity_id=e1)
    sv.persons.add(full_name="فاطمة سالم", job_title="مديرة الشؤون الإدارية", phone="+218 92 111 2233",
                   entity_id=e2)
    assert [r["id"] for r in sv.persons.search(name="ابراهيم")] == [p1]       # همزة
    assert [r["id"] for r in sv.persons.search(phone="00218912345678")] == [p1]  # صيغة دولية
    assert [r["id"] for r in sv.persons.search(phone="٠٩١٢٣٤٥٦٧٨")] == [p1]      # أرقام عربية
    assert len(sv.persons.search(category_id=_cat(ctx, "PUBLIC_CO"))) == 1
    assert len(sv.persons.search(country_id=tn)) == 1
    assert sv.catalog.entities(text="كهرباء")[0]["id"] == e2
    assert sv.catalog.entities(category_id=_cat(ctx, "LY_EMB_ABROAD"))[0]["country_name"] == "تونس"
    with pytest.raises(ValueError):
        sv.catalog.delete_category(_cat(ctx, "PUBLIC_CO"))


def test_authorization_status(ctx):
    sv = ctx.services
    pid = sv.persons.add(full_name="سالم")
    past = (date.today() - timedelta(days=10)).isoformat()
    sv.persons.add_authorization(pid, "2020-01-01", past)
    p = sv.persons.profile(pid)
    assert p["auth_status"] == "expired" and p["authorizations"][0]["status_label"] == "منتهي"
    sv.persons.add_authorization(pid, past, (date.today() + timedelta(days=300)).isoformat())
    assert sv.persons.get(pid)["auth_status_label"] == "ساري"
    with pytest.raises(ValueError):
        sv.persons.add_authorization(pid, "2025-05-01", "2025-01-01")


# ------------------------------------------------------------- extraction
def test_extract_fields_arabic_english():
    text = """الاسم: محمد عبدالله الفيتوري
الصفة الوظيفية: القنصل العام
الجهة: القنصلية الليبية في الإسكندرية
الهاتف: ٠٩١٢٣٤٥٦٧٨
البريد: m.fitouri@consulate.ly
التاريخ: 15/03/2024
تاريخ انتهاء التفويض: 2026-12-31
Name: John Smith
Title: Ambassador"""
    f = {(x.field, x.value) for x in extract_fields(text)}
    assert ("full_name", "محمد عبدالله الفيتوري") in f
    assert ("job_title", "القنصل العام") in f
    assert ("entity", "القنصلية الليبية في الإسكندرية") in f
    assert ("email", "m.fitouri@consulate.ly") in f
    assert ("date", "2024-03-15") in f
    assert ("auth_end", "2026-12-31") in f
    assert ("full_name_en", "John Smith") in f
    assert any(k == "phone" for k, _ in f)
    assert not any(k == "phone" and "2024" in v for k, v in f)
    assert parse_date("5 مارس 2023") == "2023-03-05"
    assert find_phones("call +218 91 234 5678 now") == ["+218 91 234 5678"]


# ---------------------------------------------------------- OCR & import
def _make_doc_image(path: Path, lines: list[str], sig_template=None):
    img = Image.new("RGB", (1700, 2200), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT, 46)
    y = 150
    for ln in lines:
        rtl = any("؀" <= ch <= "ۿ" for ch in ln)
        if rtl:
            w = d.textlength(ln, font=font, direction="rtl", language="ar")
            d.text((1600 - w, y), ln, font=font, fill="black", direction="rtl", language="ar")
        else:
            d.text((120, y), ln, font=font, fill="black")
        y += 90
    if sig_template is not None:
        sig = render_signature(sig_template, seed=5)
        img.paste(Image.fromarray(sig[:, :, ::-1]), (1000, 1600))
    img.save(path)


def test_ocr_import_review_flow(ctx, tmp_path):
    sv = ctx.services
    src_dir = tmp_path / "embassies"
    (src_dir / "sub").mkdir(parents=True)
    tpl = make_person_template(7)
    _make_doc_image(src_dir / "doc1.png", [
        "Name: Khaled Omar Ben Ali",
        "Title: Consul General",
        "Phone: +218 91 765 4321",
        "Email: k.benali@example.ly",
        "Date: 12/05/2025",
    ], tpl)
    _make_doc_image(src_dir / "doc_ar.png", ["الاسم: خالد عمر", "الصفة: سفير"])
    shutil.copy(src_dir / "doc1.png", src_dir / "sub" / "copy_of_doc1.png")  # نفس البصمة
    sid = sv.sources.add("ملفات السفارات", str(src_dir), _cat(ctx, "LY_EMB_ABROAD"), "png,pdf")
    chk = sv.sources.check(sid)
    assert chk["total"] == 3
    rep = sv.ingestion.scan_source(sid)
    assert (rep.found, rep.new, rep.duplicates) == (3, 2, 1)
    rep2 = sv.ingestion.scan_source(sid)
    assert rep2.new == 0  # لا إعادة استيراد
    summ = sv.ingestion.process_pending()
    assert sum(summ.values()) == 2
    did = ctx.db.scalar("SELECT id FROM documents WHERE original_path LIKE '%doc1.png'")
    doc = sv.review.document(did)
    vals = {e["field"]: e["value"] for e in doc["extractions"]}
    assert "Khaled" in vals.get("full_name_en", "") or "Khaled" in vals.get("full_name", "")
    assert "k.benali@example.ly" in vals.get("email", "")
    sigs = [e["value"] for e in doc["extractions"] if e["field"] == "signature_candidate"]
    assert sigs, "يجب اقتراح منطقة توقيع"
    # المستند العربي (يتطلب تشكيل الحروف العربية في Pillow لتوليد صورة الاختبار)
    if HAS_RAQM:
        did_ar = ctx.db.scalar("SELECT id FROM documents WHERE original_path LIKE '%doc_ar.png'")
        ar = {e["field"]: e["value"] for e in sv.review.document(did_ar)["extractions"]}
        assert "خالد" in ar.get("full_name", ""), ar
    # الاعتماد
    pid = sv.review.approve(did, {"full_name": "خالد عمر بن علي", "full_name_en": vals.get("full_name_en"),
                                  "job_title": "القنصل العام", "phone": vals.get("phone"),
                                  "email": vals.get("email"), "entity": "القنصلية الليبية في مالطا",
                                  "date": vals.get("date"), "auth_end": "2027-01-01"},
                            signature_paths=sigs[:1])
    prof = sv.persons.profile(pid)
    assert prof["entity_name"] == "القنصلية الليبية في مالطا"
    assert prof["category_name"] == "السفارات الليبية بالخارج"
    assert len(prof["signatures"]) == 1 and len(prof["certifications"]) == 1
    assert prof["auth_status"] == "active"
    assert ctx.db.scalar("SELECT status FROM documents WHERE id=?", (did,)) == "reviewed"


def test_pdf_text_layer(ctx, tmp_path):
    from reportlab.pdfgen import canvas
    p = tmp_path / "t.pdf"
    c = canvas.Canvas(str(p))
    c.drawString(72, 750, "Name: Sara Ahmed")
    c.drawString(72, 730, "Title: Director General")
    c.drawString(72, 710, "Email: sara@ministry.gov.ly")
    c.save()
    did, new = ctx.services.ingestion.import_file(p)
    r = ctx.services.ingestion.process_document(did)
    assert r["status"] == "processed", r
    d = ctx.db.one("SELECT * FROM documents WHERE id=?", (did,))
    assert d["ocr_engine"] == "pdf_text" and "Sara Ahmed" in d["ocr_text"]


def test_scanned_pdf(ctx, tmp_path):
    img = tmp_path / "scan.png"
    _make_doc_image(img, ["Name: Ali Hassan", "Title: Minister"])
    pdf = tmp_path / "scan.pdf"
    Image.open(img).convert("RGB").save(pdf, "PDF", resolution=200)
    did, _ = ctx.services.ingestion.import_file(pdf)
    ctx.services.ingestion.process_document(did)
    d = ctx.db.one("SELECT * FROM documents WHERE id=?", (did,))
    assert "tesseract" in d["ocr_engine"] and "Ali Hassan" in d["ocr_text"]


def test_failed_read_warns(ctx, tmp_path):
    p = tmp_path / "blank.png"
    Image.new("RGB", (800, 600), "white").save(p)
    did, _ = ctx.services.ingestion.import_file(p)
    r = ctx.services.ingestion.process_document(did)
    assert r["status"] == "failed" and r["warnings"]


# ------------------------------------------------------------- signatures
def test_signature_search(ctx, tmp_path):
    sv = ctx.services
    eid = sv.catalog.add_entity(name="وزارة الخارجية", category_id=_cat(ctx, "MINISTRY"))
    eid2 = sv.catalog.add_entity(name="هيئة الرقابة", category_id=_cat(ctx, "AUTHORITY"))
    pids, files = [], []
    for i in range(12):
        pid = sv.persons.add(full_name=f"شخص {i}", job_title="مدير", entity_id=eid if i % 2 == 0 else eid2)
        sv.persons.add_certification(pid, "2025-01-0%d" % (i % 9 + 1))
        f = tmp_path / f"sig{i}.png"
        imwrite_any(f, render_signature(make_person_template(100 + i), seed=1))
        sv.signatures.enroll(pid, f)
        pids.append(pid); files.append(f)
    stored = [r["image_path"] for r in ctx.db.query("SELECT image_path FROM signatures")]
    hashes = [sha256_file(p) for p in stored]
    n_before = ctx.db.scalar("SELECT COUNT(*) FROM signatures")
    sv.auth.create_user("u", "User@123", "standard")
    sv.auth.logout(); sv.auth.login("u", "User@123")
    q = render_signature(make_person_template(104), seed=77, jitter=3, angle=4, scale=0.9, noise=8)
    res = sv.signatures.search(q)
    assert res.matches and res.matches[0].person_id == pids[4], [(m.full_name, m.percent) for m in res.matches]
    assert res.matches[0].percent >= 70
    assert res.matches[0].entity_name == "وزارة الخارجية"
    assert res.disclaimer
    # تضييق النطاق: هيئة الرقابة لا تحتوي الشخص 4
    res2 = sv.signatures.search(q, category_id=_cat(ctx, "AUTHORITY"))
    assert all(m.person_id != pids[4] for m in res2.matches)
    # توقيع غير موجود
    res3 = sv.signatures.search(render_signature(make_person_template(999), seed=3), threshold=0.75)
    assert not res3.matches and "لم يتم العثور" in res3.message
    # صورة البحث لا تسجل كتوقيع، والأصول لم تتغير
    assert ctx.db.scalar("SELECT COUNT(*) FROM signatures") == n_before
    assert [sha256_file(p) for p in stored] == hashes
    assert Path(res.query_image).parent == ctx.paths.temp


# ------------------------------------------------------------------ excel
def test_excel_view_edit_import(ctx, tmp_path):
    import openpyxl
    p = tmp_path / "list.xlsx"
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = "السفارات"
    ws.append(["الاسم", "الصفة", "الجهة", "الهاتف", "الدولة", "نهاية التفويض"])
    ws.append(["عمر المختار", "سفير", "سفارة ليبيا في مصر", "0913334444", "مصر", "31/12/2026"])
    ws.append(["", "", "", "", "", ""])
    wb.create_sheet("أخرى").append(["x"])
    wb.save(p)
    sv = ctx.services
    book = sv.excel.open(p)
    assert book.sheet_names() == ["السفارات", "أخرى"]
    assert book.read_sheet("السفارات")[1][0] == "عمر المختار"
    sv.excel.set_cell(book, "السفارات", 2, 2, "سفير فوق العادة")
    bk = sv.excel.save(book)
    assert bk and bk.exists()
    assert openpyxl.load_workbook(p)["السفارات"]["B2"].value == "سفير فوق العادة"
    r = sv.excel.import_persons(book, "السفارات", {"full_name": 0, "job_title": 1, "entity": 2, "phone": 3,
                                                   "country": 4, "auth_end": 5}, _cat(ctx, "LY_EMB_ABROAD"))
    assert r["added"] == 1 and r["skipped"] == 1
    p1 = sv.persons.search(name="عمر")[0]
    assert p1["country_name"] == "مصر" and p1["auth_end"] == "2026-12-31"


# ----------------------------------------------------------------- backup
def test_backup_restore(ctx, tmp_path):
    sv = ctx.services
    pid = sv.persons.add(full_name="قبل النسخ")
    f = tmp_path / "s.png"
    imwrite_any(f, render_signature(make_person_template(1)))
    sv.signatures.enroll(pid, f)
    z = sv.backup.create()
    sv.persons.add(full_name="بعد النسخ")
    sv.persons.delete(pid)
    sv.backup.restore(z)
    names = [r["full_name"] for r in ctx.db.query("SELECT full_name FROM persons")]
    assert names == ["قبل النسخ"]
    assert Path(ctx.db.scalar("SELECT image_path FROM signatures")).exists()
    assert ctx.db.scalar("SELECT action FROM audit_log ORDER BY id DESC LIMIT 1") == "backup_restore"
