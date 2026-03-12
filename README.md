# 🛡️ FaceGuard 智慧門禁監控系統

FaceGuard 是一個基於邊緣運算的物聯網門禁專題，整合了 AI 視覺辨識（人臉特徵比對與活體檢測）、網頁端即時監控儀表板、Discord 遠端互動通知，以及具備互動感與顏文字動畫的實體 Arduino 門鎖設備。

本文件專為開發者與後續維護者撰寫，說明專案的目錄架構、環境變數設定、硬體接線方式、核心模組運作邏輯，以及跨網段的 API 行程間通訊（IPC）機制。

---

## 📂 專案目錄結構

```text
FaceGuard_Project/
├── .vscode/               # VS Code 設定檔
├── alert_image/           # 🚨 系統自動抓拍的異常事件照片存放區 (陌生人/假臉)
├── dataset/               # 🧑‍🤝‍🧑 使用者註冊的原始人臉照片資料夾 (依姓名分類)
├── FaceGuard/             # 🛠️ Arduino 韌體原始碼資料夾
│   └── FaceGuard.ino      # 偷看人特別版 (Funny Edition) 控制程式
├── models/                # AI 模型存放區
├── .env                   # 環境變數設定檔 (Discord Token, API 密鑰等)
├── dashboard.py           # 📊 Streamlit 網頁監控儀表板
├── discord_bot.py         # 🤖 Discord 遠端控制與通知機器人
├── Face_Admin.py          # ⚙️ CLI 後台特徵庫管理工具 (白名單管理)
├── FaceGuard Ultimate.py  # 🧠 系統核心主程式 (AI 視覺、硬體控制、主 API)
├── faceguard_events.db    # 🗄️ SQLite 系統日誌與事件資料庫
├── modelrgb.onnx          # 靜默活體檢測 (Liveness Detection) 模型檔
├── run_system.py          # 🚀 系統一鍵啟動腳本 (統籌啟動各模組)
└── whitelistv2.npz        # 📦 壓縮後的人臉特徵值資料庫
```

---

## ⚙️ 環境變數設定 (.env)

在啟動系統前，請在專案根目錄建立一個 `.env` 檔案，並填入以下環境變數。這對於 Discord 機器人的連線以及各模組間的安全 API 呼叫至關重要：

```env
# ==========================================
# FaceGuard 系統環境變數設定檔 (.env)
# ==========================================

# --- Discord Bot 設定 ---
# 你的 Discord 機器人 Token (請至 Discord Developer Portal 獲取)
DISCORD_BOT_TOKEN="your_discord_bot_token_here"
# 負責接收系統警報的 Discord 頻道 ID
ALERT_CHANNEL_ID="1431642881541673042"
# 允許操作遠端開門的 Discord 使用者 ID (多個請用逗號分隔)
ALLOWED_DISCORD_USER_IDS="123456789012345678,987654321098765432"

# --- 本機端 API 通訊設定 ---
# 系統內部 API 通訊的安全金鑰 (可自訂)
LOCAL_SECRET="my_super_secret_key"
# 主程式 (FaceGuard Ultimate) 接收 Discord 指令的 API 地址
LOCAL_API="[http://127.0.0.1:5001/action](http://127.0.0.1:5001/action)"
# Discord Bot 接收主程式警報的 API 地址
BOT_LOCAL_API="[http://127.0.0.1:5002/alert](http://127.0.0.1:5002/alert)"
```

---

## 🛠️ 硬體架構與接線指南 (Arduino)

本系統實體端採用 Arduino 作為控制器，並搭配周邊元件實現開關門與互動回饋。

| 元件名稱 | 規格型號 | Arduino 腳位連接 |
| :--- | :--- | :--- |
| **OLED 顯示器** | SSD1306 (I2C) | SDA 接 `A4`、SCL 接 `A5` |
| **警報蜂鳴器** | 無源/有源蜂鳴器 | 控制訊號接 `Pin 7` |
| **門鎖驅動馬達** | 步進馬達 (帶驅動板) | 控制訊號接 `Pin 8`, `9`, `10`, `11` |

> **通訊設定**：請確保主機端與 Arduino 的 Serial 傳輸速率設定為 `9600 bps`，並於 `FaceGuard Ultimate.py` 中確認對應的 COM Port（預設為 `COM9`）。

### 🎭 終端設備互動動畫 (Funny Edition)

Arduino 端內建了互動動畫，會根據主程式透過 Serial 傳來的字元指令執行對應動作：

* **待機監視模式 (`S`)**：系統閒置時，OLED 會播放左看 `( <_< )` 與右看 `( >_> )` 動畫，最後盯著前方 `( O_O )` 並顯示 "Watching You"，營造科技監視感。
* **核准通行模式 (`U`)**：OLED 顯示 "WELCOME"，步進馬達逆時針轉動開門，蜂鳴器播放成功提示音。等待 5 秒後自動順時針關門並恢復待機。
* **安全警報模式 (`A`)**：遭遇假臉或陌生人時，OLED 切換成生氣臉 `> A <` 並顯示 "GET OUT!!"。蜂鳴器會發出急促警報聲嚇阻入侵者。

---

## 🧩 軟體核心模組指南

### 1. 系統大腦：`FaceGuard Ultimate.py`
處理影像串流、AI 辨識、硬體通訊與本地端資料庫寫入的運算核心。
* **AI 雙重驗證**：先以 `modelrgb.onnx` 執行活體檢測（防照片詐騙），通過後再交由 `InsightFace` 比對白名單特徵值。
* **多重採樣註冊**：在監控畫面中按下 `R` 鍵，可直接透過視訊鏡頭連續擷取 5 張照片完成快速註冊。
* **語音與硬體連動**：依據 AI 判斷結果，透過 `pyttsx3` 播放語音，並透過 Serial Port 向 Arduino 發送動作指令。

### 2. 特徵庫管理：`Face_Admin.py`
負責處理 `dataset/` 內的人臉照片，萃取特徵並打包成 `whitelistv2.npz`。內建影片匯入、使用者刪除與資料庫重建功能。模型採延遲載入設計以加快啟動速度。

### 3. 網頁監控中心：`dashboard.py`
使用 Streamlit 打造的本地端儀表板。唯讀存取 SQLite 資料庫顯示今日通行數據與抓拍的警報照片，並提供遠端強制開門的 API 控制按鈕。

### 4. 行動通知與決策：`discord_bot.py`
內建 Flask 伺服器監聽主程式發出的異常警報。接收後透過 Discord 發送推播與照片證據，並提供 Approve/Reject 按鈕。點擊後透過非同步機制回傳 API 給主程式，實現跨網段遠端決策閉環。

---

## 🔄 IPC 通訊與資料流向 (API & Serial)

系統中各模組的高度解耦依賴本地端的 Flask API 與 UART 進行溝通：

| 發送方 | 接收方 | 通道 / Endpoint | 方法 | 傳遞內容範例 | 觸發情境 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Dashboard** | **Ultimate (Port 5001)** | HTTP `/action` | `POST` | `{"action": "unlock"}` | 管理員在網頁點擊「遠端開門」。 |
| **Discord Bot** | **Ultimate (Port 5001)** | HTTP `/action` | `POST` | `{"action": "approve"}` | 使用者在 Discord 點擊審核按鈕。 |
| **Ultimate** | **Discord Bot (Port 5002)**| HTTP `/alert` | `POST` | `{"event_id": "123", "msg": "stranger"}` | AI 偵測到活體攻擊或陌生人。 |
| **Ultimate** | **Arduino (COM9)** | UART Serial | `WRITE` | `U`, `A`, 或 `S` | 判斷結果出爐，驅動實體門鎖與 OLED。 |

---

## 🚀 快速啟動指南

1. 確保 Python 虛擬環境已建立，並安裝 `requirements.txt` 中的所有套件。
2. 確認 Arduino 已正確接線並上傳 `FaceGuard.ino`，紀錄 COM Port 號碼並更新於主程式中。
3. 建立並配置妥當 `.env` 檔案。
4. 執行一鍵啟動腳本（或依序手動啟動各模組）：
   ```bash
   python run_system.py
   ```