import logging
import os

class ColorFormatter(logging.Formatter):
    # ANSI escape codes for coloring log levels
    COLORS = {
        'DEBUG': "\033[34m",     # Blue
        'INFO': "\033[32m",      # Green
        'WARNING': "\033[33m",   # Yellow
        'ERROR': "\033[31m",     # Red
        'CRITICAL': "\033[35m"   # Purple
    }
    RESET = "\033[0m"

    def format(self, record):
        levelname = record.levelname
        formatted = super().format(record)
        if levelname in self.COLORS:
            color = self.COLORS[levelname]
            return f"{color}{formatted}{self.RESET}"
        return formatted


LOG_FORMAT = "[%(asctime)s] | %(levelname)-5s | %(filename)s: %(lineno)d |  - %(message)s"
# Always resolve the default log file path to the current working directory, unless overridden by LOG_FILE env var
LOG_FILE = os.getenv("LOG_FILE", "./app.log")

def get_logger(name: str = None, level: int = logging.DEBUG, log_to_file: bool = True) -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        # Console handler with color – force UTF-8 to avoid cp1252 errors on Windows
        stream_handler = logging.StreamHandler()
        stream_handler.stream = open(
            stream_handler.stream.fileno(),
            mode="w",
            encoding="utf-8",
            errors="replace",
            closefd=False,
            buffering=1,
        )
        stream_handler.setFormatter(ColorFormatter(fmt=LOG_FORMAT))
        logger.addHandler(stream_handler)
        # Optional file handler (without color)
        if log_to_file:
            file_handler = logging.FileHandler(LOG_FILE)
            file_handler.setFormatter(logging.Formatter(fmt=LOG_FORMAT))
            logger.addHandler(file_handler)
    logger.setLevel(level)
    logger.propagate = False
    return logger

logger = get_logger(__name__)

if __name__ == "__main__":
    logger.debug("This is a debug message")
    logger.info("This is an info message")
    logger.warning("This is a warning message")
    logger.error("This is an error message")
    logger.critical("This is a critical message")