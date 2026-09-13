import time
import threading
import concurrent.futures
import logging
from enum import Enum, auto
from typing import Callable, Any, Optional

# ==========================================
# System Configuration
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

class OverlapStrategy(Enum):
    """Defines the behavior when a new task is triggered while the previous one is still executing."""
    SKIP = auto()      # Skip the new execution entirely.
    QUEUE = auto()     # Queue the new execution and run it sequentially (FIFO).
    PARALLEL = auto()  # Run the new execution concurrently in a new thread.
    LATEST = auto()    # Cancel any pending queued tasks, keep only the newest one.

# ==========================================
# Core Timer Implementation
# ==========================================
class PreciseIntervalTimer:
    def __init__(self, interval_seconds: float, callback: Callable,
                 strategy: OverlapStrategy = OverlapStrategy.SKIP,
                 max_pending: int = 50,
                 inject_timer: bool = False, *args: Any, **kwargs: Any) -> None:
        """
        Initializes the robust precision timer.
        
        :param interval_seconds: Execution interval in seconds.
        :param callback: Target function to execute.
        :param strategy: Resolution strategy for overlapping executions.
        :param max_pending: Maximum number of queued/active tasks to prevent memory leaks.
        """
        self._interval = interval_seconds
        self._callback = callback
        self._strategy = strategy
        self._max_pending = max_pending
        self._inject_timer = inject_timer
        self._args = args
        self._kwargs = kwargs
        
        # Using Event instead of boolean for thread-safe state and interruptible waiting
        self._stop_event = threading.Event()
        self._thread = None
        self._executor = None
        
        # State management for overlapping tasks
        self._active_futures = set()
        self._futures_lock = threading.Lock()

        # --- Crash-detection state (run loop dying unexpectedly) ---
        self._crashed_exception: Optional[BaseException] = None
        self._crashed_event = threading.Event()

    @property
    def crashed(self) -> bool:
        """True if the internal run loop terminated due to an unhandled exception
        (as opposed to a normal stop() call). Sampling has stopped if this is True."""
        return self._crashed_event.is_set()

    @property
    def crash_reason(self) -> Optional[BaseException]:
        """The exception that caused the run loop to crash, if any."""
        return self._crashed_exception

    @property
    def is_running(self) -> bool:
        """True if the internal run loop is thread is currently alive and dispatching ticks."""
        return self._thread is not None and self._thread.is_alive()

    def _create_executor(self) -> concurrent.futures.ThreadPoolExecutor:
        """Instantiates the thread pool based on the chosen strategy."""
        # QUEUE strategy requires strict sequential execution (1 worker)
        workers = 1 if self._strategy == OverlapStrategy.QUEUE else 10
        return concurrent.futures.ThreadPoolExecutor(max_workers=workers)

    def start(self) -> None:
        """Starts the timer thread."""
        if not self._stop_event.is_set() and self._thread is not None and self._thread.is_alive():
            logger.warning("Timer is already running.")
            return

        # Clear any crash state left over from a previous run before starting fresh.
        self._crashed_exception = None
        self._crashed_event.clear()

        self._stop_event.clear()
        self._executor = self._create_executor()
        
        # daemon=False: Main thread will wait for this thread to terminate
        self._thread = threading.Thread(target=self._run_loop, daemon=False)
        self._thread.start()
        logger.info(f"Timer started. Interval: {self._interval}s, Strategy: {self._strategy.name}")

    def stop(self, timeout: Optional[float] = None) -> None:
        """
        Stops the timer gracefully.

        :param timeout: How long (in seconds) to wait for any callback executions
            that are already RUNNING to finish naturally before giving up on them.
            - None (default): wait indefinitely for running callbacks to finish.
              Safest choice when the callback touches hardware/shared state, since
              it guarantees no stray callback is still executing after stop()
              returns. NOTE: if a callback hangs forever, stop() will block forever
              with this default — pick an explicit timeout if that risk matters
              for your callback.
            - 0: don't wait at all (previous behavior) — callbacks still running
              are abandoned in the background and may complete after stop() returns.
            - float > 0: wait up to that many seconds, then give up and abandon
              whatever is still running.
        """
        if self._stop_event.is_set():
            return

        if self.crashed:
            logger.info("Timer had crashed; cleaning up resources from the dead run loop.")

        logger.info("Stopping timer...")
        # Instantly breaks the wait() loop in the timer thread — no new ticks
        # will be dispatched after this point.
        self._stop_event.set()
        
        if self._thread and self._thread.is_alive():
            self._thread.join()

        with self._futures_lock:
            pending_or_running = list(self._active_futures)

        if pending_or_running:
            # Cancel whatever hasn't actually started yet — these free instantly.
            for f in pending_or_running:
                f.cancel()

            # Whatever couldn't be cancelled is currently running; wait for it
            # to finish naturally, up to `timeout` seconds, before abandoning it.
            _done, not_done = concurrent.futures.wait(
                pending_or_running,
                timeout=timeout,
                return_when=concurrent.futures.ALL_COMPLETED,
            )
            if not_done:
                logger.warning(
                    f"stop(timeout={timeout}) elapsed with {len(not_done)} callback(s) "
                    f"still running. Abandoning them in the background — they may "
                    f"still complete and mutate shared state after stop() returns."
                )

        with self._futures_lock:
            self._active_futures.clear()

        if self._executor:
            # By the time we get here we've already waited (up to `timeout`) for
            # running tasks above, so wait=False here just releases the executor's
            # internal resources without blocking further.
            self._executor.shutdown(wait=False)
            
        logger.info("Timer stopped successfully.")

    def restart(self, stop_timeout: Optional[float] = None) -> None:
        """Restarts the timer execution.

        :param stop_timeout: Forwarded to stop() — how long to wait for any
            currently-running callback to finish before the new cycle begins.
            Defaults to waiting indefinitely, so a straggling callback from the
            old cycle can never overlap with the new one.
        """
        logger.info("Restarting timer process...")
        self.stop(timeout=stop_timeout)
        self.start()

    def _handle_future_result(self, future: concurrent.futures.Future) -> None:
        """
        Callback attached to every Future. 
        Ensures exceptions are logged and do not vanish silently.
        """
        try:
            if not future.cancelled():
                # Extracting result raises any exception that occurred inside the callback
                future.result()
        except Exception as e:
            logger.error(f"Unhandled exception in target callback: {e}", exc_info=True)
        finally:
            # Cleanup the reference to avoid memory accumulation
            with self._futures_lock:
                self._active_futures.discard(future)

    def _dispatch_task(self) -> None:
        """Evaluates the strategy constraints and dispatches the task."""
        with self._futures_lock:
            # Clean up already completed tasks
            self._active_futures = {f for f in self._active_futures if not f.done()}

            if self._strategy == OverlapStrategy.SKIP:
                if self._active_futures:
                    logger.warning("Strategy SKIP: Previous execution is still active. Dropping current tick.")
                    return

            elif self._strategy == OverlapStrategy.LATEST:
                # Cancel any pending queued tasks; running tasks will ignore the cancellation
                for f in self._active_futures:
                    if f.cancel():
                        logger.debug("Strategy LATEST: Cancelled a pending queued task.")
                self._active_futures = {f for f in self._active_futures if not f.done()}

            elif self._strategy in (OverlapStrategy.QUEUE, OverlapStrategy.PARALLEL):
                if len(self._active_futures) >= self._max_pending:
                    logger.error(f"Security limit reached ({self._max_pending} pending tasks). Dropping tick to prevent memory leak.")
                    return

        try:
            if self._inject_timer:
                future = self._executor.submit(self._callback, self, *self._args, **self._kwargs)
            else:
                future = self._executor.submit(self._callback, *self._args, **self._kwargs)
            with self._futures_lock:
                self._active_futures.add(future)
            # Attach the exception handler
            future.add_done_callback(self._handle_future_result)
        except RuntimeError as e:
            logger.error(f"Failed to submit task (executor might be shut down): {e}")

    def _run_loop(self) -> None:
        """Core high-precision loop."""
        next_call_time = time.perf_counter()

        try:
            while not self._stop_event.is_set():
                self._dispatch_task()

                next_call_time += self._interval
                current_time = time.perf_counter()
                sleep_duration = next_call_time - current_time

                if sleep_duration > 0:
                    # Interruptible wait: exits immediately if stop() sets the event
                    if self._stop_event.wait(timeout=sleep_duration):
                        break
                else:
                    lag = abs(sleep_duration)
                    logger.warning(f"Timer lagging behind by {lag:.4f}s. Resetting baseline.")
                    next_call_time = time.perf_counter()
        except Exception as e:
            # Anything unexpected escaping the loop body means sampling has
            # silently stopped — record it so callers can detect and react,
            # instead of just losing a thread with a traceback on stderr.
            # (Exception, not BaseException: KeyboardInterrupt/SystemExit still
            # propagate normally and are not treated as a "crash" state.)
            self._crashed_exception = e
            self._crashed_event.set()
            logger.critical(
                f"Timer run loop terminated unexpectedly due to an unhandled "
                f"exception: {e}. Sampling has STOPPED. Call stop() to release "
                f"resources, inspect crash_reason, then start() to resume.",
                exc_info=True,
            )


# ==========================================
# Example Usage
# ==========================================
def faulty_and_slow_task(counter: list, output_lock: threading.Lock) -> None:
    """Simulates a task that takes longer than the interval and might crash."""
    with output_lock:
        current_count = counter[0]
        counter[0] += 1

    logger.info(f"Task #{current_count} started execution.")
    
    # Simulate workload taking 0.3 seconds (slower than the 0.1s interval)
    time.sleep(0.3) 
    
    # Simulate an unexpected exception at the 5th execution
    if current_count == 5:
        raise ValueError("Simulated critical failure during callback!")
        
    logger.info(f"Task #{current_count} completed.")


if __name__ == "__main__":
    execution_counter = [1]
    print_lock = threading.Lock()
    
    # Test with SKIP strategy to prevent overlap when tasks are slow
    timer = PreciseIntervalTimer(
        interval_seconds=0.1, 
        callback=faulty_and_slow_task,
        strategy=OverlapStrategy.SKIP,
        max_pending=50,
        counter=execution_counter, 
        output_lock=print_lock
    )
    
    try:
        timer.start()
        
        # Let it run for 1 second, then demonstrate restart().
        # stop_timeout=1.0 here means: wait up to 1s for the in-flight 0.3s
        # task to finish before the new cycle starts, instead of racing it.
        time.sleep(1)
        timer.restart(stop_timeout=1.0)
        
        # Run for another 2 seconds
        time.sleep(2)

        if timer.crashed:
            logger.error(f"Timer crashed: {timer.crash_reason}")
        
    except KeyboardInterrupt:
        logger.info("Execution interrupted by user.")
    finally:
        timer.stop(timeout=2.0)
