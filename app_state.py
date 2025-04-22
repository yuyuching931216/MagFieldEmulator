import threading
from typing import Optional

class AppState:
    def __init__(self, interval: float, voltage_limit: float):
        self._lock = threading.RLock()
        self._paused = False
        self._interval = interval
        self.__voltage_limit = voltage_limit
        self._stop = False
        self._current_row = 0
        self._task_active = False
        self._skipped_row = 0

    @property
    def paused(self) -> bool:
        with self._lock:
            return self._paused

    @paused.setter
    def paused(self, value: bool):
        with self._lock:
            self._paused = value

    @property
    def interval(self) -> float:
        with self._lock:
            return self._interval

    @interval.setter
    def interval(self, value: float):
        with self._lock:
            self._interval = value

    @property
    def voltage_limit(self) -> float:
        with self._lock:
            return self._voltage_limit

    @property
    def stop(self) -> bool:
        with self._lock:
            return self._stop

    @stop.setter
    def stop(self, value: bool):
        with self._lock:
            self._stop = value

    @property
    def current_row(self) -> int:
        with self._lock:
            return self._current_row

    @current_row.setter
    def current_row(self, value: int):
        with self._lock:
            self._current_row = value

    @property
    def task_active(self) -> bool:
        with self._lock:
            return self._task_active

    @task_active.setter
    def task_active(self, value: bool):
        with self._lock:
            self._task_active = value
            
    @property
    def skipped_row(self) -> Optional[int]:
        with self._lock:
            return self._skipped_rowi
        
    @skipped_row.setter
    def skipped_row(self, value: Optional[int]):
        with self._lock:
            self._skipped_row = value

    def with_lock(self, func):
        """Decorator to acquire and release the lock around a function."""
        def wrapper(*args, **kwargs):
            with self._lock:
                return func(*args, **kwargs)
        return wrapper