"""
Offline Invoice — Entry point.
Run directly (python main.py) or as a PyInstaller-compiled exe.
"""
import os
import sys
import logging
import traceback
from pathlib import Path


# ── 1. Resolve log file location ─────────────────────────────────────────────
def _get_log_path() -> Path:
    if getattr(sys, "frozen", False):
        if sys.platform == "win32":
            base = Path(os.environ.get("APPDATA", Path.home())) / "OfflineInvoice"
        elif sys.platform == "darwin":
            base = Path.home() / "Library" / "Application Support" / "OfflineInvoice"
        else:
            base = Path.home() / ".local" / "share" / "OfflineInvoice"
    else:
        base = Path(__file__).parent

    base.mkdir(parents=True, exist_ok=True)
    return base / "app.log"


# ── 2. Configure logging ──────────────────────────────────────────────────────
def _setup_logging():
    from logging.handlers import RotatingFileHandler

    log_path = _get_log_path()
    root = logging.getLogger()
    root.setLevel(logging.DEBUG)

    logging.getLogger("PIL").setLevel(logging.WARNING)
    logging.getLogger("weasyprint").setLevel(logging.WARNING)
    logging.getLogger("fontTools").setLevel(logging.WARNING)

    fh = RotatingFileHandler(
        log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))
    root.addHandler(fh)

    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    root.addHandler(sh)

    logging.info("=" * 60)
    logging.info("Offline Invoice starting  (frozen=%s)",
                 getattr(sys, "frozen", False))
    logging.info("Log file: %s", log_path)
    logging.info("Python %s  |  Platform: %s",
                 sys.version.split()[0], sys.platform)

    return log_path


# ── 3. Global unhandled-exception hook ───────────────────────────────────────
def _install_exception_hook(log_path: Path):
    """
    Catches any unhandled exception, writes full traceback to app.log,
    then shows a Qt message box so the user knows where the log is.
    """
    def _handle(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        msg = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
        logging.critical("Unhandled exception:\n%s", msg)

        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication.instance()
            if _app is None:
                _app = QApplication(sys.argv)
            QMessageBox.critical(
                None,
                "Offline Invoice - Unexpected Error",
                f"An unexpected error occurred and the app needs to close.\n\n"
                f"A detailed report has been saved to:\n{log_path}\n\n"
                f"Please send this file when reporting the issue.\n\n"
                f"Error: {exc_type.__name__}: {exc_value}",
            )
        except Exception:
            pass

    sys.excepthook = _handle


# ── 4. Catch Qt-level messages (warnings, critical errors from Qt itself) ─────
def _install_qt_message_handler():
    try:
        from PySide6.QtCore import qInstallMessageHandler, QtMsgType

        def _qt_handler(mode, context, message):
            if mode == QtMsgType.QtFatalMsg or mode == QtMsgType.QtCriticalMsg:
                logging.critical("Qt [%s] %s", mode, message)
            elif mode == QtMsgType.QtWarningMsg:
                logging.warning("Qt [%s] %s", mode, message)
            else:
                logging.debug("Qt [%s] %s", mode, message)

        qInstallMessageHandler(_qt_handler)
    except Exception:
        pass  # Non-fatal — just won't capture Qt-level messages


# ── 5. WeasyPrint / subprocess setup ─────────────────────────────────────────
def _setup_weasyprint_env():
    """Configure WeasyPrint's font and DLL environment before any imports."""
    if getattr(sys, "frozen", False):
        base = Path(sys._MEIPASS)  # type: ignore[attr-defined]
        fonts_dir = base / "weasyprint_fonts"
        if fonts_dir.exists():
            os.environ["FONTCONFIG_PATH"] = str(fonts_dir)
            os.environ["FONTCONFIG_FILE"] = str(fonts_dir / "fonts.conf")

        exe_dir = Path(sys.executable).parent
        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(exe_dir))
            except Exception:
                pass
    else:
        candidates = [
            Path(r"E:\msys64\mingw64\etc\fonts"),
            Path(r"C:\msys64\mingw64\etc\fonts"),
            Path(r"D:\msys64\mingw64\etc\fonts"),
            Path(r"C:\Program Files\GTK3-Runtime Win64\etc\fonts"),
            Path(r"C:\gtk\etc\fonts"),
        ]
        for fonts_dir in candidates:
            if fonts_dir.exists():
                os.environ.setdefault("FONTCONFIG_PATH", str(fonts_dir))
                conf = fonts_dir / "fonts.conf"
                if conf.exists():
                    os.environ.setdefault("FONTCONFIG_FILE", str(conf))
                bin_dir = fonts_dir.parent.parent / "bin"
                if bin_dir.exists() and hasattr(os, "add_dll_directory"):
                    try:
                        os.add_dll_directory(str(bin_dir))
                    except Exception:
                        pass
                break

        if hasattr(os, "add_dll_directory"):
            try:
                os.add_dll_directory(str(Path(sys.executable).parent))
            except Exception:
                pass

    # Suppress fontconfig stderr noise on Windows
    try:
        devnull = open(os.devnull, "w")
        old_fd  = os.dup(2)
        os.dup2(devnull.fileno(), 2)
        try:
            import cffi  # noqa - triggers DLL load
        except Exception:
            pass
        os.dup2(old_fd, 2)
        os.close(old_fd)
        devnull.close()
    except Exception:
        pass


def _patch_subprocess_no_window():
    """Prevent WeasyPrint subprocesses from flashing a console window (Windows)."""
    if sys.platform != "win32":
        return

    import subprocess
    CREATE_NO_WINDOW = 0x08000000
    _OrigPopen = subprocess.Popen

    class _SilentPopen(_OrigPopen):
        def __init__(self, *args, **kwargs):
            kwargs["creationflags"] = (
                kwargs.get("creationflags", 0) | CREATE_NO_WINDOW)
            super().__init__(*args, **kwargs)

    subprocess.Popen = _SilentPopen


# ── Bootstrap (runs before any other imports) ─────────────────────────────────
log_path = _setup_logging()
_install_exception_hook(log_path)
_install_qt_message_handler()
_setup_weasyprint_env()
_patch_subprocess_no_window()

logging.info("Environment setup complete - importing app")

from app.ui import App  # noqa: E402 - intentional late import


if __name__ == "__main__":
    logging.info("Starting Qt main loop")
    try:
        qt_app = App(sys.argv)
        logging.info("DEBUG: App created successfully, entering exec()")
        exit_code = qt_app.exec()
        logging.info("Main loop exited cleanly (code %d)", exit_code)
        sys.exit(exit_code)
    except Exception:
        logging.critical("Crash in main loop:\n%s", traceback.format_exc())
        raise