"""Utilidades compartidas de plataforma."""
import sys

# Nombre de la tecla modificadora principal para textos de ayuda: Qt traduce
# "Ctrl" a ⌘ en macOS, así que los atajos se escriben siempre con "Ctrl".
MOD_KEY = "Cmd" if sys.platform == "darwin" else "Ctrl"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"
