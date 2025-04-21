import os
import pandas as pd
import threading
import traceback
from typing import Dict, List

class LogManager:
    def __init__(self, log_file: str, flush_interval: int = 10):
        self.log_file = log_file
        self.flush_interval = flush_interval
        self._log: List[Dict] = []
        self._lock = threading.Lock()
        self._setup_log_directory()

    def _setup_log_directory(self):
        log_dir = os.path.dirname(self.log_file)
        if log_dir and not os.path.exists(log_dir):
            os.makedirs(log_dir, exist_ok=True)

    def add_entry(self, entry: Dict):
        with self._lock:
            self._log.append(entry)

    def flush(self):
        if not self._log:
            return
        
        with self._lock:
            try:
                df = pd.DataFrame(self._log)
                write_header = not os.path.exists(self.log_file)
                df.to_csv(self.log_file, mode='a', header=write_header, index=False)
                self._log = []
            except Exception as e:
                print(f"寫入日誌失敗: {e}")
                traceback.print_exc()

    def should_flush(self, counter: int) -> bool:
        return counter % self.flush_interval == 0
        
    @property
    def entry_count(self) -> int:
        with self._lock:
            return len(self._log)
