"""The application entry point behind /usr/bin/open-transcribe-assistant."""

import sys

from open_transcribe.desktop.errors import DesktopError
from open_transcribe.desktop.runtime import refuse_root
from open_transcribe.observability.logging import configure_logging


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    try:
        refuse_root()
    except DesktopError as exc:
        sys.stderr.write(f"{exc.message}\n{exc.recovery or ''}\n")
        return 1

    from PySide6.QtWidgets import QApplication

    from open_transcribe.desktop.gui.main_window import MainWindow
    from open_transcribe.desktop.gui.theme import apply_theme

    application = QApplication(argv if argv is not None else sys.argv)
    application.setApplicationName("OpenTranscribe Setup")
    application.setDesktopFileName("open-transcribe-assistant")
    application.setOrganizationName("OpenTranscribe")
    apply_theme(application)

    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())
