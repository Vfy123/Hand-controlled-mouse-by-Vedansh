import ctypes
from ctypes import wintypes
import time
import tkinter as tk
from typing import Optional, List, Tuple

from config import config

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

# Windows Constants for No-Activate Window & Keystrokes
GWL_EXSTYLE = -20
GWLP_WNDPROC = -4
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080

SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
HWND_TOPMOST = -1
GA_ROOT = 2

WM_MOUSEACTIVATE = 0x0021
MA_NOACTIVATE = 3

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_CAPITAL = 0x14
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_LEFT = 0x25
VK_RIGHT = 0x27

# 64-bit / 32-bit Win32 API compatibility
try:
    SetWindowLongPtr = user32.SetWindowLongPtrW
    SetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
    SetWindowLongPtr.restype = ctypes.c_void_p
    GetWindowLongPtr = user32.GetWindowLongPtrW
    GetWindowLongPtr.argtypes = [wintypes.HWND, ctypes.c_int]
    GetWindowLongPtr.restype = ctypes.c_void_p
except AttributeError:
    SetWindowLongPtr = user32.SetWindowLongW
    GetWindowLongPtr = user32.GetWindowLongW

user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.CallWindowProcW.restype = ctypes.c_longlong
user32.DefWindowProcW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.DefWindowProcW.restype = ctypes.c_longlong
user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
user32.GetAncestor.restype = wintypes.HWND

user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_ulonglong]
user32.keybd_event.restype = None

WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_longlong, wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)

# Ctypes structures for SendInput
class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]

class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION)
    ]


def send_unicode_char(char: str):
    """Sends a Unicode character directly to the target application via SendInput."""
    for ch in char:
        code = ord(ch)
        inp_down = INPUT()
        inp_down.type = INPUT_KEYBOARD
        inp_down.union.ki.wVk = 0
        inp_down.union.ki.wScan = code
        inp_down.union.ki.dwFlags = KEYEVENTF_UNICODE
        inp_down.union.ki.time = 0
        inp_down.union.ki.dwExtraInfo = 0
        
        inp_up = INPUT()
        inp_up.type = INPUT_KEYBOARD
        inp_up.union.ki.wVk = 0
        inp_up.union.ki.wScan = code
        inp_up.union.ki.dwFlags = KEYEVENTF_UNICODE | KEYEVENTF_KEYUP
        inp_up.union.ki.time = 0
        inp_up.union.ki.dwExtraInfo = 0

        inputs = (INPUT * 2)(inp_down, inp_up)
        user32.SendInput(2, inputs, ctypes.sizeof(INPUT))


def send_character_input(char: str):
    """
    Sends a character into the target window (Google Chrome, Edge, Notepad, etc.)
    using hardware scan codes + virtual keys + shift state, with Unicode fallback.
    """
    for ch in char:
        vk_res = user32.VkKeyScanW(ord(ch))
        vk = vk_res & 0xFF
        shift_state = (vk_res >> 8) & 1
        ctrl_state = (vk_res >> 9) & 1
        alt_state = (vk_res >> 10) & 1
        
        if vk != 0xFF:
            scan = user32.MapVirtualKeyW(vk, 0)
            if shift_state:
                user32.keybd_event(VK_SHIFT, 0x2A, 0, 0)
            if ctrl_state:
                user32.keybd_event(VK_CONTROL, 0x1D, 0, 0)
            if alt_state:
                user32.keybd_event(VK_MENU, 0x38, 0, 0)
                
            user32.keybd_event(vk, scan, 0, 0)
            user32.keybd_event(vk, scan, KEYEVENTF_KEYUP, 0)
            
            if alt_state:
                user32.keybd_event(VK_MENU, 0x38, KEYEVENTF_KEYUP, 0)
            if ctrl_state:
                user32.keybd_event(VK_CONTROL, 0x1D, KEYEVENTF_KEYUP, 0)
            if shift_state:
                user32.keybd_event(VK_SHIFT, 0x2A, KEYEVENTF_KEYUP, 0)
        else:
            send_unicode_char(ch)


def send_virtual_key(vk_code: int):
    """Sends a virtual key code (Backspace, Enter, Space, Arrows, etc.) with hardware scan code."""
    scan = user32.MapVirtualKeyW(vk_code, 0)
    user32.keybd_event(vk_code, scan, 0, 0)
    user32.keybd_event(vk_code, scan, KEYEVENTF_KEYUP, 0)


class VirtualKeyboard:
    """
    Compact Cyberpunk Floating On-Screen Keyboard.
    Configured with true WS_EX_NOACTIVATE & WM_MOUSEACTIVATE interceptor
    so clicking keys sends keystrokes directly to search bars / text inputs
    without stealing window focus in Google Chrome, Edge, or Windows apps.
    """
    def __init__(self, root: tk.Tk):
        self.root = root
        self.window: Optional[tk.Toplevel] = None
        self.is_visible = False
        self.animating = False
        self.caps_lock = False
        self.shift_active = False
        self.key_buttons: List[Tuple[tk.Label, str, str]] = []
        self.last_target_hwnd: Optional[int] = None
        self._old_wndproc = None
        self._wndproc_callback = None
        self.last_key_press_time: float = 0.0
        self.last_pressed_key: Optional[str] = None
        self._cached_keys: List[Tuple[tk.Label, str, str, int, int, int, int]] = []
        self._cached_close_btn: Optional[Tuple[int, int, int, int]] = None
        self._current_hovered_lbl: Optional[tk.Label] = None

        # Dimensions
        self.width = 680
        self.height = 230
        self.pos_x = 0
        self.pos_y = 0

    def set_target_hwnd(self, hwnd: int):
        """Sets the active target window for keystrokes."""
        if hwnd and user32.IsWindow(hwnd):
            if self.window is None or hwnd != self.window.winfo_id():
                self.last_target_hwnd = hwnd

    def get_bounds(self) -> Optional[Tuple[int, int, int, int]]:
        """Returns (x, y, width, height) of the keyboard on screen if visible."""
        if self.is_visible and self.window is not None and self.window.winfo_exists():
            return (self.pos_x, self.pos_y, self.width, self.height)
        return None

    def is_point_inside(self, screen_x: int, screen_y: int) -> bool:
        """Returns True if (screen_x, screen_y) falls inside the keyboard window bounds."""
        if not self.is_visible or self.window is None:
            return False
        return (self.pos_x <= screen_x <= self.pos_x + self.width) and (self.pos_y <= screen_y <= self.pos_y + self.height)

    def show(self, target_hwnd: Optional[int] = None):
        if self.animating:
            return
            
        if target_hwnd and user32.IsWindow(target_hwnd):
            self.last_target_hwnd = target_hwnd
        else:
            fg_hwnd = user32.GetForegroundWindow()
            if fg_hwnd and user32.IsWindow(fg_hwnd):
                if self.window is None or fg_hwnd != self.window.winfo_id():
                    self.last_target_hwnd = fg_hwnd

        if self.window is not None and self.window.winfo_exists():
            try:
                self.window.lift()
                self.is_visible = True
                self._update_geometry_cache()
                return
            except Exception:
                self.window = None

        self.window = tk.Toplevel(self.root, takefocus=False)
        self.window.title("Hand Mouse Keyboard")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.0) # Start transparent for smooth fade in
        self.window.configure(bg="#0c0e14")

        # Center horizontally, position near bottom of screen
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        self.pos_x = (screen_w - self.width) // 2
        self.pos_y = screen_h - self.height - 40
        self.window.geometry(f"{self.width}x{self.height}+{self.pos_x}+{self.pos_y}")
        self.window.update_idletasks()

        # Apply robust Win32 no-activate styles and subclass WM_MOUSEACTIVATE
        self._apply_no_activate()

        self._build_ui()
        self._update_geometry_cache()
        self.is_visible = True

        # Smooth fade-in animation
        self._animate_fade(0.0, 0.95, 6)

    def _animate_fade(self, start_alpha: float, target_alpha: float, steps: int, on_complete=None):
        self.animating = True
        step_alpha = (target_alpha - start_alpha) / steps

        def step(i):
            if not self.window or not self.window.winfo_exists():
                self.animating = False
                return
            if i <= steps:
                alpha = start_alpha + step_alpha * i
                try:
                    self.window.attributes("-alpha", alpha)
                except Exception:
                    pass
                self.root.after(14, lambda: step(i + 1))
            else:
                try:
                    self.window.attributes("-alpha", target_alpha)
                except Exception:
                    pass
                self.animating = False
                if on_complete:
                    on_complete()

        step(1)

    def _apply_no_activate(self):
        """
        Applies WS_EX_NOACTIVATE, WS_EX_TOPMOST, and WS_EX_TOOLWINDOW to the Win32 root window.
        Also subclasses WM_MOUSEACTIVATE to return MA_NOACTIVATE, preventing Windows from ever
        deactivating Google Chrome / Edge when keys are clicked.
        """
        try:
            hwnd = self.window.winfo_id()
            root_hwnd = user32.GetAncestor(hwnd, GA_ROOT)
            if not root_hwnd:
                root_hwnd = user32.GetParent(hwnd)
            if not root_hwnd:
                root_hwnd = hwnd

            for h in set([hwnd, root_hwnd]):
                if h:
                    style = user32.GetWindowLongW(h, GWL_EXSTYLE)
                    user32.SetWindowLongW(h, GWL_EXSTYLE, style | WS_EX_NOACTIVATE | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
                    user32.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)

            # Subclass WM_MOUSEACTIVATE to return MA_NOACTIVATE
            def _subclass_proc(hWnd, uMsg, wParam, lParam):
                if uMsg == WM_MOUSEACTIVATE:
                    return MA_NOACTIVATE
                if self._old_wndproc:
                    return user32.CallWindowProcW(self._old_wndproc, hWnd, uMsg, wParam, lParam)
                return user32.DefWindowProcW(hWnd, uMsg, wParam, lParam)

            self._wndproc_callback = WNDPROC(_subclass_proc)
            old_proc = GetWindowLongPtr(root_hwnd, GWLP_WNDPROC)
            if old_proc:
                self._old_wndproc = old_proc
                SetWindowLongPtr(root_hwnd, GWLP_WNDPROC, ctypes.cast(self._wndproc_callback, ctypes.c_void_p))
        except Exception:
            pass

    def ensure_target_focus(self):
        """Ensures that the target window (e.g. Google Chrome search bar) retains or regains keyboard focus."""
        if self.last_target_hwnd and user32.IsWindow(self.last_target_hwnd):
            fg = user32.GetForegroundWindow()
            if fg != self.last_target_hwnd:
                try:
                    # Seamless foreground transition using Alt-key tap to bypass Windows foreground restriction
                    user32.keybd_event(VK_MENU, 0, 0, 0)
                    user32.SetForegroundWindow(self.last_target_hwnd)
                    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
                except Exception:
                    pass

    def hide(self):
        if not self.is_visible or self.window is None:
            return
        if self.animating:
            return
        self.is_visible = False

        def destroy_win():
            if self.window is not None:
                try:
                    self.window.destroy()
                except Exception:
                    pass
                self.window = None

        # Smooth fade-out animation
        self._animate_fade(0.95, 0.0, 5, on_complete=destroy_win)

    def toggle(self):
        if self.is_visible and self.window is not None and self.window.winfo_exists():
            self.hide()
        else:
            self.show()

    def _build_ui(self):
        outer = tk.Frame(self.window, bg="#1E2333", bd=1, takefocus=False)
        outer.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        container = tk.Frame(outer, bg="#0E111A", takefocus=False)
        container.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # 1. HEADER BAR
        # -------------------------------------------------------------
        header = tk.Frame(container, bg="#121622", height=24, takefocus=False)
        header.pack(fill=tk.X, side=tk.TOP)
        header.pack_propagate(False)

        title = tk.Label(
            header,
            text="⌨️ COMPACT KEYBOARD • AUTO-SEARCH",
            font=("Segoe UI", 8, "bold"),
            fg="#00E5FF",
            bg="#121622",
            takefocus=False
        )
        title.pack(side=tk.LEFT, padx=10)

        hint = tk.Label(
            header,
            text="Pinch keys to type into search bar",
            font=("Segoe UI", 7),
            fg="#7E88A0",
            bg="#121622",
            takefocus=False
        )
        hint.pack(side=tk.LEFT, padx=4)

        self.close_btn = tk.Label(
            header,
            text="✕ CLOSE",
            font=("Segoe UI", 8, "bold"),
            fg="#FF5252",
            bg="#121622",
            padx=8,
            cursor="hand2",
            takefocus=False
        )
        self.close_btn.pack(side=tk.RIGHT)
        self.close_btn.bind("<Button-1>", lambda e: self.hide())

        # Drag header logic
        def start_drag(event):
            self.window.x = event.x
            self.window.y = event.y

        def on_drag(event):
            deltax = event.x - self.window.x
            deltay = event.y - self.window.y
            self.pos_x = self.window.winfo_x() + deltax
            self.pos_y = self.window.winfo_y() + deltay
            self.window.geometry(f"+{self.pos_x}+{self.pos_y}")

        header.bind("<Button-1>", start_drag)
        header.bind("<B1-Motion>", on_drag)
        title.bind("<Button-1>", start_drag)
        title.bind("<B1-Motion>", on_drag)

        # -------------------------------------------------------------
        # 2. KEYBOARD KEYS GRID
        # -------------------------------------------------------------
        keys_frame = tk.Frame(container, bg="#0E111A", padx=8, pady=6, takefocus=False)
        keys_frame.pack(fill=tk.BOTH, expand=True)

        rows = [
            # Row 1: Numbers
            [("`", "~", 1), ("1", "!", 1), ("2", "@", 1), ("3", "#", 1), ("4", "$", 1),
             ("5", "%", 1), ("6", "^", 1), ("7", "&", 1), ("8", "*", 1), ("9", "(", 1),
             ("0", ")", 1), ("-", "_", 1), ("=", "+", 1), ("⌫ Back", "BACK", 2)],
            
            # Row 2: QWERTY
            [("Tab", "TAB", 1.5), ("q", "Q", 1), ("w", "W", 1), ("e", "E", 1), ("r", "R", 1),
             ("t", "T", 1), ("y", "Y", 1), ("u", "U", 1), ("i", "I", 1), ("o", "O", 1),
             ("p", "P", 1), ("[", "{", 1), ("]", "}", 1), ("\\", "|", 1)],
            
            # Row 3: ASDF
            [("Caps", "CAPS", 1.8), ("a", "A", 1), ("s", "S", 1), ("d", "D", 1), ("f", "F", 1),
             ("g", "G", 1), ("h", "H", 1), ("j", "J", 1), ("k", "K", 1), ("l", "L", 1),
             (";", ":", 1), ("'", "\"", 1), ("↵ Enter", "ENTER", 2.2)],
            
            # Row 4: ZXCV
            [("Shift", "SHIFT", 2.2), ("z", "Z", 1), ("x", "X", 1), ("c", "C", 1), ("v", "V", 1),
             ("b", "B", 1), ("n", "N", 1), ("m", "M", 1), (",", "<", 1), (".", ">", 1),
             ("/", "?", 1), ("Esc", "ESC", 1.5)],
            
            # Row 5: Space & Controls
            [("🌐 Symbols", "SYM", 2), ("Space", "SPACE", 7), ("◀", "LEFT", 1.5), ("▶", "RIGHT", 1.5), ("✕ Hide", "HIDE", 2)]
        ]

        self.key_buttons.clear()

        for row_idx, row_data in enumerate(rows):
            row_frame = tk.Frame(keys_frame, bg="#0E111A", takefocus=False)
            row_frame.pack(fill=tk.X, expand=True, pady=1)

            for key_lower, key_upper, width_weight in row_data:
                btn = self._create_key(row_frame, key_lower, key_upper, width_weight)
                self.key_buttons.append((btn, key_lower, key_upper))

    def _create_key(self, parent: tk.Frame, key_lower: str, key_upper: str, weight: float) -> tk.Label:
        display_text = key_upper if (self.caps_lock or self.shift_active) else key_lower
        
        is_special = key_lower in ["⌫ Back", "Tab", "Caps", "↵ Enter", "Shift", "Esc", "Space", "🌐 Symbols", "✕ Hide", "◀", "▶"]
        bg_col = "#141724" if not is_special else "#1A2033"
        fg_col = "#E0E6ED" if not is_special else "#00E5FF"

        lbl = tk.Label(
            parent,
            text=display_text,
            font=("Segoe UI", 9, "bold" if is_special else "normal"),
            bg=bg_col,
            fg=fg_col,
            padx=2,
            pady=4,
            bd=1,
            relief=tk.SOLID,
            cursor="hand2",
            takefocus=False
        )
        lbl._is_hovered = False
        lbl.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=1)

        def on_enter(e):
            lbl._is_hovered = True
            lbl.configure(bg="#222C44", fg="#00FFC2")

        def on_leave(e):
            lbl._is_hovered = False
            self._reset_key_color(lbl, key_lower)

        def on_click(e):
            self.ensure_target_focus()
            self._handle_key_press(key_lower, key_upper)
            lbl.configure(bg="#00E5FF", fg="#000000")
            self.window.after(80, lambda: self._reset_key_color(lbl, key_lower))

        lbl.bind("<Enter>", on_enter)
        lbl.bind("<Leave>", on_leave)
        lbl.bind("<Button-1>", on_click)

        return lbl

    def _reset_key_color(self, lbl: tk.Label, key_lower: str):
        if not lbl.winfo_exists():
            return
        is_special = key_lower in ["⌫ Back", "Tab", "Caps", "↵ Enter", "Shift", "Esc", "Space", "🌐 Symbols", "✕ Hide", "◀", "▶"]
        bg_col = "#141724" if not is_special else "#1A2033"
        fg_col = "#E0E6ED" if not is_special else "#00E5FF"

        if key_lower == "Caps" and self.caps_lock:
            lbl.configure(bg="#1E3A3A", fg="#00FF88")
        elif key_lower == "Shift" and self.shift_active:
            lbl.configure(bg="#1E3A3A", fg="#00FF88")
        else:
            lbl.configure(bg=bg_col, fg=fg_col)

    def _update_geometry_cache(self):
        """Precomputes and caches relative bounding boxes of all keys in pure Python data structures for 100% thread-safe 0ms hit-testing."""
        if not self.window or not self.window.winfo_exists():
            return
        try:
            self.window.update_idletasks()
            win_rx = self.window.winfo_rootx()
            win_ry = self.window.winfo_rooty()
            if win_rx <= 0:
                win_rx = self.pos_x
            if win_ry <= 0:
                win_ry = self.pos_y
        except Exception:
            win_rx = self.pos_x
            win_ry = self.pos_y

        cached = []
        for lbl, key_lower, key_upper in self.key_buttons:
            if not lbl.winfo_exists():
                continue
            try:
                lx = lbl.winfo_rootx() - win_rx
                ly = lbl.winfo_rooty() - win_ry
                lw = lbl.winfo_width()
                lh = lbl.winfo_height()
                if lw > 0 and lh > 0:
                    cached.append((lbl, key_lower, key_upper, lx, ly, lw, lh))
            except Exception:
                pass

        if hasattr(self, "close_btn") and self.close_btn.winfo_exists():
            try:
                cx = self.close_btn.winfo_rootx() - win_rx
                cy = self.close_btn.winfo_rooty() - win_ry
                cw = self.close_btn.winfo_width()
                ch = self.close_btn.winfo_height()
                self._cached_close_btn = (cx, cy, cw, ch)
            except Exception:
                self._cached_close_btn = None
        else:
            self._cached_close_btn = None

        if cached:
            self._cached_keys = cached

    def highlight_key_at_screen_pos(self, screen_x: int, screen_y: int):
        """Highlights the key under cursor during hand hover (pure Python thread-safe)."""
        if not self.is_visible or not self.window or not self.window.winfo_exists():
            return

        local_x = screen_x - self.pos_x
        local_y = screen_y - self.pos_y

        cached_keys = getattr(self, "_cached_keys", None)
        if not cached_keys:
            return

        hovered_lbl = None
        for lbl, key_lower, key_upper, lx, ly, lw, lh in cached_keys:
            if lx <= local_x <= lx + lw and ly <= local_y <= ly + lh:
                hovered_lbl = lbl
                break

        if hovered_lbl != self._current_hovered_lbl:
            prev_lbl = self._current_hovered_lbl
            self._current_hovered_lbl = hovered_lbl

            def _update_hover(prev=prev_lbl, curr=hovered_lbl):
                try:
                    if prev is not None and prev.winfo_exists():
                        for l, kl, ku, *_ in cached_keys:
                            if l == prev:
                                self._reset_key_color(prev, kl)
                                break
                    if curr is not None and curr.winfo_exists():
                        curr.configure(bg="#1E2C44", fg="#00FFC2")
                except Exception:
                    pass

            self.root.after(0, _update_hover)

    def trigger_key_at_screen_pos(self, screen_x: int, screen_y: int) -> Optional[str]:
        """
        Hit-tests and triggers the key at (screen_x, screen_y) directly from hand pinch.
        Pure Python 0ms cached hit testing guarantees 100% first-try click reliability.
        """
        if not self.is_visible or not self.window or not self.window.winfo_exists():
            return None

        local_x = screen_x - self.pos_x
        local_y = screen_y - self.pos_y
        now = time.time()

        # Check cached close button
        if getattr(self, "_cached_close_btn", None) is not None:
            cx, cy, cw, ch = self._cached_close_btn
            if (cx - 8) <= local_x <= (cx + cw + 8) and (cy - 8) <= local_y <= (cy + ch + 8):
                self.root.after(0, self.hide)
                return "CLOSE"

        cached_keys = getattr(self, "_cached_keys", None)
        if not cached_keys:
            self._update_geometry_cache()
            cached_keys = getattr(self, "_cached_keys", [])

        best_match = None
        min_dist_sq = 999999.0

        for item in cached_keys:
            lbl, key_lower, key_upper, lx, ly, lw, lh = item

            # Direct hit inside key box
            if lx <= local_x <= lx + lw and ly <= local_y <= ly + lh:
                best_match = (lbl, key_lower, key_upper)
                break

            # Generous edge tolerance (within 10px boundary margin)
            if (lx - 10) <= local_x <= (lx + lw + 10) and (ly - 10) <= local_y <= (ly + lh + 10):
                cx = lx + lw / 2.0
                cy = ly + lh / 2.0
                d_sq = (local_x - cx) ** 2 + (local_y - cy) ** 2
                if d_sq < min_dist_sq:
                    min_dist_sq = d_sq
                    best_match = (lbl, key_lower, key_upper)

        if best_match is not None:
            lbl, key_lower, key_upper = best_match

            # Key debounce: prevent accidental double firing within 150ms on the same key
            key_id = key_lower
            if (now - self.last_key_press_time) < 0.15 and self.last_pressed_key == key_id:
                return None

            self.last_key_press_time = now
            self.last_pressed_key = key_id

            # Trigger immediate visual key flash on main UI thread
            def _flash_key(label=lbl, kl=key_lower):
                try:
                    if label.winfo_exists():
                        label.configure(bg="#00E5FF", fg="#000000")
                        self.root.after(90, lambda: self._reset_key_color(label, kl))
                except Exception:
                    pass

            self.root.after(0, _flash_key)

            # Ensure target window focus and dispatch keystroke
            self.ensure_target_focus()
            self._handle_key_press(key_lower, key_upper)

            # Return readable key name
            if key_lower in ["⌫ Back", "↵ Enter", "Space", "Tab", "Esc", "Caps", "Shift", "🌐 Symbols", "✕ Hide", "◀", "▶"]:
                return key_lower.replace("⌫ ", "").replace("↵ ", "").replace("✕ ", "").replace("🌐 ", "")
            return key_upper if (self.caps_lock or self.shift_active) else key_lower

        return None

    def _handle_key_press(self, key_lower: str, key_upper: str):
        if key_lower == "⌫ Back":
            send_virtual_key(VK_BACK)
        elif key_lower == "↵ Enter":
            send_virtual_key(VK_RETURN)
            if config.auto_close_keyboard_on_enter:
                # Smoothly close keyboard after submitting search / input
                if self.window and self.window.winfo_exists():
                    self.window.after(120, self.hide)
        elif key_lower == "Space":
            send_virtual_key(VK_SPACE)
        elif key_lower == "Tab":
            send_virtual_key(VK_TAB)
        elif key_lower == "Esc":
            send_virtual_key(VK_ESCAPE)
            if self.window and self.window.winfo_exists():
                self.window.after(100, self.hide)
        elif key_lower == "◀":
            send_virtual_key(VK_LEFT)
        elif key_lower == "▶":
            send_virtual_key(VK_RIGHT)
        elif key_lower == "✕ Hide":
            self.hide()
        elif key_lower == "Caps":
            self.caps_lock = not self.caps_lock
            self._refresh_key_labels()
        elif key_lower == "Shift":
            self.shift_active = not self.shift_active
            self._refresh_key_labels()
        elif key_lower == "🌐 Symbols":
            self.caps_lock = not self.caps_lock
            self._refresh_key_labels()
        else:
            char_to_send = key_upper if (self.caps_lock or self.shift_active) else key_lower
            send_character_input(char_to_send)
            
            if self.shift_active:
                self.shift_active = False
                self._refresh_key_labels()

    def _refresh_key_labels(self):
        use_upper = (self.caps_lock or self.shift_active)
        for lbl, key_lower, key_upper in self.key_buttons:
            if not lbl.winfo_exists():
                continue
            if key_lower in ["⌫ Back", "Tab", "↵ Enter", "Esc", "Space", "🌐 Symbols", "✕ Hide", "◀", "▶"]:
                continue
            elif key_lower == "Caps":
                lbl.configure(bg="#1E3A3A" if self.caps_lock else "#1A2033", fg="#00FF88" if self.caps_lock else "#00E5FF")
            elif key_lower == "Shift":
                lbl.configure(bg="#1E3A3A" if self.shift_active else "#1A2033", fg="#00FF88" if self.shift_active else "#00E5FF")
            else:
                lbl.configure(text=key_upper if use_upper else key_lower)
