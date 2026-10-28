# -*- coding: utf-8 -*-
"""Perfiles del bloque «Archivo a guardar» (sin Qt).

Un **perfil** es un juego completo de valores del bloque (las `KEYS` de
grib_encode: regrillado, viento, decimales, etiqueta, empaquetado, centro,
orden, filas, longitudes, tablas) con nombre, más dos comportamientos
opcionales que cada diálogo aplica si los entiende:

* `grid`: id de una grilla con nombre (areas.Grid): Obtener datos, Generar
  y Exportar a WAFS pasan a esa zona (y a su resolución).
* `fl_mode`: modo de etiquetado de los niveles (fl_table.MODES): los
  diálogos que lo eligen lo cambian.

Los de fábrica (`FACTORY`, a partir de grib_encode.PROFILES) conservan su
`id`; se pueden editar y renombrar, no borrar (se ocultan con `enabled`), y
«Restaurar de fábrica» los devuelve. La tabla vive en la configuración
(`profiles`: vacía o ausente = fábrica) y se edita en Preferencias ▸
Perfiles. La configuración guarda los valores sueltos `save_*`, nunca «el
perfil elegido»: borrar un perfil no rompe nada.
"""
import uuid

from . import fl_table as flt
from . import grib_encode as ge

# Comportamientos de los perfiles de fábrica además de sus valores
_FACTORY_EXTRAS = {"fdp": {"grid": "fdp_arg", "fl_mode": "INDRA"}}
DEFAULT_ID = "origen"       # «Como el origen»: no se edita ni se oculta


class Profile:
    FIELDS = ("id", "name", "values", "grid", "fl_mode", "builtin", "enabled")

    def __init__(self, id, name="", values=None, grid=None, fl_mode=None, builtin=False, enabled=True):
        self.id = str(id or "").strip()
        self.name = str(name or "").strip()
        self.values = {k: v for k, v in ge.normalize(values or {}).items() if k in ge.KEYS}
        self.grid = str(grid).strip() if grid else None
        try:
            self.fl_mode = flt.normalize_mode(fl_mode) if fl_mode else None
        except ValueError:
            self.fl_mode = None
        self.builtin = bool(builtin)
        self.enabled = bool(enabled)

    @classmethod
    def from_dict(cls, d):
        d = dict(d or {})
        return cls(d.get("id", ""), d.get("name", ""), d.get("values"), d.get("grid"),
                   d.get("fl_mode"), d.get("builtin", False), d.get("enabled", True))

    def to_dict(self):
        return {"id": self.id, "name": self.name, "values": dict(self.values), "grid": self.grid,
                "fl_mode": self.fl_mode, "builtin": self.builtin, "enabled": self.enabled}

    @property
    def is_default(self):
        return self.id == DEFAULT_ID

    def same_values(self, other):
        return (self.name == other.name and self.values == other.values and self.grid == other.grid
                and self.fl_mode == other.fl_mode)

    def copy(self):
        return Profile.from_dict(self.to_dict())

    def __repr__(self):
        return f"Profile({self.id}, {self.name!r}, grid={self.grid}, fl_mode={self.fl_mode})"


def factory_profiles():
    out = []
    for key, text, vals in ge.PROFILES:
        extra = _FACTORY_EXTRAS.get(key, {})
        out.append(Profile(key, text, vals, extra.get("grid"), extra.get("fl_mode"), builtin=True))
    return out


def factory_profile(pid):
    for p in factory_profiles():
        if p.id == pid:
            return p
    return None


def profiles_from_config(cfg):
    """Tabla de perfiles de la configuración: vacía o ausente = los de
    fábrica. Se sanea (ids repetidos o vacíos) y se agregan al final los
    de fábrica que falten, sin revivir los que el usuario ocultó. «Como el
    origen» queda siempre primero y visible."""
    raw = cfg.get("profiles") if isinstance(cfg, dict) else None
    if not raw:
        return factory_profiles()
    out, seen = [], set()
    for d in raw:
        try:
            p = Profile.from_dict(d)
        except (TypeError, ValueError, AttributeError):
            continue
        if not p.id or p.id in seen:
            continue
        if factory_profile(p.id) is not None:
            p.builtin = True
        if p.is_default:
            p.enabled = True
        seen.add(p.id)
        out.append(p)
    for f in factory_profiles():
        if f.id not in seen:
            out.append(f)
    out.sort(key=lambda p: 0 if p.is_default else 1)
    return out


def profiles_to_config(profiles):
    return [p.to_dict() for p in profiles]


def find_profile(profiles, pid, enabled_only=False):
    for p in profiles:
        if p.id == pid and (p.enabled or not enabled_only):
            return p
    return None


def is_modified(profile):
    f = factory_profile(profile.id) if profile.builtin else None
    return f is not None and not profile.same_values(f)


def new_id():
    return "u_" + uuid.uuid4().hex[:8]


def profile_of(opts, profiles, prefer=None):
    """Id del perfil visible cuyos valores coinciden con `opts`, o None
    (personalizado). Si varios coinciden gana `prefer` (el elegido a mano)
    y si no, el primero de la lista: así un perfil con los mismos valores
    que otro (difieren en la grilla o el modo) no «salta» al vecino."""
    o = ge.normalize(opts)
    hits = [p.id for p in profiles if p.enabled and all(o[k] == p.values.get(k) for k in ge.KEYS)]
    if not hits:
        return None
    return prefer if prefer in hits else hits[0]


def profile_values(pid, profiles):
    p = find_profile(profiles, pid)
    return dict(p.values) if p is not None else None


def describe(profile, grids=None):
    """Resumen corto de los comportamientos: `grilla FDP Arg (1°, 51 × 36) · FL INDRA`."""
    parts = []
    if profile.grid:
        g = None
        for x in (grids or []):
            if x.id == profile.grid:
                g = x
        if g is None:
            parts.append(f"grilla {profile.grid} (no existe)")
        else:
            n = g.size()
            parts.append(f"grilla {g.name}" + (f" ({g.res:g}°, {n[0]} × {n[1]})" if n else ""))
    if profile.fl_mode:
        parts.append(f"FL {profile.fl_mode}")
    return " · ".join(parts)
