import nidaqmx
from nidaqmx.constants import TerminalConfiguration, AcquisitionType, RegenerationMode
from nidaqmx.stream_writers import AnalogMultiChannelWriter
from nidaqmx.task import Task
import traceback
import numpy as np
from typing import List

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

            self.ao_task = nidaqmx.Task()
            self.do_task = nidaqmx.Task()
            self.ai_task = nidaqmx.Task()

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
            self.voltages = voltages

            samples = np.array([np.full(self.buffer_size, v) for v in voltages])

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
            temp_task = Task(task_handle)

            if self.voltages is not None:
                samples = np.array([np.full(self.buffer_size, v) for v in self.voltages])
                writer = AnalogMultiChannelWriter(temp_task.out_stream, auto_start=False)
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
            data = self.ai_task.read()
            return data
        except Exception as e:
            print(f"讀取類比信號時發生錯誤: {e}")
            traceback.print_exc()
            return []

    def close(self):
        if self.ao_task:
            try:
                # 輸出零電壓
                self.write_voltages([0.0] * len(self.channels.get('ao', [])))
                self.ao_task.close()
                self.ai_task.close()
                self.do_task.close()
                print("已重置輸出電壓為零")
            except Exception as e:
                print(f"關閉DAQ任務時發生錯誤: {e}")
            finally:
                self.ao_task = None
