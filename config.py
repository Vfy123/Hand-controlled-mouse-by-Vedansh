import json
import os
from dataclasses import dataclass, asdict
from typing import Any, Dict

CONFIG_FILE = "config.json"

@dataclass
class AppConfig:
    # Cursor Movement & Sensitivity
    sensitivity_x: float = 1.8
    sensitivity_y: float = 1.8
    smoothing_factor: float = 0.80  # 0.10 (snappy) to 0.98 (heavy buttery smoothing)
    deadzone_margin: float = 0.15   # Margin from camera edges to map full screen
    stillness_deadband_norm: float = 0.0018  # Normalized deadband to kill micro-tremor completely
    landmark_smoothing: float = 0.50         # Stage-1 landmark temporal stabilization
    
    # 1-Euro Filter & Predictive Human Intent
    one_euro_d_cutoff: float = 1.0      # Derivative cutoff frequency (Hz)
    ballistic_acceleration: bool = True # Non-linear human motor velocity curve
    pre_click_freeze: bool = True       # Intention prediction: lock cursor position during pinch
    click_lock_breakout_dist_px: float = 55.0  # Intentional drag breakout distance in screen pixels
    click_lock_cooldown_ms: int = 120   # Post-click stabilization cooldown in milliseconds
    
    # Gesture Thresholds (Adaptive 3D Palm Scale & Anatomical Ratios)
    pinch_threshold_ratio: float = 0.15  # True physical pinch contact relative to palm scale
    pinch_click_threshold: float = 0.028 # Fallback distance
    pinch_hysteresis_ratio: float = 1.28 # Multiplier to cleanly release pinch
    right_click_threshold_ratio: float = 0.17 # Relative to palm scale for middle finger / 2-finger pinch
    right_click_threshold: float = 0.032 # Fallback distance
    right_click_mode: str = "both"       # "two_finger_pinch", "middle_pinch", or "both"
    double_click_window_ms: int = 380    # Max time between pinches for double click
    drag_hold_delay_ms: int = 380        # Time holding pinch to engage drag (prevents accidental drag on click)
    drag_breakout_dist_norm: float = 0.035 # Movement distance while pinched to immediately engage drag
    scroll_threshold: float = 0.005      # Vertical movement delta for scrolling
    scroll_speed: int = 35               # Scroll sensitivity multiplier
    scroll_smoothing: float = 0.65       # Momentum smoothing for scrolling
    scroll_invert: bool = False          # Hand up scrolls up (natural)
    auto_close_keyboard_on_enter: bool = True # Automatically close keyboard after typing Enter
    
    # Window Management Gestures (Minimize / Maximize)
    window_gestures_enabled: bool = True # Open Palm Swipe Up (Maximize) / Swipe Down (Minimize)
    palm_swipe_speed_threshold: float = 0.35 # Normalized velocity threshold for palm swipe
    window_gesture_cooldown_sec: float = 1.0 # Cooldown to prevent multi-triggering
    
    # Feature Flags & Tools
    tracking_enabled: bool = True
    show_camera_hud: bool = False
    auto_keyboard_enabled: bool = True  # Automatically popup on-screen keyboard when search/input is focused
    keyboard_visible: bool = False
    camera_index: int = 0
    camera_width: int = 640
    camera_height: int = 480
    fps_limit: int = 60
    
    # UI Theme & Positioning
    theme: str = "dark"
    top_bar_width_collapsed: int = 400
    top_bar_width_expanded: int = 450
    top_bar_height_collapsed: int = 46
    top_bar_height_expanded: int = 540
    accent_color: str = "#00E5FF" # Vibrant Cyan Neon
    secondary_accent: str = "#7C4DFF" # Deep Violet Neon
    bg_dark: str = "#0E111A"
    card_bg: str = "#121622"

class ConfigManager:
    def __init__(self, filepath: str = CONFIG_FILE):
        self.filepath = filepath
        self.config = self.load()

    def load(self) -> AppConfig:
        if os.path.exists(self.filepath):
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    valid_keys = {k: v for k, v in data.items() if hasattr(AppConfig, k)}
                    return AppConfig(**valid_keys)
            except Exception as e:
                print(f"[Config] Error loading config, using defaults: {e}")
        return AppConfig()

    def save(self):
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(asdict(self.config), f, indent=4)
        except Exception as e:
            print(f"[Config] Error saving config: {e}")

    def update(self, key: str, value: Any):
        if hasattr(self.config, key):
            setattr(self.config, key, value)
            self.save()

# Global config instance
config_manager = ConfigManager()
config = config_manager.config
