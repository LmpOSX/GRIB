# -*- coding: utf-8 -*-
"""openAIP como tercera fuente de límites de FIR (no de datos
meteorológicos). La API Core de openAIP (https://docs.openaip.net/) publica
los espacios aéreos en GeoJSON; el tipo 10 es FIR y el 11 UIR. Requiere una
clave de API gratuita (perfil de usuario en openaip.net) que se envía en el
encabezado `x-openaip-api-key` y se guarda en el llavero del sistema como
«token» de esta fuente, nunca en config.json.

Datos bajo CC BY-NC 4.0 (uso no comercial, con atribución). La cobertura
de Argentina no se pudo verificar sin clave: «Probar conexión» informa
cuántas FIR del país devuelve la API.
"""
import datetime as dt
import json
import os
import unicodedata
import urllib.parse

from .base import Source, Param, TestResult, DownloadError, DownloadCancelled, classify_exception
from .. import fir as firmod

API_URL = "https://api.core.openaip.net/api/airspaces"
KEY_HEADER = "x-openaip-api-key"
TYPE_FIR = 10
TYPE_UIR = 11
LICENSE = "CC BY-NC 4.0"
PAGE_LIMIT = 100


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if unicodedata.category(c) != "Mn").upper()


# Nombre normalizado → código OACI (openAIP no siempre trae el indicador)
_NAME_TO_CODE = {_norm(name): code for code, name in firmod.FIR_NAMES.items()}
_NAME_TO_CODE["COMODORO"] = "SAVF"
_NAME_TO_CODE["JOHANNESBURG OCEANIC"] = "FAJO"
_NAME_TO_CODE["ATLANTICO"] = "SBAO"


def code_for_name(name):
    """Código OACI de una FIR a partir de su nombre («EZEIZA FIR»,
    «FIR Comodoro Rivadavia», «SAVF»)."""
    n = _norm(name)
    import re
    m = re.search(r"\b(S[ABCGLU][A-Z]{2}|FAJO)\b", n)
    if m and m.group(1) in firmod.FIR_NAMES:
        return m.group(1)
    for key, code in _NAME_TO_CODE.items():
        if key and key in n:
            return code
    return None


class OpenAipFirSource(Source):
    key = "openaip_fir"
    name = "openAIP (límites de FIR)"
    model = "openAIP Core API · espacios aéreos tipo FIR (10) y UIR (11), en GeoJSON"
    kind = "limites"
    flight_levels = False
    needs_credentials = True
    auth_kinds = ["token"]
    doc_url = "https://docs.openaip.net/"
    description = ("Fuente opcional de límites de FIR para la capa del mapa (no es una fuente de "
                   "datos meteorológicos). La clave de API se crea gratis en el perfil de "
                   f"openaip.net y se guarda en el llavero. Datos bajo {LICENSE}: uso no comercial "
                   "con atribución; no son los límites oficiales del AIP.")
    enabled_default = True
    file_ext = ".geojson"
    expect = "any"
    params = [
        Param("pais", "País (código ISO alpha-2)", "str", "AR",
              help="Filtro `country` de la API; AR = Argentina"),
        Param("incluir_uir", "Incluir también las UIR (tipo 11)", "bool", False),
    ]
    region_filter = "ninguno"

    # ── URLs ──
    def types(self, params):
        p = self.merged_params(params)
        return [TYPE_FIR, TYPE_UIR] if p.get("incluir_uir") else [TYPE_FIR]

    def url(self, params, page=1, limit=PAGE_LIMIT):
        p = self.merged_params(params)
        q = [("country", (p.get("pais") or "AR").strip().upper()), ("page", page), ("limit", limit)]
        q += [("type", t) for t in self.types(params)]
        return API_URL + "?" + urllib.parse.urlencode(q)

    @staticmethod
    def headers(credentials):
        tok = (credentials or {}).get("token") or ""
        return {KEY_HEADER: tok, "Accept": "application/json"} if tok else {"Accept": "application/json"}

    # ── Prueba ──
    def test_connection(self, params=None, credentials=None, fetch_fn=None):
        if fetch_fn is None:
            from ..gfs_download import fetch as fetch_fn
        creds = credentials or self.credentials()
        if not (creds or {}).get("token"):
            return TestResult("credenciales", "falta la clave de API de openAIP (token)")
        try:
            data = fetch_fn(self.url(params, page=1, limit=1), headers=self.headers(creds))
            obj = firmod.parse_json_bytes(data, "openAIP")
        except DownloadError as exc:
            return TestResult("contenido", str(exc))
        except Exception as exc:
            st, msg = classify_exception(exc)
            return TestResult(st, msg)
        total = obj.get("totalCount")
        if total is None:
            total = len(obj.get("items") or [])
        pais = self.merged_params(params).get("pais", "AR")
        if not total:
            return TestResult("no_publicado", f"openAIP no tiene FIR del país {pais} "
                                              f"(se puede seguir con VATSpy o el AIP)")
        return TestResult("ok", f"openAIP responde: {total} FIR/UIR del país {pais}")

    # ── Descarga ──
    def download_firs(self, params=None, credentials=None, fetch_fn=None, progress_cb=None,
                      cancel=None, dest=None):
        """Baja todas las páginas, convierte los ítems a FirRegion y guarda
        un GeoJSON en la carpeta de datos. Devuelve (ruta, regiones,
        nombres sin código reconocido)."""
        from .base import fetch_with_retries
        if fetch_fn is None:
            from ..gfs_download import fetch as fetch_fn
        creds = credentials or self.credentials()
        if not (creds or {}).get("token"):
            raise DownloadError("Falta la clave de API de openAIP: cargala en Preferencias ▸ Fuentes ▸ "
                                "openAIP (límites de FIR).", status="credenciales")
        regions, unknown = [], []
        page = 1
        while True:
            if cancel is not None and cancel():
                raise DownloadCancelled()
            if progress_cb:
                progress_cb(f"openAIP: página {page}…", min(0.9, 0.2 * page))
            data = fetch_with_retries(fetch_fn, self.url(params, page=page),
                                      headers=self.headers(creds), cancel=cancel)
            obj = firmod.parse_json_bytes(data, "openAIP")
            items = obj.get("items") or []
            for it in items:
                r = self.item_to_region(it)
                if r is None:
                    unknown.append(str(it.get("name", "?")))
                else:
                    regions.append(r)
            total_pages = obj.get("totalPages") or 1
            if page >= total_pages or not items:
                break
            page += 1
        regions = firmod._merge_regions(regions)
        dest = dest or firmod.data_file(firmod.OPENAIP_FILE)
        meta = {"fuente": "openAIP", "oficial": False, "licencia": LICENSE, "url": API_URL,
                "descargado": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "aviso": "Límites de openAIP (no oficiales); verificar contra el AIP."}
        firmod.save_geojson(regions, dest, meta)
        if progress_cb:
            progress_cb(f"Guardado: {len(regions)} FIR en {dest}", 1.0)
        return dest, regions, unknown

    @staticmethod
    def item_to_region(item):
        """FirRegion de un ítem de la API (geometry GeoJSON + name) o None
        si no se reconoce la FIR por nombre ni por indicador."""
        name = item.get("name") or ""
        code = code_for_name(name)
        if code is None:
            return None
        polys = firmod._geometry_polygons(item.get("geometry"))
        if not polys:
            return None
        return firmod.FirRegion(code, firmod.FIR_NAMES.get(code, name), polys,
                                source="openAIP", official=False,
                                props={"fuente_detalle": f"openAIP «{name}» ({item.get('_id', '')})"})
