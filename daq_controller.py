import nidaqmx
import traceback
from typing import List

class DAQController:
    def __init__(self, device_name: str, channels: List[str]):
        self.device_name = device_name
        self.channels = channels
        self.p0_channel = [f'port0/line{i}' for i in range(8, 32)]
        self.task = None

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

            self.task = nidaqmx.Task()
            
            for ch in self.channels:
                self.task.ao_channels.add_ao_voltage_chan(ch, max_val=10.0, min_val=-10.0)

            for ch in self.p0_channel:
                self.task.di_channels.add_di_chan('{self.device_name}/{ch}')
            return True
        
        except Exception as e:
            print(f"初始化DAQ任務時發生錯誤: {e}")
            traceback.print_exc()
            return False

    def write_voltages(self, voltages: List[float]) -> bool:
        if not self.task:
            return False

        try:
            self.task.write(voltages, auto_start=True)
            return True
        except Exception as e:
            print(f"輸出電壓時發生錯誤: {e}")
            traceback.print_exc()
            return False

    def close(self):
        if self.task:
            try:
                # 輸出零電壓
                self.write_voltages([0.0] * len(self.channels))
                self.task.close()
                print("已重置輸出電壓為零")
            except Exception as e:
                print(f"關閉DAQ任務時發生錯誤: {e}")
            finally:
                self.task = None
