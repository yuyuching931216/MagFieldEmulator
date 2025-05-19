import threading
import time
import os
import json
import signal
import sys
from datetime import datetime, timezone
from typing import List

# 導入各模組
from app_config import AppConfig
from app_state import AppState
from log_manager import LogManager
from data_loader import DataLoader
from daq_controller import DAQController
from command_interface import CommandInterface

class MagneticFieldController:
    def __init__(self):
        self.MAX_VOLTAGE = 10.0  # 最大電壓 ±10V
        self.voltage_multiplier = (1.0, 1.0, 1.0)  # 電壓乘數
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        self.config = self._load_config()
        self.state = AppState(self.config.interval)
        self.log_manager = LogManager(os.path.join(self.base_path, self.config.csv_log), self.config.log_flush_interval)
        self.command_interface = CommandInterface()
        self.channels = {"ao": [f"{self.config.device_name}/ao{i}" for i in (3, 2, 1, 0)],
                         "do": [f"{self.config.device_name}/port0/line{i}" for i in range(8,32)],
                         "ai": [f"{self.config.device_name}/ai{i}" for i in range(19, 22)]}
        # 設置指令處理器
        self._register_commands()

        # 設置信號處理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def _register_commands(self):
        """註冊所有可用的指令"""
        self.command_interface.register_command("pause", lambda _: self._cmd_pause(), "暫停輸出")
        self.command_interface.register_command("resume", lambda _: self._cmd_resume(), "恢復輸出")
        self.command_interface.register_command("set interval", self._cmd_set_interval, "設定輸出間隔，用法: set interval <秒>")
        self.command_interface.register_command("status", lambda _: self._cmd_status(), "顯示目前狀態")
        self.command_interface.register_command("save config", lambda _: self._cmd_save_config(), "保存當前設定")
        self.command_interface.register_command("stop", lambda _: self._cmd_stop(), "停止程式")
        self.command_interface.register_command("help", lambda _: self.command_interface.show_help(), "顯示此幫助")
        self.command_interface.register_command("jump", self._cmd_jump, "跳至指定行數，用法: jump <行數>")

    def _load_config(self) -> AppConfig:
        config_file = os.path.join(self.base_path, "config.json")
        default_config = AppConfig()
        
        try:
            if os.path.exists(config_file):
                with open(config_file, 'r', encoding='utf-8') as f:
                    config_data = json.load(f)
                    return AppConfig.from_dict(config_data)
            else:
                with open(config_file, 'w', encoding='utf-8') as f:
                    json.dump(default_config.to_dict(), f, indent=2, ensure_ascii=False)
                return default_config
        except Exception as e:
            print(f"載入配置檔時發生錯誤: {e}")
            print("使用默認配置")
            return default_config

    def save_config(self) -> bool:
        try:
            path = os.path.join(self.base_path, "config.json")
            config_data = {
                **self.config.to_dict(),
                "interval": self.state.interval,
            }
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(config_data, f, indent=2, ensure_ascii=False)
            return True
        except Exception as e:
            print(f"保存配置時發生錯誤: {e}")
            return False

    def signal_handler(self, sig, frame):
        print(f"\n收到信號 {sig}，準備安全退出...")
        self.safe_stop()
        sys.exit(0)

    def _choose_file(self):
        data_path = os.path.join(self.base_path, self.config.csv_folder)
        files = [f for f in os.listdir(data_path) if f != '.gitkeep']
        if not files:
            print("錯誤：資料夾為空")
            sys.exit(1)
        print("請選擇要載入的磁場資料檔案：")
        for i, file in enumerate(files):
            print(f"{i}: {file}")
        try:
            choice = int(input("請輸入檔案編號："))
            if 0 <= choice < len(files):
                file_path = os.path.join(data_path, files[choice])
                self.dataframe = DataLoader.load_data(file_path)
                if self.dataframe is None:
                    print("錯誤：載入資料失敗")
                    sys.exit(1)
            else:
                print("錯誤：無效的選擇")
                sys.exit(1)
        except ValueError:
            print("錯誤：請輸入有效的數字")
            sys.exit(1)
        except IndexError:
            print("錯誤：選擇的檔案不存在")
            sys.exit(1)
        except Exception as e:
            print(f"錯誤：載入資料時發生錯誤: {e}")
            sys.exit(1)

    def safe_stop(self):
        self.state.stop = True
        print("\n正在安全停止程式...")
        # 等待任務完成
        if self.state.task_active:
            print("等待DAQ任務結束...")
            time.sleep(1)
        # 最後一次寫入日誌
        self.log_manager.flush()
        print("程式已安全停止。")

    def output_loop(self):
        @self.state.with_lock
        def skip_function():    
            if self.state.skipped_row is not None:
                self.state.current_row = self.state.skipped_row
                self.state.skipped_row = None

        rows_processed = 0
        # 儲存每軸的過去誤差，用來進行簡單校準
        error_history = {"x": [], "y": [], "z": []}
        MAX_HISTORY = 10  # 使用最近10筆誤差做平均


        with DAQController(self.config.device_name, self.channels) as daq:
            if not daq.ao_task:
                print("DAQ初始化失敗，終止輸出線程")
                return

            self.state.task_active = True
            daq.write_digital([True] * len(self.channels.get('do', [])))  # 設定數位輸出為高電平

            print("DAQ任務已初始化，開始輸出...")
            
            self.state.current_row = 0
            while self.state.current_row < len(self.dataframe):

                skip_function() 
                row = self.dataframe.iloc[self.state.current_row]
                
                if self.state.stop:
                    break
                 
                while self.state.paused and not self.state.stop:
                    time.sleep(0.1)
                
                if self.state.stop:
                    break

                # 計算開始時間
                start_time = time.perf_counter()
                    
                # 計算電壓（限制最大電壓）
                vx = row.Bx * self.config.nt_to_volt * self.voltage_multiplier[0] / 2
                vy = row.By * self.config.nt_to_volt * self.voltage_multiplier[1] / 2
                vz = row.Bz * self.config.nt_to_volt * self.voltage_multiplier[2] / 2

                vx = max(min(vx, self.MAX_VOLTAGE), -self.MAX_VOLTAGE)
                vy = max(min(vy, self.MAX_VOLTAGE), -self.MAX_VOLTAGE)
                vz = max(min(vz, self.MAX_VOLTAGE), -self.MAX_VOLTAGE)

                output_voltages = [vx, vy, vz, 5]

                # 輸出電壓
                voltage_output_success = daq.write_voltages(output_voltages)
                

                now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                local_time = datetime.now().replace(microsecond=0).isoformat()

                # 輸出結果
                print(f"[{local_time}] 輸出 B(nT)=({row.Bx:.1f}, {row.By:.1f}, {row.Bz:.1f}) → V=({vx:.4f}, {vy:.4f}, {vz:.4f}) {'✓' if voltage_output_success else '✗'}")

                # 讀取類比信號
                analog_data = daq.read_analog()
                if analog_data is not None:
                    print(f"讀取類比信號", end=': ')
                    for i in range(len(analog_data)):
                        data = analog_data[i]
                        input = (vx, vy, vz)[i]
                        name = ['Bx', 'By', 'Bz'][i]
                        print(f'{name}={data:.4f}, 差距{(data - input):.4f}', end='; ')
                    print('')
                    # 🔧 補償邏輯放這裡
                    for i, axis in enumerate(["x", "y", "z"]):
                        measured = analog_data[i]
                        expected = (vx, vy, vz)[i]
                        error = measured - expected
                        error_history[axis].append(error)

                        if len(error_history[axis]) > MAX_HISTORY:
                            error_history[axis].pop(0)

                        avg_error = sum(error_history[axis]) / len(error_history[axis])
                        
                        # 根據平均誤差進行補償
                        if axis == "x":
                            vx -= avg_error
                        elif axis == "y":
                            vy -= avg_error
                        elif axis == "z":
                            vz -= avg_error
                else:
                    print("讀取類比信號失敗")
                
                # 記錄 log
                self.log_manager.add_entry({
                    "index": self.state.current_row,	
                    "utc_time": now,
                    "local_time": local_time,
                    "bx_nt": row.Bx,
                    "by_nt": row.By,
                    "bz_nt": row.Bz,
                    "vx": vx,
                    "vy": vy,
                    "vz": vz,
                    "success": voltage_output_success,
                    "analog_data": analog_data,
                })
                
                self.state.current_row += 1
                
                # 定期寫入日誌
                rows_processed += 1
                if self.log_manager.should_flush(rows_processed):
                    self.log_manager.flush()
                    
                # 計算需要等待的時間
                elapsed = time.perf_counter() - start_time
                wait_time = max(0, self.state.interval - elapsed)
                
                # 分段等待，以便能夠更快地響應暫停或停止命令
                wait_end_time = time.perf_counter() + wait_time
                while time.perf_counter() < wait_end_time and not self.state.stop and not self.state.paused:
                    time.sleep(0.1)

            self.state.task_active = False
            print("模擬完成，已停止輸出。")

    # 指令處理函數
    def _cmd_pause(self) -> bool:
        self.state.paused = True
        print("已暫停輸出。")
        return True
        
    def _cmd_resume(self) -> bool:
        self.state.paused = False
        print("已恢復輸出。")
        return True
        
    def _cmd_set_interval(self, cmd: str) -> bool:
        try:
            parts = cmd.split()
            if len(parts) != 3:
                raise ValueError("參數數量錯誤")
                
            val = float(parts[2])
            if val <= 0:
                print("間隔必須大於0秒")
            else:
                self.state.interval = val
                print(f"輸出間隔已設為 {val} 秒。")
        except ValueError as e:
            print(f"無效的數值: {e}")
            print("語法錯誤，使用：set interval <秒>")
        return True
        
    def _cmd_status(self) -> bool:
        current_index = self.state.current_row
        total_rows = len(self.dataframe)
        progress = (current_index / total_rows) * 100 if total_rows > 0 else 0
        
        print(f"狀態：{'暫停中' if self.state.paused else '執行中'}")
        print(f"進度：{current_index}/{total_rows} ({progress:.1f}%)")
        print(f"輸出間隔：{self.state.interval} 秒")
        print(f"電壓限制：±{self.state.voltage_limit} V")
        print(f"日誌緩存條目：{self.log_manager.entry_count}")
        return True
        
    def _cmd_save_config(self) -> bool:
        if self.save_config():
            print("配置已保存")
        else:
            print("保存配置失敗")
        return True
        
    def _cmd_stop(self) -> bool:
        self.safe_stop()
        return False  # 回傳 False 表示應該結束命令循環
    def _cmd_jump(self) -> bool:
        try:
            parts = self.command_interface.get_command().split()
            if len(parts) != 2:
                raise ValueError("參數數量錯誤")
            row_number = int(parts[1])
            if row_number < 0 or row_number >= len(self.dataframe):
                raise ValueError("行數超出範圍")
            self.state.skipped_row = row_number
            print(f"跳至行數 {row_number}")
        except ValueError as e:
            print(f"無效的行數: {e}")
            print("語法錯誤，使用：jump <行數>")
        except IndexError:
            print("行數超出範圍")
            print("語法錯誤，使用：jump <行數>")
        except Exception as e:
            print(f"發生錯誤: {e}")
            return True
        return True
    

    def run(self):
        print("=== 磁場模擬控制器 ===")
        self._choose_file()
        output_thread = threading.Thread(target=self.output_loop, daemon=True)
        output_thread.start()

        try:
            self.command_interface.start_interactive_loop(">> ")
        finally:
            # 確保程式結束前執行清理工作
            self.safe_stop()
            
            # 等待輸出執行緒結束
            if output_thread.is_alive():
                output_thread.join(timeout=3.0)
            
            # 最後一次寫入日誌
            self.log_manager.flush()
            print(f"日誌已保存至：{self.config.csv_log}")

if __name__ == "__main__":
    controller = MagneticFieldController()
    controller.run()
