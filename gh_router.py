#!/usr/bin/env python3
"""Run the dependency-free CLI directly from this checkout."""
import os
from pathlib import Path
import sys

source = str(Path(__file__).resolve().parent / "src")
sys.path.insert(0, source)
os.environ["PYTHONPATH"] = source + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else "")

from github_account_router.cli import main

if __name__ == "__main__":
    sys.exit(main())
