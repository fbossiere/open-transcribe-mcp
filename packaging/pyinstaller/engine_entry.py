"""Frozen entry point for the packaged engine."""

import multiprocessing
import sys

from open_transcribe.cli import run_cli

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(run_cli())
