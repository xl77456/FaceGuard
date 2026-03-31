import streamlit as st
import sqlite3
import pandas as pd
import os
import time
import requests
from dotenv import load_dotenv
from streamlit_autorefresh import st_autorefresh

# ================= 1. 環境變數與全域設定 =================
load_dotenv()
LOCAL_SECRET = os.getenv("LOCAL_SECRET", "default_secret")

st.set_page_config(page_title="FaceGuard 監控中心", page_icon="🛡️", layout="wide")

DB_PATH = os.getenv("DB_PATH", "faceguard_events.db")
IMG_FOLDER = os.getenv("IMG_FOLDER", "alert_image")

# 解析 API 基礎位址供管理模組使用
API_URL = os.getenv("LOCAL_API", "http://127.0.0.1:5001/action")
API_BASE = API_URL.rsplit('/', 1)[0] # 將 /action 截斷，取得 http://127.0.0.1:5001

# ================= 2. 資料庫存取模組 =================
def load_data():
    if not os.path.exists(DB_PATH): return pd.DataFrame() 
    conn = sqlite3.connect(DB_PATH)
    df = pd.read_sql_query("SELECT * FROM system_events ORDER BY timestamp DESC", conn)
    conn.close()
    return df

# ================= 3. 主畫面與側邊欄 =================
st.title("🛡️ FaceGuard 智慧門禁監控中心")
st.markdown("---")

with st.sidebar:
    st.header("控制台")
    if st.button("🔄 立即刷新資料", use_container_width=True): st.rerun()
    auto_refresh = st.checkbox("開啟自動刷新 (每 5 秒)")
    if auto_refresh: st_autorefresh(interval=5000, limit=None, key="data_refresh")

    st.markdown("---")
    st.header("🎮 遠端操作")
    if st.button("🚪 遠端強制開門", type="primary", use_container_width=True):
        try:
            res = requests.post(API_URL, json={"action": "unlock"}, headers={"X-API-KEY": LOCAL_SECRET}, timeout=2)
            if res.status_code == 200: st.success("✅ 指令已發送！")
            else: st.error("❌ 發送失敗或拒絕存取")
        except: st.error("❌ 無法連線至主機")

# ================= 4. 數據分析與視覺化 =================
df = load_data()

if df.empty:
    st.warning("⚠️ 目前資料庫中沒有資料，請先執行 FaceGuard 主程式。")
else:
    col1, col2, col3, col4 = st.columns(4)
    df['timestamp'] = pd.to_datetime(df['timestamp'])
    df_today = df[df['timestamp'].dt.strftime('%Y-%m-%d') == pd.Timestamp.now().strftime('%Y-%m-%d')]
    
    with col1: st.metric("總通行次數", len(df[df['event_type'] == 'ENTRY']))
    with col2: st.metric("今日通行", len(df_today[df_today['event_type'] == 'ENTRY']), delta="本日")
    with col3: st.metric("今日警報/攔截", len(df_today[df_today['event_type'] == 'ALERT']), delta_color="inverse")
    with col4: st.metric("最後通行", df[df['event_type'] == 'ENTRY'].iloc[0]['name'] if not df[df['event_type'] == 'ENTRY'].empty else "無")

    st.markdown("---")

    # --- [新增] 分頁 3：人臉資料庫管理 ---
    tab1, tab2, tab3 = st.tabs(["📋 即時進出紀錄", "🚨 警報與抓拍證據", "⚙️ 人臉資料庫管理 (後台)"])

    with tab1:
        st.subheader("系統活動日誌 (Live Logs)")
        display_df = df[['timestamp', 'event_type', 'name', 'status', 'confidence', 'message']].head(50)
        st.dataframe(display_df.style.map(lambda v: f"color: {'green' if v=='PASS' else 'red' if v=='DENIED' else 'orange'}; font-weight: bold", subset=['status']), use_container_width=True, height=600)

    with tab2:
        st.subheader("⚠️ 安全警報事件簿")
        alerts = df[df['event_type'] == 'ALERT']
        if alerts.empty: st.success("目前沒有任何安全警報事件。")
        else:
            for _, row in alerts.iterrows():
                c1, c2 = st.columns([1, 3])
                with c1:
                    if os.path.exists(row['image_path'] or ""): st.image(row['image_path'], width=250)
                with c2:
                    st.error(f"事件時間: {row['timestamp']}"); st.write(f"**類型:** {row['status']} | **訊息:** {row['message']} | **信心分數:** {row['confidence']:.2f}")
                st.markdown("---")

    with tab3:
        st.subheader("後台特徵庫管理")
        st.info("💡 在此處上傳的影片與指令，將直接交由主機端的 AI 背景處理，不影響大門監控效能。")
        
        c_reg, c_del = st.columns(2)
        
        # 1. 新增使用者 (上傳影片)
        with c_reg:
            st.markdown("#### ➕ 註冊新使用者")
            new_name = st.text_input("使用者英文名稱", placeholder="例如: John_Doe")
            video_file = st.file_uploader("拖曳上傳人臉影片", type=["mp4", "mov", "avi"])
            
            if st.button("上傳並進行特徵萃取", type="primary", use_container_width=True):
                if not new_name or not video_file:
                    st.warning("請填寫名稱並上傳影片檔。")
                else:
                    with st.spinner("⏳ 正在背景萃取特徵並重建資料庫 (約需 10~30 秒，請勿重整)..."):
                        try:
                            files = {"file": (video_file.name, video_file.getvalue(), video_file.type)}
                            res = requests.post(f"{API_BASE}/api/upload_video", headers={"X-API-KEY": LOCAL_SECRET}, data={"name": new_name}, files=files, timeout=600)
                            if res.status_code == 200 and res.json().get("ok"):
                                st.success(f"✅ 註冊成功！已擷取 {res.json().get('saved_frames')} 張有效特徵。")
                            else: st.error(f"❌ 處理失敗: {res.text}")
                        except Exception as e: st.error(f"❌ 發生錯誤: {e}")

        # 2. 刪除使用者
        with c_del:
            st.markdown("#### 🗑️ 刪除使用者")
            try:
                user_res = requests.get(f"{API_BASE}/api/users", headers={"X-API-KEY": LOCAL_SECRET}, timeout=3)
                user_list = user_res.json().get("users", []) if user_res.status_code == 200 else []
            except: user_list = []
            
            del_target = st.selectbox("選擇要刪除的人員", ["(請選擇)"] + user_list)
            if st.button("刪除人員並更新資料庫", use_container_width=True):
                if del_target == "(請選擇)": st.warning("請先選擇人員。")
                else:
                    with st.spinner(f"⏳ 正在刪除 {del_target} 並重建特徵庫..."):
                        try:
                            res = requests.post(f"{API_BASE}/api/delete_user", headers={"X-API-KEY": LOCAL_SECRET}, json={"name": del_target}, timeout=60)
                            if res.status_code == 200:
                                st.success(f"✅ 已成功刪除 {del_target}！")
                                time.sleep(1); st.rerun()
                            else: st.error("❌ 刪除失敗")
                        except Exception as e: st.error(f"❌ 發生錯誤: {e}")
            
            st.markdown("#### 🔄 強制校正")
            if st.button("手動觸發資料庫重建", use_container_width=True):
                with st.spinner("⏳ 正在重新運算特徵庫..."):
                    try:
                        res = requests.post(f"{API_BASE}/api/rebuild", headers={"X-API-KEY": LOCAL_SECRET}, timeout=300)
                        if res.status_code == 200: st.success("✅ 資料庫重建完成！")
                    except: st.error("❌ 發生錯誤")