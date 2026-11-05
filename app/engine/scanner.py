"""تشغيل الماسح الضوئي محلياً على Windows عبر WIA أو TWAIN (دون إنترنت).

- WIA: عبر COM (pywin32) - مدعوم في أغلب الماسحات الحديثة على Windows 10/11.
- TWAIN: عبر مكتبة pytwain (اختيارية) للماسحات التي لا تدعم WIA.
- بديل احتياطي: اختيار ملف صورة من القرص.
"""
from __future__ import annotations

import sys
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .imaging import imread_any

WIA_FORMAT_PNG = "{B96B3CAF-0728-11D3-9D7B-0000F81EF32E}"
WIA_DEVICE_TYPE_SCANNER = 1
WIA_PROPS = {"dpi_x": "6147", "dpi_y": "6148", "color_intent": "6146"}


@dataclass
class ScannerDevice:
    id: str
    name: str
    backend: str  # wia | twain


class ScannerError(Exception):
    pass


def is_windows() -> bool:
    return sys.platform.startswith("win")


def list_devices() -> list[ScannerDevice]:
    devs: list[ScannerDevice] = []
    if not is_windows():
        return devs
    try:
        import win32com.client
        mgr = win32com.client.Dispatch("WIA.DeviceManager")
        for i in range(1, mgr.DeviceInfos.Count + 1):
            info = mgr.DeviceInfos.Item(i)
            if info.Type == WIA_DEVICE_TYPE_SCANNER:
                name = info.Properties("Name").Value
                devs.append(ScannerDevice(info.DeviceID, name, "wia"))
    except Exception:
        pass
    try:
        import twain
        sm = twain.SourceManager(0)
        for name in sm.GetSourceList():
            devs.append(ScannerDevice(name, f"{name} (TWAIN)", "twain"))
        sm.destroy()
    except Exception:
        pass
    return devs


def _set_prop(item, pid: str, value) -> None:
    try:
        for p in item.Properties:
            if str(p.PropertyID) == pid:
                p.Value = value
                return
    except Exception:
        pass


def scan(device: ScannerDevice, dpi: int = 300, color: bool = False, preview: bool = False,
         out_dir: Path | None = None) -> tuple[np.ndarray, Path]:
    """مسح صورة وإرجاعها كمصفوفة BGR مع مسار ملف مؤقت."""
    if not is_windows():
        raise ScannerError("الماسح الضوئي مدعوم على نظام Windows فقط")
    out_dir = Path(out_dir or tempfile.gettempdir())
    out = out_dir / f"scan_{uuid.uuid4().hex}.png"
    dpi = 100 if preview else dpi
    if device.backend == "wia":
        try:
            import win32com.client
            mgr = win32com.client.Dispatch("WIA.DeviceManager")
            dev = None
            for i in range(1, mgr.DeviceInfos.Count + 1):
                info = mgr.DeviceInfos.Item(i)
                if info.DeviceID == device.id:
                    dev = info.Connect()
                    break
            if dev is None:
                raise ScannerError("لم يتم العثور على الماسح المحدد. تأكد من توصيله وتشغيله")
            item = dev.Items(1)
            _set_prop(item, WIA_PROPS["dpi_x"], dpi)
            _set_prop(item, WIA_PROPS["dpi_y"], dpi)
            _set_prop(item, WIA_PROPS["color_intent"], 1 if color else 2)  # 1 لون، 2 رمادي
            img = item.Transfer(WIA_FORMAT_PNG)
            if out.exists():
                out.unlink()
            img.SaveFile(str(out))
        except ScannerError:
            raise
        except Exception as e:
            raise ScannerError(f"فشل المسح عبر WIA: {e}") from e
    else:
        try:
            import twain
            sm = twain.SourceManager(0)
            src = sm.OpenSource(device.id)
            try:
                src.SetCapability(twain.ICAP_XRESOLUTION, twain.TWTY_FIX32, float(dpi))
                src.SetCapability(twain.ICAP_YRESOLUTION, twain.TWTY_FIX32, float(dpi))
            except Exception:
                pass
            src.RequestAcquire(0, 0)
            handle, _ = src.XferImageNatively()
            bmp = out.with_suffix(".bmp")
            twain.DIBToBMFile(handle, str(bmp))
            twain.GlobalHandleFree(handle)
            src.destroy(); sm.destroy()
            out = bmp
        except Exception as e:
            raise ScannerError(f"فشل المسح عبر TWAIN: {e}") from e
    arr = imread_any(out)
    if arr is None:
        raise ScannerError("لم يتم استلام صورة من الماسح")
    return arr, out


def wia_dialog_scan(out_dir: Path | None = None) -> tuple[np.ndarray, Path]:
    """واجهة Windows القياسية لاختيار الماسح والمسح (أبسط خيار وأكثرها توافقاً)."""
    if not is_windows():
        raise ScannerError("الماسح الضوئي مدعوم على نظام Windows فقط")
    try:
        import win32com.client
        dlg = win32com.client.Dispatch("WIA.CommonDialog")
        img = dlg.ShowAcquireImage(WIA_DEVICE_TYPE_SCANNER, 2, 0, WIA_FORMAT_PNG, False, True, False)
        if img is None:
            raise ScannerError("تم إلغاء المسح")
        out = Path(out_dir or tempfile.gettempdir()) / f"scan_{uuid.uuid4().hex}.png"
        img.SaveFile(str(out))
    except ScannerError:
        raise
    except Exception as e:
        raise ScannerError(f"فشل المسح: {e}") from e
    arr = imread_any(out)
    if arr is None:
        raise ScannerError("لم يتم استلام صورة من الماسح")
    return arr, out
