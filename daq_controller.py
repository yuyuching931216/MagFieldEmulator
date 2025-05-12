import nidaqmx
import traceback
from typing import List

class DAQController:
    def __init__(self, device_name: str, channels: List[str]):
        self.device_name = device_name
        self.ao_channels = channels
        self.do_channels = [f'port0/line{i}' for i in range(8, 32)]
        self.ao_task = None
        self.do_task = None

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

            for ch in self.ao_channels:
                self.ao_task.ao_channels.add_ao_voltage_chan(ch, max_val=10.0, min_val=-10.0)

            for ch in self.do_channels:
                self.do_task.do_channels.add_do_chan('{self.device_name}/{ch}')

            self.do_task.write([True] * len(self.do_channels), auto_start=True)

            return True
        
        except Exception as e:
            print(f"初始化DAQ任務時發生錯誤: {e}")
            traceback.print_exc()
            return False

    def write_voltages(self, voltages: List[float]) -> bool:
        if not self.ao_task:
            return False

        try:
            self.ao_task.write(voltages, auto_start=True)
            return True
        except Exception as e:
            print(f"輸出電壓時發生錯誤: {e}")
            traceback.print_exc()
            return False

    def close(self):
        if self.ao_task:
            try:
                # 輸出零電壓
                self.write_voltages([0.0] * len(self.channels))
                self.ao_task.close()
                print("已重置輸出電壓為零")
            except Exception as e:
                print(f"關閉DAQ任務時發生錯誤: {e}")
            finally:
                self.ao_task = None
