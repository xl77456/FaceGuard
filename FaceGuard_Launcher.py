import subprocess
import sys
import time
import os
import signal
import re
import socket
import platform

# --- 1. 檔案設定 ---
BOT_SCRIPT = "discord_bot.py"
DASHBOARD_SCRIPT = "dashboard.py"
FACEGUARD_SCRIPT = "FaceGuard Ultimate.py"
ENV_FILE = ".env" # [新增] .env 檔案追蹤

# --- 2. 顏色設定 ---
try:
    from colorama import init, Fore, Style
    init(autoreset=True)
    C_CYAN = Fore.CYAN
    C_BLUE = Fore.BLUE
    C_GREEN = Fore.GREEN
    C_YELLOW = Fore.YELLOW
    C_RED = Fore.RED
    C_WHITE = Fore.WHITE
    C_BRIGHT = Style.BRIGHT
    C_RESET = Style.RESET_ALL
except ImportError:
    C_CYAN = C_BLUE = C_GREEN = C_YELLOW = C_RED = C_WHITE = C_BRIGHT = C_RESET = ""

processes = []

def clear_screen():
    os.system('cls' if os.name == 'nt' else 'clear')

def get_visible_width(s):
    """ 計算字串視覺長度 (過濾 ANSI) """
    ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
    plain_text = ansi_escape.sub('', s)
    return len(plain_text)

def print_centered_line(content, total_width, border_char="║"):
    """ 置中對齊 """
    visible_len = get_visible_width(content)
    padding = total_width - 2 - visible_len
    left_pad = padding // 2
    right_pad = padding - left_pad
    print(f"  {C_CYAN}{border_char}{' '*left_pad}{content}{' '*right_pad}{C_CYAN}{border_char}")

def print_aligned_log(tag, msg, total_width, border_char="║", status="OK"):
    """ 靠左對齊 Log，支援狀態顏色變化 """
    if status == "OK": tag_color, msg_color = C_GREEN, C_WHITE
    elif status == "WARN": tag_color, msg_color = C_YELLOW, C_YELLOW
    elif status == "FAIL": tag_color, msg_color = C_RED, C_RED
    else: tag_color, msg_color = C_CYAN, C_WHITE

    max_msg_len = total_width - 20 
    if len(msg) > max_msg_len:
        msg = msg[:max_msg_len-3] + "..."

    content = f"{tag_color}[{tag}]{msg_color} {msg}"
    visible_len = get_visible_width(content)
    padding = total_width - 4 - visible_len
    padding_space = " " * max(0, padding)
    print(f"  {C_CYAN}{border_char} {content}{padding_space} {C_CYAN}{border_char}")

# =========================================
# 🔍 真實系統檢測函式庫 (Real Diagnostics)
# =========================================
def check_network():
    try:
        socket.create_connection(("8.8.8.8", 53), timeout=1)
        return "ONLINE", "OK"
    except OSError:
        return "OFFLINE (Local Mode)", "WARN"

def check_file(filename):
    if os.path.exists(filename):
        size_kb = os.path.getsize(filename) / 1024
        return f"Found ({size_kb:.1f} KB)", "OK"
    return "Not Found", "FAIL"

def check_env_file():
    """ [新增] 檢查環境變數設定檔是否存在 """
    if os.path.exists(ENV_FILE):
        return "Loaded successfully", "OK"
    return "Missing (.env file required)", "FAIL"

def check_serial():
    try:
        import serial.tools.list_ports
        ports = list(serial.tools.list_ports.comports())
        if ports:
            return f"Device found on {ports[0].device}", "OK"
        return "No Serial Device Found", "WARN"
    except ImportError:
        return "Serial Lib not installed", "WARN"

def get_system_info():
    return f"{platform.system()} {platform.release()}", "OK"

# =========================================
def show_boot_interface():
    clear_screen()
    WIDTH = 78
    H_LINE = "═" * (WIDTH - 2)
    
    print(f"\n{C_BRIGHT}{C_CYAN}  ╔{H_LINE}╗")
    logo_lines = [
        f"{C_BLUE}███████╗ █████╗  ██████╗███████╗ ██████╗ ██╗   ██╗ █████╗ ██████╗",
        f"{C_BLUE}██╔════╝██╔══██╗██╔════╝██╔════╝██╔════╝ ██║   ██║██╔══██╗██╔══██╗",
        f"{C_BLUE}█████╗  ███████║██║     █████╗  ██║  ███╗██║   ██║███████║██████╔╝",
        f"{C_BLUE}██╔══╝  ██╔══██║██║     ██╔══╝  ██║   ██║██║   ██║██╔══██║██╔══██╗",
        f"{C_BLUE}██║     ██║  ██║╚██████╗███████╗╚██████╔╝╚██████╔╝██║  ██║██║  ██║",
        f"{C_BLUE}╚═╝     ╚═╝  ╚═╝ ╚═════╝╚══════╝ ╚═════╝  ╚═════╝ ╚═╝  ╚═╝╚═╝  ╚═╝"
    ]
    for line in logo_lines: print_centered_line(line, WIDTH)
    print_centered_line("", WIDTH)
    
    sub_lines = [
        f"{C_WHITE}███████╗██╗   ██╗███████╗████████╗███████╗███╗   ███╗",
        f"{C_WHITE}██╔════╝╚██╗ ██╔╝██╔════╝╚══██╔══╝██╔════╝████╗ ████║",
        f"{C_WHITE}███████╗ ╚████╔╝ ███████╗   ██║   █████╗  ██╔████╔██║",
        f"{C_WHITE}╚════██║  ╚██╔╝  ╚════██║   ██║   ██╔══╝  ██║╚██╔╝██║",
        f"{C_WHITE}███████║   ██║   ███████║   ██║   ███████╗██║ ╚═╝ ██║",
        f"{C_WHITE}╚══════╝   ╚═╝   ╚══════╝   ╚═╝   ╚══════╝╚═╝     ╚═╝"
    ]
    for line in sub_lines: print_centered_line(line, WIDTH)
    print(f"  {C_CYAN}╠{H_LINE}╣")
    
    # 執行真實檢測
    sys_msg, sys_status = get_system_info()
    print_aligned_log("SYSTEM", f"Host: {platform.node()} ({sys_msg})", WIDTH, status=sys_status)
    time.sleep(0.1)

    py_ver = sys.version.split()[0]
    print_aligned_log("ENV", f"Python Runtime: v{py_ver}", WIDTH)
    time.sleep(0.1)

    # [新增] Config 檢查
    msg, status = check_env_file()
    print_aligned_log("CONF", f"Environment Config (.env)... {msg}", WIDTH, status=status)
    time.sleep(0.1)

    msg, status = check_file(FACEGUARD_SCRIPT)
    print_aligned_log("CORE", f"Checking Core ({FACEGUARD_SCRIPT})... {msg}", WIDTH, status=status)
    time.sleep(0.1)

    msg, status = check_file(BOT_SCRIPT)
    print_aligned_log("BOT", f"Checking Bot ({BOT_SCRIPT})... {msg}", WIDTH, status=status)
    time.sleep(0.1)

    net_msg, net_status = check_network()
    print_aligned_log("NET", f"Network Connectivity... {net_msg}", WIDTH, status=net_status)
    time.sleep(0.1)

    iot_msg, iot_status = check_serial()
    print_aligned_log("IOT", f"Scanning Serial Ports... {iot_msg}", WIDTH, status=iot_status)
    time.sleep(0.1)

    print(f"  {C_CYAN}╠{H_LINE}╣")
    status = f"{C_YELLOW}> DIAGNOSTICS COMPLETE. Launching services..."
    print_aligned_log("STATUS", status, WIDTH)
    print(f"  {C_CYAN}╚{H_LINE}╝{C_RESET}")
    time.sleep(1.5)

def start_real_services():
    print(f"\n  {C_BRIGHT}{C_WHITE}>>> 正在啟動所有子系統... <<<{C_RESET}\n")

    if os.path.exists(BOT_SCRIPT):
        print(f"  {C_CYAN}[BOOT] Starting Discord Bot...{C_RESET}")
        try:
            p_bot = subprocess.Popen([sys.executable, BOT_SCRIPT], shell=False)
            processes.append(p_bot)
        except Exception as e: print(f"  {C_RED}[FAIL] Error: {e}{C_RESET}")
    
    time.sleep(0.5)

    if os.path.exists(DASHBOARD_SCRIPT):
        print(f"  {C_CYAN}[BOOT] Starting Dashboard...{C_RESET}")
        try:
            p_dash = subprocess.Popen([sys.executable, "-m", "streamlit", "run", DASHBOARD_SCRIPT], shell=False)
            processes.append(p_dash)
        except Exception as e: print(f"  {C_RED}[FAIL] Error: {e}{C_RESET}")
    
    time.sleep(0.5)

    if os.path.exists(FACEGUARD_SCRIPT):
        print(f"  {C_CYAN}[BOOT] Starting FaceGuard Core...{C_RESET}")
        try:
            p_face = subprocess.Popen([sys.executable, FACEGUARD_SCRIPT], shell=False)
            processes.append(p_face)
        except Exception as e: print(f"  {C_RED}[FAIL] Error: {e}{C_RESET}")

    print(f"\n  {C_BRIGHT}{C_GREEN}=== System is Running. Press Ctrl+C to Stop. ==={C_RESET}")

def signal_handler(sig, frame):
    print(f"\n  {C_YELLOW}Stopping services...{C_RESET}")
    for p in processes:
        if p.poll() is None:
            p.terminate()
    sys.exit(0)

def run():
    show_boot_interface()
    signal.signal(signal.SIGINT, signal_handler)
    start_real_services()

    try:
        while True:
            time.sleep(1)
            alive_count = sum(1 for p in processes if p.poll() is None)
            if alive_count == 0 and len(processes) > 0:
                print(f"\n  {C_RED}[WARN] All processes have stopped.{C_RESET}")
                break
    except KeyboardInterrupt:
        pass
    finally:
        signal_handler(None, None)

if __name__ == "__main__":
    try: os.system('mode con: cols=100 lines=40')
    except: pass
    run()