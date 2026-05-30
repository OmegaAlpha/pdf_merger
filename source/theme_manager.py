import os
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSettings, Qt, QObject
from PySide6.QtGui import QPalette, QColor

class ThemeManager(QObject):
    def __init__(self, app: QApplication):
        super().__init__()
        self.app = app
        
        if hasattr(Qt.ColorScheme, 'Dark'):
            self.app.styleHints().colorSchemeChanged.connect(self._on_system_theme_changed)

    def get_current_preference(self) -> str:
        settings = QSettings("PDFMerger", "PDFMergerApp")
        return settings.value("theme_preference", "System Default")

    def _on_system_theme_changed(self, color_scheme):
        if self.get_current_preference() == "System Default":
            self.apply_theme()

    def is_dark_theme(self) -> bool:
        pref = self.get_current_preference()
        if pref == "Light":
            return False
        elif pref == "Dark":
            return True
        else: # System Default
            if hasattr(Qt.ColorScheme, 'Dark'):
                return self.app.styleHints().colorScheme() == Qt.ColorScheme.Dark
            return True

    def apply_window_theme(self, window):
        is_dark = self.is_dark_theme()
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                hwnd = int(window.winId())
                DWMWA_USE_IMMERSIVE_DARK_MODE = 20
                value = ctypes.c_int(1 if is_dark else 0)
                ctypes.windll.dwmapi.DwmSetWindowAttribute(
                    hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
                )
                
                # Force Windows to redraw the titlebar immediately
                SWP_NOMOVE = 0x0002
                SWP_NOSIZE = 0x0001
                SWP_NOZORDER = 0x0004
                SWP_NOACTIVATE = 0x0010
                SWP_FRAMECHANGED = 0x0020
                ctypes.windll.user32.SetWindowPos(
                    hwnd, 0, 0, 0, 0, 0,
                    SWP_NOMOVE | SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED
                )
            except Exception:
                pass

    def apply_theme(self):
        is_dark = self.is_dark_theme()
        
        palette = self.app.palette()
        if is_dark:
            palette.setColor(QPalette.ColorRole.Window, QColor("#1E1E1E"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#252526"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#FFFFFF"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#FFFFFF"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#333337"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#FFFFFF"))
        else:
            palette.setColor(QPalette.ColorRole.Window, QColor("#F3F3F3"))
            palette.setColor(QPalette.ColorRole.Base, QColor("#FFFFFF"))
            palette.setColor(QPalette.ColorRole.Text, QColor("#202020"))
            palette.setColor(QPalette.ColorRole.WindowText, QColor("#202020"))
            palette.setColor(QPalette.ColorRole.Button, QColor("#FAFAFA"))
            palette.setColor(QPalette.ColorRole.ButtonText, QColor("#202020"))
        self.app.setPalette(palette)
        
        if getattr(sys, 'frozen', False):
            if hasattr(sys, '_MEIPASS'):
                base_dir = sys._MEIPASS
            else:
                base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
            
        qss_filename = "style_dark.qss" if is_dark else "style_light.qss"
        
        # Try multiple potential locations for the QSS files
        search_paths = [
            os.path.join(base_dir, qss_filename),
            os.path.join(base_dir, "source", qss_filename),
            # Fallback for script mode if run from root
            os.path.join(os.path.dirname(base_dir), "source", qss_filename) if not getattr(sys, 'frozen', False) else None
        ]
        
        for qss_path in search_paths:
            if qss_path and os.path.exists(qss_path):
                try:
                    with open(qss_path, "r", encoding="utf-8") as f:
                        qss_content = f.read()
                    
                    # Resolve absolute path for checkmark.svg to prevent CWD loading issues
                    checkmark_path = os.path.join(os.path.dirname(qss_path), "checkmark.svg").replace("\\", "/")
                    qss_content = qss_content.replace("url(checkmark.svg)", f"url('{checkmark_path}')")
                    
                    self.app.setStyleSheet(qss_content)
                    break
                except Exception as e:
                    print(f"Error loading stylesheet from {qss_path}: {e}")
                
        for window in self.app.topLevelWidgets():
            self.apply_window_theme(window)
