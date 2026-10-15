# -*- coding: utf-8 -*-
"""Configuración de una fuente de datos: habilitarla, sus parámetros por
defecto, credenciales (en el llavero del sistema) y «Probar conexión»."""
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame, QCheckBox,
    QComboBox, QLineEdit, QMessageBox,
)

from .glass_dialog import GlassDialog, add_shadow as _add_shadow
from ..widgets.params_form import ParamsForm
from ..sources import source_config, source_label
from ..sources import credentials as creds


class _TestWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, source, params, credentials, parent=None):
        super().__init__(parent)
        self._src, self._params, self._creds = source, params, credentials

    def run(self):
        try:
            self.done.emit(self._src.test_connection(self._params, self._creds))
        except Exception as exc:  # pragma: no cover - imprevistos
            from ..sources.base import TestResult
            self.done.emit(TestResult("error", f"{type(exc).__name__}: {exc}"))


class SourceConfigDialog(GlassDialog):
    """Al aceptar, `enabled()` y `params()` dan lo elegido; las credenciales
    se guardan en el llavero al apretar «Guardar credenciales»."""

    AUTH_LABELS = {"ninguna": "Ninguna", "usuario": "Usuario y clave", "token": "Token"}

    def __init__(self, parent=None, source=None, cfg=None):
        super().__init__(parent)
        self.source = source
        self._cfg = cfg or {}
        self._worker = None
        self.setWindowTitle(f"Fuente: {source.name}")
        self.setMinimumWidth(560)
        self._build_ui()

    def _build_ui(self):
        src = self.source
        stored = source_config(self._cfg, src.key)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 20, 20, 20)
        panel = QFrame()
        panel.setObjectName("GlassPanel")
        _add_shadow(panel)
        outer.addWidget(panel)
        lay = QVBoxLayout(panel)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        title = QLabel(source_label(src))
        title.setObjectName("Heading")
        lay.addWidget(title)
        kind = {"altura": "niveles de presión (altura)",
                "limites": "límites de FIR (capa del mapa)"}.get(src.kind, "variables de superficie")
        desc = QLabel(f"{src.model}\nTipo: {kind}"
                      + ("   ·   ✓ publica los niveles isobáricos OACI por nivel de vuelo"
                         if src.flight_levels else "")
                      + (f"\n{src.description}" if src.description else ""))
        desc.setObjectName("Hint")
        desc.setWordWrap(True)
        lay.addWidget(desc)
        if src.doc_url:
            link = QLabel(f'Documentación: <a href="{src.doc_url}">{src.doc_url}</a>')
            link.setObjectName("Hint")
            link.setOpenExternalLinks(True)
            lay.addWidget(link)

        self.chk_enabled = QCheckBox("Fuente habilitada (aparece en el selector de la ventana)")
        self.chk_enabled.setChecked(stored["enabled"])
        lay.addWidget(self.chk_enabled)

        if src.params:
            sub = QLabel("Parámetros por defecto")
            sub.setObjectName("SubHeading")
            lay.addWidget(sub)
            self.form = ParamsForm(src.params, stored["params"])
            lay.addWidget(self.form)
        else:
            self.form = None

        # ── Credenciales ──
        self.auth = None
        if src.needs_credentials:
            sub = QLabel("Credenciales (se guardan en el llavero del sistema, nunca en el proyecto)")
            sub.setObjectName("SubHeading")
            lay.addWidget(sub)
            g = QGridLayout()
            g.setHorizontalSpacing(8)
            g.addWidget(QLabel("Autenticación"), 0, 0)
            self.auth = QComboBox()
            for k in (src.auth_kinds or ["ninguna", "usuario", "token"]):
                self.auth.addItem(self.AUTH_LABELS.get(k, k), k)
            self.auth.setCurrentIndex(max(0, self.auth.findData(stored["params"].get("auth", "ninguna"))))
            self.auth.currentIndexChanged.connect(self._on_auth_changed)
            g.addWidget(self.auth, 0, 1)
            g.addWidget(QLabel("Usuario"), 1, 0)
            self.ed_user = QLineEdit()
            g.addWidget(self.ed_user, 1, 1)
            g.addWidget(QLabel("Clave"), 2, 0)
            self.ed_pass = QLineEdit()
            self.ed_pass.setEchoMode(QLineEdit.EchoMode.Password)
            g.addWidget(self.ed_pass, 2, 1)
            g.addWidget(QLabel("Token"), 3, 0)
            self.ed_token = QLineEdit()
            self.ed_token.setEchoMode(QLineEdit.EchoMode.Password)
            g.addWidget(self.ed_token, 3, 1)
            lay.addLayout(g)
            row = QHBoxLayout()
            self.lbl_creds = QLabel("")
            self.lbl_creds.setObjectName("Hint")
            row.addWidget(self.lbl_creds, 1)
            b = QPushButton("Guardar credenciales")
            b.clicked.connect(self._save_credentials)
            row.addWidget(b)
            b = QPushButton("Borrar")
            b.clicked.connect(self._delete_credentials)
            row.addWidget(b)
            lay.addLayout(row)
            self._refresh_credentials()
            self._on_auth_changed()

        # ── Probar conexión ──
        row = QHBoxLayout()
        self.btn_test = QPushButton("Probar conexión")
        self.btn_test.clicked.connect(self._test)
        row.addWidget(self.btn_test)
        self.lbl_test = QLabel("")
        self.lbl_test.setObjectName("Hint")
        self.lbl_test.setWordWrap(True)
        row.addWidget(self.lbl_test, 1)
        lay.addLayout(row)

        row = QHBoxLayout()
        row.addStretch()
        b = QPushButton("Cancelar")
        b.clicked.connect(self.reject)
        row.addWidget(b)
        b = QPushButton("Aplicar")
        b.setObjectName("AccentBtn")
        b.clicked.connect(self.accept)
        row.addWidget(b)
        lay.addLayout(row)

    # ── Credenciales ──
    def _on_auth_changed(self, *_):
        kind = self.auth.currentData()
        self.ed_user.setEnabled(kind == "usuario")
        self.ed_pass.setEnabled(kind == "usuario")
        self.ed_token.setEnabled(kind == "token")

    def _refresh_credentials(self):
        if not creds.available():
            self.lbl_creds.setText("Llavero no disponible (instalá keyring).")
            return
        cur = creds.get_all(self.source.key)
        self.lbl_creds.setText(f"Guardadas: usuario {creds.masked(cur['usuario'])}, "
                               f"clave {creds.masked(cur['clave'])}, token {creds.masked(cur['token'])}")

    def _save_credentials(self):
        try:
            kind = self.auth.currentData()
            if kind == "usuario":
                creds.set(self.source.key, "usuario", self.ed_user.text().strip())
                creds.set(self.source.key, "clave", self.ed_pass.text())
            elif kind == "token":
                creds.set(self.source.key, "token", self.ed_token.text().strip())
        except Exception as exc:
            QMessageBox.critical(self, "Credenciales", f"No se pudieron guardar:\n{exc}")
            return
        self.ed_pass.clear()
        self.ed_token.clear()
        self._refresh_credentials()

    def _delete_credentials(self):
        creds.delete(self.source.key)
        self._refresh_credentials()

    # ── Prueba ──
    def _current_credentials(self):
        if not self.source.needs_credentials:
            return {}
        cur = creds.get_all(self.source.key)
        if self.ed_user.text().strip():
            cur["usuario"] = self.ed_user.text().strip()
        if self.ed_pass.text():
            cur["clave"] = self.ed_pass.text()
        if self.ed_token.text().strip():
            cur["token"] = self.ed_token.text().strip()
        return cur

    def _test(self):
        self.btn_test.setEnabled(False)
        self.lbl_test.setText("Probando…")
        self._worker = _TestWorker(self.source, self.params(), self._current_credentials(), self)
        self._worker.done.connect(self._on_tested)
        self._worker.start()

    def _on_tested(self, result):
        self.btn_test.setEnabled(True)
        icon = {"ok": "✔", "sin_red": "✖", "credenciales": "✖", "no_publicado": "⏳"}.get(result.status, "✖")
        self.lbl_test.setText(f"{icon} {result}")
        self.last_test = result

    # ── Resultado ──
    def enabled(self):
        return self.chk_enabled.isChecked()

    def params(self):
        p = self.form.values() if self.form is not None else {}
        if self.auth is not None:
            p["auth"] = self.auth.currentData()
        return p

    def closeEvent(self, event):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(3000)
        super().closeEvent(event)
