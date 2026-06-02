import sys
from pathlib import Path

# Make scripts/ importable: rotate_vercel_tokens, rotate_gh_pat, common.*
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
