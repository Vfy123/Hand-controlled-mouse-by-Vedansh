# 🖐️ HAND MOUSE - Gesture-Controlled Desktop Cursor

An ultra-sleek, minimalist, and production-ready hand tracking mouse interface for Windows. Control your cursor, click, drag, double-click, scroll, and type on a floating virtual keyboard seamlessly with natural hand gestures in front of your webcam, accompanied by a dynamic top-middle action HUD and expandable control center.

---

## ✨ Features

- **✋ Smart Single-Hand Priority & Dual-Hand Conflict Resolution**:
  - Automatically acquires the first active/gesturing hand and grants it **100% exclusive priority**.
  - Raising your second hand will **never** cause dual-hand attraction, jumping, or misclicks.
  - Lowering your active hand seamlessly hands off control to your other gesturing hand.
- **🗖 Window Minimize & Maximize Gestures**:
  - Open Palm (all 5 fingers spread) swiped **UP** maximizes or restores the active application window.
  - Open Palm (all 5 fingers spread) swiped **DOWN** minimizes the active window to the taskbar.
- **⌨️ Automatic On-Screen Keyboard (Auto-OSK) & Universal Typing**:
  - Automatically pops up a sleek, compact, non-numpad virtual keyboard whenever you focus on a search bar, URL bar, or text input in Google Chrome, Edge, Notepad, Word, etc.
  - Uses dynamic cursor hotspot geometry and hardware scan-code injection to ensure keystrokes type directly into web search bars without stealing focus or deselecting input fields.
- **🎯 Human-Intent Predictive 1-Euro Filter & Kinematic Anchor**:
  - 4-point anatomical finger anchor + calibrated 1-Euro dynamic low-pass filter completely removes sensor noise and hand tremor while delivering zero-latency 1:1 cursor response during fast travel.
- **🔒 Pre-Click Intention Prediction & Dynamic Lock**:
  - Predicts clicks when thumb approaches index finger and freezes the target coordinates to eliminate involuntary index finger twitch/drift.
- **⚡ Non-Linear Ballistic Acceleration Curve**:
  - Automatically switches between **Micro-Aiming Precision Mode** (for 1-pixel targeting on small buttons) and **Saccade Fast Travel** (for reaching monitor edges with effortless hand flicks).
- **⚡ Dynamic Top-Middle Action HUD**:
  - Shows real-time gesture feedback (`🗖 Window Maximized`, `🗕 Window Minimized`, `🎯 Precision Aim`, `⚡ Fast Travel`, `🔒 Click Locked`, `👆 Left Click`, `⚡ Double Click`, `🖱️ Right Click`, `✊ Dragging`, `📜 Scrolling`, `⏸️ Hand Resting`).
  - Double-click the top bar to open the **Control Center** with live sliders and toggles.
- **📷 Floating Skeleton Camera HUD**: Mini PIP camera overlay showing the video feed, tracked hand joints, stabilized virtual anchor reticle, and gesture indicators.

---

## 🖐️ Gesture Reference Guide

| Gesture | Action | Description |
| :--- | :--- | :--- |
| **✋ Primary Hand Lock** | 🔒 **Exclusive Control** | First active hand drives the cursor. Secondary hand movements are completely ignored. |
| **🔄 Lower Hand** | 🔄 **Hand Handoff** | Drop active hand to smoothly hand off control to your other gesturing hand. |
| **👉 Point Index Finger** | 🎯 **Move Cursor** | Point index finger to guide the cursor across the screen with zero micro-jitter. |
| **🤏 Index + Thumb Pinch** | 👆 **Left Click** | Quick pinch and release performs an instant single left click anchored on target. |
| **🗖 Open Palm Swipe UP** | 🗖 **Maximize / Restore** | Spread all 5 fingers and swipe upwards to maximize or restore the active window. |
| **🗕 Open Palm Swipe DOWN** | 🗕 **Minimize Window** | Spread all 5 fingers and swipe downwards to minimize the active window to the taskbar. |
| **⌨️ Focus Search Bar / Text Box** | ⌨️ **Auto-OSK** | Compact on-screen keyboard appears automatically for touchless typing. |
| **⚡ Double Pinch (Index + Thumb)** | ⚡ **Double Click** | Two quick pinches within 380ms triggers a double click. |
| **✊ Hold Pinch (> 250ms)** | ✊ **Drag & Drop** | Keep thumb and index pinched while moving to drag files or windows; release pinch to drop. |
| **✌️ Two-Finger Pinch *or* Active Middle Pinch** | 🖱️ **Right Click** | Touch Index + Middle tips to Thumb, or pinch Middle to Thumb to open context menus. |
| **📜 Ring Finger + Thumb (Pinch / Glide)** | 📜 **Smooth Vertical Scroll** | Pinch ring finger to thumb and glide hand up/down to scroll web pages and documents smoothly. |
| **✊ Closed Fist** | ⏸️ **Pause / Rest Mode** | Close all fingers into a fist to pause cursor movement and rest your hand. |
| **▾ Double-Click Top Bar** | ⚙️ **Open Settings** | Double-click the top bar with your mouse or hand to open sensitivity sliders. |

---

## 🚀 How to Run

1. Run with Python:
```bash
python main.py
```
Or simply double-click `run.bat`.

---

## 🛠️ Requirements & Technology Stack

- **Python 3.11+**
- **MediaPipe Tasks 1.0+** (`hand_landmarker.task`)
- **OpenCV** (`opencv-python`)
- **NumPy**
- **Pillow** & **Tkinter**
- **PyWin32 & Windows ctypes**
