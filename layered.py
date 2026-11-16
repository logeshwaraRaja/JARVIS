"""Per-pixel-alpha window (UpdateLayeredWindow) so the floating mic has smooth, anti-aliased edges."""
import ctypes
from ctypes import POINTER, byref, c_int, c_long, c_uint, c_void_p
from ctypes import wintypes as wt

import numpy as np

user32 = ctypes.WinDLL("user32", use_last_error=True)
gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)


class BIH(ctypes.Structure):
    _fields_ = [("biSize", wt.DWORD), ("biWidth", wt.LONG), ("biHeight", wt.LONG), ("biPlanes", wt.WORD),
                ("biBitCount", wt.WORD), ("biCompression", wt.DWORD), ("biSizeImage", wt.DWORD),
                ("biXPelsPerMeter", wt.LONG), ("biYPelsPerMeter", wt.LONG),
                ("biClrUsed", wt.DWORD), ("biClrImportant", wt.DWORD)]


class BLEND(ctypes.Structure):
    _fields_ = [("BlendOp", ctypes.c_ubyte), ("BlendFlags", ctypes.c_ubyte),
                ("SourceConstantAlpha", ctypes.c_ubyte), ("AlphaFormat", ctypes.c_ubyte)]


user32.GetAncestor.argtypes = [c_void_p, c_uint]
user32.GetAncestor.restype = c_void_p
user32.GetWindowLongW.argtypes = [c_void_p, c_int]
user32.GetWindowLongW.restype = c_long
user32.SetWindowLongW.argtypes = [c_void_p, c_int, c_long]
user32.UpdateLayeredWindow.argtypes = [c_void_p, c_void_p, POINTER(wt.POINT), POINTER(wt.SIZE), c_void_p,
                                       POINTER(wt.POINT), wt.DWORD, POINTER(BLEND), wt.DWORD]
user32.UpdateLayeredWindow.restype = wt.BOOL
gdi32.CreateCompatibleDC.argtypes = [c_void_p]
gdi32.CreateCompatibleDC.restype = c_void_p
gdi32.CreateDIBSection.argtypes = [c_void_p, POINTER(BIH), c_uint, POINTER(c_void_p), c_void_p, wt.DWORD]
gdi32.CreateDIBSection.restype = c_void_p
gdi32.SelectObject.argtypes = [c_void_p, c_void_p]
gdi32.SelectObject.restype = c_void_p


class LayeredWindow:
    def __init__(self, tkwin):
        tkwin.update_idletasks()
        self.hwnd = user32.GetAncestor(tkwin.winfo_id(), 2) or tkwin.winfo_id()
        ex = user32.GetWindowLongW(self.hwnd, -20)
        # LAYERED | NOACTIVATE | TOOLWINDOW
        user32.SetWindowLongW(self.hwnd, -20, ex | 0x00080000 | 0x08000000 | 0x00000080)
        self.memdc = gdi32.CreateCompatibleDC(None)
        self.cache = {}
        self.last = None

    def _make(self, img):
        w, h = img.size
        a = np.asarray(img.convert("RGBA"), dtype=np.float32)
        rgb = a[..., :3] * (a[..., 3:4] / 255.0)                      # premultiply
        bgra = np.dstack([rgb[..., 2], rgb[..., 1], rgb[..., 0], a[..., 3]]).round().astype(np.uint8)
        bih = BIH(40, w, -h, 1, 32, 0, w * h * 4, 0, 0, 0, 0)         # top-down 32-bit
        bits = c_void_p()
        hbmp = gdi32.CreateDIBSection(self.memdc, byref(bih), 0, byref(bits), None, 0)
        if not hbmp or not bits.value:
            raise OSError("CreateDIBSection failed")
        ctypes.memmove(bits.value, bgra.tobytes(), w * h * 4)
        return hbmp, (w, h)

    def show(self, key, make_img):
        if key == self.last:
            return
        if key not in self.cache:
            self.cache[key] = self._make(make_img())
        hbmp, (w, h) = self.cache[key]
        gdi32.SelectObject(self.memdc, hbmp)
        size, src = wt.SIZE(w, h), wt.POINT(0, 0)
        blend = BLEND(0, 0, 255, 1)   # AC_SRC_OVER, AC_SRC_ALPHA
        if not user32.UpdateLayeredWindow(self.hwnd, None, None, byref(size), self.memdc, byref(src),
                                          0, byref(blend), 2):
            raise OSError("UpdateLayeredWindow failed")
        self.last = key
