#!/usr/bin/env python
"""Forwarder to root clean_up_.py"""
import runpy
from pathlib import Path

target = Path(__file__).resolve().parent.parent / "clean_up_.py"
if __name__ == "__main__":
    runpy.run_path(str(target), run_name="__main__")
