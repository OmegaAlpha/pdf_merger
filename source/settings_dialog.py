from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, 
    QComboBox, QPushButton, QDialogButtonBox, QCheckBox,
    QTabWidget, QWidget
)
from PySide6.QtCore import QSettings, QEvent, Qt

class SettingsDialog(QDialog):
    def __init__(self, theme_manager, language_manager, parent=None):
        super().__init__(parent)
        self.theme_manager = theme_manager
        self.language_manager = language_manager
        
        self.setFixedSize(450, 280)
        
        self.layout = QVBoxLayout(self)
        
        # Create Tab Widget
        self.tab_widget = QTabWidget(self)
        
        # --- TAB 1: General Settings ---
        self.tab_general = QWidget()
        self.tab_general.setObjectName("tab_general")
        self.tab_general.setAttribute(Qt.WA_StyledBackground, True)
        general_layout = QVBoxLayout(self.tab_general)
        
        # Theme Setting
        theme_layout = QHBoxLayout()
        self.theme_label = QLabel()
        self.theme_combo = QComboBox()
        self.theme_combo.addItem("System Default", "System Default")
        self.theme_combo.addItem("Light", "Light")
        self.theme_combo.addItem("Dark", "Dark")
        
        current_pref = self.theme_manager.get_current_preference()
        for i in range(self.theme_combo.count()):
            if self.theme_combo.itemData(i) == current_pref:
                self.theme_combo.setCurrentIndex(i)
                break
            
        theme_layout.addWidget(self.theme_label)
        theme_layout.addWidget(self.theme_combo)
        general_layout.addLayout(theme_layout)

        # Language Setting
        lang_layout = QHBoxLayout()
        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        for code, name in self.language_manager.supported_languages.items():
            self.lang_combo.addItem(name, code)
            
        current_lang = self.language_manager.current_lang
        for i in range(self.lang_combo.count()):
            if self.lang_combo.itemData(i) == current_lang:
                self.lang_combo.setCurrentIndex(i)
                break
                
        lang_layout.addWidget(self.lang_label)
        lang_layout.addWidget(self.lang_combo)
        general_layout.addLayout(lang_layout)
        general_layout.addStretch()
        
        # --- TAB 2: Operations Settings ---
        self.tab_operations = QWidget()
        self.tab_operations.setObjectName("tab_operations")
        self.tab_operations.setAttribute(Qt.WA_StyledBackground, True)
        operations_layout = QVBoxLayout(self.tab_operations)
        
        # Auto-create first-page bookmark checkbox
        auto_bookmark_layout = QHBoxLayout()
        self.auto_bookmark_cb = QCheckBox()
        settings = QSettings("PDFMerger", "PDFMergerApp")
        auto_bookmark_pref = settings.value("auto_bookmark_first_page", True, type=bool)
        self.auto_bookmark_cb.setChecked(auto_bookmark_pref)
        auto_bookmark_layout.addWidget(self.auto_bookmark_cb)
        operations_layout.addLayout(auto_bookmark_layout)
        
        # Open after merge checkbox
        open_after_merge_layout = QHBoxLayout()
        self.open_after_merge_cb = QCheckBox()
        open_after_merge_pref = settings.value("open_after_merge", True, type=bool)
        self.open_after_merge_cb.setChecked(open_after_merge_pref)
        open_after_merge_layout.addWidget(self.open_after_merge_cb)
        operations_layout.addLayout(open_after_merge_layout)
        operations_layout.addStretch()
        
        # Add Tabs to Tab Widget
        self.tab_widget.addTab(self.tab_general, "")
        self.tab_widget.addTab(self.tab_operations, "")
        self.layout.addWidget(self.tab_widget)
        
        # Buttons
        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.accepted.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        self.layout.addWidget(self.button_box)
        
        self.retranslateUi()

    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self):
        self.setWindowTitle(self.tr("Settings"))
        
        # Translate Tab headers
        self.tab_widget.setTabText(0, self.tr("General"))
        self.tab_widget.setTabText(1, self.tr("Operations"))
        
        self.theme_label.setText(self.tr("Appearance Theme:"))
        self.lang_label.setText(self.tr("Language:"))
        self.auto_bookmark_cb.setText(self.tr("Create bookmark to first page if none exists"))
        self.open_after_merge_cb.setText(self.tr("Open merged PDF automatically on completion"))
        
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText(self.tr("OK"))
        self.button_box.button(QDialogButtonBox.StandardButton.Cancel).setText(self.tr("Cancel"))
        
        # Translate theme combo items
        theme_translations = {
            "System Default": self.tr("System Default"),
            "Light": self.tr("Light"),
            "Dark": self.tr("Dark")
        }
        for i in range(self.theme_combo.count()):
            key = self.theme_combo.itemData(i)
            self.theme_combo.setItemText(i, theme_translations.get(key, key))

    def accept(self):
        settings = QSettings("PDFMerger", "PDFMergerApp")
        
        # Save theme
        theme_pref = self.theme_combo.itemData(self.theme_combo.currentIndex())
        settings.setValue("theme_preference", theme_pref)
        self.theme_manager.apply_theme()
        
        # Save and apply language
        lang_code = self.lang_combo.itemData(self.lang_combo.currentIndex())
        self.language_manager.apply_language(lang_code)
        
        # Save auto bookmark first page setting
        settings.setValue("auto_bookmark_first_page", self.auto_bookmark_cb.isChecked())
        
        # Save open after merge setting
        settings.setValue("open_after_merge", self.open_after_merge_cb.isChecked())
        
        super().accept()
