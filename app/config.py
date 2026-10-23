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
    "hex_visible": False,    # panel hexadecimal a la izquierda del mapa
    "recent_files": [],      # list[str] — most-recent first
    "last_directory": "",    # directorio de trabajo de la sesión (el del último archivo abierto o exportado)
    "download_dir": "",      # directorio de trabajo por defecto (vacío = Documentos); ver working_dir()
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
    "map_coast": True,            # costas y fronteras (menú Capas)
    "map_graticule": True,        # meridianos y paralelos con rótulos (menú Capas)
    "map_zoom_step": 20,          # % de acercamiento por paso de la rueda (o por botón ±)
    "map_fine_divisor": 5,        # modo fino (Cmd/Ctrl o Shift apretados): rueda y arrastre ÷ N
    # Capa de límites de FIR (ver app/fir.py)
    "fir_enabled": False,          # dibujar las FIR de Argentina
    "fir_neighbors": False,        # dibujar también las FIR vecinas (más tenues)
    "fir_active": ["SARR", "SACF", "SAMF", "SAEF", "SAVF", "SUEO", "SGFA", "SLLF",
                   "SCEZ", "SCCZ", "SBCW", "SBBS", "SBAO", "FAJO"],   # códigos tildados
    "fir_color": "#b39ddb",        # contorno y etiqueta de las FIR argentinas
    "fir_neighbor_color": "#8d8da8",
    "fir_line_width": 1.3,
    "fir_fill_alpha": 0.08,        # relleno semitransparente (0 = sin relleno)
    "fir_label_size": 9,           # pt de la etiqueta (nombre + código)
    "fir_preferred": "vatspy",     # fuente descargada preferida: 'vatspy' | 'openaip'
    "fir_user_file": "",           # GeoJSON/KML/SHP propio (reemplaza a las demás fuentes)
    # Working Area de cada FIR (ver app/working_area.py): cuadrado en NM sobre
    # un plano estereográfico tangente; se carga a mano en Vista ▸ FIR ▸ FIR…
    "working_areas": [],           # [{code, tangent_lat, tangent_lon, vertex_lat, vertex_lon,
                                   #   width_nm, height_nm, radius_km, enabled}]
    "wa_show": False,              # dibujar la WA junto con cada FIR mostrada
    "wa_color": "#ffd54f",
    "wa_line_width": 1.3,
    "wa_label_size": 8,
    "magvar_convention": "east_positive",   # signo de la variación magnética al escribirla (working_area.MAGVAR_CONVENTIONS)
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
    # Áreas de descarga por FIR (ver app/areas.py): tabla, margen y formato
    "areas": [],                        # vacío = las cinco FIR argentinas por defecto
    "areas_margin_deg": 1.0,            # margen que se suma por fuera al usar el área
    "areas_coord_format": "decimal",    # 'decimal' | 'gm' (grados-minutos con hemisferio)
    "download_area_mode": "fir",        # último modo del bloque Área: 'fir' | 'manual'
    "download_area_codes": ["SARR", "SACF", "SAMF", "SAEF", "SAVF"],   # casillas marcadas
    "download_manual_region": [4.0, -64.0, -90.0, -22.0],              # última zona manual (N, S, W, E)
    "download_area_draw": False,        # dibujar los rectángulos del área en el mapa
    # Bloque «Archivo a guardar» (Preferencias ▸ Guardar; también en Obtener
    # datos, Generar GRIB y Guardar como…): cómo se graba lo que escribe el visor
    "save_wind": "uv",                  # viento: 'uv' (UGRD/VGRD) | 'dirspeed' (WDIR/WIND)
    "save_dec_wind": None,              # decimales del viento: None (como el origen) | 0 | 1 | 2
    "save_dec_temp": None,              # decimales de la temperatura: ídem
    "save_label": "modo",               # etiqueta de capa por Nivel: 'modo' | 'nominal' | 'isa' | 'isa_int'
    "save_packing": "origen",           # empaquetado: 'origen' | 'simple' | 'ieee' (un valor por celda)
    "save_centre": "origen",            # centro generador: 'origen' | 'missing' (65535)
    "save_scan": "origen",              # orden de las celdas: 'origen' | 'ns_we' | 'ns_ew' | 'sn_we' | 'sn_ew'
    "save_rows": "origen",              # filas: 'origen' | 'consecutivas' | 'intercaladas' (bustrofedón)
    "generate_res_deg": 0.25,           # última resolución de «Generar GRIB…»
    # Formato WAFS (formato interno único del visor)
    "wafs_convert": True,               # valor inicial de «Convertir a WAFS» en el diálogo de descarga
    "wafs_convert_local": True,         # convertir también los archivos locales al abrirlos
    "wafs_mode": "OACI",                # modo de etiquetado de los FL (fl_table.MODES): INDRA | OACI (17, por defecto) | OACI56 | WAFS
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

    Mientras dura la sesión es la carpeta del último archivo abierto (también
    desde el Finder o la línea de comandos) o de la última exportación
    (`last_directory`). Si todavía no hay uno, o ya no existe, es el
    directorio por defecto de Preferencias ▸ Descarga (`download_dir`), y si
    tampoco está, Documentos.
    """
    for d in (cfg.get("last_directory"), cfg.get("download_dir")):
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


def _migrate_save(cfg):
    """«Viento en el archivo» (download_wind_format) pasó al bloque Archivo a guardar."""
    if "download_wind_format" in cfg:
        old = cfg.pop("download_wind_format")
        if cfg.get("save_wind") in (None, DEFAULTS["save_wind"]) and old in ("uv", "dirspeed"):
            cfg["save_wind"] = old


def load_config() -> dict:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                data = json.load(f)
            # merge with defaults for any missing keys
            merged = dict(DEFAULTS)
            merged.update(data)
            _migrate(merged)
            _migrate_save(merged)
            return merged
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict):
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
