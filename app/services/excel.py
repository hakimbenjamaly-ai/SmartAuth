"""عرض ملفات Excel وتعديلها والتنقل بين أوراقها، واستيراد الأشخاص منها (للمشغل الرئيسي فقط)."""
from __future__ import annotations

import shutil
from datetime import datetime
from pathlib import Path

from ..core.permissions import EDIT_DATA, EXCEL_EDIT, EXCEL_VIEW, require
from . import BaseService

EXCEL_EXT = (".xlsx", ".xlsm", ".xls")


class ExcelWorkbook:
    """غلاف بسيط حول openpyxl. ملفات .xls القديمة تُقرأ فقط (عبر xlrd إن وُجد)."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.readonly = self.path.suffix.lower() == ".xls"
        if self.readonly:
            self._load_xls()
        else:
            import openpyxl
            self.wb = openpyxl.load_workbook(self.path, data_only=False)
        self.dirty = False

    def _load_xls(self):
        try:
            import xlrd
        except ImportError as e:
            raise ValueError("قراءة ملفات .xls القديمة تتطلب مكتبة xlrd. احفظ الملف بصيغة .xlsx") from e
        book = xlrd.open_workbook(str(self.path))
        self._xls = {s.name: [[s.cell_value(r, c) for c in range(s.ncols)] for r in range(s.nrows)]
                     for s in book.sheets()}

    def sheet_names(self) -> list[str]:
        return list(self._xls) if self.readonly else self.wb.sheetnames

    def read_sheet(self, name: str, max_rows: int = 20000) -> list[list]:
        if self.readonly:
            return self._xls[name][:max_rows]
        ws = self.wb[name]
        rows = []
        for row in ws.iter_rows(min_row=1, max_row=min(ws.max_row, max_rows), values_only=True):
            rows.append(["" if v is None else v for v in row])
        return rows

    def set_cell(self, sheet: str, row: int, col: int, value) -> None:
        """row/col تبدأ من 1."""
        if self.readonly:
            raise ValueError("الملف للقراءة فقط (.xls). احفظه بصيغة .xlsx للتعديل")
        ws = self.wb[sheet]
        if isinstance(value, str):
            v = value.strip()
            if v.startswith("="):
                value = v
            else:
                try:
                    value = int(v) if v.lstrip("-").isdigit() else float(v) if v.replace(".", "", 1).lstrip("-").isdigit() else value
                except ValueError:
                    pass
        ws.cell(row=row, column=col, value=value)
        self.dirty = True

    def add_sheet(self, name: str) -> None:
        if self.readonly:
            raise ValueError("الملف للقراءة فقط")
        self.wb.create_sheet(name)
        self.dirty = True

    def save(self, backup_dir: Path | None = None) -> Path | None:
        if self.readonly:
            raise ValueError("الملف للقراءة فقط")
        bk = None
        if backup_dir and self.path.exists():
            backup_dir.mkdir(parents=True, exist_ok=True)
            bk = backup_dir / f"{self.path.stem}_{datetime.now():%Y%m%d_%H%M%S}{self.path.suffix}"
            shutil.copy2(self.path, bk)
        self.wb.save(self.path)
        self.dirty = False
        return bk


class ExcelService(BaseService):
    @require(EXCEL_VIEW)
    def list_files(self):
        """ملفات Excel المسجلة من مصادر البيانات."""
        return self.db.query("SELECT d.id, d.original_path, d.archive_path, d.imported_at, s.name AS source_name "
                             "FROM documents d LEFT JOIN data_sources s ON s.id=d.source_id "
                             "WHERE lower(d.file_type) IN ('xlsx','xlsm','xls') ORDER BY d.original_path")

    @require(EXCEL_VIEW)
    def open(self, path: str | Path) -> ExcelWorkbook:
        p = Path(path)
        if p.suffix.lower() not in EXCEL_EXT:
            raise ValueError("ليس ملف Excel")
        self.audit("excel_open", str(p))
        return ExcelWorkbook(p)

    @require(EXCEL_EDIT)
    def save(self, wb: ExcelWorkbook) -> Path | None:
        bk = wb.save(self.ctx.paths.backups / "excel_versions")
        self.audit("excel_save", str(wb.path), f"backup={bk}")
        return bk

    @require(EXCEL_EDIT)
    def set_cell(self, wb: ExcelWorkbook, sheet: str, row: int, col: int, value) -> None:
        wb.set_cell(sheet, row, col, value)

    @require(EXCEL_VIEW, EDIT_DATA)
    def import_persons(self, wb: ExcelWorkbook, sheet: str, mapping: dict[str, int],
                       category_id: int, header_rows: int = 1, entity_name: str | None = None) -> dict:
        """استيراد الأشخاص من ورقة: mapping = {"full_name": 0, "job_title": 1, "entity": 2, "phone": 3,
        "email": 4, "country": 5, "auth_start": 6, "auth_end": 7} (أرقام أعمدة تبدأ من 0)."""
        from ..engine.extract import parse_date
        sv = self.ctx.services
        rows = wb.read_sheet(sheet)[header_rows:]
        added = updated = skipped = 0
        errors = []

        def cell(r, key):
            i = mapping.get(key)
            if i is None or i >= len(r):
                return ""
            v = r[i]
            if isinstance(v, datetime):
                return v.date().isoformat()
            return str(v).strip() if v not in (None, "") else ""

        for n, r in enumerate(rows, header_rows + 1):
            name = cell(r, "full_name")
            if not name:
                skipped += 1
                continue
            try:
                country_id = None
                cname = cell(r, "country")
                if cname:
                    row = self.db.one("SELECT id FROM countries WHERE name_ar=? OR name_en=?", (cname, cname))
                    country_id = row["id"] if row else sv.catalog.add_country(cname)
                ename = cell(r, "entity") or entity_name
                eid = sv.catalog.find_or_create_entity(ename, category_id, country_id) if ename else None
                data = {"full_name": name, "job_title": cell(r, "job_title") or None,
                        "phone": cell(r, "phone") or None, "email": cell(r, "email") or None,
                        "full_name_en": cell(r, "full_name_en") or None, "entity_id": eid}
                ex = self.db.one("SELECT id FROM persons WHERE norm_ar(full_name)=norm_ar(?) "
                                 "AND IFNULL(entity_id,0)=IFNULL(?,0)", (name, eid))
                if ex:
                    sv.persons.update(ex["id"], **{k: v for k, v in data.items() if v})
                    pid = ex["id"]; updated += 1
                else:
                    pid = sv.persons.add(**data); added += 1
                s, e = cell(r, "auth_start"), cell(r, "auth_end")
                s, e = (parse_date(s) or s or None), (parse_date(e) or e or None)
                if s or e:
                    sv.persons.add_authorization(pid, s, e, entity_id=eid)
            except Exception as ex_:
                errors.append(f"السطر {n}: {ex_}")
        self.audit("excel_import_persons", str(wb.path), f"added={added} updated={updated}")
        return {"added": added, "updated": updated, "skipped": skipped, "errors": errors}
