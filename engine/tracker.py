import cv2
import math
import os
import threading
import time
import urllib.request
from typing import Callable, Optional, Tuple, Dict, Any, List

import mediapipe as mp
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import numpy as np

from config import config
from engine.mouse_controller import MouseController

MODEL_URL = "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/latest/hand_landmarker.task"
MODEL_PATH = "hand_landmarker.task"

def ensure_model_file():
    if not os.path.exists(MODEL_PATH) or os.path.getsize(MODEL_PATH) < 1000000:
        print("[Tracker] Downloading Hand Landmarker task model...")
        urllib.request.urlretrieve(MODEL_URL, MODEL_PATH)
        print("[Tracker] Model downloaded successfully.")

class LowPassFilter:
    """1st-order IIR Exponential Low-Pass Filter with initialization guard."""
    def __init__(self, alpha: float = 0.0, init_val: float = 0.0):
        self.val = init_val
        self.has_init = False
        self.alpha = alpha

    def filter(self, val: float, alpha: Optional[float] = None) -> float:
        if alpha is not None:
            self.alpha = alpha
        if not self.has_init:
            self.val = val
            self.has_init = True
            return val
        self.val = self.alpha * val + (1.0 - self.alpha) * self.val
        return self.val

    def reset(self):
        self.has_init = False
        self.val = 0.0


class LandmarkSmoother:
    """
    Stage-1 Temporal Filter directly on MediaPipe 3D Landmark coordinates.
    Dampens high-frequency subpixel sensor noise at the vision source.
    """
    def __init__(self, alpha: float = 0.50):
        self.alpha = alpha
        self.prev_landmarks: Optional[List[Tuple[float, float, float]]] = None

    def smooth(self, landmarks) -> List[Any]:
        if landmarks is None or len(landmarks) == 0:
            self.prev_landmarks = None
            return landmarks

        curr_raw = [(lm.x, lm.y, lm.z) for lm in landmarks]
        if self.prev_landmarks is None or len(self.prev_landmarks) != len(curr_raw):
            self.prev_landmarks = curr_raw
            return landmarks

        # Low-pass filter each landmark
        smoothed = []
        alpha = max(0.20, min(0.95, config.landmark_smoothing))
        for i in range(len(curr_raw)):
            cx, cy, cz = curr_raw[i]
            px, py, pz = self.prev_landmarks[i]
            sx = alpha * cx + (1.0 - alpha) * px
            sy = alpha * cy + (1.0 - alpha) * py
            sz = alpha * cz + (1.0 - alpha) * pz
            smoothed.append((sx, sy, sz))

        self.prev_landmarks = smoothed

        class SmoothLandmark:
            __slots__ = ("x", "y", "z")
            def __init__(self, x, y, z):
                self.x = x
                self.y = y
                self.z = z

        return [SmoothLandmark(s[0], s[1], s[2]) for s in smoothed]

    def reset(self):
        self.prev_landmarks = None


class HandPriorityManager:
    """
    Guarantees Single-Hand Exclusive Priority.
    When a hand is raised and active, it locks onto that hand's spatial position.
    Secondary hands entering the view or being raised with the other hand are 100% ignored.
    When the primary hand is lowered or drops out of view, it smoothly promotes
    any active gesturing hand to become the new primary hand.
    """
    def __init__(self):
        self.locked_wrist_pos: Optional[Tuple[float, float]] = None
        self.last_seen_time: float = 0.0
        self.lock_hold_duration_sec: float = 0.40

    def select_active_hand(self, raw_hands_list: List[Any], tracker_ref) -> Optional[Any]:
        if not raw_hands_list:
            if (time.time() - self.last_seen_time) > self.lock_hold_duration_sec:
                self.locked_wrist_pos = None
            return None

        now = time.time()

        # 1. If we already have a locked active hand, match it across detected hands in new frame
        if self.locked_wrist_pos is not None:
            best_match = None
            best_dist = 999.0
            for hand in raw_hands_list:
                wrist = hand[0]
                dist = math.hypot(wrist.x - self.locked_wrist_pos[0], wrist.y - self.locked_wrist_pos[1])
                if dist < best_dist:
                    best_dist = dist
                    best_match = hand

            # If matching hand is found within continuity radius and is not dropped to desk
            if best_match is not None and best_dist < 0.35 and best_match[0].y < 0.92:
                self.locked_wrist_pos = (best_match[0].x, best_match[0].y)
                self.last_seen_time = now
                return best_match
            else:
                if (now - self.last_seen_time) > self.lock_hold_duration_sec:
                    self.locked_wrist_pos = None

        # 2. No active lock: Search all detected hands for the best gesturing / elevated hand
        best_candidate = None
        best_score = -999.0

        for hand in raw_hands_list:
            wrist = hand[0]
            if wrist.y > 0.90:
                continue

            palm_scale = tracker_ref._calculate_palm_scale(hand)
            index_ext = tracker_ref._is_finger_extended(hand[8], hand[6], hand[5], wrist, palm_scale)
            
            elevation = (1.0 - wrist.y)
            score = elevation * 1.5 + (1.0 if index_ext else 0.0)

            if score > best_score:
                best_score = score
                best_candidate = hand

        if best_candidate is not None:
            self.locked_wrist_pos = (best_candidate[0].x, best_candidate[0].y)
            self.last_seen_time = now
            return best_candidate

        return None

    def reset(self):
        self.locked_wrist_pos = None
        self.last_seen_time = 0.0


class OneEuroFilter:
    """
    Casiez et al. (CHI 2012) 1-Euro Filter operating in normalized coordinate space.
    Dynamically modulates cutoff frequency based on input speed to eliminate
    low-speed tremor while guaranteeing zero-lag fast movements.
    """
    def __init__(self, min_cutoff: float = 0.06, beta: float = 2.50, d_cutoff: float = 1.0):
        self.min_cutoff = min_cutoff
        self.beta = beta
        self.d_cutoff = d_cutoff
        self.x_filt = LowPassFilter()
        self.dx_filt = LowPassFilter()
        self.prev_x: Optional[float] = None
        self.prev_time: Optional[float] = None

    def _alpha(self, cutoff: float, dt: float) -> float:
        tau = 1.0 / (2.0 * math.pi * cutoff)
        return 1.0 / (1.0 + tau / dt)

    def filter(self, x: float, timestamp: float, min_cutoff: Optional[float] = None, beta: Optional[float] = None) -> float:
        if min_cutoff is not None:
            self.min_cutoff = min_cutoff
        if beta is not None:
            self.beta = beta

        if self.prev_x is None or self.prev_time is None:
            self.prev_x = x
            self.prev_time = timestamp
            self.x_filt.reset()
            self.dx_filt.reset()
            self.x_filt.filter(x, 1.0)
            self.dx_filt.filter(0.0, 1.0)
            return x

        dt = max(1e-4, timestamp - self.prev_time)
        self.prev_time = timestamp

        # Compute raw derivative in normalized units per second
        dx = (x - self.prev_x) / dt
        self.prev_x = x

        alpha_d = self._alpha(self.d_cutoff, dt)
        edx = self.dx_filt.filter(dx, alpha_d)

        # Dynamic cutoff frequency: speed in normalized coords scaled for responsive snap
        cutoff = max(0.01, self.min_cutoff + self.beta * abs(edx))
        alpha = self._alpha(cutoff, dt)

        return self.x_filt.filter(x, alpha)

    def reset(self):
        self.prev_x = None
        self.prev_time = None
        self.x_filt.reset()
        self.dx_filt.reset()


class ClickLockManager:
    """
    Guarantees 100% stable, drift-free clicking.
    Locks the cursor coordinates the moment the user initiates a pinch gesture,
    preventing the physiological index finger twitch/drift from moving the cursor
    onto adjacent window buttons (e.g. hitting Close instead of Minimize).
    """
    def __init__(self):
        self.is_locked: bool = False
        self.locked_screen_pos: Optional[Tuple[float, float]] = None
        self.lock_start_time: float = 0.0
        self.unlock_cooldown_until: float = 0.0
        self.prev_pinch_dist: Optional[float] = None
        self.pinch_velocity: float = 0.0

    def update(
        self,
        pinch_dist: float,
        eff_threshold: float,
        current_screen_pos: Tuple[float, float],
        is_pinching_active: bool,
        is_dragging_active: bool,
        now: float
    ) -> Tuple[bool, Optional[Tuple[float, float]]]:
        if not config.pre_click_freeze:
            self.is_locked = False
            self.locked_screen_pos = None
            return False, None

        if is_dragging_active:
            self.is_locked = False
            self.locked_screen_pos = None
            return False, None

        # Check post-click release cooldown
        if now < self.unlock_cooldown_until:
            if self.locked_screen_pos is not None:
                return True, self.locked_screen_pos

        # Calculate approach velocity
        if self.prev_pinch_dist is not None:
            raw_vel = (self.prev_pinch_dist - pinch_dist)
            self.pinch_velocity = 0.6 * self.pinch_velocity + 0.4 * raw_vel
        self.prev_pinch_dist = pinch_dist

        # Approach window: within 115% of calibrated click threshold and closing or already pinched
        is_in_approach_zone = pinch_dist < (eff_threshold * 1.15)
        is_closing = self.pinch_velocity > 0.002

        should_lock = (is_in_approach_zone and is_closing) or is_pinching_active

        if should_lock:
            if not self.is_locked:
                self.is_locked = True
                self.locked_screen_pos = current_screen_pos
                self.lock_start_time = now

            # Check breakout for intentional Drag & Drop
            held_duration_ms = (now - self.lock_start_time) * 1000.0
            if held_duration_ms > config.drag_hold_delay_ms:
                if self.locked_screen_pos is not None:
                    dist = math.hypot(
                        current_screen_pos[0] - self.locked_screen_pos[0],
                        current_screen_pos[1] - self.locked_screen_pos[1]
                    )
                    if dist > config.click_lock_breakout_dist_px:
                        # Intentional drag breakout
                        self.is_locked = False
                        self.locked_screen_pos = None
                        return False, None

            return True, self.locked_screen_pos
        else:
            if self.is_locked:
                # Pinch was released -> engage post-click settle cooldown
                self.is_locked = False
                self.unlock_cooldown_until = now + (config.click_lock_cooldown_ms / 1000.0)
                return True, self.locked_screen_pos
            return False, None

    def reset(self):
        self.is_locked = False
        self.locked_screen_pos = None
        self.lock_start_time = 0.0
        self.unlock_cooldown_until = 0.0
        self.prev_pinch_dist = None
        self.pinch_velocity = 0.0


class HumanIntentSmoother:
    """
    Advanced Multi-Stage Spatial Filter operating in Normalized Landmark Space:
    1. Calibrated 2D 1-Euro Dynamic Low-Pass Filter with responsive velocity tuning
    2. Zero-Tremor Stillness Deadband with smooth Cubic Hermite blend
    3. Human Motor Ballistic Acceleration (Micro-Targeting vs Fast Traversal)
    4. Anti-Twitch Pre-Click Anchor Lock
    """
    def __init__(self):
        self.filter_x = OneEuroFilter()
        self.filter_y = OneEuroFilter()
        self.click_locker = ClickLockManager()
        
        self.last_norm_x: Optional[float] = None
        self.last_norm_y: Optional[float] = None
        self.last_screen_x: Optional[float] = None
        self.last_screen_y: Optional[float] = None
        self.last_time: Optional[float] = None
        self.current_intent_mode: str = "NORMAL"

    def filter(
        self,
        raw_norm_x: float,
        raw_norm_y: float,
        screen_width: int,
        screen_height: int,
        smoothing_factor: float,
        pinch_dist: float,
        eff_pinch_thresh: float,
        is_pinching_active: bool = False,
        is_dragging: bool = False
    ) -> Tuple[float, float, str]:
        curr_time = time.perf_counter()

        # Dynamic parameter mapping from user's smoothing setting (0.10 to 0.98)
        clamped_smooth = max(0.05, min(0.98, smoothing_factor))
        inv_smooth = (1.0 - clamped_smooth)
        eff_min_cutoff = 0.03 + (inv_smooth ** 2.2) * 1.8  # 0.03 Hz (buttery stillness) to 1.8 Hz
        eff_beta = 0.60 + inv_smooth * 3.80                 # High responsiveness during fast flicks

        if self.last_norm_x is None or self.last_time is None:
            self.last_norm_x = raw_norm_x
            self.last_norm_y = raw_norm_y
            self.last_time = curr_time
            self.filter_x.filter(raw_norm_x, curr_time, eff_min_cutoff, eff_beta)
            self.filter_y.filter(raw_norm_y, curr_time, eff_min_cutoff, eff_beta)
            
            sc_x, sc_y = self._norm_to_screen(raw_norm_x, raw_norm_y, screen_width, screen_height)
            self.last_screen_x, self.last_screen_y = sc_x, sc_y
            return sc_x, sc_y, "NORMAL"

        dt = max(1e-4, curr_time - self.last_time)
        self.last_time = curr_time

        # -------------------------------------------------------------
        # 1. 1-EURO FILTER IN NORMALIZED SPACE
        # -------------------------------------------------------------
        f_norm_x = self.filter_x.filter(raw_norm_x, curr_time, min_cutoff=eff_min_cutoff, beta=eff_beta)
        f_norm_y = self.filter_y.filter(raw_norm_y, curr_time, min_cutoff=eff_min_cutoff, beta=eff_beta)

        # -------------------------------------------------------------
        # 2. ZERO-TREMOR STILLNESS DEADBAND (Noise-Gate with Hermite Blend)
        # -------------------------------------------------------------
        dx = f_norm_x - self.last_norm_x
        dy = f_norm_y - self.last_norm_y
        dist_norm = math.hypot(dx, dy)
        speed_norm = dist_norm / dt

        deadband = max(0.0004, config.stillness_deadband_norm)
        if dist_norm < deadband:
            if dist_norm < deadband * 0.35:
                # Pure stillness lock: 0.0 movement
                f_norm_x = self.last_norm_x
                f_norm_y = self.last_norm_y
            else:
                # Smooth Cubic Hermite ramp to eliminate sticky transitions
                t = (dist_norm - deadband * 0.35) / (deadband * 0.65)
                weight = t * t * (3.0 - 2.0 * t)
                f_norm_x = self.last_norm_x + dx * weight
                f_norm_y = self.last_norm_y + dy * weight

        # -------------------------------------------------------------
        # 3. BALLISTIC ACCELERATION CURVE (Precision vs Fast Travel)
        # -------------------------------------------------------------
        intent_mode = "NORMAL"
        if config.ballistic_acceleration and not is_dragging:
            if speed_norm < 0.040:
                # Micro-Targeting Hover Mode (fine button targeting)
                intent_mode = "PRECISION"
                t = max(0.0, min(1.0, speed_norm / 0.040))
                gain = 0.55 + t * 0.45
                f_norm_x = self.last_norm_x + (f_norm_x - self.last_norm_x) * gain
                f_norm_y = self.last_norm_y + (f_norm_y - self.last_norm_y) * gain
            elif speed_norm > 0.30:
                # Fast Travel (sweeping across monitors)
                intent_mode = "TRAVEL"
                t = min(1.0, (speed_norm - 0.30) / 0.60)
                gain = 1.0 + t * 0.60
                f_norm_x = self.last_norm_x + (f_norm_x - self.last_norm_x) * gain
                f_norm_y = self.last_norm_y + (f_norm_y - self.last_norm_y) * gain

        self.last_norm_x = f_norm_x
        self.last_norm_y = f_norm_y

        # Convert filtered normalized position to screen coordinates
        screen_x, screen_y = self._norm_to_screen(f_norm_x, f_norm_y, screen_width, screen_height)

        # -------------------------------------------------------------
        # 4. CLICK-LOCK & PRE-CLICK ANCHOR FREEZE (Zero Target Drift)
        # -------------------------------------------------------------
        curr_screen_pos = (self.last_screen_x if self.last_screen_x is not None else screen_x,
                           self.last_screen_y if self.last_screen_y is not None else screen_y)
        
        is_locked, locked_pos = self.click_locker.update(
            pinch_dist=pinch_dist,
            eff_threshold=eff_pinch_thresh,
            current_screen_pos=curr_screen_pos,
            is_pinching_active=is_pinching_active,
            is_dragging_active=is_dragging,
            now=curr_time
        )

        if is_locked and locked_pos is not None:
            self.current_intent_mode = "PRE_CLICK"
            return locked_pos[0], locked_pos[1], "PRE_CLICK"

        self.last_screen_x = screen_x
        self.last_screen_y = screen_y
        self.current_intent_mode = intent_mode
        return screen_x, screen_y, intent_mode

    def _norm_to_screen(self, norm_x: float, norm_y: float, screen_w: int, screen_h: int) -> Tuple[float, float]:
        deadzone = config.deadzone_margin
        # Map from deadzone box to [0.0, 1.0] with edge overdrive for effortless corner reach
        mapped_x = (norm_x - deadzone) / max(0.1, 1.0 - 2.0 * deadzone)
        mapped_y = (norm_y - deadzone) / max(0.1, 1.0 - 2.0 * deadzone)

        # Apply Sensitivity from center
        cx, cy = 0.5, 0.5
        mapped_x = cx + (mapped_x - cx) * config.sensitivity_x
        mapped_y = cy + (mapped_y - cy) * config.sensitivity_y

        # Clamp
        mapped_x = max(0.0, min(1.0, mapped_x))
        mapped_y = max(0.0, min(1.0, mapped_y))

        return mapped_x * screen_w, mapped_y * screen_h

    def reset(self):
        self.filter_x.reset()
        self.filter_y.reset()
        self.click_locker.reset()
        self.last_norm_x = None
        self.last_norm_y = None
        self.last_screen_x = None
        self.last_screen_y = None
        self.last_time = None
        self.current_intent_mode = "NORMAL"


class HandTracker:
    def __init__(
        self,
        mouse_controller: MouseController,
        on_action_update: Optional[Callable[[str, str], None]] = None,
        on_click_callback: Optional[Callable[[int, int], None]] = None,
        keyboard: Optional[Any] = None
    ):
        self.mouse = mouse_controller
        self.on_action_update = on_action_update
        self.on_click_callback = on_click_callback
        self.keyboard = keyboard
        self.running = False
        self.thread: Optional[threading.Thread] = None
        
        self.hand_priority = HandPriorityManager()
        self.landmark_smoother = LandmarkSmoother(alpha=config.landmark_smoothing)
        self.smoother = HumanIntentSmoother()
        self.cap: Optional[cv2.VideoCapture] = None
        self.detector = None
        
        # State tracking for gestures
        self.current_action = "Initializing"
        self.action_detail = "Starting engine"
        self.fps = 0.0
        
        # Left click / double click / drag state
        self.is_pinching_left = False
        self.pinch_left_start_time = 0.0
        self.last_left_click_time = 0.0
        self.last_click_pos = (0, 0)
        self.was_dragging = False
        
        # Right click state
        self.is_pinching_right = False
        self.last_right_click_time = 0.0
        
        # Scroll tracking
        self.is_scrolling = False
        self.last_scroll_y = 0.0
        self.scroll_accumulator = 0.0
        self.scroll_velocity = 0.0
        self.scroll_direction = "IDLE"

        # Window management gesture tracking (Open Palm Swipe Up/Down)
        self.last_palm_y = 0.5
        self.last_palm_time = 0.0
        self.palm_velocity_y = 0.0
        self.last_window_gesture_time = 0.0
        
        # Frame buffer and telemetry for Camera HUD
        self.latest_frame = None
        self.latest_landmarks = None
        self.latest_palm_scale = 0.20
        self.latest_pinch_dist = 0.0
        self.latest_pinch_thresh = 0.035
        self.latest_pinch_release_thresh = 0.045
        self.latest_pinch_proximity = 0.0
        self.latest_right_dist = 0.0
        self.latest_gesture_state = "POINT"
        self.pinch_start_pos = (0, 0)
        self.frame_lock = threading.Lock()

    def initialize_detector(self):
        ensure_model_file()
        base_options = python.BaseOptions(model_asset_path=MODEL_PATH)
        options = vision.HandLandmarkerOptions(
            base_options=base_options,
            num_hands=2,
            min_hand_detection_confidence=0.55,
            min_hand_presence_confidence=0.55,
            min_tracking_confidence=0.55
        )
        self.detector = vision.HandLandmarker.create_from_options(options)

    def start(self):
        if self.running:
            return
        self.running = True
        self.thread = threading.Thread(target=self._tracking_loop, daemon=True)
        self.thread.start()

    def stop(self):
        self.running = False
        if self.thread and self.thread.is_alive():
            self.thread.join(timeout=2.0)
        if self.cap and self.cap.isOpened():
            self.cap.release()
        self.mouse.release_all()
        self._update_action("Stopped", "Hand tracking paused")

    def _update_action(self, action: str, detail: str = ""):
        self.current_action = action
        self.action_detail = detail
        if self.on_action_update:
            try:
                self.on_action_update(action, detail)
            except Exception:
                pass

    def _dist_2d(self, p1, p2) -> float:
        return math.hypot(p1.x - p2.x, p1.y - p2.y)

    def _dist_3d(self, p1, p2, z_weight: float = 0.85) -> float:
        """Calculates 3D depth-compensated Euclidean distance between two landmarks."""
        z1 = getattr(p1, 'z', 0.0)
        z2 = getattr(p2, 'z', 0.0)
        return math.hypot(p1.x - p2.x, p1.y - p2.y, (z1 - z2) * z_weight)

    def _calculate_palm_scale(self, landmarks) -> float:
        """Calculate invariant 3D hand scale from wrist (0) to middle MCP (9)."""
        wrist = landmarks[0]
        middle_mcp = landmarks[9]
        index_mcp = landmarks[5]
        pinky_mcp = landmarks[17]
        palm_len = self._dist_3d(middle_mcp, wrist, 0.60)
        palm_width = self._dist_3d(pinky_mcp, index_mcp, 0.60)
        scale = (palm_len + palm_width) / 2.0
        return max(0.08, min(0.45, scale))

    def _is_finger_extended(self, tip, pip, mcp, wrist, palm_scale: float) -> bool:
        """Determines if a finger is extended outwards vs curled into the palm."""
        d_tip_wrist = self._dist_3d(tip, wrist, 0.60)
        d_pip_wrist = self._dist_3d(pip, wrist, 0.60)
        d_tip_mcp = self._dist_3d(tip, mcp, 0.60)
        return (d_tip_wrist > d_pip_wrist * 1.05) and (d_tip_mcp > palm_scale * 0.50)

    def _tracking_loop(self):
        self.initialize_detector()
        
        camera_idx = config.camera_index
        self.cap = cv2.VideoCapture(camera_idx, cv2.CAP_DSHOW)
        if not self.cap.isOpened():
            self.cap = cv2.VideoCapture(camera_idx)
            
        if not self.cap.isOpened():
            self._update_action("No Camera", "Please connect a webcam")
            return

        # Zero-latency OpenCV camera buffer setting
        try:
            self.cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        except Exception:
            pass

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, config.camera_width)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, config.camera_height)
        self.cap.set(cv2.CAP_PROP_FPS, config.fps_limit)

        prev_frame_time = time.time()
        self._update_action("Ready", "Waiting for hand...")

        while self.running:
            success, frame = self.cap.read()
            if not success or frame is None:
                time.sleep(0.005)
                continue

            curr_time = time.time()
            dt = curr_time - prev_frame_time
            prev_frame_time = curr_time
            if dt > 0:
                self.fps = 0.9 * self.fps + 0.1 * (1.0 / dt)

            # Flip horizontally for natural mirror behavior
            frame = cv2.flip(frame, 1)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb_frame)

            detection_result = self.detector.detect(mp_image)

            if not config.tracking_enabled:
                with self.frame_lock:
                    self.latest_frame = frame
                    self.latest_landmarks = None
                    self.latest_gesture_state = "PAUSED"
                self._update_action("Paused", "Tracking disabled in menu")
                if self.mouse.is_dragging:
                    self.mouse.stop_drag()
                time.sleep(0.02)
                continue

            if detection_result.hand_landmarks and len(detection_result.hand_landmarks) > 0:
                active_raw_hand = self.hand_priority.select_active_hand(detection_result.hand_landmarks, self)
                
                if active_raw_hand is not None:
                    smoothed_landmarks = self.landmark_smoother.smooth(active_raw_hand)
                    
                    with self.frame_lock:
                        self.latest_frame = frame
                        self.latest_landmarks = [smoothed_landmarks]

                    self._process_hand(smoothed_landmarks, frame.shape)
                else:
                    self._on_no_active_hand(frame)
            else:
                self._on_no_active_hand(frame)

            time.sleep(0.001)

    def _on_no_active_hand(self, frame):
        self.hand_priority.reset()
        self.landmark_smoother.reset()
        self.smoother.reset()
        if self.mouse.is_dragging:
            self.mouse.stop_drag()
        self.is_pinching_left = False
        self.is_pinching_right = False
        self.is_scrolling = False
        self.scroll_accumulator = 0.0
        self.scroll_velocity = 0.0
        with self.frame_lock:
            self.latest_frame = frame
            self.latest_landmarks = None
            self.latest_gesture_state = "SEARCHING"
        self._update_action("Searching", "Bring hand into view")

    def _process_hand(self, landmarks, frame_shape):
        wrist = landmarks[0]
        thumb_tip = landmarks[4]
        thumb_ip = landmarks[3]
        thumb_mcp = landmarks[2]
        
        index_tip = landmarks[8]
        index_dip = landmarks[7]
        index_pip = landmarks[6]
        index_mcp = landmarks[5]
        
        middle_tip = landmarks[12]
        middle_pip = landmarks[10]
        middle_mcp = landmarks[9]
        
        ring_tip = landmarks[16]
        ring_pip = landmarks[14]
        ring_mcp = landmarks[13]
        
        pinky_tip = landmarks[20]
        pinky_pip = landmarks[18]
        pinky_mcp = landmarks[17]

        now = time.time()

        # Invariant 3D Palm Scale
        palm_scale = self._calculate_palm_scale(landmarks)
        
        # Adaptive thresholds scaled to 3D hand scale
        eff_left_pinch_thresh = max(0.018, min(0.060, palm_scale * config.pinch_threshold_ratio))
        eff_right_pinch_thresh = max(0.020, min(0.065, palm_scale * config.right_click_threshold_ratio))
        eff_ring_pinch_thresh = max(0.020, min(0.065, palm_scale * config.pinch_threshold_ratio * 1.15))
        
        hysteresis = max(1.18, config.pinch_hysteresis_ratio)
        eff_left_release_thresh = eff_left_pinch_thresh * hysteresis
        eff_right_release_thresh = eff_right_pinch_thresh * hysteresis
        eff_ring_release_thresh = eff_ring_pinch_thresh * hysteresis

        # 3D Depth-Compensated Euclidean Distances
        dist_thumb_index = self._dist_3d(thumb_tip, index_tip, 0.85)
        dist_thumb_middle = self._dist_3d(thumb_tip, middle_tip, 0.85)
        dist_index_middle = self._dist_3d(index_tip, middle_tip, 0.85)
        dist_thumb_ring = self._dist_3d(thumb_tip, ring_tip, 0.85)
        dist_thumb_pinky = self._dist_3d(thumb_tip, pinky_tip, 0.85)

        # Proximity percentage (0% = wide open, 100% = pinched)
        proximity_span = max(0.01, eff_left_pinch_thresh * 2.0)
        pinch_proximity = max(0.0, min(1.0, 1.0 - (dist_thumb_index - eff_left_pinch_thresh) / proximity_span))

        with self.frame_lock:
            self.latest_palm_scale = palm_scale
            self.latest_pinch_dist = dist_thumb_index
            self.latest_pinch_thresh = eff_left_pinch_thresh
            self.latest_pinch_release_thresh = eff_left_release_thresh
            self.latest_pinch_proximity = pinch_proximity
            self.latest_right_dist = dist_thumb_middle

        # Finger extension states
        index_ext = self._is_finger_extended(index_tip, index_pip, index_mcp, wrist, palm_scale)
        middle_ext = self._is_finger_extended(middle_tip, middle_pip, middle_mcp, wrist, palm_scale)
        ring_ext = self._is_finger_extended(ring_tip, ring_pip, ring_mcp, wrist, palm_scale)
        pinky_ext = self._is_finger_extended(pinky_tip, pinky_pip, pinky_mcp, wrist, palm_scale)

        # Distance of all fingertips to wrist (for fist detection)
        d_wrist_index = self._dist_3d(wrist, index_tip, 0.60)
        d_wrist_middle = self._dist_3d(wrist, middle_tip, 0.60)
        d_wrist_ring = self._dist_3d(wrist, ring_tip, 0.60)
        d_wrist_pinky = self._dist_3d(wrist, pinky_tip, 0.60)

        is_tight_fist = (
            (not index_ext) and (not middle_ext) and (not ring_ext) and (not pinky_ext) and
            (d_wrist_index < palm_scale * 0.95) and 
            (d_wrist_middle < palm_scale * 0.95) and 
            (d_wrist_ring < palm_scale * 0.95) and 
            (d_wrist_pinky < palm_scale * 0.95)
        )

        # -------------------------------------------------------------
        # 1. REST / CLOSED FIST PAUSE
        # -------------------------------------------------------------
        if is_tight_fist and not self.is_pinching_left:
            with self.frame_lock:
                self.latest_gesture_state = "REST"
            self._update_action("⏸️ Hand Resting", "Fist closed - cursor paused")
            if self.mouse.is_dragging:
                self.mouse.stop_drag()
            self.is_scrolling = False
            return

        # -------------------------------------------------------------
        # 2. WINDOW MINIMIZE & MAXIMIZE GESTURES (Open Palm Swipe Up/Down)
        # -------------------------------------------------------------
        is_all_fingers_spread = (
            index_ext and middle_ext and ring_ext and pinky_ext and
            (dist_index_middle > palm_scale * 0.22) and
            (self._dist_3d(middle_tip, ring_tip, 0.60) > palm_scale * 0.20) and
            (self._dist_3d(ring_tip, pinky_tip, 0.60) > palm_scale * 0.20) and
            (dist_thumb_index > eff_left_pinch_thresh * 1.5)
        )

        palm_center_y = (wrist.y + middle_mcp.y) / 2.0
        palm_dt = max(1e-4, now - self.last_palm_time)
        if self.last_palm_time > 0:
            raw_palm_vy = (palm_center_y - self.last_palm_y) / palm_dt
            self.palm_velocity_y = 0.5 * self.palm_velocity_y + 0.5 * raw_palm_vy
        self.last_palm_y = palm_center_y
        self.last_palm_time = now

        if config.window_gestures_enabled and is_all_fingers_spread and not self.is_pinching_left:
            time_since_last_gesture = now - self.last_window_gesture_time

            # Swipe Up (Negative Y velocity in camera space) -> Maximize / Restore Active Window
            if self.palm_velocity_y < -config.palm_swipe_speed_threshold and time_since_last_gesture > config.window_gesture_cooldown_sec:
                self.mouse.maximize_active_window()
                self.last_window_gesture_time = now
                with self.frame_lock:
                    self.latest_gesture_state = "MAXIMIZE"
                self._update_action("🗖 Window Maximized", "Open Palm Swipe Up")
                return

            # Swipe Down (Positive Y velocity in camera space) -> Minimize Active Window
            elif self.palm_velocity_y > config.palm_swipe_speed_threshold and time_since_last_gesture > config.window_gesture_cooldown_sec:
                self.mouse.minimize_active_window()
                self.last_window_gesture_time = now
                with self.frame_lock:
                    self.latest_gesture_state = "MINIMIZE"
                self._update_action("🗕 Window Minimized", "Open Palm Swipe Down")
                return
            elif time_since_last_gesture > config.window_gesture_cooldown_sec:
                with self.frame_lock:
                    self.latest_gesture_state = "OPEN_PALM"
                self._update_action("🖐️ Open Palm", "Swipe Up: Maximize | Down: Minimize")
                return

        # -------------------------------------------------------------
        # 3. RING FINGER + THUMB SCROLLING
        # -------------------------------------------------------------
        is_ring_thumb_scroll = (
            (dist_thumb_ring < eff_ring_pinch_thresh if not self.is_scrolling else dist_thumb_ring < eff_ring_release_thresh) and
            dist_thumb_index > (eff_left_pinch_thresh * 1.30)
        )

        if is_ring_thumb_scroll and not self.is_pinching_left:
            scroll_pt_y = (thumb_tip.y + ring_tip.y) / 2.0
            with self.frame_lock:
                self.latest_gesture_state = "SCROLL"

            if not self.is_scrolling:
                self.is_scrolling = True
                self.last_scroll_y = scroll_pt_y
                self.scroll_accumulator = 0.0
                self.scroll_velocity = 0.0
                self._update_action("📜 Ring-Thumb Scroll", "Glide hand up/down")
            else:
                dy = scroll_pt_y - self.last_scroll_y
                self.last_scroll_y = scroll_pt_y
                
                direction_multiplier = -1.0 if not config.scroll_invert else 1.0
                
                if abs(dy) > config.scroll_threshold:
                    target_velocity = dy * direction_multiplier * config.scroll_speed * 14.0
                    self.scroll_velocity = (
                        self.scroll_velocity * config.scroll_smoothing + 
                        target_velocity * (1.0 - config.scroll_smoothing)
                    )
                    self.scroll_accumulator += self.scroll_velocity
                    
                    steps = int(self.scroll_accumulator)
                    if steps != 0:
                        self.mouse.scroll(steps)
                        self.scroll_accumulator -= steps
                        dir_str = "Up ⬆️" if steps > 0 else "Down ⬇️"
                        self.scroll_direction = dir_str
                        self._update_action("📜 Scrolling", f"Scroll {dir_str}")
                else:
                    self.scroll_velocity *= 0.5
            return
        else:
            self.is_scrolling = False
            self.scroll_accumulator = 0.0
            self.scroll_velocity = 0.0

        # -------------------------------------------------------------
        # 4. LIVE CURSOR MOVEMENT & 1-EURO KINEMATIC ANCHOR
        # -------------------------------------------------------------
        self.mouse.refresh_screen_size()
        
        # Anatomical Index Finger Kinematic Anchor (Zero Subpixel Tremor)
        raw_norm_x = index_tip.x * 0.70 + index_dip.x * 0.20 + index_pip.x * 0.10
        raw_norm_y = index_tip.y * 0.70 + index_dip.y * 0.20 + index_pip.y * 0.10
        
        is_left_pinched = (
            (dist_thumb_index < eff_left_pinch_thresh) if not self.is_pinching_left
            else (dist_thumb_index < eff_left_release_thresh)
        )

        is_pinching_active = is_left_pinched or self.is_pinching_right
        is_dragging_active = self.mouse.is_dragging or self.was_dragging
        
        filtered_x, filtered_y, intent_mode = self.smoother.filter(
            raw_norm_x=raw_norm_x,
            raw_norm_y=raw_norm_y,
            screen_width=self.mouse.screen_width,
            screen_height=self.mouse.screen_height,
            smoothing_factor=config.smoothing_factor,
            pinch_dist=dist_thumb_index,
            eff_pinch_thresh=eff_left_pinch_thresh,
            is_pinching_active=is_pinching_active,
            is_dragging=is_dragging_active
        )
        
        self.mouse.move_to(filtered_x, filtered_y)
        curr_pos = (int(filtered_x), int(filtered_y))

        # Real-time hover glow on keyboard keys
        if self.keyboard and self.keyboard.is_visible and self.keyboard.is_point_inside(curr_pos[0], curr_pos[1]):
            self.keyboard.highlight_key_at_screen_pos(curr_pos[0], curr_pos[1])

        # -------------------------------------------------------------
        # 5. RIGHT CLICK (Disambiguated Context Menu)
        # -------------------------------------------------------------
        # 1. Middle finger + Thumb pinch: Middle tip touches Thumb tip while index is separate
        is_middle_thumb_pinch = (
            (dist_thumb_middle < eff_right_pinch_thresh if not self.is_pinching_right else dist_thumb_middle < eff_right_release_thresh) and
            (dist_thumb_middle < dist_thumb_index * 0.90 or dist_thumb_index > eff_left_pinch_thresh * 1.30)
        )

        # 2. Two-finger pinch: Both index & middle tips together against thumb
        is_two_finger_pinch = (
            (dist_thumb_middle < eff_right_pinch_thresh * 1.25) and
            (dist_thumb_index < eff_left_pinch_thresh * 1.25) and
            (dist_index_middle < palm_scale * 0.25)
        )

        is_right_pinched = False
        if config.right_click_mode == "two_finger_pinch":
            is_right_pinched = is_two_finger_pinch
        elif config.right_click_mode == "middle_pinch":
            is_right_pinched = is_middle_thumb_pinch
        else:
            is_right_pinched = is_middle_thumb_pinch or is_two_finger_pinch

        if is_right_pinched and not self.is_pinching_left:
            with self.frame_lock:
                self.latest_gesture_state = "RIGHT_CLICK"
            if not self.is_pinching_right:
                self.is_pinching_right = True
                if (now - self.last_right_click_time) > 0.35:
                    self.mouse.right_click()
                    self.last_right_click_time = now
                    self._update_action("🖱️ Right Click", "Context menu triggered")
            return
        else:
            if self.is_pinching_right and dist_thumb_middle > eff_right_release_thresh:
                self.is_pinching_right = False

        # -------------------------------------------------------------
        # 6. LEFT CLICK, KEYBOARD PINCH TYPING, DRAG & DROP, DOUBLE CLICK
        # -------------------------------------------------------------
        is_over_keyboard = (
            self.keyboard is not None and 
            self.keyboard.is_visible and 
            self.keyboard.is_point_inside(curr_pos[0], curr_pos[1])
        )

        if is_left_pinched:
            with self.frame_lock:
                self.latest_gesture_state = "LEFT_CLICK" if not self.was_dragging else "DRAG"

            if not self.is_pinching_left:
                self.is_pinching_left = True
                self.pinch_left_start_time = now
                self.pinch_start_pos = curr_pos
                self.was_dragging = False

                if is_over_keyboard:
                    # Instant single-pinch key activation on pinch-down contact!
                    key_name = self.keyboard.trigger_key_at_screen_pos(curr_pos[0], curr_pos[1])
                    self.last_left_click_time = now
                    self.last_click_pos = curr_pos
                    if key_name:
                        self._update_action(f"⌨️ Typed '{key_name}'", "Sent to input field")
                    else:
                        self._update_action("⌨️ Keyboard", "Key clicked")
                else:
                    self._update_action("🤏 Pinched", "Tap to click • Hold/Move to drag")
            else:
                pinch_duration_ms = (now - self.pinch_left_start_time) * 1000.0
                drag_dist_px = math.hypot(curr_pos[0] - self.pinch_start_pos[0], curr_pos[1] - self.pinch_start_pos[1])
                breakout_px = config.drag_breakout_dist_norm * max(self.mouse.screen_width, self.mouse.screen_height)
                
                # Intentional drag engage: either held long enough OR intentionally moved while pinched
                is_intentional_movement = (drag_dist_px > breakout_px and pinch_duration_ms > 120.0)
                is_held_drag = (pinch_duration_ms >= config.drag_hold_delay_ms)

                if not is_over_keyboard and (is_held_drag or is_intentional_movement):
                    if not self.mouse.is_dragging:
                        self.mouse.start_drag()
                        self.was_dragging = True
                    self._update_action("✊ Dragging", "Moving selection / object...")
        else:
            if self.is_pinching_left:
                pinch_duration_ms = (now - self.pinch_left_start_time) * 1000.0
                self.is_pinching_left = False

                if self.mouse.is_dragging or self.was_dragging:
                    self.mouse.stop_drag()
                    self.was_dragging = False
                    self._update_action("✨ Dropped", "Drag released successfully")
                elif not is_over_keyboard and pinch_duration_ms < config.drag_hold_delay_ms:
                    time_since_last_click_ms = (now - self.last_left_click_time) * 1000.0
                    dist_to_last = math.hypot(curr_pos[0] - self.last_click_pos[0], curr_pos[1] - self.last_click_pos[1])

                    if time_since_last_click_ms < config.double_click_window_ms and dist_to_last < 90:
                        self.mouse.double_click()
                        self.last_left_click_time = 0.0
                        self._update_action("⚡ Double Click", "Activated!")
                    else:
                        self.mouse.left_click()
                        self.last_left_click_time = now
                        self.last_click_pos = curr_pos
                        self._update_action("👆 Left Click", "Selected item")
                        
                        # Notify click callback for intelligent search/text input activation
                        if self.on_click_callback:
                            try:
                                self.on_click_callback(curr_pos[0], curr_pos[1])
                            except Exception:
                                pass

        with self.frame_lock:
            if not self.is_pinching_left and not self.is_pinching_right and not self.is_scrolling:
                if dist_thumb_index < eff_left_pinch_thresh * 1.35:
                    self.latest_gesture_state = "APPROACH"
                else:
                    self.latest_gesture_state = "POINT"

        if not self.is_pinching_left and not self.is_pinching_right and not self.is_scrolling:
            if intent_mode == "PRE_CLICK":
                self._update_action("🔒 Click Locked", "Target Anchored • Drift Prevented")
            elif intent_mode == "PRECISION":
                self._update_action("🎯 Precision Aim", "Micro-Hover • Stillness Locked")
            elif intent_mode == "TRAVEL":
                self._update_action("⚡ Fast Travel", "Dynamic Acceleration Active")
            else:
                self._update_action("🎯 Smooth Tracking", "Zero-Jitter Filter Active")
