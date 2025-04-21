import threading
import time
import readline
import pandas as pd
import nidaqmx
from datetime import datetime, UTC

# === 常數設定 ===
CSV_INPUT = "600 Meg.txt"
CSV_FOLDER = "data"
CSV_LOG = "output_log.csv"
DEVICE_NAME = "Dev1"
AO_CHANNELS = [f"{DEVICE_NAME}/ao0", f"{DEVICE_NAME}/ao1", f"{DEVICE_NAME}/ao2"]
NT_TO_VOLT = 1.0 / 10000  # 1V = 10,000nT
DEFAULT_INTERVAL = 60.0  # 每 60 秒輸出一次
DEFAULT_VOLTAGE_LIMIT = 10.0  # 最大電壓 ±10V

# === 共享狀態 ===
state = {
    "paused": False,
    "interval": DEFAULT_INTERVAL,
    "voltage_limit": DEFAULT_VOLTAGE_LIMIT,
    "stop": False,
}

log = []

# === 載入資料檔 ===
print("載入磁場資料中...")
df = pd.read_csv(CSV_FOLDER + '\\' + CSV_INPUT, delim_whitespace=True, skiprows=3)
df = df.rename(columns={
    df.columns[0]: 'Time',
    df.columns[1]: 'Bx',
    df.columns[2]: 'By',
    df.columns[3]: 'Bz'
})
print(f"資料筆數：{len(df)}")

# === 實時輸出執行緒 ===
def output_loop():
    with nidaqmx.Task() as task:
        for ch in AO_CHANNELS:
            task.ao_channels.add_ao_voltage_chan(ch)

        for i, row in df.iterrows():
            if state["stop"]:
                break

            while state["paused"]:
                time.sleep(0.1)

            # 計算電壓（限制最大電壓）
            vx = max(min(row.Bx * NT_TO_VOLT, state["voltage_limit"]), -state["voltage_limit"])
            vy = max(min(row.By * NT_TO_VOLT, state["voltage_limit"]), -state["voltage_limit"])
            vz = max(min(row.Bz * NT_TO_VOLT, state["voltage_limit"]), -state["voltage_limit"])

            # 輸出電壓
            task.write([vx, vy, vz])
            now = datetime.now(UTC).isoformat()

            print(f"[{now}] 輸出 B(nT)=({row.Bx:.1f}, {row.By:.1f}, {row.Bz:.1f}) → V=({vx:.4f}, {vy:.4f}, {vz:.4f})")

            # 記錄 log
            log.append({
                "time": now,
                "bx_nt": row.Bx,
                "by_nt": row.By,
                "bz_nt": row.Bz,
                "vx": vx,
                "vy": vy,
                "vz": vz
            })

            # 等待間隔
            for _ in range(int(state["interval"] * 10)):
                if state["stop"]: break
                time.sleep(0.1)

    print("模擬完成，已停止輸出。")

# === CLI 補全 ===
COMMANDS = [
    "pause", "resume", "set interval", "set voltage limit", "status", "help", "stop"
]

def completer(text, state):
    options = [cmd for cmd in COMMANDS if cmd.startswith(text)]
    return options[state] if state < len(options) else None

readline.parse_and_bind("tab: complete")
readline.set_completer(completer)

# === CLI 互動執行緒 ===
def command_loop():
    print("輸入指令（輸入 help 查看指令列表）")
    while not state["stop"]:
        try:
            cmd = input(">> ").strip()
        except (EOFError, KeyboardInterrupt):
            state["stop"] = True
            break

        if cmd == "pause":
            state["paused"] = True
            print("已暫停輸出。")
        elif cmd == "resume":
            state["paused"] = False
            print("已恢復輸出。")
        elif cmd.startswith("set interval"):
            try:
                _, _, val = cmd.split()
                state["interval"] = float(val)
                print(f"輸出間隔已設為 {val} 秒。")
            except:
                print("語法錯誤，使用：set interval <秒>")
        elif cmd.startswith("set voltage limit"):
            try:
                _, _, _, val = cmd.split()
                state["voltage_limit"] = float(val)
                print(f"電壓上限已設為 ±{val} V。")
            except:
                print("語法錯誤，使用：set voltage limit <V>")
        elif cmd == "status":
            print(f"狀態：{'暫停中' if state['paused'] else '執行中'}")
            print(f"輸出間隔：{state['interval']} 秒")
            print(f"電壓限制：±{state['voltage_limit']} V")
        elif cmd == "help":
            print("可用指令：")
            for c in COMMANDS:
                print(" -", c)
        elif cmd == "stop":
            state["stop"] = True
            break
        else:
            print("未知指令，輸入 help 查看。")

# === 主程序 ===
threading.Thread(target=output_loop, daemon=True).start()
command_loop()

# === 輸出 log ===
if log:
    pd.DataFrame(log).to_csv(CSV_LOG, index=False)
    print("輸出 log 檔：", CSV_LOG)
