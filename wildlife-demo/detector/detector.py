import os, io, time, base64, asyncio, smtplib, ssl, json
from email.message import EmailMessage

from dotenv import load_dotenv
load_dotenv()

import cv2
from ultralytics import YOLO
from PIL import Image
import websockets

# ----------------------- Config -----------------------
# Camera / model
CAMERA_URL = os.getenv("CAMERA_URL", "0")
CAMERA_URL = 0 if CAMERA_URL == "0" else CAMERA_URL
MODEL_PATH = os.getenv("YOLO_MODEL", "yolov8n.pt")

# WebSocket
WS_HOST = os.getenv("WS_HOST", "127.0.0.1")
WS_PORT = int(os.getenv("WS_PORT", "8765"))

# Email (Gmail app password required)
EMAIL_ON = os.getenv("EMAIL_ON", "true").lower() == "true"
GMAIL_FROM = os.getenv("GMAIL_FROM", "").strip()
GMAIL_TO = [x.strip() for x in os.getenv("GMAIL_TO", "").split(",") if x.strip()]
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "").strip()

# Cooldown & which events should notify (comma list)
ALERT_COOLDOWN_SEC = int(os.getenv("ALERT_COOLDOWN_SEC", "30"))
EMAIL_NOTIFY_FOR = set(a.strip().lower() for a in os.getenv(
    "EMAIL_NOTIFY_FOR", "human,animal,vehicle,weapon"
).split(",") if a.strip())

# Categories (COCO names)
ANIMALS = {
    "bird", "cat", "dog", "horse", "sheep", "cow",
    "elephant", "bear", "zebra", "giraffe"
}
VEHICLES = {"bicycle", "car", "motorcycle", "bus", "truck", "train"}
WEAPONS = {"knife", "scissors", "gun", "pistol", "rifle"}  # not in standard COCO

COLORS = {
    "human": (0, 200, 0),      # Green (BGR)
    "animal": (0, 165, 255),   # Orange
    "vehicle": (255, 0, 0),    # Blue
    "other": (128, 128, 128),  # Gray
}

clients = set()
last_alert_ts = 0

# ----------------------- Utils -----------------------
def encode_frame_b64(bgr):
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    pil = Image.fromarray(rgb)
    buf = io.BytesIO()
    pil.save(buf, format="JPEG", quality=70)
    return base64.b64encode(buf.getvalue()).decode("utf-8")

def can_email():
    return EMAIL_ON and GMAIL_FROM and GMAIL_TO and GMAIL_APP_PASSWORD

def send_email_with_image(subject, body, bgr_frame):
    if not can_email():
        return False
    try:
        ok, enc = cv2.imencode(".jpg", bgr_frame)
        if not ok:
            return False
        img_bytes = enc.tobytes()

        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = GMAIL_FROM
        msg["To"] = ", ".join(GMAIL_TO)
        msg.set_content(body)
        msg.add_attachment(img_bytes, maintype="image", subtype="jpeg", filename="alert.jpg")

        context = ssl.create_default_context()
        with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
            server.login(GMAIL_FROM, GMAIL_APP_PASSWORD)
            server.send_message(msg)

        print("[EMAIL] sent to:", GMAIL_TO, flush=True)
        return True
    except Exception as e:
        print(f"[EMAIL ERROR] {e}", flush=True)
        return False

async def broadcast(payload):
    if not clients:
        return
    data = json.dumps(payload)
    await asyncio.gather(*[c.send(data) for c in list(clients)], return_exceptions=True)

# ------------------- WebSocket handler ----------------
async def ws_handler(websocket):
    clients.add(websocket)
    try:
        async for message in websocket:
            try:
                data = json.loads(message)
            except Exception:
                continue
            cmd = data.get("cmd")
            if cmd == "start":
                source = data.get("source", "webcam")
                path = data.get("path")
                asyncio.create_task(run_detector(source, path))
                await websocket.send(json.dumps({"type":"status","status":"started","source":source}))
            elif cmd == "stop":
                stop_flags["stop"] = True
            elif cmd == "ping":
                await websocket.send(json.dumps({"type":"pong"}))
    finally:
        clients.discard(websocket)

stop_flags = {"stop": False}

# ---------------------- Detector loop -----------------
async def run_detector(source="webcam", path=None):
    global last_alert_ts
    stop_flags["stop"] = False

    # Load model (downloads if not present)
    model = YOLO(MODEL_PATH)

    # Choose capture
    if source == "file" and path:
        cap = cv2.VideoCapture(path)
    elif source == "ipcam" and path:
        cap = cv2.VideoCapture(path)
    else:
        cap = cv2.VideoCapture(CAMERA_URL)

    if not cap.isOpened():
        await broadcast({"type":"status","status":"error","msg":"Cannot open video source"})
        return

    target_w = 960

    while not stop_flags["stop"]:
        ok, frame = cap.read()
        if not ok:
            await asyncio.sleep(0.05)
            break

        # Downscale for speed
        h, w = frame.shape[:2]
        if w > target_w:
            scale = target_w / w
            frame = cv2.resize(frame, (int(w*scale), int(h*scale)))

        results = model(frame, imgsz=640, conf=0.45, verbose=False)[0]
        names = results.names

        # Flags
        human_found = False
        animal_list = []
        vehicle_found = False
        weapon_found = False
        others_count = 0

        draw = frame.copy()

        for box in results.boxes:
            cls_id = int(box.cls)
            conf = float(box.conf)
            label = names.get(cls_id, str(cls_id))
            x1, y1, x2, y2 = map(int, box.xyxy[0].tolist())

            if label == "person":
                group = "human"; human_found = True
            elif label in ANIMALS:
                group = "animal"; animal_list.append(label)
            elif label in VEHICLES:
                group = "vehicle"; vehicle_found = True
            elif label in WEAPONS:
                group = "other"; weapon_found = True
            else:
                group = "other"; others_count += 1

            color = COLORS[group]
            cv2.rectangle(draw, (x1, y1), (x2, y2), color, 2)
            cv2.putText(draw, f"{label} {conf:.2f}", (x1, max(20, y1-6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2, cv2.LINE_AA)

        # Email alert logic (default: ALL) + cooldown
        now = time.time()
        want = (
            (human_found and "human" in EMAIL_NOTIFY_FOR) or
            (animal_list and "animal" in EMAIL_NOTIFY_FOR) or
            (vehicle_found and "vehicle" in EMAIL_NOTIFY_FOR) or
            (weapon_found and "weapon" in EMAIL_NOTIFY_FOR)
        )

        alerted = False
        if want and (now - last_alert_ts > ALERT_COOLDOWN_SEC):
            last_alert_ts = now
            subject = "⚠️ Wildlife Detector Alert"
            parts = []
            if human_found: parts.append("Human")
            if animal_list: parts.append(f"Animals: {', '.join(animal_list)}")
            if vehicle_found: parts.append("Vehicle")
            if weapon_found: parts.append("Weapon-like object")
            body = "Detected -> " + ", ".join(parts)
            alerted = send_email_with_image(subject, body, draw)

        # Send frame to clients
        b64 = encode_frame_b64(draw)
        await broadcast({
            "type": "frame",
            "b64": b64,
            "flags": {
                "human": human_found,
                "animals": animal_list,
                "vehicle": vehicle_found,
                "weapon": weapon_found,
                "others": others_count,
                "alerted": alerted
            }
        })

    cap.release()
    await broadcast({"type":"status","status":"stopped"})

# ------------------------- Main -----------------------
async def main():
    print(f"[WS] starting ws://{WS_HOST}:{WS_PORT}", flush=True)
    async with websockets.serve(ws_handler, WS_HOST, WS_PORT, max_size=8*1024*1024):
        await asyncio.Future()

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except OSError as e:
        print(f"[WS ERROR] {e}", flush=True)
    except KeyboardInterrupt:
        pass
