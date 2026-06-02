import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from common.db_backup_base import run_backup

if __name__ == "__main__":
    run_backup(app_name="tiffanys-space")
