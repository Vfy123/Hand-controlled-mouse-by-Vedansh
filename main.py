import sys
import os
import signal
import tkinter as tk

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from config import config, config_manager
from engine.mouse_controller import MouseController
from engine.tracker import HandTracker
from engine.caret_detector import CaretDetector
from ui.camera_hud import CameraHUD
from ui.keyboard import VirtualKeyboard
from ui.top_bar import FloatingTopBar

def main():
    print("=" * 65)
    print("  🖐️ HAND MOUSE - Next-Gen Gesture Controlled Interface")
    print("=" * 65)
    print("  • ✋ Single-Hand Priority = 100% Exclusive Lock (No 2-Hand Conflict)")
    print("  • 🔄 Lower Hand = Seamless Handoff to Other Hand")
    print("  • 👉 Point Index Finger = Move Cursor (Zero Micro-Jitter)")
    print("  • 🤏 Pinch Index + Thumb = Left Click (Rock-Solid Anchor Lock)")
    print("  • 🗖 Open Palm Swipe UP = Maximize / Restore Active Window")
    print("  • 🗕 Open Palm Swipe DOWN = Minimize Active Window")
    print("  • ⌨️ Click Search Bar / Input = Auto On-Screen Keyboard Pop-Up")
    print("  • ⚡ Double Pinch Index + Thumb = Double Click")
    print("  • ✊ Hold Pinch Index + Thumb = Drag & Drop")
    print("  • ✌️ 2-Finger Pinch / Active Middle = Right Click (Context Menu)")
    print("  • 📜 Ring Finger + Thumb Pinch = Smooth Vertical Scroll (Glide Up/Down)")
    print("  • ⏸️ Closed Fist = Pause / Rest Mode")
    print("  • ▾ Double-Click Top Bar = Open Settings & Sensitivity Menu")
    print("=" * 65)

    # 1. Initialize Mouse Controller
    mouse = MouseController()

    # 2. Setup Tkinter Root for UI
    root = tk.Tk()
    root.title("Hand Mouse HUD")

    # 3. Create Virtual On-Screen Keyboard
    keyboard = VirtualKeyboard(root=root)

    # 4. Create Vision Tracker
    tracker = HandTracker(mouse_controller=mouse, keyboard=keyboard)

    # 5. Create Camera PIP HUD
    camera_hud = CameraHUD(root=root, tracker=tracker)

    # 6. Create Top Floating Action Bar
    top_bar = FloatingTopBar(root=root, tracker=tracker, camera_hud=camera_hud, keyboard=keyboard)

    # Connect tracker action callback to top bar
    tracker.on_action_update = top_bar.update_action_text

    # 7. Create Windows Caret / Search Bar Click Detector
    def on_show_keyboard(target_hwnd=None):
        root.after(0, lambda: keyboard.show(target_hwnd))

    def on_hide_keyboard():
        root.after(0, keyboard.hide)

    caret_detector = CaretDetector(
        on_show_keyboard=on_show_keyboard,
        on_hide_keyboard=on_hide_keyboard
    )

    # Hook tracker left-clicks to trigger keyboard on search inputs
    def on_hand_click(click_x: int, click_y: int):
        caret_detector.on_click(click_x, click_y, keyboard.get_bounds())

    tracker.on_click_callback = on_hand_click

    # 8. Start Background Services
    tracker.start()
    caret_detector.start()

    # Clean shutdown handler
    def cleanup():
        print("\n[Hand Mouse] Shutting down cleanly...")
        caret_detector.stop()
        tracker.stop()
        camera_hud.hide()
        keyboard.hide()
        try:
            root.destroy()
        except Exception:
            pass
        print("[Hand Mouse] Goodbye!")
        sys.exit(0)

    root.protocol("WM_DELETE_WINDOW", cleanup)
    signal.signal(signal.SIGINT, lambda sig, frame: cleanup())

    # Start UI Event Loop
    try:
        root.mainloop()
    except KeyboardInterrupt:
        cleanup()

if __name__ == "__main__":
    main()
