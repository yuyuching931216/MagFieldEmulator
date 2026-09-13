import nidaqmx
from nidaqmx.constants import TerminalConfiguration, AcquisitionType, RegenerationMode, READ_ALL_AVAILABLE
import nidaqmx.error_codes
from nidaqmx.stream_writers import AnalogMultiChannelWriter
import traceback
import numpy as np
from typing import List
from threading import Lock
import copy

class DAQController:
    def __init__(self, device_name: str, channels: dict[str, List[str]], sample_rate: int = 1000, buffer_size: int = 1000):
        self.device_name = device_name
        self.ao_task = None
        self.do_task = None
        self.ai_task = None
        self.channels = channels
        self.sample_rate = sample_rate
        self.buffer_size = buffer_size
        self.voltages : List[float] = [0.0] * len(self.channels.get('ao', []))
        self.lock = Lock()

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
            
            self.ao_task.out_stream.regen_mode = RegenerationMode.DONT_ALLOW_REGENERATION

            self.ao_task.register_every_n_samples_transferred_from_buffer_event(self.buffer_size, self._buffer_callback)

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
            traceback.print_exc()
            return False

    def write_voltages(self, voltages: List[float]) -> bool:
        if not self.ao_task:
            return False

        if len(voltages) != len(self.channels.get('ao', [])):
            raise ValueError(f"錯誤：輸入電壓數量 {len(voltages)} 與通道數量 {len(self.channels.get('ao', []))} 不匹配")

        try:
            with self.lock:
                self.voltages = voltages

                samples = np.array([np.full(self.buffer_size, v,dtype=np.float64) for v in voltages])

                writer = AnalogMultiChannelWriter(self.ao_task.out_stream, auto_start=False)

                if not self.ao_task.is_task_done():
                    self.ao_task.stop()
                writer.write_many_sample(samples)
                self.ao_task.start()
            return True
        except Exception as e:
            print(f"輸出電壓時發生錯誤: {e}")
            traceback.print_exc()
            return False

    def _buffer_callback(self, task_handle, event_type, sample_number, callback_data):
        try:
            if self.ao_task is None:
                print("AO task， 跳過callback")
                return 0
            try:
                if self.ao_task.is_task_done():
                    return 0
            except nidaqmx.error_codes.DAQmxErrors as e:
                print(f"無法檢查task狀態:{e}")
                return 0

            with self.lock:
                if self.voltages is not None:
                    samples = np.array([np.full(self.buffer_size, v,dtype=np.float64) for v in self.voltages])
                    writer = AnalogMultiChannelWriter(self.ao_task.out_stream, auto_start=False)
                    writer.write_many_sample(samples)
        except nidaqmx.errors.DaqError as e:
            print(f"緩衝區回呼錯誤: {e}")
            traceback.print_exc()
        return 0

    def write_digital(self, data: List[int]) -> bool:
        if not self.do_task:
            return False
        try:
            self.do_task.write(data, auto_start=True)
            return True
        except Exception as e:
            print(f"輸出數位信號時發生錯誤: {e}")
            traceback.print_exc()
            return False
        
    def read_analog(self) -> List[float]:
        if not self.ai_task:
            return []
        try:
            # reader = AnalogMultiChannelReader()

            raw_data = self.ai_task.read(number_of_samples_per_channel=READ_ALL_AVAILABLE)
            raw_data = copy.deepcopy(raw_data)

            # print(type(raw_data))
            # print(len(raw_data))

            if len(raw_data) < 3:
                raise ValueError(f"Expected 3 channels, got {len(raw_data)}")

            if any(len(row) == 0 for row in raw_data[:3]):
                return


            index = len(raw_data[0]) - 1
            # print("index =", index)

            data = [raw_data[0][index], raw_data[1][index], raw_data[2][index]]
            return data
                # print(f'{type(raw_data[0])}')
        except Exception as e:
            print(f"讀取類比信號時發生錯誤: {e}")
            traceback.print_exc()
            return []

    def close(self):
        if self.ao_task:
            try:
                # 輸出零電壓
                if self.ao_task:
                    self.write_voltages([0.0] * len(self.channels.get('ao', [])))
                    # self.ao_task.unregister_every_n_samples_transferred_from_buffer_event()
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
                traceback.print_exc()