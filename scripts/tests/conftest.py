import sys
from pathlib import Path

# Make scripts/ importable: rotate_secret, common.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
