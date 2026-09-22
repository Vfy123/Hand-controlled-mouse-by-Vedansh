import cv2
import threading
import time
import tkinter as tk
from PIL import Image, ImageTk
from typing import Optional

from config import config

HAND_CONNECTIONS = [
    (0, 1), (1, 2), (2, 3), (3, 4),        # Thumb
    (0, 5), (5, 6), (6, 7), (7, 8),        # Index
    (5, 9), (9, 10), (10, 11), (11, 12),   # Middle
    (9, 13), (13, 14), (14, 15), (15, 16), # Ring
    (13, 17), (17, 18), (18, 19), (19, 20),# Pinky
    (0, 17)                                # Palm base
]

class CameraHUD:
    def __init__(self, root: tk.Tk, tracker):
        self.root = root
        self.tracker = tracker
        self.window: Optional[tk.Toplevel] = None
        self.canvas: Optional[tk.Canvas] = None
        self.running = False
        self.photo_img = None
        
        self.width = 260
        self.height = 195

    def show(self):
        if self.window is not None:
            try:
                self.window.lift()
                return
            except Exception:
                self.window = None

        self.window = tk.Toplevel(self.root)
        self.window.title("Hand Camera HUD")
        self.window.overrideredirect(True)
        self.window.attributes("-topmost", True)
        self.window.attributes("-alpha", 0.94)
        self.window.configure(bg="#0c0e14")

        # Position at bottom-right corner of screen
        screen_w = self.window.winfo_screenwidth()
        screen_h = self.window.winfo_screenheight()
        x = screen_w - self.width - 24
        y = screen_h - self.height - 50
        self.window.geometry(f"{self.width}x{self.height}+{x}+{y}")

        # Header bar for dragging
        header = tk.Frame(self.window, bg="#141724", height=24)
        header.pack(fill=tk.X, side=tk.TOP)

        title_lbl = tk.Label(header, text="📷 SKELETON & GESTURE FEED", font=("Segoe UI", 8, "bold"), fg="#00E5FF", bg="#141724")
        title_lbl.pack(side=tk.LEFT, padx=8, pady=2)

        close_btn = tk.Label(header, text="✕", font=("Segoe UI", 9, "bold"), fg="#8F96A3", bg="#141724", cursor="hand2")
        close_btn.pack(side=tk.RIGHT, padx=8)
        close_btn.bind("<Button-1>", lambda e: self.hide())

        # Dragging logic
        def start_drag(event):
            self.window.x = event.x
            self.window.y = event.y

        def on_drag(event):
            deltax = event.x - self.window.x
            deltay = event.y - self.window.y
            x = self.window.winfo_x() + deltax
            y = self.window.winfo_y() + deltay
            self.window.geometry(f"+{x}+{y}")

        header.bind("<Button-1>", start_drag)
        header.bind("<B1-Motion>", on_drag)
        title_lbl.bind("<Button-1>", start_drag)
        title_lbl.bind("<B1-Motion>", on_drag)

        # Video canvas
        self.canvas = tk.Canvas(self.window, width=self.width, height=self.height - 24, bg="#0c0e14", highlightthickness=0)
        self.canvas.pack(fill=tk.BOTH, expand=True)

        self.running = True
        self._update_feed()

    def hide(self):
        self.running = False
        if self.window is not None:
            try:
                self.window.destroy()
            except Exception:
                pass
            self.window = None

    def toggle(self):
        if self.window is not None and self.window.winfo_exists():
            self.hide()
            config.show_camera_hud = False
        else:
            self.show()
            config.show_camera_hud = True

    def _update_feed(self):
        if not self.running or self.window is None or not self.window.winfo_exists():
            return

        with self.tracker.frame_lock:
            frame = self.tracker.latest_frame
            landmarks = self.tracker.latest_landmarks
            palm_scale = self.tracker.latest_palm_scale
            pinch_d = self.tracker.latest_pinch_dist
            pinch_thresh = getattr(self.tracker, 'latest_pinch_thresh', 0.035)
            pinch_proximity = getattr(self.tracker, 'latest_pinch_proximity', 0.0)
            right_d = self.tracker.latest_right_dist
            state = self.tracker.latest_gesture_state
            scroll_dir = self.tracker.scroll_direction

        if frame is not None:
            try:
                hud_h = self.height - 24
                hud_w = self.width
                preview = cv2.resize(frame, (hud_w, hud_h))

                if landmarks and len(landmarks) > 0:
                    lm = landmarks[0]
                    
                    # Draw base skeleton connections
                    for start_idx, end_idx in HAND_CONNECTIONS:
                        pt1 = (int(lm[start_idx].x * hud_w), int(lm[start_idx].y * hud_h))
                        pt2 = (int(lm[end_idx].x * hud_w), int(lm[end_idx].y * hud_h))
                        cv2.line(preview, pt1, pt2, (60, 45, 25), 1, cv2.LINE_AA)

                    # Draw landmark joints
                    for i, pt in enumerate(lm):
                        px, py = int(pt.x * hud_w), int(pt.y * hud_h)
                        if i in [4, 8, 12, 16, 20]:
                            cv2.circle(preview, (px, py), 3, (0, 229, 255), -1, cv2.LINE_AA)
                        else:
                            cv2.circle(preview, (px, py), 2, (140, 140, 140), -1, cv2.LINE_AA)

                    p_thumb = (int(lm[4].x * hud_w), int(lm[4].y * hud_h))
                    p_index = (int(lm[8].x * hud_w), int(lm[8].y * hud_h))
                    p_dip = (int(lm[7].x * hud_w), int(lm[7].y * hud_h))
                    p_pip = (int(lm[6].x * hud_w), int(lm[6].y * hud_h))
                    p_mid = (int(lm[12].x * hud_w), int(lm[12].y * hud_h))
                    p_ring = (int(lm[16].x * hud_w), int(lm[16].y * hud_h))

                    # Kinematic Virtual Anchor Point
                    anchor_x = int((lm[8].x * 0.70 + lm[7].x * 0.20 + lm[6].x * 0.10) * hud_w)
                    anchor_y = int((lm[8].y * 0.70 + lm[7].y * 0.20 + lm[6].y * 0.10) * hud_h)

                    # State-Specific Visualizer Overlays
                    if state == "MAXIMIZE":
                        cv2.putText(preview, "MAXIMIZE WINDOW [SWIPE UP]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 255, 100), 1, cv2.LINE_AA)
                    elif state == "MINIMIZE":
                        cv2.putText(preview, "MINIMIZE WINDOW [SWIPE DOWN]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 180, 255), 1, cv2.LINE_AA)
                    elif state == "OPEN_PALM":
                        cv2.putText(preview, "OPEN PALM [UP=MAX | DOWN=MIN]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 229, 255), 1, cv2.LINE_AA)
                    elif state == "LEFT_CLICK":
                        cv2.line(preview, p_thumb, p_index, (0, 255, 100), 3, cv2.LINE_AA)
                        cv2.circle(preview, p_thumb, 5, (0, 255, 100), -1, cv2.LINE_AA)
                        cv2.circle(preview, p_index, 5, (0, 255, 100), -1, cv2.LINE_AA)
                        cv2.putText(preview, "LEFT PINCH [CLICK]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 255, 100), 1, cv2.LINE_AA)
                    elif state == "DRAG":
                        cv2.line(preview, p_thumb, p_index, (0, 165, 255), 4, cv2.LINE_AA)
                        cv2.circle(preview, p_index, 6, (0, 165, 255), -1, cv2.LINE_AA)
                        cv2.circle(preview, p_thumb, 6, (0, 165, 255), -1, cv2.LINE_AA)
                        cv2.putText(preview, "PINCH & MOVE [DRAGGING]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (0, 165, 255), 1, cv2.LINE_AA)
                    elif state == "RIGHT_CLICK":
                        cv2.line(preview, p_thumb, p_mid, (255, 80, 220), 3, cv2.LINE_AA)
                        cv2.circle(preview, p_mid, 5, (255, 80, 220), -1, cv2.LINE_AA)
                        cv2.circle(preview, p_thumb, 5, (255, 80, 220), -1, cv2.LINE_AA)
                        cv2.putText(preview, "RIGHT CLICK [MENU]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.40, (255, 80, 220), 1, cv2.LINE_AA)
                    elif state == "SCROLL":
                        cv2.line(preview, p_thumb, p_ring, (0, 229, 255), 3, cv2.LINE_AA)
                        cv2.circle(preview, p_thumb, 5, (0, 229, 255), -1, cv2.LINE_AA)
                        cv2.circle(preview, p_ring, 5, (0, 229, 255), -1, cv2.LINE_AA)
                        mid_pt = ((p_thumb[0] + p_ring[0]) // 2, (p_thumb[1] + p_ring[1]) // 2)
                        
                        arrow_offset = -12 if "Up" in scroll_dir else (12 if "Down" in scroll_dir else 0)
                        if arrow_offset != 0:
                            cv2.arrowedLine(preview, mid_pt, (mid_pt[0], mid_pt[1] + arrow_offset), (0, 229, 255), 2, tipLength=0.4)
                        cv2.putText(preview, f"RING SCROLL [{scroll_dir}]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (0, 229, 255), 1, cv2.LINE_AA)
                    elif state == "REST":
                        cv2.putText(preview, "PAUSED [FIST CLOSED]", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.38, (80, 80, 255), 1, cv2.LINE_AA)
                    elif state == "APPROACH":
                        cv2.line(preview, p_thumb, p_index, (0, 215, 255), 1, cv2.LINE_AA)
                        cv2.circle(preview, (anchor_x, anchor_y), 4, (0, 215, 255), 1, cv2.LINE_AA)
                        cv2.putText(preview, "APPROACHING PINCH", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 215, 255), 1, cv2.LINE_AA)
                    else: # POINT
                        cv2.circle(preview, (anchor_x, anchor_y), 4, (0, 229, 255), 1, cv2.LINE_AA)
                        cv2.drawMarker(preview, (anchor_x, anchor_y), (0, 229, 255), markerType=cv2.MARKER_CROSS, markerSize=10, thickness=1)
                        cv2.putText(preview, "POINT & HOVER", (8, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.36, (0, 229, 255), 1, cv2.LINE_AA)

                    # Real-Time Pinch Proximity Meter (Bottom Gauge)
                    meter_x1, meter_y1 = 10, hud_h - 12
                    meter_x2, meter_y2 = hud_w - 10, hud_h - 6
                    meter_width = meter_x2 - meter_x1
                    cv2.rectangle(preview, (meter_x1, meter_y1), (meter_x2, meter_y2), (35, 40, 55), -1)
                    
                    fill_w = int(meter_width * pinch_proximity)
                    bar_color = (0, 255, 100) if pinch_proximity >= 0.95 else ((0, 165, 255) if pinch_proximity > 0.65 else (0, 200, 220))
                    if fill_w > 0:
                        cv2.rectangle(preview, (meter_x1, meter_y1), (meter_x1 + fill_w, meter_y2), bar_color, -1)
                    
                    # Threshold notch mark at 50%
                    notch_x = meter_x1 + int(meter_width * 0.70)
                    cv2.line(preview, (notch_x, meter_y1 - 2), (notch_x, meter_y2 + 2), (255, 255, 255), 1)

                rgb = cv2.cvtColor(preview, cv2.COLOR_BGR2RGB)
                img = Image.fromarray(rgb)
                self.photo_img = ImageTk.PhotoImage(image=img)
                self.canvas.create_image(0, 0, image=self.photo_img, anchor=tk.NW)
            except Exception:
                pass

        self.root.after(30, self._update_feed)
