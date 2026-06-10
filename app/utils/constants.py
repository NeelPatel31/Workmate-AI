from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
FILES_ROOT = PROJECT_ROOT / "files"
COMPOSE_FILE = PROJECT_ROOT / "filesystem-env" / "docker-compose.yml"

CONTAINER_NAME = "sandbox-env"
CONTAINER_UPLOADS_DIR = "/usr-data/uploads"
CONTAINER_OUTPUT_DIR = "/usr-data/output"
CONTAINER_SCRATCHPAD_DIR = "/scratchpad"

MAX_LINES = 400
DEFAULT_TIMEOUT = 30
TIMEOUT_EXIT_CODE = 124  # GNU timeout(1) when the duration is exceeded
TIMEOUT_KILL_AFTER = 5  # seconds between SIGTERM and SIGKILL
TIMEOUT_PYTHON_GRACE = 3  # reader deadline beyond kill-after

# Aliases used by the bash executor
UPLOADS_DIR = CONTAINER_UPLOADS_DIR
OUTPUT_DIR = CONTAINER_OUTPUT_DIR
FILES_DIR = CONTAINER_SCRATCHPAD_DIR
