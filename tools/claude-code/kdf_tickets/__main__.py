"""
Run the tickets tool as kdf-tickets.sh runs it, this folder named to an isolated interpreter with -I and -B.

Python puts the folder it runs first on the import path. This takes it off and adds the folder holding the package at
the end instead, so the standard library and the venv come first, and every module of the tool is imported by its full
name, kdf_tickets.<module>, the command line among them once the path is set.
"""

# standard imports
import importlib
import sys
from pathlib import Path

sys.path.pop(0)
sys.path.append(str(Path(__file__).resolve().parent.parent))
sys.exit(importlib.import_module("kdf_tickets.cli").main())
