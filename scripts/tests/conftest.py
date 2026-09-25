import sys
from pathlib import Path

# Make scripts/ importable: rotate_secret, common.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
# and e2e/, the self-contained stack driver its own tests import (test_e2e_engine.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "e2e"))
