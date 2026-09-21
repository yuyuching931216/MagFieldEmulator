import os
import pandas as pd
import threading
import traceback
from queue import Queue
from typing import Dict, List
from datetime import datetime
from app_logger import log_exception

class LogManager:
    def __init__(self, log_dir: str, flush_interval: int = 10):
        self.log_dir = log_dir
        self.flush_interval = flush_interval
        self._log: List[Dict] = []
        self._lock = threading.Lock()
        self._setup_log_directory()
        self.log_file = self._generate_log_filename()
        self.counter = 0
        self._queue = Queue()
        self._closed = False
        self._worker = threading.Thread(
            target=self._worker_loop,
            name="log-writer",
            daemon=False,
        )
        self._worker.start()

    def _setup_log_directory(self):
        if not os.path.exists(self.log_dir):
            os.makedirs(self.log_dir, exist_ok=True)

    def _generate_log_filename(self) -> str:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self.log_dir, f"log_{timestamp}.csv")

    def add_entry(self, entry: Dict):
        with self._lock:
            if self._closed:
                raise RuntimeError("LogManager 已關閉")
            self.counter += 1
            self._queue.put(("entry", entry))

    def flush(self):
        with self._lock:
            if self._closed:
                return
            completed = threading.Event()
            self._queue.put(("flush", completed))
        completed.wait()

    def close(self):
        with self._lock:
            if self._closed:
                return
            self._closed = True
            completed = threading.Event()
            self._queue.put(("close", completed))
        completed.wait()
        self._worker.join()

    def _worker_loop(self):
        while True:
            action, payload = self._queue.get()
            try:
                if action == "entry":
                    with self._lock:
                        self._log.append(payload)
                        should_flush = self.counter >= self.flush_interval
                    if should_flush:
                        self._write_log()
                else:
                    self._write_log()
                    if action == "close":
                        payload.set()
                        return
                    payload.set()
            except Exception as e:
                print(f"寫入日誌失敗: {e}")
                log_exception("背景寫入日誌例外")
                if action != "entry":
                    payload.set()
            finally:
                self._queue.task_done()

    def _write_log(self):
        with self._lock:
            if not self._log:
                return
            try:
                df = pd.DataFrame(self._log)
                write_header = not os.path.exists(self.log_file)
                df.to_csv(self.log_file, mode='a', header=write_header, index=False)
                self._log = []
                self.counter = 0
            except Exception as e:
                print(f"寫入日誌失敗: {e}")
                log_exception("寫入日誌例外")

    def should_flush(self) -> bool:
        with self._lock:
            return self.counter >= self.flush_interval

    @property
    def entry_count(self) -> int:
        with self._lock:
            return self.counter
