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
    "window_w": 1600,
    "window_h": 1000,
    "panel_visible": True,   # panel lateral de controles visible
    "recent_files": [],      # list[str] — most-recent first
    "last_directory": "",    # working directory for open/save dialogs
    "projection": "platecarree",   # clave de wind_plot.PROJECTIONS
    # Mapa: valores iniciales de CONFIG del panel (se guardan al cambiarlos)
    "map_wind_style": "barbas",   # 'barbas' | 'flechas' | 'curvas' (wind_plot.WIND_STYLES)
    "map_extra_info": False,
    "map_grid": False,
    "map_grid_step": 10,          # grilla de grados: 10, 5 o 1
    "map_fill": False,
    "map_stride": 1,
    "map_label_size": 7,          # tamaño (pt) de los rótulos de Extra Info
    "map_label_units": True,      # rótulos con unidad ("12 kt  −45 °C")
    # Fuentes de datos: última elegida y configuración por fuente
    "source": "gfs",
    "sources": {},                      # {clave: {"enabled": bool, "params": {...}}}
    "cache_max_mb": 500,                # caché de descargas (0 = sin límite)
    "cache_max_days": 3,
    # Descarga: valores iniciales del diálogo
    "download_merge": True,             # un solo archivo con todos los pasos
    "download_open": True,              # abrir en el visor al terminar
    "download_h_from": 6,
    "download_h_to": 12,
    "download_h_step": 3,
    # Formato WAFS (formato interno único del visor)
    "wafs_convert": True,               # convertir a WAFS lo que se descarga (fuentes de altura)
    "wafs_convert_local": True,         # convertir también los archivos locales al abrirlos
    "wafs_fl_min": 50,                  # rango de FL por defecto (FL050–FL530 = GFS 850–100 hPa)
    "wafs_fl_max": 530,
    "wafs_fl_extend": True,             # ampliar el rango si el origen cubre más niveles (hasta FL600)
    "wafs_extrapolate": False,          # FL fuera del origen: omitir (False) o nivel más cercano
    # Motor de lectura: 'eccodes' (biblioteca Python) o 'wgrib2' (programa externo)
    "engine": "eccodes",
    "wgrib2_path": "",                  # vacío = buscar en el PATH
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


def _migrate(cfg: dict):
    """Claves de versiones anteriores → configuración por fuente."""
    if "download_resolution" in cfg or "download_extra_levels" in cfg:
        sources = dict(cfg.get("sources") or {})
        gfs = dict(sources.get("gfs") or {})
        params = dict(gfs.get("params") or {})
        if "download_resolution" in cfg:
            params.setdefault("resolucion", cfg.pop("download_resolution"))
        if "download_extra_levels" in cfg:
            params.setdefault("niveles_intermedios", cfg.pop("download_extra_levels"))
        gfs["params"] = params
        sources["gfs"] = gfs
        cfg["sources"] = sources


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            # merge with defaults for any missing keys
            merged = dict(DEFAULTS)
            merged.update(data)
            _migrate(merged)
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
