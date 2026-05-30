import sys
from pathlib import Path

# allow importing from sibling directories when running directly
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.db_backup_base import run_backup

if __name__ == "__main__":
    run_backup(app_name="auth")
