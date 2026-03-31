# FaceGuard 智慧門禁監控系統

> 基於邊緣運算的 IoT 智慧門禁專案，整合 AI 雙重人臉驗證、活體檢測防詐騙、Streamlit 網頁儀表板、Discord 遠端遙控，以及具備顏文字動畫的 Arduino 實體門鎖。

---

## 目錄

- [專案簡介](#專案簡介)
- [功能特色](#功能特色)
- [系統架構](#系統架構)
- [技術堆疊](#技術堆疊)
- [硬體需求與接線](#硬體需求與接線)
- [安裝指南](#安裝指南)
- [環境變數設定](#環境變數設定-env)
- [使用說明](#使用說明)
- [API 端點參考](#api-端點參考)
- [模組說明](#模組說明)
- [專案目錄結構](#專案目錄結構)

---

## 專案簡介

FaceGuard 是一套完整的邊緣端智慧門禁系統。攝影機擷取到人臉後，系統會先以自訂 ONNX 模型進行**活體檢測**（防止以照片或螢幕欺騙），通過後再以 **InsightFace** 進行人臉特徵比對，確認為白名單成員後才驅動 Arduino 開門。一旦偵測到假臉或陌生人，系統會立刻拍照存證、觸發 Arduino 警報，並透過 **Discord Bot** 推播附圖通知，讓管理員在手機上一鍵核准或拒絕。

---

## 功能特色

**AI 雙重驗證**
- 活體檢測（Anti-Spoofing）：ONNX 模型判斷是否為真實人臉，防止照片/螢幕詐騙
- 人臉識別：InsightFace (buffalo_l) 以餘弦相似度比對特徵向量，閾值 0.65
- 滑動視窗平均分數，避免單幀誤判

**實體硬體控制（Arduino）**
- 步進馬達自動開關門，開門後 5 秒自動上鎖
- SSD1306 OLED 顯示器即時顯示狀態顏文字動畫（待機偷看、WELCOME 開門、生氣警報）
- 蜂鳴器提示音與急促警報音效

**Discord 遠端管理**
- 偵測到陌生人或假臉時，立即附圖推播至指定 Discord 頻道
- 管理員可直接在手機點擊 Approve / Reject 按鈕遠端控制門鎖
- 白名單 Discord 使用者 ID 權限控管

**Streamlit 網頁儀表板**
- 即時進出紀錄（每 5 秒自動刷新）
- 警報事件簿，含自動抓拍的異常影像
- 後台人臉資料庫管理：上傳影片註冊新成員、一鍵刪除人員、手動觸發特徵重建
- 遠端強制開門按鈕

**系統穩定性設計**
- 執行緒鎖 (`model_lock`) 確保監控與後台特徵重建不產生 AI 模型衝突
- 攝影機獨立執行緒串流，避免主迴圈阻塞
- OpenCV 繪製崩潰保護機制，主程式不會因單幀錯誤閃退
- 智慧補光提示（環境亮度低於閾值時顯示白色邊框提示）
- Discord Bot 非同步事件迴圈（`run_in_executor`）避免阻塞 HTTP 請求

---

## 系統架構

```
┌─────────────────────────────────────────────────────┐
│                   使用者端                           │
│   瀏覽器 (Streamlit)      Discord App (手機/電腦)    │
└──────────┬──────────────────────────┬────────────────┘
           │ HTTP (port 5001)          │ Discord API
           ▼                           ▼
┌──────────────────┐        ┌──────────────────────┐
│  FaceGuard       │◄──────►│  discord_bot.py       │
│  Ultimate.py     │  HTTP  │  Flask (port 5002)    │
│  Flask (port 5001│        │  + Discord.py Bot     │
│  + AI Core       │        └──────────────────────┘
│  + Camera Loop   │
└──────────┬───────┘
           │ Serial (UART 9600 bps)
           ▼
┌──────────────────┐
│  Arduino         │
│  OLED + Buzzer   │
│  + Stepper Motor │
└──────────────────┘
```

所有跨模組通訊皆以本機 HTTP API 進行，並以 `X-API-KEY` Header 驗證身分。

---

## 技術堆疊

| 層級 | 技術 |
|------|------|
| AI 活體檢測 | ONNX Runtime（`modelrgb.onnx`，自訓練 RGB 活體模型） |
| AI 人臉辨識 | InsightFace (`buffalo_l`)，餘弦相似度比對 |
| 主程式框架 | Python + Flask（REST API）+ OpenCV（影像串流） |
| 資料庫 | SQLite via SQLAlchemy |
| 網頁儀表板 | Streamlit + streamlit-autorefresh |
| 遠端通知 | Discord.py v2（互動式按鈕元件）|
| 硬體韌體 | Arduino C++，Adafruit_GFX + Adafruit_SSD1306 |
| 設定管理 | python-dotenv |
| 特徵儲存 | NumPy `.npz` 壓縮格式 |

---

## 硬體需求與接線

**主機端（PC）**
- 網路攝影機（USB）
- Arduino（Uno / Nano 等）連接至 COM Port

**Arduino 周邊接線**

| 元件 | 規格 | Arduino 腳位 |
|------|------|-------------|
| OLED 顯示器 | SSD1306 (I2C, 128×64) | SDA → A4，SCL → A5 |
| 蜂鳴器 | 無源或有源蜂鳴器 | 控制腳 → Pin 7 |
| 步進馬達 | 帶驅動板（4線控制） | Pin 8, 9, 10, 11 |

**Arduino 函式庫相依**
- `Adafruit_GFX`
- `Adafruit_SSD1306`

請在 Arduino IDE 的函式庫管理員中安裝上述兩個函式庫，再燒錄 `FaceGuard/FaceGuard.ino`。

---

## 安裝指南

### 1. 建立 Python 虛擬環境（建議）

```bash
python -m venv venv
venv\Scripts\activate
```

### 2. 安裝 Python 相依套件

```bash
pip install opencv-python numpy requests pyserial flask python-dotenv \
            onnxruntime insightface sqlalchemy \
            streamlit streamlit-autorefresh \
            "discord.py[voice]" pandas colorama
```

> 若機器有 NVIDIA GPU，可改安裝 `onnxruntime-gpu` 以啟用 CUDA 加速。

### 3. 確認模型檔案

確保以下兩個 AI 模型已存在：

```
FaceGuard_Project/
├── models/
│   └── buffalo_l/          ← InsightFace 自動下載（首次執行時）
└── modelrgb.onnx           ← 活體檢測模型（需手動放置）
```

### 4. 燒錄 Arduino 韌體

以 Arduino IDE 開啟 `FaceGuard/FaceGuard.ino`，確認已安裝 Adafruit 函式庫後燒錄至 Arduino。

### 5. 建立 `.env` 設定檔

參考下方 [環境變數設定](#環境變數設定-env) 章節。

---

## 環境變數設定 (.env)

在專案根目錄建立 `.env` 檔案：

```env
# ===== 系統安全與 API 通訊 =====
LOCAL_SECRET=your_super_secret_key_here
LOCAL_API=http://127.0.0.1:5001/action
BOT_LOCAL_API=http://127.0.0.1:5002/alert

# ===== Discord Bot 設定 =====
DISCORD_BOT_TOKEN=your_discord_bot_token_here
ALLOWED_DISCORD_USER_IDS=123456789012345678,987654321098765432
ALERT_CHANNEL_ID=your_discord_channel_id_here

# ===== 路徑與資料庫 =====
DB_PATH=faceguard_events.db
IMG_FOLDER=alert_image
DATASET_DIR=dataset
NPZ_PATH=whitelistv2.npz
ONNX_PATH=models/modelrgb.onnx

# ===== 硬體控制 =====
ARDUINO_PORT=COM9
BAUD_RATE=9600
```

| 變數 | 說明 |
|------|------|
| `LOCAL_SECRET` | 所有本機 API 請求的認證金鑰，請設定複雜的隨機字串 |
| `DISCORD_BOT_TOKEN` | 至 Discord Developer Portal 申請 Bot Token |
| `ALLOWED_DISCORD_USER_IDS` | 有權點擊 Approve/Reject 的 Discord 使用者 ID（逗號分隔） |
| `ALERT_CHANNEL_ID` | 接收警報推播的 Discord 頻道 ID |
| `ARDUINO_PORT` | Arduino 的序列埠號（Windows 為 COM#，Linux 為 /dev/ttyUSB#） |

---

## 使用說明

### 一鍵啟動（建議方式）

```bash
python FaceGuard_Launcher.py
```

啟動器會依序執行系統診斷（環境變數、檔案、網路、序列埠），確認無誤後自動啟動：
1. Discord Bot（後台通知服務）
2. Streamlit 儀表板（自動開啟瀏覽器）
3. FaceGuard 主程式（開啟攝影機視窗）

按下 `Ctrl+C` 可同時關閉所有子程序。

---

### 人臉註冊

**方式一：直接在攝影機視窗操作（本機）**

在攝影機視窗中，面對攝影機後按下 `R` 鍵，跳出輸入框填入英文名稱，系統會連續擷取 5 幀特徵取平均值存檔。

**方式二：透過儀表板上傳影片（遠端）**

1. 開啟 Streamlit 儀表板（預設 http://localhost:8501）
2. 進入「人臉資料庫管理」分頁
3. 輸入英文名稱，上傳 MP4/MOV/AVI 影片
4. 系統會每 10 幀取樣一次（最多 15 幀），AI 萃取特徵後自動重建資料庫

---

### 門禁流程

```
攝影機偵測到人臉
    │
    ▼
活體檢測（ONNX）
    ├── 分數 < 0.65 → 假臉警報 → 拍照存證 → Discord 推播 → Arduino 警報音
    │
    └── 分數 ≥ 0.65 → InsightFace 特徵比對
            ├── 相似度 < 0.65 → 陌生人警報 → 拍照存證 → Discord 推播
            │
            └── 相似度 ≥ 0.65 → 辨識成功 → Arduino 開門（10 秒冷卻）
```

---

## API 端點參考

所有 API 請求需在 Header 中帶入 `X-API-KEY: <LOCAL_SECRET>`。

**主程式 API（Port 5001）**

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/action` | 執行門鎖動作，`{"action": "unlock"}` 或 `{"action": "reject"}` |
| GET  | `/api/users` | 取得所有已註冊使用者列表 |
| POST | `/api/upload_video` | 上傳影片註冊新使用者，Form Data: `name`，File: `file` |
| POST | `/api/delete_user` | 刪除使用者，`{"name": "John_Doe"}` |
| POST | `/api/rebuild` | 手動觸發特徵庫全量重建 |

**Discord Bot API（Port 5002）**

| 方法 | 路徑 | 說明 |
|------|------|------|
| POST | `/alert` | 接收主程式的異常警報並推播至 Discord，`{"event_id", "msg", "image_path", "conf"}` |

---

## 模組說明

### `FaceGuard Ultimate.py` — 系統核心

- 執行 OpenCV 攝影機串流（獨立執行緒，避免阻塞）
- AI 推理迴圈（獨立執行緒）：活體檢測 → 人臉識別 → 硬體決策
- Flask 伺服器（獨立執行緒）：接收儀表板與 Discord Bot 的指令
- 以 `model_lock` 確保監控迴圈與後台重建任務不會同時存取 AI 模型
- `DatabaseLogger`：節流寫入 SQLite，避免高頻 I/O

### `dashboard.py` — 網頁監控儀表板

- Streamlit 三分頁介面：即時日誌、警報證據、人臉庫管理
- `streamlit-autorefresh` 前端無阻塞自動刷新（每 5 秒）
- 側邊欄遠端強制開門按鈕

### `discord_bot.py` — Discord 遠端控制

- `discord.py` v2 互動式按鈕（`View` + `Button`）
- Flask Port 5002 接收主程式 HTTP 推播，透過 `run_coroutine_threadsafe` 橋接同步/非同步
- `ALLOWED_DISCORD_USER_IDS` 防止未授權使用者誤操作

### `FaceGuard_Launcher.py` — 一鍵啟動器

- 彩色 ASCII Art 開機畫面（colorama）
- 真實系統診斷：OS 資訊、Python 版本、.env 存在、序列埠掃描、網路連線
- `subprocess.Popen` 管理三個子程序，`Ctrl+C` 統一終止

### `FaceGuard/FaceGuard.ino` — Arduino 韌體（Funny Edition）

- 接收單字元序列指令：`U`（開門）、`A`（警報）、`S`（待機）
- 待機動畫：左看 `( <_< )` → 右看 `( >_> )` → 盯著你 `( O_O ) Watching You`
- 開門動畫：`WELCOME` → 步進馬達逆時針 → 5 秒後自動順時針關門
- 警報動畫：`> A < GET OUT!!` + 蜂鳴器三連發

---

## 專案目錄結構

```
FaceGuard_Project/
├── FaceGuard/
│   └── FaceGuard.ino          # Arduino 韌體（顏文字 Funny Edition）
├── models/
│   └── buffalo_l/             # InsightFace 模型（首次執行自動下載）
├── dataset/                   # 已註冊人員的人臉照片（依姓名分子資料夾）
├── alert_image/               # 系統自動抓拍的異常事件影像
├── .env                       # 環境變數設定（需自行建立，勿提交至版控）
├── FaceGuard Ultimate.py      # 系統主程式（AI 核心 + Flask API + 攝影機）
├── FaceGuard_Launcher.py      # 一鍵啟動腳本
├── dashboard.py               # Streamlit 網頁儀表板
├── discord_bot.py             # Discord 遠端通知與控制 Bot
├── modelrgb.onnx              # 活體檢測 ONNX 模型
├── whitelistv2.npz            # 已壓縮的人臉特徵向量資料庫
└── faceguard_events.db        # SQLite 事件記錄資料庫
```

> **注意**：`.env` 檔案包含私鑰與 Token，請務必加入 `.gitignore`，不要提交至公開版本庫。
