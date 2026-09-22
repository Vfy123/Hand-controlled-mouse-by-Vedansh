import ctypes
from ctypes import wintypes
import tkinter as tk
from tkinter import ttk
import time
from typing import Callable, Optional

from config import config, config_manager
from ui.camera_hud import CameraHUD
from ui.keyboard import VirtualKeyboard

user32 = ctypes.windll.user32

# Win32 Constants for Always-On-Top Tool Window
GWL_EXSTYLE = -20
WS_EX_NOACTIVATE = 0x08000000
WS_EX_TOPMOST = 0x00000008
WS_EX_TOOLWINDOW = 0x00000080
HWND_TOPMOST = -1
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SWP_FRAMECHANGED = 0x0020
GA_ROOT = 2

class FloatingTopBar:
    def __init__(self, root: tk.Tk, tracker, camera_hud: CameraHUD, keyboard: Optional[VirtualKeyboard] = None):
        self.root = root
        self.tracker = tracker
        self.camera_hud = camera_hud
        self.keyboard = keyboard
        
        self.is_expanded = False
        self.animating = False
        
        # Dimensions
        self.collapsed_width = 400
        self.collapsed_height = 46
        self.expanded_width = 450
        self.expanded_height = 515
        
        # State
        self.screen_width = self.root.winfo_screenwidth()
        self.current_width = self.collapsed_width
        self.current_height = self.collapsed_height
        
        # Configure root window as borderless topmost overlay
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.96)
        self.root.configure(bg="#0c0e14")
        
        # Initial positioning: Centered horizontally at the top with slight 10px margin
        self.pos_x = (self.screen_width - self.collapsed_width) // 2
        self.pos_y = 10
        self.root.geometry(f"{self.collapsed_width}x{self.collapsed_height}+{self.pos_x}+{self.pos_y}")
        self.root.update_idletasks()

        # Apply robust Win32 Topmost & ToolWindow styles
        self._apply_topmost_flags()

        # Bind events & dragging
        self._setup_ui()
        self._bind_mouse_events()
        
        # Background periodic updates & topmost watchdog
        self._update_loop()

    def _apply_topmost_flags(self):
        """Forces the top bar to remain a topmost tool window on Windows."""
        try:
            hwnd = self.root.winfo_id()
            root_hwnd = user32.GetAncestor(hwnd, GA_ROOT)
            if not root_hwnd:
                root_hwnd = hwnd
            for h in set([hwnd, root_hwnd]):
                if h:
                    style = user32.GetWindowLongW(h, GWL_EXSTYLE)
                    user32.SetWindowLongW(h, GWL_EXSTYLE, style | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE)
                    user32.SetWindowPos(h, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOMOVE | SWP_NOSIZE | SWP_NOACTIVATE | SWP_FRAMECHANGED)
        except Exception:
            pass

    def _setup_ui(self):
        # Outer Border Container (Creates sleek glowing border effect)
        self.border_frame = tk.Frame(self.root, bg="#1E2333", bd=1)
        self.border_frame.pack(fill=tk.BOTH, expand=True, padx=1, pady=1)

        self.main_container = tk.Frame(self.border_frame, bg="#0E111A")
        self.main_container.pack(fill=tk.BOTH, expand=True)

        # -------------------------------------------------------------
        # 1. COLLAPSED BAR (Always visible at the top)
        # -------------------------------------------------------------
        self.bar_frame = tk.Frame(self.main_container, bg="#0E111A", height=self.collapsed_height, cursor="hand2")
        self.bar_frame.pack(fill=tk.X, side=tk.TOP)
        self.bar_frame.pack_propagate(False)

        # Left: Pulsing Status Dot & Icon
        self.status_dot = tk.Label(self.bar_frame, text="●", font=("Segoe UI", 12, "bold"), fg="#00E5FF", bg="#0E111A")
        self.status_dot.pack(side=tk.LEFT, padx=(12, 6), pady=8)

        # Center Left: Action Text & Subtext
        self.text_container = tk.Frame(self.bar_frame, bg="#0E111A")
        self.text_container.pack(side=tk.LEFT, fill=tk.Y, pady=6)

        self.action_title_label = tk.Label(
            self.text_container,
            text="🎯 Tracking: Moving Cursor",
            font=("Segoe UI", 10, "bold"),
            fg="#FFFFFF",
            bg="#0E111A",
            anchor="w"
        )
        self.action_title_label.pack(anchor="w")

        self.action_detail_label = tk.Label(
            self.text_container,
            text="Zero-Jitter Filter • Ready",
            font=("Segoe UI", 8),
            fg="#7E88A0",
            bg="#0E111A",
            anchor="w"
        )
        self.action_detail_label.pack(anchor="w")

        # Right: FPS Badge & Expand Arrow
        self.right_container = tk.Frame(self.bar_frame, bg="#0E111A")
        self.right_container.pack(side=tk.RIGHT, padx=(6, 12), pady=8)

        self.expand_hint_btn = tk.Label(
            self.right_container,
            text="▾ MENU",
            font=("Segoe UI", 8, "bold"),
            fg="#00E5FF",
            bg="#161B29",
            padx=7,
            pady=3,
            cursor="hand2"
        )
        self.expand_hint_btn.pack(side=tk.RIGHT, padx=4)

        self.fps_badge = tk.Label(
            self.right_container,
            text="60 FPS",
            font=("Segoe UI", 8),
            fg="#5C667E",
            bg="#0E111A"
        )
        self.fps_badge.pack(side=tk.RIGHT, padx=4)

        # Subtle bottom glowing accent strip
        self.accent_strip = tk.Frame(self.bar_frame, bg="#00E5FF", height=2)
        self.accent_strip.pack(side=tk.BOTTOM, fill=tk.X)

        # -------------------------------------------------------------
        # 2. EXPANDED SETTINGS MENU (Hidden when collapsed)
        # -------------------------------------------------------------
        self.menu_frame = tk.Frame(self.main_container, bg="#0E111A")
        
        # Menu Header / Separator
        sep = tk.Frame(self.menu_frame, bg="#1E2333", height=1)
        sep.pack(fill=tk.X, pady=(0, 10))

        menu_header = tk.Frame(self.menu_frame, bg="#0E111A")
        menu_header.pack(fill=tk.X, padx=16, pady=(0, 10))

        lbl_settings = tk.Label(menu_header, text="⚙️ SENSITIVITY & GESTURE CONTROLS", font=("Segoe UI", 9, "bold"), fg="#8F9BB3", bg="#0E111A")
        lbl_settings.pack(side=tk.LEFT)

        close_btn = tk.Label(menu_header, text="▲ COLLAPSE", font=("Segoe UI", 8, "bold"), fg="#00E5FF", bg="#161B29", padx=8, pady=2, cursor="hand2")
        close_btn.pack(side=tk.RIGHT)
        close_btn.bind("<Button-1>", lambda e: self.toggle_menu())

        # Sliders Area
        sliders_box = tk.Frame(self.menu_frame, bg="#121622", padx=12, pady=10)
        sliders_box.pack(fill=tk.X, padx=14, pady=4)

        # 1. Sensitivity Slider
        self.sens_val_lbl = tk.Label(sliders_box, text=f"{config.sensitivity_x:.1f}x", font=("Segoe UI", 9, "bold"), fg="#00E5FF", bg="#121622")
        self._create_slider_row(
            parent=sliders_box,
            title="🎯 Cursor Speed / Sensitivity",
            subtitle="Controls how quickly hand movements translate to screen travel",
            from_=0.5,
            to=3.5,
            initial=config.sensitivity_x,
            val_lbl=self.sens_val_lbl,
            on_change=self._on_sens_change
        )

        # 2. Smoothing Slider
        self.smooth_val_lbl = tk.Label(sliders_box, text=f"{int(config.smoothing_factor * 100)}%", font=("Segoe UI", 9, "bold"), fg="#00E5FF", bg="#121622")
        self._create_slider_row(
            parent=sliders_box,
            title="✨ Jitter Smoothing & Anti-Tremor",
            subtitle="Higher = Rock-solid stillness | Lower = Ultra-snappy response",
            from_=0.10,
            to=0.98,
            initial=config.smoothing_factor,
            val_lbl=self.smooth_val_lbl,
            on_change=self._on_smoothing_change
        )

        # 3. Pinch Sensitivity (Click threshold)
        self.pinch_val_lbl = tk.Label(sliders_box, text=f"{int(config.pinch_threshold_ratio * 100)}%", font=("Segoe UI", 9, "bold"), fg="#00E5FF", bg="#121622")
        self._create_slider_row(
            parent=sliders_box,
            title="🤏 Pinch Sensitivity (Click Contact)",
            subtitle="Thumb-to-index distance ratio to register pinch (Default: 15%)",
            from_=0.08,
            to=0.28,
            initial=config.pinch_threshold_ratio,
            val_lbl=self.pinch_val_lbl,
            on_change=self._on_pinch_change
        )

        # 4. Drag Hold Delay Slider
        self.drag_val_lbl = tk.Label(sliders_box, text=f"{config.drag_hold_delay_ms}ms", font=("Segoe UI", 9, "bold"), fg="#00E5FF", bg="#121622")
        self._create_slider_row(
            parent=sliders_box,
            title="✊ Drag & Drop Engage Hold Delay",
            subtitle="Hold pinch duration required before engaging drag mode",
            from_=200,
            to=700,
            initial=config.drag_hold_delay_ms,
            val_lbl=self.drag_val_lbl,
            on_change=self._on_drag_delay_change
        )

        # 5. Scroll Speed Slider
        self.scroll_val_lbl = tk.Label(sliders_box, text=f"{config.scroll_speed}", font=("Segoe UI", 9, "bold"), fg="#00E5FF", bg="#121622")
        self._create_slider_row(
            parent=sliders_box,
            title="📜 Ring-Thumb Scroll Speed",
            subtitle="Sensitivity when gliding ring finger & thumb up/down",
            from_=10,
            to=80,
            initial=config.scroll_speed,
            val_lbl=self.scroll_val_lbl,
            on_change=self._on_scroll_change
        )

        # Action Buttons Row 1
        btn_row = tk.Frame(self.menu_frame, bg="#0E111A")
        btn_row.pack(fill=tk.X, padx=14, pady=(6, 3))

        # Camera PIP Toggle Button
        self.cam_hud_btn = tk.Button(
            btn_row,
            text="📷 Skeleton PIP [OFF]",
            font=("Segoe UI", 8, "bold"),
            fg="#FFFFFF",
            bg="#1E2333",
            activebackground="#2A3147",
            activeforeground="#00E5FF",
            relief=tk.FLAT,
            padx=6,
            pady=4,
            cursor="hand2",
            command=self._toggle_camera_pip
        )
        self.cam_hud_btn.pack(side=tk.LEFT, padx=(0, 3), expand=True, fill=tk.X)

        # Keyboard Manual Toggle Button
        self.keyboard_btn = tk.Button(
            btn_row,
            text="⌨️ Keyboard",
            font=("Segoe UI", 8, "bold"),
            fg="#00E5FF",
            bg="#16222E",
            activebackground="#1E2F3F",
            relief=tk.FLAT,
            padx=6,
            pady=4,
            cursor="hand2",
            command=self._toggle_keyboard
        )
        self.keyboard_btn.pack(side=tk.LEFT, padx=3, expand=True, fill=tk.X)

        # Tracking Pause/Resume Toggle
        self.track_toggle_btn = tk.Button(
            btn_row,
            text="🟢 Tracking [ON]",
            font=("Segoe UI", 8, "bold"),
            fg="#00E5FF",
            bg="#16222E",
            activebackground="#1E2F3F",
            relief=tk.FLAT,
            padx=6,
            pady=4,
            cursor="hand2",
            command=self._toggle_tracking
        )
        self.track_toggle_btn.pack(side=tk.LEFT, padx=(3, 0), expand=True, fill=tk.X)

        # Action Buttons Row 2 (Toggles & Reset)
        btn_row_2 = tk.Frame(self.menu_frame, bg="#0E111A")
        btn_row_2.pack(fill=tk.X, padx=14, pady=(3, 6))

        # Auto-Keyboard Toggle
        self.auto_osk_btn = tk.Button(
            btn_row_2,
            text="⌨️ Auto-OSK [ON]" if config.auto_keyboard_enabled else "⌨️ Auto-OSK [OFF]",
            font=("Segoe UI", 8, "bold"),
            fg="#00FF88" if config.auto_keyboard_enabled else "#8F96A3",
            bg="#122A1E" if config.auto_keyboard_enabled else "#141724",
            activebackground="#1B3A2B",
            relief=tk.FLAT,
            padx=5,
            pady=3,
            cursor="hand2",
            command=self._toggle_auto_keyboard
        )
        self.auto_osk_btn.pack(side=tk.LEFT, padx=(0, 2), expand=True, fill=tk.X)

        # Ballistics Toggle
        self.ballistic_btn = tk.Button(
            btn_row_2,
            text="⚡ Ballistics [ON]" if config.ballistic_acceleration else "⚡ Ballistics [OFF]",
            font=("Segoe UI", 8, "bold"),
            fg="#00E5FF" if config.ballistic_acceleration else "#8F96A3",
            bg="#16222E" if config.ballistic_acceleration else "#141724",
            activebackground="#1E2F3F",
            relief=tk.FLAT,
            padx=5,
            pady=3,
            cursor="hand2",
            command=self._toggle_ballistics
        )
        self.ballistic_btn.pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)

        # Click-Lock Toggle
        self.pre_click_btn = tk.Button(
            btn_row_2,
            text="🔒 Click-Lock [ON]" if config.pre_click_freeze else "🔒 Click-Lock [OFF]",
            font=("Segoe UI", 8, "bold"),
            fg="#00FF88" if config.pre_click_freeze else "#8F96A3",
            bg="#122A1E" if config.pre_click_freeze else "#141724",
            activebackground="#1B3A2B",
            relief=tk.FLAT,
            padx=5,
            pady=3,
            cursor="hand2",
            command=self._toggle_pre_click
        )
        # Window Gestures Toggle
        self.win_gestures_btn = tk.Button(
            btn_row_2,
            text="🗖 Win Gestures [ON]" if config.window_gestures_enabled else "🗖 Win Gestures [OFF]",
            font=("Segoe UI", 8, "bold"),
            fg="#00FF88" if config.window_gestures_enabled else "#8F96A3",
            bg="#122A1E" if config.window_gestures_enabled else "#141724",
            activebackground="#1B3A2B",
            relief=tk.FLAT,
            padx=5,
            pady=3,
            cursor="hand2",
            command=self._toggle_window_gestures
        )
        self.win_gestures_btn.pack(side=tk.LEFT, padx=2, expand=True, fill=tk.X)

        # Reset Defaults Button
        reset_btn = tk.Button(
            btn_row_2,
            text="↺ Reset",
            font=("Segoe UI", 8),
            fg="#8F96A3",
            bg="#141724",
            activebackground="#202438",
            relief=tk.FLAT,
            padx=5,
            pady=3,
            cursor="hand2",
            command=self._reset_defaults
        )
        reset_btn.pack(side=tk.LEFT, padx=(2, 0))

        # Bottom Quick Gesture Guide Card
        guide_box = tk.Frame(self.menu_frame, bg="#10131E", padx=10, pady=8, bd=1, relief=tk.SOLID)
        guide_box.pack(fill=tk.X, padx=14, pady=(4, 10))

        guide_title = tk.Label(guide_box, text="🖐️ GESTURE & MULTI-HAND CHEATSHEET", font=("Segoe UI", 8, "bold"), fg="#00E5FF", bg="#10131E")
        guide_title.pack(anchor="w", pady=(0, 2))

        guide_text = (
            "• 👉 Point Index: Move cursor smoothly | 🤏 Pinch Thumb+Index: Left Click\n"
            "• 🗖 Open Palm Swipe UP: Maximize / Restore Active Window\n"
            "• 🗕 Open Palm Swipe DOWN: Minimize Active Window to Taskbar\n"
            "• ⌨️ Click Search Bar: On-Screen Keyboard pops up for fast typing\n"
            "• ✌️ 2-Finger Pinch / Active Middle: Right Click | 📜 Ring+Thumb Glide: Scroll\n"
            "• ✋ Hand Handoff: Lower hand to hand off control | ⏸️ Fist: Pause cursor"
        )
        guide_lbl = tk.Label(
            guide_box,
            text=guide_text,
            font=("Segoe UI", 7),
            fg="#8E99B2",
            bg="#10131E",
            justify=tk.LEFT
        )
        guide_lbl.pack(anchor="w")

    def _create_slider_row(self, parent, title, subtitle, from_, to, initial, val_lbl, on_change):
        row = tk.Frame(parent, bg="#121622")
        row.pack(fill=tk.X, pady=4)

        top_line = tk.Frame(row, bg="#121622")
        top_line.pack(fill=tk.X)

        lbl = tk.Label(top_line, text=title, font=("Segoe UI", 8, "bold"), fg="#FFFFFF", bg="#121622")
        lbl.pack(side=tk.LEFT)
        val_lbl.master = top_line
        val_lbl.pack(side=tk.RIGHT)

        slider = ttk.Scale(row, from_=from_, to=to, value=initial, command=on_change)
        slider.pack(fill=tk.X, pady=(2, 1))

    def _bind_mouse_events(self):
        # Double clicking anywhere on the bar expands/collapses it
        widgets_to_bind = [
            self.bar_frame,
            self.status_dot,
            self.action_title_label,
            self.action_detail_label,
            self.text_container,
            self.right_container,
            self.expand_hint_btn,
            self.fps_badge,
            self.accent_strip
        ]

        # Enable dragging to reposition the bar anywhere on screen
        self._drag_data = {"x": 0, "y": 0, "dragging": False}

        def on_drag_start(event):
            self._drag_data["x"] = event.x_root - self.root.winfo_x()
            self._drag_data["y"] = event.y_root - self.root.winfo_y()
            self._drag_data["dragging"] = True

        def on_drag_motion(event):
            if self._drag_data["dragging"]:
                new_x = event.x_root - self._drag_data["x"]
                new_y = event.y_root - self._drag_data["y"]
                # Clamp to screen
                new_x = max(0, min(new_x, self.screen_width - self.current_width))
                new_y = max(0, min(new_y, self.root.winfo_screenheight() - self.current_height))
                self.pos_x = new_x
                self.pos_y = new_y
                self.root.geometry(f"+{self.pos_x}+{self.pos_y}")

        def on_drag_stop(event):
            self._drag_data["dragging"] = False

        for w in widgets_to_bind:
            w.bind("<Double-Button-1>", lambda e: self.toggle_menu())
            if w == self.expand_hint_btn:
                w.bind("<Button-1>", lambda e: self.toggle_menu())
            else:
                w.bind("<Button-1>", on_drag_start)
                w.bind("<B1-Motion>", on_drag_motion)
                w.bind("<ButtonRelease-1>", on_drag_stop)

    def toggle_menu(self):
        if self.animating:
            return
        self.is_expanded = not self.is_expanded
        self._animate_menu_transition()

    def _animate_menu_transition(self):
        self.animating = True
        target_w = self.expanded_width if self.is_expanded else self.collapsed_width
        target_h = self.expanded_height if self.is_expanded else self.collapsed_height
        
        if self.is_expanded:
            self.menu_frame.pack(fill=tk.BOTH, expand=True, side=tk.TOP)
            self.expand_hint_btn.configure(text="▲ CLOSE", fg="#FF5252")
        else:
            self.menu_frame.pack_forget()
            self.expand_hint_btn.configure(text="▾ MENU", fg="#00E5FF")

        # Smooth resize steps
        steps = 8
        curr_w = self.current_width
        curr_h = self.current_height
        
        step_w = (target_w - curr_w) / steps
        step_h = (target_h - curr_h) / steps

        def step(i):
            if i <= steps:
                w = int(curr_w + step_w * i)
                h = int(curr_h + step_h * i)
                x = (self.screen_width - w) // 2
                self.root.geometry(f"{w}x{h}+{x}+{self.pos_y}")
                self.root.lift()
                self._apply_topmost_flags()
                self.root.after(12, lambda: step(i + 1))
            else:
                self.current_width = target_w
                self.current_height = target_h
                x = (self.screen_width - target_w) // 2
                self.root.geometry(f"{target_w}x{target_h}+{x}+{self.pos_y}")
                self.root.lift()
                self._apply_topmost_flags()
                self.animating = False

        step(1)

    def _on_sens_change(self, val):
        v = float(val)
        config_manager.update("sensitivity_x", round(v, 2))
        config_manager.update("sensitivity_y", round(v, 2))
        self.sens_val_lbl.configure(text=f"{v:.1f}x")

    def _on_smoothing_change(self, val):
        v = float(val)
        config_manager.update("smoothing_factor", round(v, 2))
        self.smooth_val_lbl.configure(text=f"{int(v * 100)}%")

    def _on_pinch_change(self, val):
        v = float(val)
        config_manager.update("pinch_threshold_ratio", round(v, 2))
        self.pinch_val_lbl.configure(text=f"{int(v * 100)}%")

    def _on_drag_delay_change(self, val):
        v = int(float(val))
        config_manager.update("drag_hold_delay_ms", v)
        self.drag_val_lbl.configure(text=f"{v}ms")

    def _on_scroll_change(self, val):
        v = int(float(val))
        config_manager.update("scroll_speed", v)
        self.scroll_val_lbl.configure(text=f"{v}")

    def _toggle_camera_pip(self):
        self.camera_hud.toggle()
        if self.camera_hud.window is not None:
            self.cam_hud_btn.configure(text="📷 Skeleton PIP [ON]", fg="#00E5FF", bg="#16293A")
        else:
            self.cam_hud_btn.configure(text="📷 Skeleton PIP [OFF]", fg="#FFFFFF", bg="#1E2333")

    def _toggle_keyboard(self):
        if self.keyboard:
            self.keyboard.toggle()

    def _toggle_auto_keyboard(self):
        config.auto_keyboard_enabled = not config.auto_keyboard_enabled
        config_manager.update("auto_keyboard_enabled", config.auto_keyboard_enabled)
        if config.auto_keyboard_enabled:
            self.auto_osk_btn.configure(text="⌨️ Auto-OSK [ON]", fg="#00FF88", bg="#122A1E")
        else:
            self.auto_osk_btn.configure(text="⌨️ Auto-OSK [OFF]", fg="#8F96A3", bg="#141724")

    def _toggle_tracking(self):
        config.tracking_enabled = not config.tracking_enabled
        config_manager.update("tracking_enabled", config.tracking_enabled)
        if config.tracking_enabled:
            self.track_toggle_btn.configure(text="🟢 Tracking [ON]", fg="#00E5FF", bg="#16222E")
        else:
            self.track_toggle_btn.configure(text="🔴 Tracking [PAUSED]", fg="#FF5252", bg="#2D181D")

    def _toggle_ballistics(self):
        config.ballistic_acceleration = not config.ballistic_acceleration
        config_manager.update("ballistic_acceleration", config.ballistic_acceleration)
        if config.ballistic_acceleration:
            self.ballistic_btn.configure(text="⚡ Ballistics [ON]", fg="#00E5FF", bg="#16222E")
        else:
            self.ballistic_btn.configure(text="⚡ Ballistics [OFF]", fg="#8F96A3", bg="#141724")

    def _toggle_window_gestures(self):
        config.window_gestures_enabled = not config.window_gestures_enabled
        config_manager.update("window_gestures_enabled", config.window_gestures_enabled)
        if config.window_gestures_enabled:
            self.win_gestures_btn.configure(text="🗖 Win Gestures [ON]", fg="#00FF88", bg="#122A1E")
        else:
            self.win_gestures_btn.configure(text="🗖 Win Gestures [OFF]", fg="#8F96A3", bg="#141724")

    def _toggle_pre_click(self):
        config.pre_click_freeze = not config.pre_click_freeze
        config_manager.update("pre_click_freeze", config.pre_click_freeze)
        if config.pre_click_freeze:
            self.pre_click_btn.configure(text="🔒 Click-Lock [ON]", fg="#00FF88", bg="#122A1E")
        else:
            self.pre_click_btn.configure(text="🔒 Click-Lock [OFF]", fg="#8F96A3", bg="#141724")

    def _reset_defaults(self):
        config_manager.update("sensitivity_x", 1.8)
        config_manager.update("sensitivity_y", 1.8)
        config_manager.update("smoothing_factor", 0.80)
        config_manager.update("pinch_threshold_ratio", 0.15)
        config_manager.update("drag_hold_delay_ms", 380)
        config_manager.update("scroll_speed", 35)
        config_manager.update("scroll_invert", False)
        config_manager.update("ballistic_acceleration", True)
        config_manager.update("pre_click_freeze", True)
        config_manager.update("auto_keyboard_enabled", True)
        config_manager.update("window_gestures_enabled", True)
        self.sens_val_lbl.configure(text="1.8x")
        self.smooth_val_lbl.configure(text="80%")
        self.pinch_val_lbl.configure(text="15%")
        self.drag_val_lbl.configure(text="380ms")
        self.scroll_val_lbl.configure(text="35")
        self.auto_osk_btn.configure(text="⌨️ Auto-OSK [ON]", fg="#00FF88", bg="#122A1E")
        self.ballistic_btn.configure(text="⚡ Ballistics [ON]", fg="#00E5FF", bg="#16222E")
        self.pre_click_btn.configure(text="🔒 Click-Lock [ON]", fg="#00FF88", bg="#122A1E")
        self.win_gestures_btn.configure(text="🗖 Win Gestures [ON]", fg="#00FF88", bg="#122A1E")

    def update_action_text(self, action: str, detail: str):
        # Update labels safely from vision thread
        def _update():
            self.action_title_label.configure(text=action)
            self.action_detail_label.configure(text=detail)
            
            # Dynamic status dot & accent strip coloring
            if "Maximize" in action:
                self.status_dot.configure(text="🗖", fg="#00FF88")
                self.accent_strip.configure(bg="#00FF88")
            elif "Minimize" in action:
                self.status_dot.configure(text="🗕", fg="#FFB300")
                self.accent_strip.configure(bg="#FFB300")
            elif "Click" in action or "Pinched" in action:
                self.status_dot.configure(text="●", fg="#00FF88")
                self.accent_strip.configure(bg="#00FF88")
            elif "Double" in action:
                self.status_dot.configure(text="⚡", fg="#FFE600")
                self.accent_strip.configure(bg="#FFE600")
            elif "Right" in action:
                self.status_dot.configure(text="●", fg="#B388FF")
                self.accent_strip.configure(bg="#B388FF")
            elif "Drag" in action:
                self.status_dot.configure(text="●", fg="#FF9100")
                self.accent_strip.configure(bg="#FF9100")
            elif "Scroll" in action:
                self.status_dot.configure(text="●", fg="#00E5FF")
                self.accent_strip.configure(bg="#00E5FF")
            elif "Typed" in action or "Keyboard" in action:
                self.status_dot.configure(text="⌨️", fg="#00E5FF")
                self.accent_strip.configure(bg="#00E5FF")
            elif "Precision" in action:
                self.status_dot.configure(text="🎯", fg="#00E5FF")
                self.accent_strip.configure(bg="#00E5FF")
            elif "Travel" in action:
                self.status_dot.configure(text="⚡", fg="#7C4DFF")
                self.accent_strip.configure(bg="#7C4DFF")
            elif "Lock" in action:
                self.status_dot.configure(text="🔒", fg="#00FFC2")
                self.accent_strip.configure(bg="#00FFC2")
            elif "Rest" in action or "Paused" in action:
                self.status_dot.configure(text="●", fg="#FF5252")
                self.accent_strip.configure(bg="#FF5252")
            elif "Palm" in action:
                self.status_dot.configure(text="🖐️", fg="#00E5FF")
                self.accent_strip.configure(bg="#00E5FF")
            else:
                self.status_dot.configure(text="●", fg="#00E5FF")
                self.accent_strip.configure(bg="#00E5FF")

        self.root.after(0, _update)

    def _update_loop(self):
        # Update FPS display
        fps_text = f"{int(self.tracker.fps)} FPS" if self.tracker.fps > 0 else "-- FPS"
        self.fps_badge.configure(text=fps_text)
        
        # Periodic Topmost & Visibility Watchdog (Ensures top bar never disappears)
        try:
            if self.root.state() == "iconic":
                self.root.deiconify()
            self.root.lift()
            self._apply_topmost_flags()
        except Exception:
            pass

        self.root.after(400, self._update_loop)
