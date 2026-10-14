# -*- coding: utf-8 -*-
"""Credenciales de las fuentes restringidas, guardadas en el llavero del
sistema (Keychain en macOS, Credential Manager en Windows, Secret Service en
Linux) a través de `keyring`. Nunca se escriben en config.json ni en logs.

Cada fuente tiene hasta tres secretos: usuario, clave y token. Se guardan
bajo el servicio "Visor GRIB/<clave de la fuente>".
"""
from ..config import APP_NAME

try:
    import keyring
    KEYRING_ERROR = None
except Exception as _exc:  # pragma: no cover - depende del entorno
    keyring = None
    KEYRING_ERROR = str(_exc)

FIELDS = ("usuario", "clave", "token")


def _service(source_key):
    return f"{APP_NAME}/{source_key}"


def available():
    return keyring is not None


def get(source_key, field):
    if keyring is None or field not in FIELDS:
        return None
    try:
        return keyring.get_password(_service(source_key), field)
    except Exception:
        return None


def get_all(source_key):
    return {f: get(source_key, f) for f in FIELDS}


def set(source_key, field, value):  # noqa: A001 - nombre claro para el módulo
    if keyring is None:
        raise RuntimeError("keyring no disponible: " + str(KEYRING_ERROR))
    if field not in FIELDS:
        raise ValueError(field)
    if value:
        keyring.set_password(_service(source_key), field, value)
    else:
        delete(source_key, field)


def delete(source_key, field=None):
    """Borra un secreto o los tres de la fuente."""
    if keyring is None:
        return
    for f in ([field] if field else FIELDS):
        try:
            keyring.delete_password(_service(source_key), f)
        except Exception:
            pass


def masked(value):
    """Para mostrar en pantalla sin revelar el secreto."""
    if not value:
        return "(sin definir)"
    return "•" * min(len(value), 12)
