"""
Native background blur — applied directly to the main window's NSView.

No companion window needed: we insert an NSVisualEffectView as the
bottom-most subview of the Qt window's own NSWindow contentView.
"""
import sys
import platform


def apply_blur(widget) -> bool:
    """Apply native blur to a QWidget's backing window. Call after widget.show()."""
    system = platform.system()
    if system == "Darwin":
        return _blur_macos(widget)
    elif system == "Windows":
        return _blur_windows(widget)
    return False


def _blur_macos(widget) -> bool:
    try:
        import objc
        from AppKit import NSVisualEffectView, NSColor
        from ctypes import c_void_p

        wid = int(widget.winId())
        ns_view = objc.objc_object(c_void_p=wid)
        ns_window = ns_view.window()

        if ns_window is None:
            return False

        # ── Native titlebar: transparent + full-size content view ──
        # NSWindowStyleMaskFullSizeContentView = 1 << 15 = 32768
        ns_window.setStyleMask_(ns_window.styleMask() | (1 << 15))
        ns_window.setTitlebarAppearsTransparent_(True)
        # NSWindowTitleVisible = 0: mostrar "proyecto — archivo.ppto" en la barra
        ns_window.setTitleVisibility_(0)

        content_view = ns_window.contentView()
        superview = content_view.superview()  # NSThemeFrame

        if superview is None:
            return False

        # Create the blur effect view sized to the full window frame
        effect_view = NSVisualEffectView.alloc().initWithFrame_(superview.bounds())
        effect_view.setMaterial_(13)      # HUDWindow — dark frosted glass
        effect_view.setBlendingMode_(0)   # BehindWindow
        effect_view.setState_(1)          # Active
        effect_view.setAutoresizingMask_(18)  # width + height flexible

        # Insert as sibling of contentView, positioned BELOW it
        # NSWindowBelow = -1 (NOT 0, which is NSWindowOut)
        superview.addSubview_positioned_relativeTo_(
            effect_view, -1, content_view)

        # Make the window transparent so the blur shows through
        ns_window.setBackgroundColor_(NSColor.clearColor())
        ns_window.setOpaque_(False)

        return True

    except ImportError:
        print("[blur] pyobjc not installed. Run: pip install pyobjc-framework-Cocoa",
              file=sys.stderr)
        return False
    except Exception as e:
        print(f"[blur] macOS blur failed: {e}", file=sys.stderr)
        return False


def _blur_windows(widget) -> bool:
    try:
        import ctypes

        hwnd = int(widget.winId())

        # Windows 11: Acrylic backdrop
        try:
            DWMWA_SYSTEMBACKDROP_TYPE = 38
            DWMSBT_ACRYLIC = 3
            val = ctypes.c_int(DWMSBT_ACRYLIC)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                ctypes.byref(val), ctypes.sizeof(val))
            return True
        except Exception:
            pass

        # Windows 10 fallback
        class ACCENT_POLICY(ctypes.Structure):
            _fields_ = [("AccentState", ctypes.c_int),
                        ("AccentFlags", ctypes.c_int),
                        ("GradientColor", ctypes.c_int),
                        ("AnimationId", ctypes.c_int)]

        class WINDOWCOMPOSITIONATTRIBDATA(ctypes.Structure):
            _fields_ = [("Attribute", ctypes.c_int),
                        ("Data", ctypes.c_void_p),
                        ("SizeOfData", ctypes.c_size_t)]

        accent = ACCENT_POLICY()
        accent.AccentState = 3
        data = WINDOWCOMPOSITIONATTRIBDATA()
        data.Attribute = 19
        data.Data = ctypes.cast(ctypes.pointer(accent), ctypes.c_void_p)
        data.SizeOfData = ctypes.sizeof(accent)
        ctypes.windll.user32.SetWindowCompositionAttribute(hwnd, ctypes.byref(data))
        return True

    except Exception as e:
        print(f"[blur] Windows blur failed: {e}", file=sys.stderr)
        return False
