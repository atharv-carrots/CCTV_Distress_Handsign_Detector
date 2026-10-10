import warnings
import os

# --- SUPPRESS BENIGN MACOS / PROTOBUF / TENSORFLOW WARNINGS ---
warnings.filterwarnings("ignore")
os.environ['TF_CPP_MIN_LOG_LEVEL'] = '3'

import cv2
import numpy as np
import mediapipe as mp
import serial
import time
import requests

# --- CONFIGURATION ---
CAMERA_SOURCE = 0  # 0 for Built-in Webcam
CAMERA_ID = "CAM_ZONE_04_NORTH_HALL"

# Static Camera Location Payload
LATITUDE = 19.0760
LONGITUDE = 72.8777
LOCATION_LINK = f"https://maps.google.com/?q={LATITUDE},{LONGITUDE}"

HOLD_DURATION_REQUIRED = 3.0      # Seconds required to confirm distress gesture
PEACE_OUT_HOLD_REQUIRED = 2.5     # Seconds required to trigger Easter Egg photo

# Occlusion / Lens Tamper Settings
OCCLUSION_LUM_THRESH = 15     # Mean brightness cutoff (0-255)
OCCLUSION_TIME_LIMIT = 35.0   # Seconds before flagging camera tamper

# --- TELEGRAM API CONFIGURATION ---
TELEGRAM_BOT_TOKEN =  os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = "to be filled"

# --- MACOS ARDUINO SERIAL BRIDGE ---
SERIAL_PORT = '/dev/cu.usbserial-10'  # Your Mac USB serial path
BAUD_RATE = 9600

try:
    ser = serial.Serial(SERIAL_PORT, BAUD_RATE, timeout=0.1)
    time.sleep(2)
    print(f"[INFO] Hardware Bridge Online on {SERIAL_PORT}!")
except Exception as e:
    ser = None
    print(f"[WARN] Hardware Bridge Offline ({e}). Running in Standalone Simulation Mode.")

# --- MEDIAPIPE INITIALIZATION ---
mp_hands = mp.solutions.hands
mp_drawing = mp.solutions.drawing_utils
hands = mp_hands.Hands(
    max_num_hands=6,               # Detects multiple hands simultaneously
    min_detection_confidence=0.7,
    min_tracking_confidence=0.7
)

cap = cv2.VideoCapture(CAMERA_SOURCE)

# Timers & System State Flags
distress_start_time = None
peace_out_start_time = None
occlusion_start_time = None

distress_confirmed = False
peace_out_confirmed = False

ack_received = False
photo_captured = False           # Single dispatch per distress event
peace_out_photo_captured = False # Single dispatch per peace out event


def draw_y2k_aesthetic_text(frame, text, center_x, y_pos):
    """
    Renders multi-layered Y2K Cyber/Neon Glitch text in pure OpenCV.
    Positioned dynamically with chromatic aberration shadows and core highlights.
    """
    font = cv2.FONT_HERSHEY_TRIPLEX
    scale = 1.05
    thickness = 2

    # Calculate exact text dimensions to auto-center horizontally
    (text_w, text_h), _ = cv2.getTextSize(text, font, scale, thickness)
    x = center_x - (text_w // 2)
    y = y_pos

    # Layer 1: Deep Violet Drop Shadow (+4, +4 offset)
    cv2.putText(frame, text, (x + 4, y + 4), font, scale, (80, 0, 80), thickness + 6, cv2.LINE_AA)
    # Layer 2: Electric Cyan Out-glow (-2, -2 offset)
    cv2.putText(frame, text, (x - 2, y - 2), font, scale, (255, 255, 0), thickness + 3, cv2.LINE_AA)
    # Layer 3: Hot Neon Pink Base
    cv2.putText(frame, text, (x, y), font, scale, (255, 20, 147), thickness + 1, cv2.LINE_AA)
    # Layer 4: Pure White Foreground Highlight
    cv2.putText(frame, text, (x, y), font, scale, (255, 255, 255), 1, cv2.LINE_AA)


def send_telegram_alert(frame_snapshot, event_type="DISTRESS"):
    """
    Dispatches snapshot photo, custom text caption, and native Google Maps pin 
    directly to your Telegram account.
    """
    timestamp = int(time.time())
    
    if event_type == "DISTRESS":
        filename = f"EMERGENCY_SNAP_{timestamp}.jpg"
        caption_text = (
            f"🚨 *SOS EMERGENCY DISTRESS ALERT* 🚨\n\n"
            f"📍 *Camera ID:* `{CAMERA_ID}`\n"
            f"🗺️ *Google Maps Location:*\n{LOCATION_LINK}\n\n"
            f"⚠️ *Status:* Silent Distress Gesture Verified (>3.0s hold)."
        )
    elif event_type == "PEACE_OUT":
        filename = f"PEACE_OUT_SNAP_{timestamp}.jpg"
        caption_text = (
            f"✌️✨ *PEACE OUT GNGG !! EASTER EGG UNLOCKED!* ✨✌️\n\n"
            f"📍 *Camera ID:* `{CAMERA_ID}`\n"
            f"🗺️ *Google Maps Location:*\n{LOCATION_LINK}\n\n"
            f"🎉 *Status:* Peace sign held (>2.5s)! Stay safe, stay stylish! 🚀💥"
        )
    else:  # OCCLUSION / TAMPERING
        filename = f"TAMPER_SNAP_{timestamp}.jpg"
        caption_text = (
            f"⚠️ *CAMERA OCCLUSION / TAMPER ALERT* ⚠️\n\n"
            f"📍 *Camera ID:* `{CAMERA_ID}`\n"
            f"🗺️ *Google Maps Location:*\n{LOCATION_LINK}\n\n"
            f"🚫 *Status:* Camera lens covered or blinded for >35 seconds!"
        )

    cv2.imwrite(filename, frame_snapshot)

    # 1. Dispatch High-Resolution Photo with Caption
    url_photo = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendPhoto"
    try:
        with open(filename, 'rb') as photo:
            payload = {
                'chat_id': TELEGRAM_CHAT_ID,
                'caption': caption_text,
                'parse_mode': 'Markdown'
            }
            files = {'photo': photo}
            response = requests.post(url_photo, data=payload, files=files, timeout=10)

        if response.status_code == 200:
            print(f"[SUCCESS] {event_type} Photo & Location Sent via Telegram!")
        else:
            print(f"[ERROR] Telegram API Error: {response.text}")

    except Exception as e:
        print(f"[FAILED] Could not send Telegram alert: {e}")

    # 2. Dispatch Native Interactive Map Pin
    url_location = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendLocation"
    try:
        loc_payload = {
            'chat_id': TELEGRAM_CHAT_ID,
            'latitude': LATITUDE,
            'longitude': LONGITUDE
        }
        requests.post(url_location, data=loc_payload, timeout=5)
    except Exception as e:
        print(f"[WARN] Failed to send location pin: {e}")


def detect_universal_distress_sign(hand_landmarks):
    """
    Universal Distress Hand Sign (Signal for Help):
    1. Thumb tucked across the palm towards pinky base.
    2. All 4 fingers folded over the thumb.
    """
    lm = hand_landmarks.landmark
    thumb_tip = lm[4]
    pinky_mcp = lm[17]
    index_mcp = lm[5]

    thumb_tucked = abs(thumb_tip.x - pinky_mcp.x) < abs(index_mcp.x - pinky_mcp.x) * 0.8

    index_folded  = lm[8].y > lm[6].y
    middle_folded = lm[12].y > lm[10].y
    ring_folded   = lm[16].y > lm[14].y
    pinky_folded  = lm[20].y > lm[18].y

    return thumb_tucked and index_folded and middle_folded and ring_folded and pinky_folded


def detect_peace_out_sign(hand_landmarks):
    """Easter Egg Gesture: Index & Middle up, Ring & Pinky folded."""
    lm = hand_landmarks.landmark
    i_open = lm[8].y < lm[6].y
    m_open = lm[12].y < lm[10].y
    r_folded = lm[16].y > lm[14].y
    p_folded = lm[20].y > lm[18].y
    return i_open and m_open and r_folded and p_folded


# --- MAIN REAL-TIME VISION LOOP ---
while cap.isOpened():
    ret, frame = cap.read()
    if not ret:
        break

    frame = cv2.flip(frame, 1)
    h, w, _ = frame.shape
    gray_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

    # --- 1. LENS OCCLUSION CHECK ---
    mean_brightness = np.mean(gray_frame)
    if mean_brightness < OCCLUSION_LUM_THRESH:
        if occlusion_start_time is None:
            occlusion_start_time = time.time()
        
        elapsed_occlusion = time.time() - occlusion_start_time
        if elapsed_occlusion >= OCCLUSION_TIME_LIMIT:
            cv2.putText(frame, "WARNING: CAMERA COVERED / TAMPER DETECTED", (20, 80),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
            
            if not photo_captured:
                send_telegram_alert(frame, event_type="OCCLUSION")
                photo_captured = True

            if ser and ser.is_open:
                ser.write(b'O')
    else:
        occlusion_start_time = None

    # --- 2. MULTI-HAND GESTURE PROCESSING ---
    rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
    results = hands.process(rgb_frame)

    raw_distress_detected = False
    peace_out_detected = False

    if results.multi_hand_landmarks:
        for hand_landmarks in results.multi_hand_landmarks:
            mp_drawing.draw_landmarks(frame, hand_landmarks, mp_hands.HAND_CONNECTIONS)

            if detect_universal_distress_sign(hand_landmarks):
                raw_distress_detected = True

            if detect_peace_out_sign(hand_landmarks):
                peace_out_detected = True

    # --- 3. DISTRESS HOLD TIMER LOGIC (3 SECONDS) ---
    if raw_distress_detected:
        if distress_start_time is None:
            distress_start_time = time.time()

        elapsed_hold = time.time() - distress_start_time

        if elapsed_hold >= HOLD_DURATION_REQUIRED:
            distress_confirmed = True
            hold_progress = 1.0
        else:
            hold_progress = elapsed_hold / HOLD_DURATION_REQUIRED
    else:
        distress_start_time = None
        distress_confirmed = False
        photo_captured = False  # Reset capture state when hand drops
        ack_received = False
        hold_progress = 0.0

    # --- 4. PEACE OUT HOLD TIMER LOGIC (2.5 SECONDS) ---
    if peace_out_detected:
        if peace_out_start_time is None:
            peace_out_start_time = time.time()

        elapsed_peace_hold = time.time() - peace_out_start_time

        if elapsed_peace_hold >= PEACE_OUT_HOLD_REQUIRED:
            peace_out_confirmed = True
            peace_out_hold_progress = 1.0
        else:
            peace_out_hold_progress = elapsed_peace_hold / PEACE_OUT_HOLD_REQUIRED
    else:
        peace_out_start_time = None
        peace_out_confirmed = False
        peace_out_photo_captured = False  # Reset capture state when gesture drops
        peace_out_hold_progress = 0.0

    # --- 5. HARDWARE COMMUNICATION & FILE I/O ---
    if raw_distress_detected:
        signal_char = '1'
    elif peace_out_detected:
        signal_char = '2'
    else:
        signal_char = '0'

    if ser and ser.is_open:
        # Transmit binary/state flag to Arduino
        ser.write(signal_char.encode())
        
        # Read Acknowledgement from Arduino Hardware Latch
        if ser.in_waiting > 0:
            try:
                ack = ser.readline().decode().strip()
                if ack in ["ACK_DISPATCH", "ALARM_TRIGGERED"]:
                    ack_received = True
            except Exception:
                pass

    # Backup text stream for Verilog HDL testbench simulation
    with open("gesture_data.txt", "w") as f:
        f.write(f"{signal_char}\n")

    # --- 6. TELEGRAM PHOTO DISPATCH LOGIC ---
    if distress_confirmed and not photo_captured:
        send_telegram_alert(frame, event_type="DISTRESS")
        photo_captured = True

    if peace_out_confirmed and not peace_out_photo_captured:
        send_telegram_alert(frame, event_type="PEACE_OUT")
        peace_out_photo_captured = True

    # --- 7. ONSCREEN HUD & VISUAL FEEDBACK ---
    if raw_distress_detected and not distress_confirmed:
        bar_w = int(300 * hold_progress)
        cv2.rectangle(frame, (20, 50), (320, 70), (50, 50, 50), -1)
        cv2.rectangle(frame, (20, 50), (20 + bar_w, 70), (0, 255, 255), -1)
        cv2.putText(frame, f"HOLD FOR DISTRESS: {elapsed_hold:.1f}s / 3.0s", (20, 42),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    elif distress_confirmed:
        cv2.putText(frame, "🚨 DISTRESS CONFIRMED (TELEGRAM SENT)", (20, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
        cv2.putText(frame, f"LOCATION: {LOCATION_LINK}", (20, 75),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    else:
        status_label = "SYSTEM SAFE [ARDUINO ONLINE]" if (ser and ser.is_open) else "SYSTEM SAFE [STANDALONE MODE]"
        cv2.putText(frame, status_label, (20, 45),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

    # --- 8. Y2K AESTHETIC EASTER EGG HUD OVERLAY ---
    center_x_pos = w // 2
    lower_mid_y_pos = int(h * 0.72)  # Positioned between middle and bottom screen

    if peace_out_detected and not peace_out_confirmed:
        bar_w = int(300 * peace_out_hold_progress)
        cv2.rectangle(frame, (20, 90), (320, 110), (50, 50, 50), -1)
        cv2.rectangle(frame, (20, 90), (20 + bar_w, 110), (255, 20, 147), -1)
        cv2.putText(frame, f"HOLD PEACE OUT: {elapsed_peace_hold:.1f}s / 2.5s", (20, 82),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 20, 147), 2)
        
        # Live aesthetic preview text while holding
        draw_y2k_aesthetic_text(frame, "xXX_ PEACE OUT GNGG _XXx", center_x_pos, lower_mid_y_pos)

    if peace_out_confirmed:
        # Full Y2K aesthetic banner once hold timer completes
        draw_y2k_aesthetic_text(frame, "*+:  PEACE OUT GNGG !!  :+*", center_x_pos, lower_mid_y_pos)

    if ack_received:
        cv2.putText(frame, "HARDWARE LATCH CONFIRMED (ACK_DISPATCH)", (20, h - 30),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)

    cv2.imshow("S.I.G.N.A.L. Security Feed", frame)
    if cv2.waitKey(1) & 0xFF == ord('q'):
        break

cap.release()
cv2.destroyAllWindows()
if ser and ser.is_open:
    ser.close()
