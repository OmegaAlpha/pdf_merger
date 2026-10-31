import os
import sys
from PySide6.QtCore import QObject, QTranslator, QCoreApplication, QSettings, Signal

class LanguageManager(QObject):
    language_changed = Signal(str)

    def __init__(self, app):
        super().__init__()
        self.app = app
        self.settings = QSettings("PDFMerger", "PDFMergerApp")
        self.translator = QTranslator()
        
        # Supported languages mapping: code -> Display Name
        self.supported_languages = {
            "en": "English",
            "nb": "Norsk (Bokmål)"
        }
        
        # Load saved language or default to English
        self.current_lang = self.settings.value("language", "en", type=str)

    def init_language(self):
        self.apply_language(self.current_lang)

    def apply_language(self, lang_code):
        if lang_code not in self.supported_languages:
            lang_code = "en"
            
        # Remove old translator if any
        QCoreApplication.removeTranslator(self.translator)
        
        if lang_code != "en":
            # Load translation file
            base_path = os.path.dirname(os.path.abspath(__file__))
            candidate_dirs = [
                os.path.join(os.path.dirname(sys.executable), "translations"),
                os.path.join(getattr(sys, "_MEIPASS", ""), "translations") if hasattr(sys, "_MEIPASS") else None,
                os.path.join(os.path.dirname(base_path), "translations"),
                os.path.join(base_path, "translations"),
            ]
            
            trans_path = None
            for trans_base_dir in candidate_dirs:
                if not trans_base_dir or not os.path.exists(trans_base_dir):
                    continue
                p1 = os.path.join(trans_base_dir, f"pdf_merger_{lang_code}.qm")
                if os.path.exists(p1):
                    trans_path = p1
                    break
                if lang_code == "nb":
                    p2 = os.path.join(trans_base_dir, "pdf_merger_nb_NO.qm")
                    if os.path.exists(p2):
                        trans_path = p2
                        break

            if trans_path and os.path.exists(trans_path):
                if self.translator.load(trans_path):
                    QCoreApplication.installTranslator(self.translator)
                else:
                    print(f"Failed to load translation: {trans_path}")
            else:
                # If file doesn't exist, we just stay in English (or fallback)
                print(f"Translation file not found for language: {lang_code}")
        
        self.current_lang = lang_code
        self.settings.setValue("language", lang_code)
        self.language_changed.emit(lang_code)

    def get_current_language_name(self):
        return self.supported_languages.get(self.current_lang, "English")
