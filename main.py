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
    BUFFER_UPDATE_INTERVAL_SECONDS = 3.0
    INITIAL_BUFFER_SECONDS = 13.0
    MIN_PENDING_SAMPLES = 10000
    DAQ_SAMPLE_RATE = 1000

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
        self._analog_timer = None
        self._analog_callback = None
        self._daq = None
        self._resume_sample_offset = 0
        self._resume_needs_rebuild = False
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
        self.command_interface.register_command("set analog interval", self._cmd_set_analog_interval, "設定 analog 讀取間隔，用法: set analog interval <秒>")
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
                migrated = "analog_interval" not in config_data
                if migrated:
                    config_data["analog_interval"] = config_data.get(
                        "interval", default_config.interval
                    )
                config = AppConfig.from_dict(config_data)
                if migrated:
                    with open(config_file, 'w', encoding='utf-8') as f:
                        json.dump(config.to_dict(), f, indent=2, ensure_ascii=False)
                    print(
                        "Config updated: added analog_interval="
                        f"{config.analog_interval} from interval."
                    )
                return config
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
            config_data["analog_interval"] = self.config.analog_interval
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
        with DAQController(
            self.config.device_name,
            self.channels,
            sample_rate=self.DAQ_SAMPLE_RATE,
        ) as daq:
            self._daq = daq
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
            daq.clear_output()
            self.state.current_row = 0

            def analog_loop(timer):
                if self.state.stop or self.state.paused:
                    return
                analog_data = daq.read_analog()
                success = bool(analog_data and len(analog_data) >= 3)
                entry = {
                    "record_type": "analog_measurement",
                    "index": None,
                    "utc_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                    "local_time": datetime.now().replace(microsecond=0).isoformat(),
                    "success": success,
                    "analog_interval": self.config.analog_interval,
                }
                if success:
                    entry.update({
                        "analog_raw_x": analog_data[0],
                        "analog_raw_y": analog_data[1],
                        "analog_raw_z": analog_data[2],
                        "analog_calibrated_x": analog_data[0] / 10 * 100000,
                        "analog_calibrated_y": analog_data[1] / 10 * 100000,
                        "analog_calibrated_z": analog_data[2] / 10 * 100000,
                    })
                self.log_manager.add_entry(entry)

            self._analog_callback = analog_loop
            self._analog_timer = PreciseIntervalTimer(
                interval_seconds=self.config.analog_interval,
                callback=self._analog_callback,
                strategy=OverlapStrategy.SKIP,
                max_pending=1,
                inject_timer=True,
            )
            self._analog_timer.start()

            def samples_for_interval(interval):
                samples = round(interval * self.DAQ_SAMPLE_RATE)
                if samples <= 0:
                    raise ValueError("interval 轉換後的 DAQ samples 必須大於 0")
                return samples

            def voltage_for_row(row):
                values = [
                    row.Bx * self.config.nt_to_volt * self.voltage_gain[0] + self.voltage_offset[0],
                    row.By * self.config.nt_to_volt * self.voltage_gain[1] + self.voltage_offset[1],
                    row.Bz * self.config.nt_to_volt * self.voltage_gain[2] + self.voltage_offset[2],
                ]
                values = [
                    max(min(value, self.MAX_VOLTAGE), -self.MAX_VOLTAGE) / 2
                    for value in values
                ]
                return values + [6]

            def append_rows(row_count, initial=False):
                rows = []
                sample_total = 0
                interval = self.state.interval
                while (
                    self.state.current_row < len(self.dataframe)
                    and (initial and sample_total < self.DAQ_SAMPLE_RATE * self.INITIAL_BUFFER_SECONDS
                         or not initial and sample_total < self.DAQ_SAMPLE_RATE * self.BUFFER_UPDATE_INTERVAL_SECONDS)
                ):
                    row_index = self.state.current_row
                    row = self.dataframe.iloc[row_index]
                    sample_count = samples_for_interval(interval)
                    if not initial and self._resume_sample_offset:
                        sample_count = max(sample_count - self._resume_sample_offset, 1)
                        self._resume_sample_offset = 0
                    voltages = voltage_for_row(row)
                    rows.append((row_index, row, voltages, sample_count))
                    sample_total += sample_count
                    self.state.current_row += 1
                    if not initial and len(rows) >= row_count:
                        break

                if not rows:
                    return 0, 0

                for row_index, row, voltages, sample_count in rows:
                    write_success = daq.append_voltages(voltages, sample_count)
                    pending = daq.get_pending_samples()
                    print(
                        f"[DAQ INPUT] index={row_index} "
                        f"B=({row.Bx:.1f}, {row.By:.1f}, {row.Bz:.1f}) nT -> "
                        f"V=({voltages[0]:.4f}, {voltages[1]:.4f}, {voltages[2]:.4f}) "
                        f"samples={sample_count} write={'OK' if write_success else 'FAILED'} "
                        f"buffer_pending={pending}"
                    )
                    if not write_success:
                        return len(rows), sample_total
                    self.log_manager.add_entry({
                        "record_type": "daq_input",
                        "index": row_index,
                        "utc_time": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
                        "local_time": datetime.now().replace(microsecond=0).isoformat(),
                        "bx_nt": row.Bx,
                        "by_nt": row.By,
                        "bz_nt": row.Bz,
                        "vx": voltages[0],
                        "vy": voltages[1],
                        "vz": voltages[2],
                        "samples": sample_count,
                        "buffer_pending": pending,
                        "success": True,
                    })
                return len(rows), sample_total

            print(
                f"[DAQ BUFFER] initial load started: "
                f"target_seconds={self.INITIAL_BUFFER_SECONDS:.1f}, "
                f"interval={self.state.interval}"
            )
            initial_rows, initial_samples = append_rows(0, initial=True)
            print(
                f"[DAQ BUFFER] initial load complete: added={initial_rows} rows, "
                f"added_samples={initial_samples}, pending={daq.get_pending_samples()}"
            )
            daq.start_output()

            def main_loop(timer):
                if self.state.stop:
                    timer.request_stop()
                    return
                if self.state.paused:
                    return
                if self._resume_needs_rebuild:
                    daq.clear_output()
                    self._resume_needs_rebuild = False
                if self.state.current_row >= len(self.dataframe):
                    timer.request_stop()
                    return
                pending = daq.get_pending_samples()
                if pending > self.MIN_PENDING_SAMPLES:
                    print(
                        f"[DAQ BUFFER] update skipped: pending={pending} samples "
                        f"(> threshold={self.MIN_PENDING_SAMPLES})"
                    )
                    return

                print(
                    f"[DAQ BUFFER] update started: "
                    f"target_seconds={self.BUFFER_UPDATE_INTERVAL_SECONDS:.1f}, "
                    f"interval={self.state.interval}"
                )
                added_rows, added_samples = append_rows(
                    round(self.BUFFER_UPDATE_INTERVAL_SECONDS / self.state.interval)
                )
                print(
                    f"[DAQ BUFFER] update complete: added={added_rows} rows, "
                    f"added_samples={added_samples}, pending={daq.get_pending_samples()}"
                )

            timer = PreciseIntervalTimer(
                interval_seconds=self.BUFFER_UPDATE_INTERVAL_SECONDS,
                callback=main_loop,
                strategy=OverlapStrategy.SKIP,
                max_pending=1,
                inject_timer=True,
            )
            self._timer = timer
            timer.start()

            while timer.is_running:
                time.sleep(0.1)

            timer.stop(timeout=5.0)
            if self._analog_timer is not None:
                self._analog_timer.stop(timeout=5.0)
                self._analog_timer = None
            while daq.get_pending_samples() > 0 and not self.state.stop:
                time.sleep(0.1)
            self.state.task_active = False
            self._daq = None
            print("模擬完成，已停止輸出。")


    # 指令處理函數
    def _cmd_pause(self) -> bool:
        self.state.paused = True
        if self._analog_timer is not None:
            self._analog_timer.stop(timeout=5.0)
        if self._daq is not None:
            pending = self._daq.get_pending_samples()
            generated = self._daq.get_samples_generated()
            samples_per_row = max(round(self.state.interval * self.DAQ_SAMPLE_RATE), 1)
            consumed = max(generated, 0)
            self.state.current_row = max(
                0, self.state.current_row - round(pending / samples_per_row)
            )
            self._resume_sample_offset = consumed % samples_per_row
            self._daq.clear_output()
            self._daq.write_voltages([0.0] * len(self.channels["ao"]))
            self._resume_needs_rebuild = True
        print("已暫停輸出。")
        return True
        
    def _cmd_resume(self) -> bool:
        self.state.paused = False
        if self._analog_timer is not None:
            self._analog_timer.start()
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

    def _cmd_set_analog_interval(self, cmd: str) -> bool:
        try:
            parts = cmd.split()
            if len(parts) != 4:
                raise ValueError("parameter count is invalid")

            value = float(parts[3])
            if value <= 0:
                print("Analog interval must be greater than 0 seconds.")
                return True

            self.config.analog_interval = value
            if self._analog_timer is not None:
                self._analog_timer.stop(timeout=5.0)
                self._analog_timer = PreciseIntervalTimer(
                    interval_seconds=value,
                    callback=self._analog_callback,
                    strategy=OverlapStrategy.SKIP,
                    max_pending=1,
                    inject_timer=True,
                )
                if not self.state.paused:
                    self._analog_timer.start()
            print(f"Analog interval set to {value} seconds.")
        except ValueError as e:
            print(f"Invalid analog interval: {e}")
            print("Usage: set analog interval <seconds>")
        return True
        
    def _cmd_status(self) -> bool:
        current_index = self.state.current_row
        total_rows = len(self.dataframe)
        progress = (current_index / total_rows) * 100 if total_rows > 0 else 0
        
        print(f"狀態：{'暫停中' if self.state.paused else '執行中'}")
        print(f"進度：{current_index}/{total_rows} ({progress:.1f}%)")
        print(f"輸出間隔：{self.state.interval} 秒")
        print(f"Analog interval: {self.config.analog_interval} seconds")
        print(f"電壓限制：±{self.state.voltage_limit} V")
        print(f"日誌緩存條目：{self.log_manager.entry_count}")
        return True
        
    def _cmd_save_config(self) -> bool:
        if self.save_config():
            print(
                "Config updated: "
                f"interval={self.state.interval}, "
                f"analog_interval={self.config.analog_interval}."
            )
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
