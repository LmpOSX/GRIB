import json
import os
import sys

APP_NAME = "Visor GRIB"


def _resolve_config_path() -> str:
    """Return the config file path.

    - Frozen app bundle (py2app / PyInstaller):
        * macOS:   ~/Library/Application Support/Visor GRIB/config.json
        * Windows: %APPDATA%/Visor GRIB/config.json
        * Linux:   ~/.config/Visor GRIB/config.json
      This keeps user prefs (recent files, accent, geometry, …) persistent
      across upgrades where the .app bundle is replaced.
    - Development mode (running main.py from source):
        repo_root/config.json — unchanged, convenient for testing.
    """
    frozen = getattr(sys, "frozen", False) or ".app/Contents/" in __file__
    if not frozen:
        return os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "config.json"
        )

    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    elif sys.platform == "win32":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")

    folder = os.path.join(base, APP_NAME)
    try:
        os.makedirs(folder, exist_ok=True)
    except OSError:
        pass
    return os.path.join(folder, "config.json")


CONFIG_PATH = _resolve_config_path()

DEFAULTS = {
    "accent_color": "#4A90D9",
    "font_size": 13,
    "opacity": 180,          # 80–255, controls background translucency
    "window_x": 100,
    "window_y": 100,
    "window_w": 1400,
    "window_h": 860,
    "recent_files": [],      # list[str] — most-recent first
    "last_directory": "",    # working directory for open/save dialogs
    "projection": "platecarree",   # clave de wind_plot.PROJECTIONS
}

OPACITY_MIN = 80
OPACITY_MAX = 255

FONT_SIZE_MIN = 9
FONT_SIZE_MAX = 22

RECENT_FILES_MAX = 10


def default_working_dir() -> str:
    """Primera ejecución: Documents / Documentos / carpeta del usuario."""
    home = os.path.expanduser("~")
    for name in ("Documents", "Documentos"):
        d = os.path.join(home, name)
        if os.path.isdir(d):
            return d
    return home


def working_dir(cfg: dict) -> str:
    """Directorio de trabajo vigente para abrir / guardar / exportar.

    Es la carpeta del último .grib2 abierto o de la última exportación (`last_directory`).
    Si todavía no hay uno, o ya no existe, cae al default.
    """
    d = cfg.get("last_directory") or ""
    if d and os.path.isdir(d):
        return d
    return default_working_dir()


def push_recent_file(cfg: dict, path: str):
    """Add path to the front of recent_files (dedup), cap to RECENT_FILES_MAX
    and update last_directory. Mutates cfg in place."""
    if not path:
        return
    abs_path = os.path.abspath(path)
    recents = [p for p in (cfg.get("recent_files") or []) if p != abs_path]
    recents.insert(0, abs_path)
    cfg["recent_files"] = recents[:RECENT_FILES_MAX]
    parent = os.path.dirname(abs_path)
    if parent:
        cfg["last_directory"] = parent


def remove_recent_file(cfg: dict, path: str):
    """Remove a path from recent_files (e.g. when the file no longer exists)."""
    if not path:
        return
    abs_path = os.path.abspath(path)
    cfg["recent_files"] = [
        p for p in (cfg.get("recent_files") or []) if p != abs_path
    ]


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            # merge with defaults for any missing keys
            merged = dict(DEFAULTS)
            merged.update(data)
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
