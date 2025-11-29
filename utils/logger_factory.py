# logger_factory.py

import logging
import colorlog
import os
import sys
from config.settings import settings


LOG_DIR = settings.LOG_PATH
os.makedirs(LOG_DIR, exist_ok=True)

def get_formatter():
    return colorlog.ColoredFormatter(
        '%(log_color)s%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        reset=True,
        log_colors={
            'DEBUG': 'white,bg_black',
            'INFO': 'cyan',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'bold_red,bg_white',
        },
    )

def trim_log_file(log_file="vaultbot.log", max_size=5 * 1024 * 1024):
    """Trim a log file to the last max_size bytes (keeps the newest logs)."""
    path = os.path.join(LOG_DIR, log_file)
    try:
        if os.path.exists(path):
            size = os.path.getsize(path)
            if size > max_size:
                with open(path, "rb") as f:
                    f.seek(-max_size, os.SEEK_END)
                    data = f.read()
                with open(path, "wb") as f:
                    f.write(data)
    except Exception as e:
        print(f"Failed to trim log file {path}: {e}")

def setup_logger(name: str, log_file: str = "vaultbot.log", level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger(name)
    logger.setLevel(level)

    if logger.hasHandlers():
        return logger  # avoid duplicate handlers on reload

    formatter = get_formatter()
    # Only pass filename to trim_log_file, not full path
    trim_log_file(log_file, 5 * 1024 * 1024)
    log_path = os.path.join(LOG_DIR, log_file)

    file_handler = logging.FileHandler(log_path, mode='a')
    file_handler.setFormatter(formatter)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler.setFormatter(formatter)

    logger.addHandler(file_handler)
    logger.addHandler(stream_handler)

    return logger
