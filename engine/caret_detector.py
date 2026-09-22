import ctypes
from ctypes import wintypes
import threading
import time
from typing import Callable, Optional, Tuple

from config import config

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG)
    ]

class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND),
        ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND),
        ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND),
        ("hwndCaret", wintypes.HWND),
        ("rcCaret", RECT)
    ]

class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]

class CURSORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("hCursor", ctypes.c_void_p),
        ("ptScreenPos", POINT)
    ]

class ICONINFO(ctypes.Structure):
    _fields_ = [
        ("fIcon", wintypes.BOOL),
        ("xHotspot", wintypes.DWORD),
        ("yHotspot", wintypes.DWORD),
        ("hbmMask", ctypes.c_void_p),
        ("hbmColor", ctypes.c_void_p)
    ]

# Explicit 64-bit ctypes argtypes & restypes (Prevents int overflow on 64-bit Windows pointers)
user32.GetCursorInfo.argtypes = [ctypes.c_void_p]
user32.GetCursorInfo.restype = wintypes.BOOL

user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
user32.GetIconInfo.restype = wintypes.BOOL

gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
gdi32.DeleteObject.restype = wintypes.BOOL

user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
user32.GetWindowThreadProcessId.restype = wintypes.DWORD

user32.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.c_void_p]
user32.GetGUIThreadInfo.restype = wintypes.BOOL

user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetWindowTextW.restype = ctypes.c_int

user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
user32.GetClassNameW.restype = ctypes.c_int

user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.c_void_p]
user32.GetWindowRect.restype = wintypes.BOOL

GUI_CARETBLINKING = 0x00000001
IDC_IBEAM = 32513
IDC_ARROW = 32512

h_ibeam = user32.LoadCursorW(None, wintypes.LPCWSTR(IDC_IBEAM))
h_arrow = user32.LoadCursorW(None, wintypes.LPCWSTR(IDC_ARROW))

class CaretDetector:
    """
    Intelligent Click-to-Type and Search Bar Detector:
    1. Intercepts left clicks to detect when the user clicks into a search bar / text field.
    2. Uses multi-tier detection:
       - Windows Caret and Focus tracking via GetGUIThreadInfo
       - Dynamic Cursor Hotspot Geometry (detects I-Beam cursors in Google Chrome, Edge, WhatsApp, etc.)
       - Native messaging apps (WhatsApp, Telegram, Discord, Slack) chat input and search bar support
       - Window Class & Child Window Inspection
    3. Opens on-screen keyboard for search inputs and smoothly manages active target HWND.
    """
    def __init__(
        self,
        on_show_keyboard: Optional[Callable[[Optional[int]], None]] = None,
        on_hide_keyboard: Optional[Callable[[], None]] = None
    ):
        self.on_show_keyboard = on_show_keyboard
        self.on_hide_keyboard = on_hide_keyboard
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.is_keyboard_open = False
        self._last_click_time = 0.0
        self.last_target_hwnd: Optional[int] = None

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._background_monitor, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=1.0)

    def is_cursor_ibeam(self) -> bool:
        """
        Returns True if the current mouse cursor is an I-Beam (text typing cursor).
        Supports native Windows system cursors, high-DPI cursors, WhatsApp, and browser cursors.
        """
        try:
            ci = CURSORINFO()
            ci.cbSize = ctypes.sizeof(CURSORINFO)
            if user32.GetCursorInfo(ctypes.byref(ci)):
                if not ci.hCursor:
                    return False
                # 1. Direct handle match against standard system I-Beam
                if ci.hCursor == h_ibeam:
                    return True
                # 2. Check hotspot geometry: I-Beam cursors are centered horizontally & vertically
                icon_info = ICONINFO()
                if user32.GetIconInfo(ci.hCursor, ctypes.byref(icon_info)):
                    xh = icon_info.xHotspot
                    yh = icon_info.yHotspot
                    # Safely clean up GDI bitmap handles created by GetIconInfo
                    try:
                        if icon_info.hbmMask:
                            gdi32.DeleteObject(icon_info.hbmMask)
                        if icon_info.hbmColor:
                            gdi32.DeleteObject(icon_info.hbmColor)
                    except Exception:
                        pass
                    
                    # I-Beam hotspots are centered (e.g. (8, 9), (16, 16), (12, 12)), whereas arrows are (0,0) and hands are top-edge
                    if (3 <= xh <= 26) and (3 <= yh <= 26) and abs(int(xh) - int(yh)) <= 7:
                        return True
        except Exception:
            pass
        return False

    def is_caret_or_edit_focused(self, click_x: Optional[int] = None, click_y: Optional[int] = None) -> bool:
        """Checks if active foreground window or clicked child control is a text / search input."""
        try:
            fg = user32.GetForegroundWindow()
            if not fg or not user32.IsWindow(fg):
                return False

            # 1. Target Thread GUI Info (Windows Caret & Focus)
            pid = wintypes.DWORD()
            tid = user32.GetWindowThreadProcessId(fg, ctypes.byref(pid))
            
            gui_info = GUITHREADINFO()
            gui_info.cbSize = ctypes.sizeof(GUITHREADINFO)
            if tid and user32.GetGUIThreadInfo(tid, ctypes.byref(gui_info)):
                if gui_info.hwndCaret:
                    return True
                caret_w = gui_info.rcCaret.right - gui_info.rcCaret.left
                caret_h = gui_info.rcCaret.bottom - gui_info.rcCaret.top
                if caret_w > 0 and caret_h > 0:
                    return True
                if gui_info.flags & GUI_CARETBLINKING:
                    return True
                if gui_info.hwndFocus:
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(gui_info.hwndFocus, buf, 256)
                    cname = buf.value.lower()
                    if any(kw in cname for kw in ["edit", "textbox", "search", "richedit", "input", "omnibox", "entry", "text", "richeditbox"]):
                        return True

            # 2. Window Class Inspection at Click Coordinate (specific input controls only)
            if click_x is not None and click_y is not None:
                pt = POINT(click_x, click_y)
                hwnd_at_pt = user32.WindowFromPoint(pt)
                if hwnd_at_pt:
                    buf = ctypes.create_unicode_buffer(256)
                    user32.GetClassNameW(hwnd_at_pt, buf, 256)
                    cname = buf.value.lower()
                    if any(kw in cname for kw in ["edit", "richedit", "searchbox", "textbox", "omnibox", "entry", "richeditbox"]):
                        return True

            # 3. Dedicated Messaging App Support (WhatsApp Desktop, Telegram, Discord, Teams, Slack, Messenger)
            title_buf = ctypes.create_unicode_buffer(512)
            user32.GetWindowTextW(fg, title_buf, 512)
            w_title = title_buf.value.lower()
            
            class_buf = ctypes.create_unicode_buffer(512)
            user32.GetClassNameW(fg, class_buf, 512)
            w_class = class_buf.value.lower()

            is_chat_app = any(app in w_title for app in ["whatsapp", "telegram", "discord", "slack", "signal", "teams", "messenger"]) or ("whatsapp" in w_class)
            
            if is_chat_app:
                if click_x is not None and click_y is not None:
                    rect = RECT()
                    if user32.GetWindowRect(fg, ctypes.byref(rect)):
                        w = rect.right - rect.left
                        h = rect.bottom - rect.top
                        if w > 100 and h > 100:
                            # Bottom message input box area (where "Type a message" is located in WhatsApp)
                            msg_box_top = rect.bottom - max(110, int(h * 0.22))
                            if (rect.left <= click_x <= rect.right) and (msg_box_top <= click_y <= rect.bottom):
                                return True
                            # Top-left search bar area (where "Search or start new chat" is located in WhatsApp)
                            search_box_right = rect.left + max(250, int(w * 0.42))
                            search_box_bottom = rect.top + min(160, int(h * 0.20))
                            if (rect.left <= click_x <= search_box_right) and (rect.top + 30 <= click_y <= search_box_bottom):
                                return True
        except Exception:
            pass

        return False

    def on_click(self, click_x: int, click_y: int, keyboard_bounds: Optional[Tuple[int, int, int, int]] = None):
        """
        Called when a left click occurs anywhere on screen.
        Determines whether to show the keyboard (clicked on search/input)
        or hide the keyboard (clicked away).
        """
        if not config.auto_keyboard_enabled:
            return

        self._last_click_time = time.time()

        # If click is inside the on-screen keyboard itself, do not hide!
        if keyboard_bounds is not None:
            kx, ky, kw, kh = keyboard_bounds
            if kx <= click_x <= (kx + kw) and ky <= click_y <= (ky + kh):
                return

        fg_hwnd = user32.GetForegroundWindow()
        if fg_hwnd and user32.IsWindow(fg_hwnd):
            self.last_target_hwnd = fg_hwnd

        # Check if user clicked on a text field / search bar immediately
        is_text_target = self.is_cursor_ibeam() or self.is_caret_or_edit_focused(click_x, click_y)

        if is_text_target:
            self.is_keyboard_open = True
            if self.on_show_keyboard:
                self.on_show_keyboard(self.last_target_hwnd)
        else:
            # Multi-tier delayed check (45ms and 110ms) to catch asynchronous browser DOM focus events (Google Chrome, Edge, etc.)
            def _delayed_check(click_t, target_h):
                if click_t != self._last_click_time:
                    return
                # Check after initial browser layout tick
                if self.is_cursor_ibeam() or self.is_caret_or_edit_focused(click_x, click_y):
                    self.is_keyboard_open = True
                    if self.on_show_keyboard:
                        self.on_show_keyboard(target_h)
                    return

                # Check second time for slower web apps
                time.sleep(0.065)
                if click_t != self._last_click_time:
                    return
                if self.is_cursor_ibeam() or self.is_caret_or_edit_focused(click_x, click_y):
                    self.is_keyboard_open = True
                    if self.on_show_keyboard:
                        self.on_show_keyboard(target_h)
                else:
                    # User clicked on non-text area -> dismiss on-screen keyboard
                    self.is_keyboard_open = False
                    if self.on_hide_keyboard:
                        self.on_hide_keyboard()

            curr_click_t = self._last_click_time
            curr_target_h = self.last_target_hwnd
            threading.Thread(target=lambda: (time.sleep(0.045), _delayed_check(curr_click_t, curr_target_h)), daemon=True).start()

    def _background_monitor(self):
        """Lightweight background caretaker ensuring state consistency."""
        while self.running:
            time.sleep(0.25)
