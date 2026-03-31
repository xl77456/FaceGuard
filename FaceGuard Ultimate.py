import os
import time
import threading
import cv2
import numpy as np
import requests
import serial
import tkinter as tk
import shutil  # [新增] 用於刪除使用者資料夾
from tkinter import simpledialog
from collections import deque
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import onnxruntime as ort
from insightface.app import FaceAnalysis
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from numpy.linalg import norm

# ================= 1. 環境變數與路徑設定 =================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

IMAGE_SAVE_DIR = os.path.join(BASE_DIR, os.getenv("IMG_FOLDER", "alert_image"))
DATASET_DIR = os.path.join(BASE_DIR, os.getenv("DATASET_DIR", "dataset"))
NPZ_PATH = os.path.join(BASE_DIR, os.getenv("NPZ_PATH", "whitelistv2.npz"))

os.makedirs(IMAGE_SAVE_DIR, exist_ok=True)
os.makedirs(DATASET_DIR, exist_ok=True)

_onnx_env = os.getenv("ONNX_PATH", "models/modelrgb.onnx")
ONNX_PATH = os.path.join(BASE_DIR, _onnx_env) if "/" in _onnx_env else os.path.join(BASE_DIR, "models", _onnx_env)
if not os.path.exists(ONNX_PATH):
    ONNX_PATH = os.path.join(BASE_DIR, "modelrgb.onnx")

ARDUINO_PORT = os.getenv("ARDUINO_PORT", "COM9")
BAUD_RATE = int(os.getenv("BAUD_RATE", 9600))
LOCAL_SECRET = os.getenv("LOCAL_SECRET")

# ================= 2. 演算法參數設定 =================
LIVE_THRESHOLD = 0.65       
COSINE_THRESHOLD = 0.65     
REQUIRED_SUCCESS_FRAMES = 1 
CROP_SCALE = 2.5            

ENABLE_LOGGING = True
LOG_INTERVAL = 1  
DOOR_CYCLE_TIME = 10

# [新增] 執行緒鎖：保護 AI 模型，確保監控與後台重建不會發生衝突
model_lock = threading.Lock()

# ================= 3. 資料庫管理 =================
Base = declarative_base()

class SystemEvent(Base):
    __tablename__ = "system_events"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=datetime.now)
    event_type = Column(String)  
    name = Column(String)        
    status = Column(String)      
    confidence = Column(Float)   
    message = Column(String)     
    image_path = Column(String, nullable=True) 

db_file = os.getenv("DB_PATH", "faceguard_events.db")
engine = create_engine(f"sqlite:///{db_file}", echo=False)
Base.metadata.create_all(engine)
Session = sessionmaker(bind=engine)

# ================= 4. 人臉特徵管理與重建邏輯 =================
known_faces = {} 

def load_whitelist_npz(filename):
    global known_faces
    if not os.path.exists(filename):
        print(f"[WARN] 找不到特徵資料庫: {filename} (將於註冊時建立)")
        known_faces = {}
        return
    try:
        print(f"[DB] 正在載入特徵資料庫: {filename} ...")
        data = np.load(filename)
        names, vectors = data['names'], data['embeds']
        known_faces = {} 
        for name, vec in zip(names, vectors):
            if isinstance(name, np.bytes_): name = name.decode('utf-8')
            known_faces[name] = vec
        print(f"[DB] 資料庫載入完成！共 {len(known_faces)} 位使用者")
    except Exception as e: print(f"[DB ERROR] 載入失敗: {e}")

def rebuild_database_logic():
    """ [新增] 由 API 觸發的後台資料庫重建邏輯 """
    print(f"\n🔄 [後台任務] 正在重建資料庫 ({NPZ_PATH})...")
    users = [d for d in os.listdir(DATASET_DIR) if os.path.isdir(os.path.join(DATASET_DIR, d))]
    names, embeddings = [], []
    
    for user in users:
        user_dir = os.path.join(DATASET_DIR, user)
        imgs = [f for f in os.listdir(user_dir) if f.lower().endswith(('.jpg','.png','.jpeg'))]
        vectors = []
        
        for img_file in imgs:
            img = cv2.imread(os.path.join(user_dir, img_file))
            if img is None: continue
            
            # [關鍵] 使用 model_lock 確保不與主監控迴圈衝突
            with model_lock:
                faces = app_face.get(img)
                
            if faces:
                face = max(faces, key=lambda x: (x.bbox[2]-x.bbox[0]) * (x.bbox[3]-x.bbox[1]))
                vectors.append(face.embedding)
                
        if vectors:
            avg_vec = np.mean(vectors, axis=0)
            avg_vec = avg_vec / np.linalg.norm(avg_vec)
            names.append(user)
            embeddings.append(avg_vec)
            
    np.savez_compressed(NPZ_PATH, names=np.array(names), embeds=np.array(embeddings))
    load_whitelist_npz(NPZ_PATH)  # 重新載入記憶體
    print(f"🎉 [後台任務] 更新完成！共 {len(names)} 位使用者。")
    return True

def save_new_face(name, embedding, frame_image):
    global known_faces
    try:
        current_names, current_embeds = [], []
        if os.path.exists(NPZ_PATH):
            data = np.load(NPZ_PATH, allow_pickle=True)
            current_names, current_embeds = data['names'].tolist(), data['embeds'].tolist()
        
        current_names = [str(n) if not isinstance(n, str) else n for n in current_names]
        if name in current_names:
            idx = current_names.index(name)
            current_embeds[idx] = embedding
        else:
            current_names.append(name)
            current_embeds.append(embedding)
        
        np.savez_compressed(NPZ_PATH, names=np.array(current_names), embeds=np.array(current_embeds))
        known_faces[name] = embedding

        user_folder = os.path.join(DATASET_DIR, name)
        os.makedirs(user_folder, exist_ok=True)
        cv2.imwrite(os.path.join(user_folder, f"{name}_{int(time.time())}.jpg"), frame_image)
        return True
    except Exception as e:
        print(f"[REGISTER ERROR] {e}")
        return False

def find_best_match(current_embedding, threshold=0.65):
    max_score, best_name = 0.0, "Unknown"
    if len(known_faces) == 0: return "Unknown", 0.0
    for name, saved_embedding in known_faces.items():
        score = np.dot(current_embedding, saved_embedding) / (norm(current_embedding) * norm(saved_embedding))
        if score > max_score: max_score, best_name = score, name
    return best_name if max_score >= threshold else "Unknown", max_score

# ================= 5. Arduino & DB Logger =================
class ArduinoController:
    def __init__(self, port, baud):
        self.ser = None
        try:
            self.ser = serial.Serial(port, baud, timeout=1)
            time.sleep(2)
            print(f"[SERIAL] Arduino 已連線！({port})")
            self.send_command("STANDBY")
        except:
            print(f"[SERIAL] 無法連線 Arduino (模擬模式)")

    def send_command(self, action):
        if not self.ser: return
        try:
            cmd_char = None
            act = str(action).upper()
            if "UNLOCK" in act: cmd_char = b'U'
            elif "LOCK" in act: cmd_char = b'L'
            elif "ALERT" in act: cmd_char = b'A'
            elif "STANDBY" in act: cmd_char = b'S'
            if cmd_char: self.ser.write(cmd_char)
        except Exception as e: print(f"[SERIAL ERROR] {e}")

arduino_ctrl = ArduinoController(ARDUINO_PORT, BAUD_RATE)

class DatabaseLogger:
    def __init__(self):
        self.enabled = ENABLE_LOGGING
        self.last_log_time = 0

    def log(self, live_score, name, id_score, status, hw_state):
        if not self.enabled or status in ["NO FACE", "SCANNING"]: return 
        if time.time() - self.last_log_time < LOG_INTERVAL: return
        try:
            session = Session()
            final_status = "PASS" if status == "REAL" else "DENIED" if status == "FAKE" else status
            current_type = "ENTRY" if hw_state == "UNLOCK" else "LOG"
            session.add(SystemEvent(event_type=current_type, name=str(name), status=final_status,
                confidence=float(id_score), message=f"Liveness: {live_score:.2f}"))
            session.commit(); session.close()
            self.last_log_time = time.time()
        except Exception as e: print(f"[LOG ERROR] {e}")

logger = DatabaseLogger()

# ================= 6. CamStream & AI Model =================
class CamStream:
    def __init__(self, src=0):
        self.lock = threading.Lock()
        self.stopped = False
        self.frame = None
        self.stream = cv2.VideoCapture(src, cv2.CAP_DSHOW)
        self.stream.set(3, 640); self.stream.set(4, 480); self.stream.set(5, 30)
        
        # [優化] 給攝影機 0.5 秒暖機時間，避免太快讀取導致失敗
        time.sleep(0.5)
        (grabbed, self.frame) = self.stream.read()
        if not grabbed:
            print(f"[WARN] 攝影機初始讀取失敗 (src={src})，可能是被 OBS 或其他程式佔用。")

    def start(self):
        if not self.stopped: threading.Thread(target=self.update, daemon=True).start()
        return self

    def update(self):
        while not self.stopped:
            if not self.stream.isOpened(): continue
            (grabbed, frame) = self.stream.read()
            if grabbed:
                with self.lock: self.frame = frame
            else: 
                time.sleep(0.01) # 若讀取失敗則稍微等待再試

    def read(self):
        with self.lock: return self.frame.copy() if self.frame is not None else None

    def stop(self):
        self.stopped = True; self.stream.release()

class LivenessModelONNX:
    def __init__(self, model_path):
        self.sess = ort.InferenceSession(model_path, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.input_name = self.sess.get_inputs()[0].name
        shp = self.sess.get_inputs()[0].shape
        self.h, self.w = int(shp[-2]) or 80, int(shp[-1]) or 80
        
    def score(self, img):
        img = cv2.resize(img, (self.w, self.h)).astype(np.float32)
        inp = ((img - 127.5) / 128.0).transpose(2, 0, 1)[None, ...]
        o = self.sess.run(None, {self.input_name: inp})[0]
        e = np.exp(o - np.max(o, axis=1, keepdims=True))
        return float((e / np.sum(e, axis=1, keepdims=True))[0, 1])

live_model = LivenessModelONNX(ONNX_PATH)
app_face = FaceAnalysis(name='buffalo_l', root=BASE_DIR, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
app_face.prepare(ctx_id=0, det_size=(640, 640))
load_whitelist_npz(NPZ_PATH)

# ================= 7. Flask & Admin API =================
def process_alert(frame, msg, confidence=0.0):
    event_id = str(int(time.time() * 1000))
    img_full_path = os.path.join(IMAGE_SAVE_DIR, f"alert_{event_id}.jpg")
    cv2.imwrite(img_full_path, frame)
    try:
        session = Session()
        e_type = "FAKE_FACE" if "假臉" in msg else "STRANGER"
        session.add(SystemEvent(event_type="ALERT", name="Unknown", status=e_type,
            confidence=float(confidence), message=msg, image_path=img_full_path))
        session.commit(); session.close() 
    except Exception as e: print(f"[DB ERROR] {e}")

    bot_api = os.getenv("BOT_LOCAL_API", "http://127.0.0.1:5002/alert")
    threading.Thread(target=lambda: requests.post(bot_api, json={"event_id": event_id, "msg": msg, "image_path": img_full_path, "conf": confidence}, timeout=5).status_code).start()
    return event_id

app_flask = Flask(__name__)

def check_auth():
    return request.headers.get('X-API-KEY') == LOCAL_SECRET

@app_flask.route("/action", methods=["POST"])
def action():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 403
    act = str((request.json or {}).get("action")).lower()
    if act in ("approve", "unlock"): threading.Thread(target=arduino_ctrl.send_command, args=("UNLOCK",)).start()
    elif act in ("reject", "deny", "block"): threading.Thread(target=arduino_ctrl.send_command, args=("ALERT",)).start()
    return jsonify({"ok": True})

@app_flask.route("/api/users", methods=["GET"])
def get_users():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 403
    users = [d for d in os.listdir(DATASET_DIR) if os.path.isdir(os.path.join(DATASET_DIR, d))]
    return jsonify({"users": sorted(users)})

@app_flask.route("/api/delete_user", methods=["POST"])
def delete_user():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 403
    name = request.json.get("name")
    if name:
        # 1. 刪除該使用者的照片資料夾
        shutil.rmtree(os.path.join(DATASET_DIR, name), ignore_errors=True)
        
        # 2. [優化] 光速刪除法：直接從 .npz 特徵檔中移除該人員，不重新跑 AI 運算
        if os.path.exists(NPZ_PATH):
            data = np.load(NPZ_PATH, allow_pickle=True)
            current_names, current_embeds = data['names'].tolist(), data['embeds'].tolist()
            
            # 將名稱轉為普通字串以利比對
            current_names_str = [str(n) if not isinstance(n, str) else n for n in current_names]
            
            if name in current_names_str:
                idx = current_names_str.index(name)
                current_names_str.pop(idx)
                current_embeds.pop(idx)
                
                # 重新存檔
                np.savez_compressed(NPZ_PATH, names=np.array(current_names_str), embeds=np.array(current_embeds))
                # 讓 AI 重新讀取最新的特徵庫進記憶體
                load_whitelist_npz(NPZ_PATH)
                
        return jsonify({"ok": True})
    return jsonify({"error": "Missing name"}), 400

@app_flask.route("/api/upload_video", methods=["POST"])
def upload_video():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 403
    if 'file' not in request.files or 'name' not in request.form:
        return jsonify({"error": "Missing parameters"}), 400
    
    file, name = request.files['file'], request.form['name'].strip()
    temp_path = os.path.join(BASE_DIR, f"temp_{int(time.time())}.mp4")
    file.save(temp_path)
    
    try:
        save_folder = os.path.join(DATASET_DIR, name)
        os.makedirs(save_folder, exist_ok=True)
        cap = cv2.VideoCapture(temp_path)
        count, saved = 0, 0
        
        while True:
            ret, frame = cap.read()
            if not ret: break
            if count % 10 == 0: 
                cv2.imwrite(os.path.join(save_folder, f"{name}_{int(time.time()*1000)}_{count}.jpg"), frame)
                saved += 1
                if saved >= 15: break
            count += 1
            
        cap.release()
        os.remove(temp_path) 
        
        rebuild_database_logic() 
        return jsonify({"ok": True, "saved_frames": saved})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app_flask.route("/api/rebuild", methods=["POST"])
def manual_rebuild():
    if not check_auth(): return jsonify({"error": "Unauthorized"}), 403
    rebuild_database_logic()
    return jsonify({"ok": True})

def run_flask(): 
    app_flask.run(host="127.0.0.1", port=5001, debug=False, threaded=True)

# ================= 8. AI Loop =================
shared_data = {"frame": None, "result": {"liveness": "SCANNING", "color_live": (200,200,200), "name": "", "color_white": (0,0,255), "bbox": None, "live_conf": 0.0, "id_conf": 0.0, "hw_state": "IDLE", "embedding": None}, "is_registering": False}
ai_lock = threading.Lock()

def ai_loop_worker():
    score_window = deque(maxlen=10)
    alert_cooldown, last_alert_time, consecutive_success, last_unlock_time = 10, 0, 0, 0 
    print(f"[INFO] AI 核心啟動")

    while True:
        with ai_lock: 
            frame, is_reg_mode = shared_data["frame"], shared_data.get("is_registering", False)

        if frame is None: time.sleep(0.01); continue

        try:
            rgb, (h_frame, w_frame) = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB), frame.shape[:2]
            
            with model_lock:
                faces = app_face.get(frame)

            liveness_state, detected_name, color_live, color_white, final_bbox, current_embedding = "NO FACE", "", (0, 0, 255), (0, 0, 255), None, None
            is_alert, alert_msg, id_conf, current_conf, is_pass, hw_state, alert_conf_val = False, "", 0.0, 0.0, False, "IDLE", 0.0

            if faces:
                f = max(faces, key=lambda x:(x.bbox[2]-x.bbox[0])*(x.bbox[3]-x.bbox[1]))
                bbox = f.bbox.astype(np.int32)
                final_bbox, current_embedding = bbox, f.embedding

                cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
                crop_size = max(bbox[2] - bbox[0], bbox[3] - bbox[1]) * CROP_SCALE
                x1, y1 = max(0, int(cx - crop_size / 2)), max(0, int(cy - crop_size / 2))
                x2, y2 = min(w_frame, int(cx + crop_size / 2)), min(h_frame, int(cy + crop_size / 2))
                face_crop = rgb[y1:y2, x1:x2]
                
                if face_crop.size > 0:
                    score = live_model.score(face_crop)
                    score_window.append(score)
                    current_conf = float(np.mean(score_window))

                    if current_conf >= LIVE_THRESHOLD:
                        liveness_state, color_live = "REAL", (0, 255, 0)
                        name, similarity = find_best_match(f.embedding, threshold=COSINE_THRESHOLD)
                        id_conf = float(similarity)

                        if name != "Unknown":
                            detected_name, color_white, is_pass = name, (0, 255, 0), True
                        else:
                            detected_name, color_white = "UNKNOWN", (0, 0, 255)
                            if not is_reg_mode: is_alert, alert_msg, alert_conf_val = True, "⚠️ 陌生人", id_conf
                    else:
                        liveness_state, color_live = "FAKE", (0, 0, 255)
                        if not is_reg_mode: is_alert, alert_msg, alert_conf_val = True, "🚨 假臉攻擊", current_conf
            
            if is_reg_mode:
                hw_state = "REGISTRATION"
            else:
                if (time.time() - last_unlock_time) < DOOR_CYCLE_TIME:
                    hw_state, consecutive_success = "CLOSING", 0 
                    if detected_name: detected_name += " (WAIT)"
                else:
                    if is_pass:
                        consecutive_success += 1
                        if consecutive_success >= REQUIRED_SUCCESS_FRAMES:
                            print(f"[OPEN] {detected_name} (Score: {id_conf:.2f})")
                            threading.Thread(target=arduino_ctrl.send_command, args=("UNLOCK",)).start()
                            last_unlock_time, detected_name, hw_state, consecutive_success = time.time(), detected_name + " (OPEN)", "UNLOCK", 0
                    else: consecutive_success = 0

                if is_alert and hw_state != "CLOSING":
                    hw_state = "ALERT"
                    if (time.time() - last_alert_time > alert_cooldown):
                        print(f"[ALERT] {alert_msg}")
                        process_alert(frame.copy(), alert_msg, confidence=alert_conf_val)
                        threading.Thread(target=arduino_ctrl.send_command, args=("ALERT",)).start()
                        last_alert_time = time.time()

            with ai_lock:
                shared_data["result"] = {"liveness": liveness_state, "color_live": color_live, "name": detected_name, "color_white": color_white, "bbox": final_bbox, "live_conf": current_conf, "id_conf": id_conf, "hw_state": hw_state, "embedding": current_embedding}
        except Exception as e: print(f"[AI ERROR] {e}")

# ================= 9. Main =================
def get_user_name_popup():
    root = tk.Tk()
    root.withdraw(); root.attributes("-topmost", True)
    name = simpledialog.askstring("FaceGuard 註冊", "請輸入新使用者名稱 (英文):", parent=root)
    root.destroy()
    return name if name else ""

def main():
    threading.Thread(target=run_flask, daemon=True).start()
    threading.Thread(target=ai_loop_worker, daemon=True).start()
    
    print("[INFO] 正在初始化攝影機...")
    cam = CamStream(0).start()
    print(f"[INFO] FaceGuard Ultimate v9.2 (防崩潰與鏡頭重連機制)")

    prev_time = time.time() 
    empty_frame_count = 0
    
    try:
        while True:
            frame = cam.read()
            # [除錯機制] 如果抓不到畫面，不要死當，印出警告給使用者
            if frame is None:
                empty_frame_count += 1
                if empty_frame_count % 100 == 0:
                    print("[WARN] 等待攝影機畫面中... (請確認鏡頭未被其他程式佔用)")
                time.sleep(0.05)
                continue
                
            empty_frame_count = 0 # 成功抓到畫面就歸零
            
            try:
                with ai_lock: 
                    shared_data["frame"] = frame.copy()
                    res = shared_data["result"]

                # --- 智能補光機制 ---
                avg_brightness = np.mean(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY))
                h, w = frame.shape[:2]
                if avg_brightness < 50:
                    cv2.rectangle(frame, (0,0), (w,h), (255,255,255), 20)
                    cv2.putText(frame, "LIGHTING...", (w//2-80, h-50), cv2.FONT_HERSHEY_SIMPLEX, 1, (255,255,255), 2)

                # --- 繪製人臉框 ---
                if res["bbox"] is not None:
                    x1, y1, x2, y2 = res["bbox"]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), res["color_white"], 2)
                    text_content = res['name'] if res['name'] else res['liveness']
                    color = res["color_white"] if res['name'] else res["color_live"]
                    cv2.rectangle(frame, (x1, y1-30), (x1+200, y1), color, -1)
                    cv2.putText(frame, text_content, (x1+5, y1-5), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,0,0), 2)

                # --- FPS 計算 ---
                curr = time.time()
                fps = 1 / (curr - prev_time) if (curr - prev_time) > 0 else 0
                prev_time = curr 
                
                cv2.rectangle(frame, (0,0), (w, 50), (0,0,0), -1)
                cv2.putText(frame, f"FPS: {int(fps)} | Live: {res['live_conf']:.2f} | ID: {res['id_conf']:.2f}", (10, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0,255,255), 2)
                
                # --- 狀態標示 ---
                hw_state = res.get('hw_state', 'IDLE')
                if hw_state == "UNLOCK":
                    cv2.circle(frame, (w-30, 25), 15, (0, 255, 0), -1); cv2.putText(frame, "OPEN", (w-110, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)
                elif hw_state == "ALERT":
                    cv2.circle(frame, (w-30, 25), 15, (0, 0, 255), -1); cv2.putText(frame, "ALARM", (w-120, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                elif hw_state == "REGISTRATION":
                    cv2.circle(frame, (w-30, 25), 15, (0, 255, 255), -1); cv2.putText(frame, "REG...", (w-110, 35), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 255), 2)

                logger.log(res['live_conf'], res['name'], res['id_conf'], res['liveness'], hw_state)
                cv2.putText(frame, "Press 'R' to Register", (10, h-10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150,150,150), 2)
                cv2.imshow("FaceGuard Ultimate", frame)
                
                k = cv2.waitKey(1) & 0xFF
                if k == 27: break
                
                # --- 註冊模式 ---
                if k in (ord('r'), ord('R')) and res["embedding"] is not None:
                    with ai_lock: shared_data["is_registering"] = True
                    print("\n" + "="*40 + "\n  【 多重採樣註冊模式 】(已暫停警報)\n" + "="*40)
                    try:
                        new_name = get_user_name_popup()
                        if new_name:
                            print(f">>> 準備開始擷取 {new_name}... 請稍微轉動頭部")
                            collected_embeddings = []
                            for i in range(5):
                                temp_frame = frame.copy()
                                cv2.rectangle(temp_frame, (0, h//2 - 50), (w, h//2 + 50), (0,0,0), -1)
                                cv2.putText(temp_frame, f"Capturing {i+1}/5...", (w//2 - 150, h//2 + 10), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (0,255,255), 2)
                                cv2.imshow("FaceGuard Ultimate", temp_frame); cv2.waitKey(500) 
                                with ai_lock:
                                    current_emb = shared_data["result"]["embedding"]
                                    if current_emb is not None: collected_embeddings.append(current_emb)
                            if collected_embeddings:
                                save_new_face(new_name, np.mean(collected_embeddings, axis=0) / norm(np.mean(collected_embeddings, axis=0)), frame)
                                print(f"[INFO] 註冊完成！")
                    except Exception as e: print(f"[ERROR] 註冊時發生錯誤: {e}")
                    finally:
                        with ai_lock: shared_data["is_registering"] = False
                        print("="*40 + "\n[INFO] 恢復正常監控模式")

            # [新增] 崩潰捕捉器：如果 OpenCV 繪製失敗，印出錯誤但不會閃退
            except Exception as loop_e:
                print(f"[MAIN LOOP ERROR] 畫面繪製時發生錯誤: {loop_e}")
                time.sleep(1) 

    except KeyboardInterrupt: pass
    finally: cam.stop(); cv2.destroyAllWindows()

if __name__ == "__main__": main()