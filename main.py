import threading
import time
import os
import json
import signal
import sys
from datetime import datetime, timezone
from typing import List
from sklearn.linear_model import LinearRegression

# 導入各模組
from app_config import AppConfig
from app_state import AppState
from app_logger import setup_logging
from log_manager import LogManager
from data_loader import DataLoader
from daq_controller import DAQController
from command_interface import CommandInterface
from testing_data import testing_data
from precise_interval_timer import PreciseIntervalTimer, OverlapStrategy

class MagneticFieldController:
    def __init__(self):
        self.MAX_VOLTAGE = 10.0  # 最大電壓 ±10V
        self.voltage_gain = (1.182, 1.18, 1.206)  # 電壓乘數
        self.voltage_offset = (0.0, 0.0, 0.0)  # 電壓偏移
        self.base_path = os.path.dirname(os.path.abspath(__file__))
        setup_logging(os.path.join(self.base_path, "logs"))
        self.config = self._load_config()
        setup_logging(os.path.join(self.base_path, self.config.csv_log_folder))
        self.state = AppState(self.config.interval)
        self.log_manager = LogManager(os.path.join(self.base_path, self.config.csv_log_folder), self.config.log_flush_interval)
        self.command_interface = CommandInterface()
        self._timer = None
        self.channels = {'ao': [f"{self.config.device_name}/ao{i}" for i in (2, 3, 1, 0)],
                         'do': [f"{self.config.device_name}/port0/line{i}" for i in range(0,32)],
                         'ai': [f"{self.config.device_name}/ai{i}" for i in (19, 20, 21)]}
        # 設置指令處理器
        self._register_commands()

        # init do pin state
        self._initialize_digital_control()

        # 設置信號處理
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

    def _initialize_digital_control(self):
        # 建立長度為 32 的布林陣列 (對應 P0.0 到 P0.31)，預設全為 False (0)
        self.digital_states = [False] * 32
        
        # 1. 強制設定所有 Reserved Lines 為 True (1)
        reserved_lines = [0, 1, 2, 3, 4, 5, 6, 7, 11, 12, 14, 27, 28]
        for line in reserved_lines:
            self.digital_states[line] = True
            
        # 2. 設定常規運行與狀態控制
        self.digital_states[8] = True   # P0.8: AUX Self-Test Enable (1 = Normal)
        self.digital_states[9] = True  # P0.9: DUT Self-Test Enable (1 = Normal)
        self.digital_states[10] = True  # P0.10: DUT Input Gain (1 = Gain x1)
        self.digital_states[13] = True  # P0.13: LED colour (1 = Green)
        self.digital_states[15] = True  # P0.15: Alarm Buzzer (1 = Silent)
        
        # 3. 設定感測器輸入模式
        # P0.24, P0.25, P0.26 are False by default (Single-ended, Normal polarity)
        # DUT using Diff mode
        # self.digital_states[25] = True
        
        # 4. 停用硬體濾波器
        self.digital_states[29] = True  # P0.29: Filter Enable (1 = No Filter)

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
        self.calibrators = {
            "x": {"model": LinearRegression(), "X": [], "y": []},
            "y": {"model": LinearRegression(), "X": [], "y": []},
            "z": {"model": LinearRegression(), "X": [], "y": []},
        }

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
        self.state.stop = True
        raise KeyboardInterrupt

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
                return False
        except ValueError:
            print("錯誤：請輸入有效的數字")
            return False
        except IndexError:
            print("錯誤：選擇的檔案不存在")
            return False
        except Exception as e:
            print(f"錯誤：載入資料時發生錯誤: {e}")
            return False
        return True

    def safe_stop(self):
        self.state.stop = True
        print("\n正在安全停止程式...")
        if self._timer is not None:
            print("等待DAQ任務結束...")
            self._timer.stop(timeout=5.0)
        # 最後一次寫入日誌
        self.log_manager.flush()
        print("程式已安全停止。")

    def output_loop(self):
        @self.state.with_lock
        def skip_function():    
            if self.state.skipped_row is not None:
                self.state.current_row = self.state.skipped_row
                self.state.skipped_row = None

        # 誤差調整
        #self.fix_voltage_offset()

        rows_processed = 0
        # 儲存每軸的過去誤差，用來進行簡單校準
        #error_history = {"x": [], "y": [], "z": []}
        #MAX_HISTORY = 10  # 使用最近10筆誤差做平均

        # inner function to define the main loop of the DAQ
        def main_loop(timer: PreciseIntervalTimer):
            skip_function() 

            if self.state.current_row >= len(self.dataframe):
                timer.request_stop()
                return
            if self.state.stop:
                timer.request_stop()
                return
                
            if self.state.paused and not self.state.stop:
                return
                
            row = self.dataframe.iloc[self.state.current_row]

            # 計算電壓（限制最大電壓）
            vx = row.Bx * self.config.nt_to_volt * self.voltage_gain[0] + self.voltage_offset[0]
            vy = row.By * self.config.nt_to_volt * self.voltage_gain[1] + self.voltage_offset[1]
            vz = row.Bz * self.config.nt_to_volt * self.voltage_gain[2] + self.voltage_offset[2]

            vx = max(min(vx, self.MAX_VOLTAGE), -self.MAX_VOLTAGE) / 2
            vy = max(min(vy, self.MAX_VOLTAGE), -self.MAX_VOLTAGE) / 2
            vz = max(min(vz, self.MAX_VOLTAGE), -self.MAX_VOLTAGE) / 2

            output_voltages = [vx, vy, vz, 6]

            # 輸出電壓
            voltage_output_success = daq.write_voltages(output_voltages)
            

            now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            local_time = datetime.now().replace(microsecond=0).isoformat()

            # 輸出結果
            print(f"[{local_time}] 輸出 B(nT)=({row.Bx:.1f}, {row.By:.1f}, {row.Bz:.1f}) -> V=({vx:.4f}, {vy:.4f}, {vz:.4f}) {'V' if voltage_output_success else 'X'}")

            # 讀取類比信號
            analog_data = daq.read_analog()
            if analog_data is not None:
                print(f"讀取類比信號 :")
                for i in range(len(analog_data)):
                    measured = (analog_data[i] - self.analog_offset[i]) /10
                    axis = ['x', 'y', 'z'][i] if i < 3 else 'other'
                    print(f'{axis.upper()}={measured * 100000: .0f}(nT) -> V={measured: .4f}(v)', end='; ')
                    print('')
            else:
                print("讀取類比信號失敗")

            print('\n')

            # 記錄 log
            log_entry = {
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
            }
            
            if analog_data is not None:
                log_entry.update({
                    "analog_x": (analog_data[0] - self.analog_offset[0]) *10000,
                    "analog_y": (analog_data[1] - self.analog_offset[1]) *10000,
                    "analog_z": (analog_data[2] - self.analog_offset[2]) *10000,
                })
            
            self.log_manager.add_entry(log_entry)
            
            self.state.current_row += 1
            
        "def main_loop end"

        with DAQController(self.config.device_name, self.channels) as daq:
            if not daq.ao_task:
                print("DAQ初始化失敗，終止輸出線程")
                return
            
            self.state.task_active = True
            daq.write_digital(self.digital_states)
            daq.write_voltages([0, 0, 0, 6])
            offset_sum = [0, 0, 0]
            self.analog_offset = [0, 0, 0]
            # 預熱
            for i in range(6):
                daq.read_analog()
                time.sleep(0.5)

            
            # 讀ai 3 次
            for i in range(3):
                analog_data = daq.read_analog()
                for j in range(3):
                    offset_sum[j] += analog_data[j]

                print(f'ai read {analog_data}')
                
                time.sleep(1)

            # 求平均作為offset
            for i in range(3):
                self.analog_offset[i] = offset_sum[i] / 3
            print(f"已矯正DUT誤差，{self.analog_offset}")
            

            print("DAQ任務已初始化，開始輸出...")
            
            self.state.current_row = 0

            timer = PreciseIntervalTimer(
                interval_seconds=self.config.interval, 
                callback=main_loop,
                strategy=OverlapStrategy.SKIP,
                max_pending=50,
                inject_timer=True
            )
            self._timer = timer

            """Waiting the DAQ to initialize"""
            time.sleep(2)
            timer.start()

            while timer.is_running:
                time.sleep(0.1)

            timer.stop(timeout=5.0)
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
            elif val > 3600:  # 限制最大間隔為1小時
                print("間隔不能超過3600秒（1小時）")
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
        
    def _cmd_jump(self, cmd: str) -> bool:
        try:
            if self.dataframe is None:
                print("錯誤：尚未載入資料")
                return True
                
            parts = cmd.split()
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
        while not self._choose_file():
            pass
        
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
            
            self.log_manager.close()
            print(f"日誌已保存至：{self.config.csv_log_folder}")

if __name__ == "__main__":
    controller = MagneticFieldController()
    controller.run()
