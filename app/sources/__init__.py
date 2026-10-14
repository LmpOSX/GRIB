# -*- coding: utf-8 -*-
"""Registro de fuentes de datos. Para sumar una fuente: implementarla como
subclase de `base.Source` en su módulo y agregarla a `SOURCES`."""
from .base import (  # noqa: F401
    Source, Param, Request, DownloadJob, DownloadError, DownloadCancelled, TestResult,
    read_provenance,
)
from .gfs import GFSSource
from .wafs import WAFSSource
from .ecmwf import ECMWFSource
from .icon import IconSource
from .smn import SMNSource
from .generic import GenericSource

# Orden del selector: la aeronáutica destacada primero tras el GFS
SOURCES = [GFSSource(), WAFSSource(), ECMWFSource(), IconSource(), SMNSource(), GenericSource()]


def all_sources():
    return list(SOURCES)


def get_source(key):
    for s in SOURCES:
        if s.key == key:
            return s
    return None


def source_config(cfg, key):
    """Configuración guardada de una fuente: {'enabled': bool, 'params': {}}."""
    src = get_source(key)
    stored = (cfg.get("sources") or {}).get(key) or {}
    enabled = stored.get("enabled", src.enabled_default if src else True)
    params = src.merged_params(stored.get("params")) if src else dict(stored.get("params") or {})
    return {"enabled": bool(enabled), "params": params}


def set_source_config(cfg, key, enabled=None, params=None):
    sources = dict(cfg.get("sources") or {})
    entry = dict(sources.get(key) or {})
    if enabled is not None:
        entry["enabled"] = bool(enabled)
    if params is not None:
        entry["params"] = dict(params)
    sources[key] = entry
    cfg["sources"] = sources


def enabled_sources(cfg):
    return [s for s in SOURCES if source_config(cfg, s.key)["enabled"]]


def source_label(src):
    """Nombre para combos, con el indicador ✓ FL cuando publica niveles por FL."""
    return f"{src.name}  ✓ FL" if src.flight_levels else src.name
