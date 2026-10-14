"""Utilidades de formato compartidas."""
import sys

# Nombre de la tecla modificadora principal para textos de ayuda: Qt traduce
# "Ctrl" a ⌘ en macOS, así que los atajos se escriben siempre con "Ctrl".
MOD_KEY = "Cmd" if sys.platform == "darwin" else "Ctrl"
IS_MAC = sys.platform == "darwin"
IS_WINDOWS = sys.platform == "win32"


def fmt_number(val: float, decimals: int = 2) -> str:
    """
    Formato numérico español: miles con '.' y decimal con ','.
    Ejemplos: 1.234.567,89  /  42  /  3,50
    """
    if val == int(val) and decimals == 0:
        # sin decimales: solo miles
        formatted = f"{int(val):,}"
    elif val == int(val):
        formatted = f"{val:,.{decimals}f}"
    else:
        formatted = f"{val:,.{decimals}f}"

    # US → ES: 1,234,567.89 → 1.234.567,89
    return formatted.replace(",", "X").replace(".", ",").replace("X", ".")


def fmt_qty(val: float) -> str:
    """Para cantidades: sin decimales si es entero, hasta 2 si tiene fracción."""
    if val == int(val):
        return fmt_number(val, 0)
    return fmt_number(val, 2)


def fmt_price(val: float) -> str:
    """Para precios: siempre 2 decimales."""
    return fmt_number(val, 2)
