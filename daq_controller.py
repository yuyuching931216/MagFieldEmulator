import nidaqmx
from nidaqmx.constants import TerminalConfiguration, AcquisitionType, RegenerationMode, READ_ALL_AVAILABLE
import nidaqmx.error_codes
from nidaqmx.stream_writers import AnalogMultiChannelWriter
import traceback
import numpy as np
from typing import List
from threading import RLock
import copy
from app_logger import log_exception

class DAQController:
    def __init__(self, device_name: str, channels: dict[str, List[str]], sample_rate: int = 1000, buffer_size: int = 13000):
        self.device_name = device_name
        self.ao_task = None
        self.do_task = None
        self.ai_task = None
        self.channels = channels
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.voltages : List[float] = [0.0] * len(self.channels.get('ao', []))
        self.lock = RLock()
        self.samples_written = 0
        self.samples_generated = 0

    def __enter__(self):
        self.initialize()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def initialize(self) -> bool:
        try:
            system = nidaqmx.system.System.local()
            if self.device_name not in system.devices:
                print(f"錯誤：找不到DAQ設備 {self.device_name}")
                return False

            self.ao_task = nidaqmx.Task(new_task_name='ao task')
            self.do_task = nidaqmx.Task(new_task_name='do task')
            self.ai_task = nidaqmx.Task(new_task_name='ai task')

            for ch in self.channels.get('ao', []):
                self.ao_task.ao_channels.add_ao_voltage_chan(ch)

            self.ao_task.timing.cfg_samp_clk_timing(self.sample_rate,
                                                    sample_mode=AcquisitionType.CONTINUOUS, 
                                                    samps_per_chan=self.buffer_size)
            self.ao_task.out_stream.output_buf_size = self.buffer_size + 3000
            
            self.ao_task.out_stream.regen_mode = RegenerationMode.DONT_ALLOW_REGENERATION

            self.ao_task.register_every_n_samples_transferred_from_buffer_event(
                self.sample_rate, self._buffer_callback
            )

            for ch in self.channels.get('do', []):
                self.do_task.do_channels.add_do_chan(ch)

            for ch in self.channels.get('ai', []):
                self.ai_task.ai_channels.add_ai_voltage_chan(ch, terminal_config=TerminalConfiguration.NRSE)

            self.ai_task.timing.cfg_samp_clk_timing(self.sample_rate,
                                                    sample_mode=AcquisitionType.CONTINUOUS, 
                                                    samps_per_chan=self.buffer_size)

            self.ai_task.start()
            return True
        
        except Exception as e:
            print(f"初始化DAQ任務時發生錯誤: {e}")
            log_exception("初始化DAQ任務例外")
            return False

    def write_voltages(self, voltages: List[float]) -> bool:
        if not self.ao_task:
            return False

        if len(voltages) != len(self.channels.get('ao', [])):
            raise ValueError(f"錯誤：輸入電壓數量 {len(voltages)} 與通道數量 {len(self.channels.get('ao', []))} 不匹配")

        try:
            with self.lock:
                self.voltages = list(voltages)
                samples = np.array([np.full(self.buffer_size, v, dtype=np.float64) for v in voltages])

                writer = AnalogMultiChannelWriter(self.ao_task.out_stream, auto_start=False)

                if not self.ao_task.is_task_done():
                    self.ao_task.stop()
                writer.write_many_sample(samples)
                self.samples_written = self.buffer_size
                self.samples_generated = 0
                self.ao_task.start()
            return True
        except Exception as e:
            print(f"輸出電壓時發生錯誤: {e}")
            log_exception("輸出電壓例外")
            return False

    def append_voltages(self, voltages: List[float], sample_count: int) -> bool:
        if not self.ao_task:
            return False
        if len(voltages) != len(self.channels.get('ao', [])):
            raise ValueError(f"錯誤：輸入電壓數量 {len(voltages)} 與通道數量 {len(self.channels.get('ao', []))} 不匹配")
        if sample_count <= 0:
            raise ValueError("追加的 samples 數量必須大於 0")

        try:
            with self.lock:
                samples = np.array([
                    np.full(sample_count, voltage, dtype=np.float64)
                    for voltage in voltages
                ])
                writer = AnalogMultiChannelWriter(self.ao_task.out_stream, auto_start=False)
                writer.write_many_sample(samples)
                self.samples_written += sample_count
            return True
        except Exception as e:
            print(f"追加電壓資料時發生錯誤: {e}")
            log_exception("追加電壓資料例外")
            return False

    def get_samples_generated(self) -> int:
        with self.lock:
            return self.samples_generated

    def get_pending_samples(self) -> int:
        with self.lock:
            return max(self.samples_written - self.samples_generated, 0)

    def stop_output(self) -> None:
        with self.lock:
            if self.ao_task and not self.ao_task.is_task_done():
                self.ao_task.stop()

    def start_output(self) -> None:
        with self.lock:
            if self.ao_task:
                self.ao_task.start()

    def clear_output(self) -> None:
        with self.lock:
            if self.ao_task:
                if not self.ao_task.is_task_done():
                    self.ao_task.stop()
                self.ao_task.close()
                self.ao_task = nidaqmx.Task(new_task_name='ao task')
                for channel in self.channels.get('ao', []):
                    self.ao_task.ao_channels.add_ao_voltage_chan(channel)
                self.ao_task.timing.cfg_samp_clk_timing(
                    self.sample_rate,
                    sample_mode=AcquisitionType.CONTINUOUS,
                    samps_per_chan=self.buffer_size,
                )
                self.ao_task.out_stream.output_buf_size = self.buffer_size + 3000
                self.ao_task.out_stream.regen_mode = RegenerationMode.DONT_ALLOW_REGENERATION
                self.ao_task.register_every_n_samples_transferred_from_buffer_event(
                    self.sample_rate, self._buffer_callback
                )
                self.samples_written = 0
                self.samples_generated = 0

    def _buffer_callback(self, task_handle, event_type, sample_number, callback_data):
        with self.lock:
            try:
                try:
                    if self.ao_task is None:
                        print("AO task， 跳過callback")
                        return 0
                    if self.ao_task.is_task_done():
                        return 0
                except nidaqmx.errors.DaqError as e:
                    print(f"無法檢查task狀態:{e}")
                    return 0

                try:
                    generated = self.ao_task.out_stream.total_samp_per_chan_generated
                    self.samples_generated = max(self.samples_generated, generated)
                except nidaqmx.errors.DaqError:
                    pass
            except nidaqmx.errors.DaqError as e:
                print(f"緩衝區回呼錯誤: {e}")
                log_exception("緩衝區回呼例外")
        return 0

    def write_digital(self, data: List[int]) -> bool:
        if not self.do_task:
            return False
        try:
            self.do_task.write(data, auto_start=True)
            return True
        except Exception as e:
            print(f"輸出數位信號時發生錯誤: {e}")
            log_exception("輸出數位信號例外")
            return False
        
    def read_analog_samples(self) -> List[List[float]]:
        if not self.ai_task:
            return [[], [], []]
        try:
            raw_data = self.ai_task.read(number_of_samples_per_channel=READ_ALL_AVAILABLE)
            raw_data = copy.deepcopy(raw_data)

            if len(raw_data) < 3:
                raise ValueError(f"Expected 3 channels, got {len(raw_data)}")

            channel_samples = [list(raw_data[index]) for index in range(3)]
            sample_count = min(len(samples) for samples in channel_samples)
            if sample_count == 0:
                return [[], [], []]

            return [samples[:sample_count] for samples in channel_samples]
        except Exception as e:
            print(f"讀取類比信號時發生錯誤: {e}")
            log_exception("讀取類比信號例外")
            return [[], [], []]

    def read_analog(self) -> List[float]:
        """Read all available samples and return the latest sample per channel."""
        samples = self.read_analog_samples()
        if not samples or any(not channel for channel in samples):
            return []
        return [channel[-1] for channel in samples]

    def close(self):
        with self.lock:
            try:
                # 輸出零電壓
                if self.ao_task:
                    self.write_voltages([0.0] * len(self.channels.get('ao', [])))
                    self.ao_task.close()
                    self.ao_task=None
                if self.ai_task:
                    self.ai_task.close()
                    self.ai_task=None
                if self.do_task:    
                    self.do_task.close()
                    self.do_task=None
                print("已重置輸出電壓為零")
            except Exception as e:
                print(f"關閉DAQ任務時發生錯誤: {e}")
                log_exception("關閉DAQ任務例外")
