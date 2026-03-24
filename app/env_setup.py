"""Entry point — run directly or via PyInstaller .exe"""
import app.env_setup  # noqa: F401 — must be first, sets fontconfig + DLL paths

from app.ui import App

if __name__ == "__main__":
    app = App()
    app.mainloop()