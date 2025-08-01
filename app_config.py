from typing import Dict
from dataclasses import dataclass

@dataclass
class AppConfig:
    csv_input: str = "None"
    csv_folder: str = "data"
    csv_log_folder: str = "logs"
    device_name: str = "Dev1"
    nt_to_volt: float = 1.0 / 100000  # 1V = 10,000nT
    interval: float = 60.0  # 每 60 秒輸出一次
    log_flush_interval: int = 10  # 每處理10筆數據寫入一次日誌

    @classmethod
    def from_dict(cls, config_dict: Dict) -> 'AppConfig':
        return cls(**{k: config_dict.get(k, v) for k, v in cls.__dataclass_fields__.items()})

    def to_dict(self) -> Dict:
        return self.__dict__
