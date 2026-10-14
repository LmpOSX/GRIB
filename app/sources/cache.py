# -*- coding: utf-8 -*-
"""Caché local de descargas: cada pedido (URL + encabezados relevantes) se
guarda como un archivo nombrado por el hash del pedido. Antes de bajar se
consulta; después de bajar se limpia por antigüedad y tamaño."""
import hashlib
import os
import sys
import time

from ..config import APP_NAME


def default_cache_dir():
    if sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Caches")
    elif sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
    else:
        base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return os.path.join(base, APP_NAME, "descargas")


class DownloadCache:
    def __init__(self, folder=None, max_mb=500, max_days=3):
        self.folder = folder or default_cache_dir()
        self.max_mb = float(max_mb)
        self.max_days = float(max_days)

    @staticmethod
    def key_for(url, extra=""):
        return hashlib.sha1((url + "\n" + (extra or "")).encode("utf-8")).hexdigest()

    def path_for(self, url, extra=""):
        return os.path.join(self.folder, self.key_for(url, extra) + ".bin")

    def get(self, url, extra=""):
        """Bytes guardados para el pedido o None (también si están vencidos)."""
        p = self.path_for(url, extra)
        if not os.path.isfile(p):
            return None
        if self.max_days > 0 and (time.time() - os.path.getmtime(p)) > self.max_days * 86400:
            try:
                os.remove(p)
            except OSError:
                pass
            return None
        with open(p, "rb") as fh:
            return fh.read()

    def put(self, url, data, extra=""):
        os.makedirs(self.folder, exist_ok=True)
        p = self.path_for(url, extra)
        tmp = p + ".parte"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, p)
        return p

    def entries(self):
        if not os.path.isdir(self.folder):
            return []
        out = []
        for name in os.listdir(self.folder):
            p = os.path.join(self.folder, name)
            if os.path.isfile(p):
                st = os.stat(p)
                out.append((p, st.st_size, st.st_mtime))
        return out

    def size_bytes(self):
        return sum(sz for _p, sz, _m in self.entries())

    def cleanup(self):
        """Borra lo vencido y, si se supera el tamaño máximo, lo más viejo.
        Devuelve la cantidad de archivos borrados."""
        removed = 0
        now = time.time()
        entries = []
        for p, sz, mt in self.entries():
            if (self.max_days > 0 and now - mt > self.max_days * 86400) or p.endswith(".parte"):
                try:
                    os.remove(p)
                    removed += 1
                except OSError:
                    pass
            else:
                entries.append((p, sz, mt))
        total = sum(sz for _p, sz, _m in entries)
        limit = self.max_mb * 1e6
        for p, sz, _mt in sorted(entries, key=lambda e: e[2]):
            if total <= limit:
                break
            try:
                os.remove(p)
                total -= sz
                removed += 1
            except OSError:
                pass
        return removed

    def clear(self):
        removed = 0
        for p, _sz, _mt in self.entries():
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
        return removed
