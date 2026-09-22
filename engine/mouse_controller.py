import ctypes
import time
from typing import Tuple

# Windows Constants for mouse events
MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
MOUSEEVENTF_RIGHTDOWN = 0x0008
MOUSEEVENTF_RIGHTUP = 0x0010
MOUSEEVENTF_MIDDLEDOWN = 0x0020
MOUSEEVENTF_MIDDLEUP = 0x0040
MOUSEEVENTF_WHEEL = 0x0800
MOUSEEVENTF_ABSOLUTE = 0x8000

# Screen Metrics
SM_CXSCREEN = 0
SM_CYSCREEN = 1

user32 = ctypes.windll.user32

class MouseController:
    def __init__(self):
        # Prevent Windows DPI scaling distortion for precision coordinates
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2) # Per-monitor DPI aware
        except Exception:
            try:
                user32.SetProcessDPIAware()
            except Exception:
                pass
        
        self.screen_width = user32.GetSystemMetrics(SM_CXSCREEN)
        self.screen_height = user32.GetSystemMetrics(SM_CYSCREEN)
        self.is_dragging = False
        self.last_x = self.screen_width // 2
        self.last_y = self.screen_height // 2

    def refresh_screen_size(self):
        self.screen_width = user32.GetSystemMetrics(SM_CXSCREEN)
        self.screen_height = user32.GetSystemMetrics(SM_CYSCREEN)

    def move_to(self, x: int, y: int):
        """Move cursor directly to target screen coordinates (clamped to screen boundaries)."""
        x_clamped = max(0, min(int(x), self.screen_width - 1))
        y_clamped = max(0, min(int(y), self.screen_height - 1))
        user32.SetCursorPos(x_clamped, y_clamped)
        self.last_x = x_clamped
        self.last_y = y_clamped

    def get_position(self) -> Tuple[int, int]:
        class POINT(ctypes.Structure):
            _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
        return (pt.x, pt.y)

    def left_down(self):
        user32.mouse_event(MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)

    def left_up(self):
        user32.mouse_event(MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)

    def right_down(self):
        user32.mouse_event(MOUSEEVENTF_RIGHTDOWN, 0, 0, 0, 0)

    def right_up(self):
        user32.mouse_event(MOUSEEVENTF_RIGHTUP, 0, 0, 0, 0)

    def left_click(self):
        self.left_down()
        time.sleep(0.02)
        self.left_up()

    def double_click(self):
        self.left_click()
        time.sleep(0.05)
        self.left_click()

    def right_click(self):
        self.right_down()
        time.sleep(0.02)
        self.right_up()

    def start_drag(self):
        if not self.is_dragging:
            self.left_down()
            self.is_dragging = True

    def stop_drag(self):
        if self.is_dragging:
            self.left_up()
            self.is_dragging = False

    def scroll(self, steps: int):
        """Scroll vertically. Positive = scroll up, Negative = scroll down."""
        # Standard mouse wheel delta is 120 per click
        wheel_delta = steps * 120
        user32.mouse_event(MOUSEEVENTF_WHEEL, 0, 0, wheel_delta, 0)

    def release_all(self):
        """Safety reset of all pressed buttons."""
        if self.is_dragging:
            self.stop_drag()
        self.left_up()
        self.right_up()

    def get_foreground_window(self) -> int:
        """Returns the handle of the current active foreground window."""
        return user32.GetForegroundWindow()

    def get_foreground_window_title(self) -> str:
        """Returns the title text of the current active window."""
        hwnd = self.get_foreground_window()
        if not hwnd:
            return ""
        buf = ctypes.create_unicode_buffer(512)
        user32.GetWindowTextW(hwnd, buf, 512)
        return buf.value

    def maximize_active_window(self) -> bool:
        """
        Maximizes the active foreground window.
        If already maximized, toggles / restores it.
        """
        SW_MAXIMIZE = 3
        SW_RESTORE = 9
        SW_SHOWMAXIMIZED = 3
        
        hwnd = self.get_foreground_window()
        if not hwnd or not user32.IsWindow(hwnd):
            return False

        # Ignore desktop or shell tray window
        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        cname = class_buf.value.lower()
        if cname in ["progman", "workerw", "shell_traywnd"]:
            return False

        # Check window placement to see if already maximized
        class WINDOWPLACEMENT(ctypes.Structure):
            _fields_ = [
                ("length", ctypes.c_uint),
                ("flags", ctypes.c_uint),
                ("showCmd", ctypes.c_uint),
                ("ptMinPosition", ctypes.c_long * 2),
                ("ptMaxPosition", ctypes.c_long * 2),
                ("rcNormalPosition", ctypes.c_long * 4)
            ]

        wp = WINDOWPLACEMENT()
        wp.length = ctypes.sizeof(WINDOWPLACEMENT)
        if user32.GetWindowPlacement(hwnd, ctypes.byref(wp)):
            if wp.showCmd == SW_SHOWMAXIMIZED:
                # Restore if already maximized
                user32.ShowWindowAsync(hwnd, SW_RESTORE)
                return True
        
        user32.ShowWindowAsync(hwnd, SW_MAXIMIZE)
        return True

    def minimize_active_window(self) -> bool:
        """Minimizes the active foreground window to the taskbar."""
        SW_MINIMIZE = 6
        hwnd = self.get_foreground_window()
        if not hwnd or not user32.IsWindow(hwnd):
            return False

        class_buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buf, 256)
        cname = class_buf.value.lower()
        if cname in ["progman", "workerw", "shell_traywnd"]:
            return False

        user32.ShowWindowAsync(hwnd, SW_MINIMIZE)
        return True
