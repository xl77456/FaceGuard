import os, requests, discord
from discord.ext import commands
from discord.ui import View, Button
from dotenv import load_dotenv
import asyncio
import threading
from flask import Flask, request, jsonify

# ================= 1. 環境變數與全域設定 =================
load_dotenv()
DISCORD_BOT_TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LOCAL_SECRET = os.getenv("LOCAL_SECRET")
LOCAL_API = os.getenv("LOCAL_API", "http://127.0.0.1:5001/action")
ALLOWED_DISCORD_USER_IDS = set(map(int, os.getenv("ALLOWED_DISCORD_USER_IDS", "").split(","))) if os.getenv("ALLOWED_DISCORD_USER_IDS") else set()
ALERT_CHANNEL_ID = int(os.getenv("ALERT_CHANNEL_ID", "0"))

# ================= 2. Discord Bot 初始化 =================
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

@bot.event
async def on_ready():
    print(f"✅ Discord Bot 已登入：{bot.user} (id={bot.user.id})")
    print(f"📡 監聽頻道：{ALERT_CHANNEL_ID}")
    print(f"🌐 本地 API: {LOCAL_API}")

# ================= 3. 核心邏輯：發送警報至 Discord =================
async def send_alert_to_discord(event_id: str, msg: str, image_path: str = None):
    channel = bot.get_channel(ALERT_CHANNEL_ID)
    if channel is None:
        try: channel = await bot.fetch_channel(ALERT_CHANNEL_ID)
        except:
            print(f"[ERROR] 找不到頻道 ID: {ALERT_CHANNEL_ID}")
            return

    view = View()
    view.add_item(Button(label="✅ Approve", style=discord.ButtonStyle.success, custom_id=f"approve_{event_id}"))
    view.add_item(Button(label="❌ Reject", style=discord.ButtonStyle.danger, custom_id=f"reject_{event_id}"))

    content = f"{msg}\nEvent ID: `{event_id}`"

    try:
        file = discord.File(image_path, filename="alert.jpg") if image_path and os.path.exists(image_path) else None
        await channel.send(content=content, view=view, file=file)
        print(f"[INFO] 已發送警報訊息至 Discord ({event_id})")
    except Exception as e: print(f"[ERROR] 發送失敗: {e}")

# ================= 4. 互動邏輯：處理按鈕點擊 =================
@bot.event
async def on_interaction(interaction: discord.Interaction):
    try:
        cid = interaction.data.get("custom_id", "")
        if cid.startswith("approve_") or cid.startswith("reject_"):
            event_id = cid.split("_")[1]
            action = "approve" if cid.startswith("approve_") else "reject"
            user_id = str(interaction.user.id)

            if ALLOWED_DISCORD_USER_IDS and int(user_id) not in ALLOWED_DISCORD_USER_IDS:
                await interaction.response.send_message("❌ 你沒有權限執行此操作。", ephemeral=True)
                return

            await interaction.response.send_message(f"⏳ 正在執行 {action}...", ephemeral=True)

            headers = {"X-API-KEY": LOCAL_SECRET, "Content-Type": "application/json"}
            payload = {"action": action} # 與主程式的 action 欄位對齊

            def send_request():
                return requests.post(LOCAL_API, json=payload, headers=headers, timeout=5)

            r = await bot.loop.run_in_executor(None, send_request)
            
            try:
                res = r.json()
                if res.get("ok"):
                    await interaction.followup.send(f"✅ 已執行 `{action}` for event `{event_id}`", ephemeral=True)
                else:
                    await interaction.followup.send(f"❌ 執行失敗: {res.get('error')}", ephemeral=True)
            except: await interaction.followup.send(f"❌ FaceGuard 回應格式錯誤", ephemeral=True)

    except Exception as e: print("[ERROR] on_interaction:", e)

# ================= 5. 本地 API：接收 FaceGuard 觸發通知 =================
flask_app = Flask("discord-bot-api")

@flask_app.route("/alert", methods=["POST"])
def recv_alert():
    data = request.json or {}
    event_id = data.get("event_id")
    msg = data.get("msg")
    image_path = data.get("image_path")
    
    if bot.loop.is_running():
        asyncio.run_coroutine_threadsafe(send_alert_to_discord(event_id, msg, image_path), bot.loop)
        return jsonify({"ok": True, "status": "queued"})
    else:
        return jsonify({"ok": False, "error": "Bot not running"}), 500

def flask_thread():
    # 這裡的 Port 可以從 .env 讀取對應的 BOT_LOCAL_API 中的 Port，但為保持簡單暫時寫死
    flask_app.run(host="127.0.0.1", port=5002, debug=False, use_reloader=False)

if __name__ == "__main__":
    t = threading.Thread(target=flask_thread, daemon=True)
    t.start()
    bot.run(DISCORD_BOT_TOKEN)