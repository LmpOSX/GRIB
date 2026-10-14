# -*- coding: utf-8 -*-
"""Transportes para la fuente genérica: HTTP(S) con autenticación básica o
token, FTP y SFTP. Todos devuelven bytes y aceptan chunk_cb / cancel /
max_bytes como `gfs_download.fetch`."""
import base64
import ftplib
import io
import urllib.parse

from .base import DownloadCancelled


def auth_headers(auth, creds):
    """Encabezados HTTP según el tipo de autenticación."""
    creds = creds or {}
    if auth == "usuario" and creds.get("usuario"):
        raw = f"{creds.get('usuario', '')}:{creds.get('clave', '')}".encode("utf-8")
        return {"Authorization": "Basic " + base64.b64encode(raw).decode("ascii")}
    if auth == "token" and creds.get("token"):
        return {"Authorization": "Bearer " + creds["token"]}
    return {}


def fetch_ftp(url, creds=None, chunk_cb=None, cancel=None, max_bytes=None, timeout=60):
    u = urllib.parse.urlparse(url)
    creds = creds or {}
    user = u.username or creds.get("usuario") or "anonymous"
    pw = u.password or creds.get("clave") or "visor@grib"
    buf = io.BytesIO()
    got = [0]

    class _Stop(Exception):
        pass

    def cb(block):
        if cancel is not None and cancel():
            raise DownloadCancelled()
        buf.write(block)
        got[0] += len(block)
        if chunk_cb:
            chunk_cb(got[0], size)
        if max_bytes is not None and got[0] >= max_bytes:
            raise _Stop()
    ftp = ftplib.FTP()
    ftp.connect(u.hostname, u.port or 21, timeout=timeout)
    try:
        ftp.login(user, pw)
        try:
            size = ftp.size(u.path)
        except Exception:
            size = None
        try:
            ftp.retrbinary("RETR " + u.path, cb, blocksize=256 * 1024)
        except _Stop:
            try:
                ftp.abort()
            except Exception:
                pass
    finally:
        try:
            ftp.quit()
        except Exception:
            ftp.close()
    return buf.getvalue()


def fetch_sftp(url, creds=None, chunk_cb=None, cancel=None, max_bytes=None, timeout=60):
    try:
        import paramiko
    except Exception as exc:
        raise RuntimeError("SFTP requiere paramiko (pip install paramiko)") from exc
    u = urllib.parse.urlparse(url)
    creds = creds or {}
    user = u.username or creds.get("usuario")
    pw = u.password or creds.get("clave")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(u.hostname, port=u.port or 22, username=user, password=pw, timeout=timeout,
                   allow_agent=True, look_for_keys=True)
    try:
        sftp = client.open_sftp()
        try:
            try:
                size = sftp.stat(u.path).st_size
            except Exception:
                size = None
            buf = io.BytesIO()
            got = 0
            with sftp.open(u.path, "rb") as fh:
                fh.prefetch()
                while True:
                    if cancel is not None and cancel():
                        raise DownloadCancelled()
                    block = fh.read(256 * 1024)
                    if not block:
                        break
                    buf.write(block)
                    got += len(block)
                    if chunk_cb:
                        chunk_cb(got, size)
                    if max_bytes is not None and got >= max_bytes:
                        break
            return buf.getvalue()
        finally:
            sftp.close()
    finally:
        client.close()


def fetch_any(url, auth="ninguna", creds=None, chunk_cb=None, cancel=None, max_bytes=None,
              http_fetch=None, timeout=120):
    """Despacha por esquema: http/https (con encabezados de autenticación),
    ftp y sftp."""
    scheme = urllib.parse.urlparse(url).scheme.lower()
    if scheme in ("http", "https"):
        from .. import gfs_download
        fn = http_fetch or gfs_download.fetch
        return fn(url, headers=auth_headers(auth, creds), chunk_cb=chunk_cb, cancel=cancel,
                  max_bytes=max_bytes, timeout=timeout)
    if scheme == "ftp":
        return fetch_ftp(url, creds, chunk_cb, cancel, max_bytes)
    if scheme == "sftp":
        return fetch_sftp(url, creds, chunk_cb, cancel, max_bytes)
    raise ValueError(f"Protocolo no soportado: {scheme or '(sin esquema)'}")
