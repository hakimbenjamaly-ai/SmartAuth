"""وحدة البحث عن التوقيع باستخدام الماسح الضوئي (Scanner Signature Search)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QComboBox, QDoubleSpinBox, QFileDialog, QGridLayout, QGroupBox, QLabel,
                               QListWidget, QListWidgetItem, QSplitter, QVBoxLayout, QWidget)

from ...engine import scanner
from ...engine import signature as eng
from ...engine.imaging import imread_any
from ...services.signatures import DEFAULT_THRESHOLD
from ..widgets import ImageBox, Page, button, combo_fill, error, guarded, hbox, info, run_with_progress
from .persons import PersonProfileDialog


class SignatureSearchPage(Page):
    title = "البحث باستخدام التوقيع"
    subtitle = ("ضع التوقيع على الماسح الضوئي ثم امسحه، أو اختر صورة من الجهاز. "
                "تتم المقارنة محلياً بالكامل دون إرسال أي صورة خارج الجهاز.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self.image = None       # الصورة الحالية (مصفوفة)
        self.approved = False
        self.result = None

        # ------------------------------------------------- الماسح
        sc = QGroupBox("الماسح الضوئي")
        g = QGridLayout(sc)
        self.devices = QComboBox()
        self.dpi = QComboBox()
        for d in (200, 300, 400, 600):
            self.dpi.addItem(f"{d} DPI", d)
        self.dpi.setCurrentIndex(1)
        g.addWidget(QLabel("جهاز المسح:"), 0, 0); g.addWidget(self.devices, 0, 1, 1, 3)
        g.addWidget(QLabel("الدقة:"), 0, 4); g.addWidget(self.dpi, 0, 5)
        self.b_start = button("تشغيل الماسح الضوئي", self.start_scanner, "secondary")
        self.b_preview = button("معاينة المسح", self.preview, "secondary")
        self.b_scan = button("بدء المسح", self.scan)
        self.b_rescan = button("إعادة المسح", self.rescan, "secondary")
        self.b_file = button("اختيار صورة من الجهاز", self.from_file, "secondary")
        self.b_approve = button("اعتماد صورة التوقيع للبحث", self.approve, "accent")
        g.addLayout(hbox(self.b_start, self.b_preview, self.b_scan, self.b_rescan, self.b_file, None,
                         self.b_approve), 1, 0, 1, 6)
        self.layout_.addWidget(sc)

        # ------------------------------------------------- نطاق البحث
        sb = QGroupBox("نطاق البحث (اختياري)")
        sg = QGridLayout(sb)
        self.cat = QComboBox(); self.country = QComboBox(); self.entity = QComboBox()
        self.cat.currentIndexChanged.connect(self._ents); self.country.currentIndexChanged.connect(self._ents)
        self.thr = QDoubleSpinBox(); self.thr.setRange(30, 95); self.thr.setSuffix(" %")
        self.thr.setValue(DEFAULT_THRESHOLD * 100)
        sg.addWidget(QLabel("التصنيف:"), 0, 0); sg.addWidget(self.cat, 0, 1)
        sg.addWidget(QLabel("الدولة:"), 0, 2); sg.addWidget(self.country, 0, 3)
        sg.addWidget(QLabel("الجهة:"), 1, 0); sg.addWidget(self.entity, 1, 1, 1, 3)
        sg.addWidget(QLabel("أقل نسبة تشابه:"), 0, 4); sg.addWidget(self.thr, 0, 5)
        self.b_search = button("بحث في قاعدة البيانات", self.search)
        sg.addWidget(self.b_search, 1, 4, 1, 2)
        self.layout_.addWidget(sb)

        # ------------------------------------------------- النتائج
        split = QSplitter(Qt.Horizontal)
        lw = QWidget(); lv = QVBoxLayout(lw); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(QLabel("<b>النتائج مرتبة حسب نسبة التشابه</b>"))
        self.results = QListWidget()
        self.results.currentRowChanged.connect(self.show_match)
        self.results.itemDoubleClicked.connect(self.open_profile)
        lv.addWidget(self.results, 1)
        self.notfound = QLabel(""); self.notfound.setObjectName("NotFound"); self.notfound.setWordWrap(True)
        self.notfound.hide(); lv.addWidget(self.notfound)
        lv.addWidget(button("فتح صفحة بيانات الشخص", self.open_profile, "secondary"))
        split.addWidget(lw)

        cw = QWidget(); cv = QVBoxLayout(cw); cv.setContentsMargins(0, 0, 0, 0)
        cmp_box = QGroupBox("المقارنة البصرية جنباً إلى جنب")
        cg = QGridLayout(cmp_box)
        self.img_scan = ImageBox("التوقيع الممسوح", 420, 230)
        self.img_clean = ImageBox("بعد المعالجة", 420, 230)
        self.img_ref = ImageBox("التوقيع المسجل", 420, 230)
        cg.addWidget(QLabel("<b>التوقيع الممسوح</b>"), 0, 0); cg.addWidget(QLabel("<b>التوقيع المسجل</b>"), 0, 1)
        cg.addWidget(self.img_scan, 1, 0); cg.addWidget(self.img_ref, 1, 1)
        cg.addWidget(QLabel("التوقيع الممسوح بعد إزالة الخلفية والتشويش:"), 2, 0)
        cg.addWidget(self.img_clean, 3, 0)
        self.details = QLabel(""); self.details.setWordWrap(True); self.details.setAlignment(Qt.AlignTop)
        self.details.setTextInteractionFlags(Qt.TextSelectableByMouse)
        cg.addWidget(self.details, 3, 1)
        cv.addWidget(cmp_box, 1)
        disc = QLabel("⚠ " + eng.DISCLAIMER); disc.setObjectName("Disclaimer"); disc.setWordWrap(True)
        cv.addWidget(disc)
        split.addWidget(cw)
        split.setSizes([360, 900])
        self.layout_.addWidget(split, 1)
        self._update_buttons()
        self._loaded = False

    def on_show(self):
        if not self._loaded:
            combo_fill(self.cat, self.sv.catalog.categories(), "name", "جميع الجهات")
            combo_fill(self.country, self.sv.catalog.countries(), "name_ar", "كل الدول")
            self._ents()
            self.start_scanner(silent=True)
            self.sv.signatures.cleanup_temp()
            self._loaded = True

    def _ents(self, *_):
        combo_fill(self.entity, self.sv.catalog.entities(category_id=self.cat.currentData(),
                                                         country_id=self.country.currentData()), "name", "الكل")

    def _update_buttons(self):
        has = self.image is not None
        self.b_rescan.setEnabled(has)
        self.b_approve.setEnabled(has and not self.approved)
        self.b_search.setEnabled(has and self.approved)

    # ------------------------------------------------------------ scanning
    def start_scanner(self, silent: bool = False):
        self.devices.clear()
        if not scanner.is_windows():
            self.devices.addItem("الماسح متاح على Windows فقط - استخدم (اختيار صورة من الجهاز)", None)
            return
        devs = scanner.list_devices()
        for d in devs:
            self.devices.addItem(d.name, d)
        self.devices.addItem("نافذة Windows لاختيار الماسح (WIA)", "dialog")
        if not devs and not silent:
            info(self, "لم يتم العثور على ماسح ضوئي متصل. تأكد من توصيل الجهاز وتثبيت تعريفه (TWAIN/WIA).")

    def _do_scan(self, preview: bool):
        dev = self.devices.currentData()
        if dev is None:
            return info(self, "لا يوجد ماسح ضوئي محدد")
        try:
            if dev == "dialog":
                img, _ = scanner.wia_dialog_scan(self.ctx.paths.temp)
            else:
                img, _ = scanner.scan(dev, dpi=self.dpi.currentData(), preview=preview, out_dir=self.ctx.paths.temp)
        except scanner.ScannerError as e:
            return error(self, e)
        self._set_image(img)

    def preview(self):
        self._do_scan(True)

    def scan(self):
        self._do_scan(False)

    def rescan(self):
        self.image = None; self.approved = False
        self.results.clear(); self.notfound.hide()
        for b in (self.img_scan, self.img_clean, self.img_ref):
            b.clear(); b.setText(b._caption)
        self.details.clear()
        self._update_buttons()
        if self.devices.currentData() is not None:
            self.scan()

    @guarded
    def from_file(self):
        f, _ = QFileDialog.getOpenFileName(self, "اختر صورة التوقيع", "",
                                           "صور (*.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if f:
            img = imread_any(f)
            if img is None:
                return error(self, "تعذر قراءة الصورة")
            self._set_image(img)

    def _set_image(self, img):
        self.image = img
        self.approved = False
        self.img_scan.show_array(img)
        self.img_clean.show_array(eng.cleaned_preview(img))
        self.results.clear(); self.notfound.hide(); self.img_ref.clear(); self.details.clear()
        self._update_buttons()

    def approve(self):
        self.approved = True
        self._update_buttons()
        self.search()

    # -------------------------------------------------------------- search
    def search(self):
        if self.image is None or not self.approved:
            return
        run_with_progress(self, "جاري مقارنة التوقيع بقاعدة البيانات...", self.sv.signatures.search,
                          self.image, category_id=self.cat.currentData(), country_id=self.country.currentData(),
                          entity_id=self.entity.currentData(), threshold=self.thr.value() / 100.0,
                          with_progress=False, on_done=self._show_results)

    def _show_results(self, res):
        self.result = res
        self.results.clear()
        if not res.matches:
            self.notfound.setText(res.message + "\nيمكنك إعادة المسح أو توسيع نطاق البحث.")
            self.notfound.show()
            return
        self.notfound.hide()
        for i, m in enumerate(res.matches, 1):
            it = QListWidgetItem(f"{i}. {m.full_name} — {m.percent}% تشابه\n    {m.job_title or ''} | {m.entity_name or ''}")
            it.setData(Qt.UserRole, m)
            if m.percent >= 85:
                it.setForeground(Qt.darkGreen)
            elif m.percent < 65:
                it.setForeground(Qt.darkYellow)
            self.results.addItem(it)
        self.results.setCurrentRow(0)

    def show_match(self, row):
        it = self.results.item(row)
        if not it:
            return
        m = it.data(Qt.UserRole)
        self.img_ref.show_path(m.image_path)
        self.details.setText(
            f"<b>الاسم:</b> {m.full_name}<br><b>الصفة الوظيفية:</b> {m.job_title or '—'}<br>"
            f"<b>الجهة:</b> {m.entity_name or '—'}<br><b>الدولة:</b> {m.country_name or '—'}<br>"
            f"<b>نسبة التشابه:</b> <span style='font-size:14pt'>{m.percent}%</span><br>"
            f"<b>تاريخ التصديق:</b> {m.last_cert or '—'}<br>"
            f"<b>حالة التفويض:</b> {m.auth_status_label}" + (f" (حتى {m.auth_end})" if m.auth_end else "") +
            f"<br><br><small>عدد التوقيعات التي تمت مقارنتها: {self.result.searched} — "
            f"الزمن: {self.result.elapsed:.1f} ث</small>")

    def open_profile(self, *_):
        it = self.results.currentItem()
        if it:
            PersonProfileDialog(self.ctx, it.data(Qt.UserRole).person_id, self).exec()
