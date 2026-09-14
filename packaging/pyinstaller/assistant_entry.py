"""Frozen entry point for OpenTranscribe Setup."""

import multiprocessing
import sys

from open_transcribe.desktop.gui.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
