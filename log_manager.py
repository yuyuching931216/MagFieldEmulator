import os
import pandas as pd
import threading
import traceback
from typing import Dict, List
from datetime import datetime

class LogManager:
    def __init__(self, log_dir: str, flush_interval: int = 10):
        self.log_dir = log_dir
        self.flush_interval = flush_interval
        self._log: List[Dict] = []
        self._lock = threading.Lock()
        self._setup_log_directory()
        self.log_file = self._generate_log_filename()

    def _setup_log_directory(self):
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

    def _generate_log_filename(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.log_dir, f"log_{timestamp}.csv")

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
