import builtins
import os
import sys
from datetime import datetime
from typing import Any

from loguru import logger


_original_print = builtins.print
_print_wrapped = False


def _print_and_log(*args: Any, sep: str = " ", end: str = "\n",
                   file=None, flush: bool = False):
    _original_print(*args, sep=sep, end=end, file=file, flush=flush)

    if file is not None and file is not sys.stdout:
        return

    message = sep.join(str(arg) for arg in args)
    if end != "\n":
        message += end
    if message:
        logger.info(message.rstrip("\r\n"))


def setup_logging(log_dir: str):
    """Keep console output unchanged and mirror it to a daily Loguru file."""
    global _print_wrapped

    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f"{datetime.now():%Y%m%d}.log")
    logger.remove()
    logger.add(
        log_path,
        encoding="utf-8",
        enqueue=True,
        backtrace=True,
        diagnose=False,
        format="{time:YYYY-MM-DD HH:mm:ss.SSS} | {level:<8} | {message}",
    )

    if not _print_wrapped:
        builtins.print = _print_and_log
        _print_wrapped = True


def log_exception(message: str):
    logger.exception(message)