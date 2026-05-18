import os
from datetime import datetime
from PySide6.QtWidgets import (
    QMainWindow,
    QWidget,
    QVBoxLayout,
    QHBoxLayout,
    QPushButton,
    QTableView,
    QFileDialog,
    QLineEdit,
    QLabel,
    QHeaderView,
    QAbstractItemView,
    QStatusBar,
    QMessageBox,
    QProgressBar,
    QStyle,
    QGridLayout,
    QSplitter,
    QSplitterHandle,
    QListWidget,
    QListWidgetItem,
    QMenu,
)
from PySide6.QtCore import Qt, QSize, QSettings, QTimer, QEvent, QRect
from PySide6.QtGui import QIcon, QPixmap, QImage, QAction, QKeySequence, QShortcut, QPainter, QColor

from viewmodel import MainViewModel
from bookmarks_pane import BookmarksPane
from settings_dialog import SettingsDialog


class _SplitterOverlay(QWidget):
    """
    A solid-blue widget parented to the splitter's parent (not the splitter
    itself — QSplitter would absorb it into its panel layout).  It is raised
    above all siblings so it renders on top of the splitter panels, giving a
    5-px visual expansion with zero extra layout gap.
    Mouse events pass through it so dragging the 1-px handle still works.
    """

    ACCENT = QColor("#0078D4")

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.hide()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), self.ACCENT)
        p.end()


class ThinSplitterHandle(QSplitterHandle):
    """
    A 1-px splitter handle (handleWidth=1).  On hover/press it tells
    ThinSplitter to show a 5-px blue overlay widget raised above the
    adjacent panels — giving a visual expansion with no extra layout gap.
    """

    HANDLE_WIDTH    = 1   # pixels allocated between panels in the layout
    HOVER_VIS_WIDTH = 5   # pixels wide the blue bar appears on hover
    LINE_LIGHT      = QColor("#D1D1D1")
    LINE_DARK       = QColor("#3E3E42")

    def __init__(self, orientation, parent):
        super().__init__(orientation, parent)
        self._hovered = False
        self._pressed = False
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------
    # Overlay management
    # ------------------------------------------------------------------

    def _show_overlay(self):
        sp = self.splitter()
        if not isinstance(sp, ThinSplitter):
            return
        overlay = sp._get_overlay()
        if overlay is None:
            return

        hr = self.geometry()   # handle rect in splitter's own coordinate space
        if self.orientation() == Qt.Orientation.Horizontal:
            actual_width = hr.width()
            extra = (self.HOVER_VIS_WIDTH - actual_width) // 2
            local_rect = QRect(hr.x() - extra, hr.y(), self.HOVER_VIS_WIDTH, hr.height())
        else:
            actual_height = hr.height()
            extra = (self.HOVER_VIS_WIDTH - actual_height) // 2
            local_rect = QRect(hr.x(), hr.y() - extra, hr.width(), self.HOVER_VIS_WIDTH)

        # Convert from splitter's coordinate space → overlay's parent coordinate space
        parent_widget = overlay.parentWidget()
        tl = sp.mapTo(parent_widget, local_rect.topLeft())
        overlay.setGeometry(QRect(tl.x(), tl.y(), local_rect.width(), local_rect.height()))
        overlay.show()
        overlay.raise_()

    def _hide_overlay(self):
        sp = self.splitter()
        if isinstance(sp, ThinSplitter) and sp._overlay is not None:
            sp._overlay.hide()

    # ------------------------------------------------------------------
    # Input events
    # ------------------------------------------------------------------

    def enterEvent(self, event):
        self._hovered = True
        self._show_overlay()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._hovered = False
        if not self._pressed:
            self._hide_overlay()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        self._pressed = True
        self._show_overlay()
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # Let QSplitterHandle move the handle first, then reposition the overlay
        super().mouseMoveEvent(event)
        if self._pressed:
            self._show_overlay()

    def moveEvent(self, event):
        super().moveEvent(event)
        if self._pressed or self._hovered:
            self._show_overlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._pressed or self._hovered:
            self._show_overlay()

    def mouseReleaseEvent(self, event):
        self._pressed = False
        if not self._hovered:
            self._hide_overlay()
        super().mouseReleaseEvent(event)

    # ------------------------------------------------------------------
    # Paint — just the 1-px hairline; hover state is drawn by the overlay
    # ------------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        bg = self.palette().window().color()
        is_dark = bg.lightness() < 128
        line_color = self.LINE_DARK if is_dark else self.LINE_LIGHT
        painter.fillRect(self.rect(), line_color)
        painter.end()


class ThinSplitter(QSplitter):
    """QSplitter with a 1-px hairline divider that expands to 5-px blue on hover."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Overlay is created lazily so it can be parented to self.parentWidget()
        # rather than self — QSplitter would absorb any direct child into its
        # panel layout and give it a full-panel-sized geometry.
        self._overlay: "_SplitterOverlay | None" = None

    def _get_overlay(self) -> "_SplitterOverlay | None":
        if self._overlay is None:
            parent = self.parentWidget()
            if parent is None:
                return None
            self._overlay = _SplitterOverlay(parent)
        return self._overlay

    def createHandle(self):
        return ThinSplitterHandle(self.orientation(), self)


class MainWindow(QMainWindow):
    def __init__(self, viewmodel: MainViewModel, theme_manager=None, language_manager=None):
        super().__init__()
        self.vm = viewmodel
        self.theme_manager = theme_manager
        self.language_manager = language_manager
        self._current_project_path = None
        self._app_title = "PDF Merger"
        self.setMinimumSize(QSize(900, 500))
        self.setAcceptDrops(True)

        # Debouncing for selection changes
        self.selection_timer = QTimer(self)
        self.selection_timer.setSingleShot(True)
        self.selection_timer.setInterval(200) # 200ms debounce
        self.selection_timer.timeout.connect(self._on_selection_timer_timeout)

        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        self._setup_menubar()
        self._setup_ui()
        self._bind_viewmodel()
        
        self.retranslateUi()

        if self.theme_manager:
            self.theme_manager.apply_window_theme(self)


    def changeEvent(self, event):
        if event.type() == QEvent.Type.LanguageChange:
            self.retranslateUi()
        super().changeEvent(event)

    def retranslateUi(self):
        self.setWindowTitle(self._app_title if not self._current_project_path else f"{self._app_title} — {os.path.splitext(os.path.basename(self._current_project_path))[0]}")
        
        if hasattr(self, 'file_menu'):
            self.file_menu.setTitle(self.tr("&File"))
            self.open_project_action.setText(self.tr("&Open Project..."))
            self.save_project_action.setText(self.tr("&Save Project"))
            self.save_as_action.setText(self.tr("Save Project &As..."))
            self.settings_action.setText(self.tr("&Settings..."))
            
        if hasattr(self, 'edit_menu'):
            self.edit_menu.setTitle(self.tr("&Edit"))
            # Update all commands currently on the undo stack with their translated descriptions
            try:
                from PySide6.QtCore import QCoreApplication
                if self.vm and self.vm.undo_stack:
                    stack = self.vm.undo_stack
                    for idx in range(stack.count()):
                        cmd = stack.command(idx)
                        if hasattr(cmd, 'description_key') and hasattr(cmd, 'context'):
                            cmd.setText(QCoreApplication.translate(cmd.context, cmd.description_key))
            except Exception:
                pass
            self._update_undo_redo_text()
            
        if hasattr(self, 'empty_label'):
            self.empty_label.setText(self.tr("Drag and drop PDF files here\nor click 'Add PDFs' to begin"))
            
        if hasattr(self, 'preview_label'):
            self.preview_label.setText(self.tr("Page Previews"))
            
        if hasattr(self, 'add_btn'):
            self.add_btn.setText(self.tr(" Add PDFs"))
            self.remove_btn.setText(self.tr(" Remove Selected"))
            
            preview_checked = self.toggle_preview_btn.isChecked()
            self.toggle_preview_btn.setText(self.tr(" Hide Preview") if preview_checked else self.tr(" Show Preview"))
            
            bookmarks_checked = self.toggle_bookmarks_btn.isChecked()
            self.toggle_bookmarks_btn.setText(self.tr(" Hide Bookmarks") if bookmarks_checked else self.tr(" Show Bookmarks"))
            
            self.bookmarks_pane.retranslateUi()
            self.merge_btn.setText(self.tr(" Merge PDFs"))
            
        if hasattr(self, 'output_label'):
            self.output_label.setText(self.tr("Output File:"))
            self.output_dir_btn.setText(self.tr(" Set Output Directory"))
            self.output_dir_btn.setToolTip(self.tr("Current Output Dir:\n{0}").format(self.vm.output_dir))

        # Update table headers
        if hasattr(self, 'pdf_table'):
            model = self.vm.pdf_list_model
            model.headers = [
                self.tr("Name"), 
                self.tr("Size (KB)"), 
                self.tr("Modified Date"), 
                self.tr("Pages")
            ]
            model.headerDataChanged.emit(Qt.Orientation.Horizontal, 0, 3)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            files = [url.toLocalFile() for url in urls if url.isLocalFile() and url.toLocalFile().lower().endswith('.pdf')]
            if files:
                self.vm.set_last_open_dir(os.path.dirname(files[0]))
                self.add_btn.setEnabled(False)
                self.vm.add_pdfs(files)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

    def _setup_menubar(self):
        menubar = self.menuBar()
        self.file_menu = menubar.addMenu("")

        self.open_project_action = QAction("", self)
        self.open_project_action.setShortcut("Ctrl+O")
        self.open_project_action.triggered.connect(self.on_open_project)
        self.file_menu.addAction(self.open_project_action)

        self.save_project_action = QAction("", self)
        self.save_project_action.setShortcut("Ctrl+S")
        self.save_project_action.triggered.connect(self.on_save_project)
        self.file_menu.addAction(self.save_project_action)

        self.save_as_action = QAction("", self)
        self.save_as_action.setShortcut("Ctrl+Shift+S")
        self.save_as_action.triggered.connect(self.on_save_project_as)
        self.file_menu.addAction(self.save_as_action)

        self.file_menu.addSeparator()
        
        self.settings_action = QAction("", self)
        self.settings_action.triggered.connect(self.on_settings_open)
        self.file_menu.addAction(self.settings_action)

        self._setup_edit_menu()

    def _setup_edit_menu(self):
        menubar = self.menuBar()
        self.edit_menu = menubar.addMenu(self.tr("&Edit"))
        
        self.undo_action = QAction("", self)
        self.undo_action.setShortcut(QKeySequence.StandardKey.Undo)
        self.undo_action.triggered.connect(self.vm.undo_stack.undo)
        self.edit_menu.addAction(self.undo_action)
        
        self.redo_action = QAction("", self)
        self.redo_action.setShortcut(QKeySequence.StandardKey.Redo)
        self.redo_action.triggered.connect(self.vm.undo_stack.redo)
        self.edit_menu.addAction(self.redo_action)
        
        self.vm.undo_stack.canUndoChanged.connect(self.undo_action.setEnabled)
        self.vm.undo_stack.canRedoChanged.connect(self.redo_action.setEnabled)
        self.vm.undo_stack.undoTextChanged.connect(self._update_undo_redo_text)
        self.vm.undo_stack.redoTextChanged.connect(self._update_undo_redo_text)
        
        # Initial state
        self.undo_action.setEnabled(self.vm.undo_stack.canUndo())
        self.redo_action.setEnabled(self.vm.undo_stack.canRedo())
        self._update_undo_redo_text()

    def _update_undo_redo_text(self):
        try:
            # Safety check: if vm or undo_stack C++ object is deleted (shutdown)
            if not self.vm or not self.vm.undo_stack:
                return
            
            undo_cmd = self.vm.undo_stack.undoText()
            if undo_cmd:
                self.undo_action.setText(self.tr("&Undo {0}").format(undo_cmd))
            else:
                self.undo_action.setText(self.tr("&Undo"))
                
            redo_cmd = self.vm.undo_stack.redoText()
            if redo_cmd:
                self.redo_action.setText(self.tr("&Redo {0}").format(redo_cmd))
            else:
                self.redo_action.setText(self.tr("&Redo"))
        except RuntimeError:
            # Handle cases where libshiboken reports object already deleted
            pass

    def _setup_ui(self):
        # Table view setup
        self.pdf_table = QTableView()
        self.pdf_table.setModel(self.vm.pdf_list_model)
        header = self.pdf_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionsMovable(True)
        header.setSectionsClickable(True)
        
        self.pdf_table.setColumnWidth(2, 150)
        self.pdf_table.verticalHeader().setVisible(False)
        
        self._is_resizing_header = False
        header.sectionResized.connect(self._on_section_resized)
        
        self.pdf_table._original_resizeEvent = self.pdf_table.resizeEvent
        self.pdf_table.resizeEvent = self._on_table_resize

        self.pdf_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        
        # Drag and Drop internally handled by model
        self.pdf_table.setDragEnabled(True)
        self.pdf_table.setAcceptDrops(True)
        self.pdf_table.setDropIndicatorShown(True)
        self.pdf_table.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.pdf_table.setDragDropOverwriteMode(False)
        self.pdf_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.pdf_table.setSortingEnabled(True)
        self._clear_sort_indicator()

        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key_Delete), self.pdf_table)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.delete_shortcut.activated.connect(self.on_remove_pdfs)

        # Context menu
        self.pdf_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.pdf_table.customContextMenuRequested.connect(self._on_table_context_menu)
        
        # Table Container for Overlay
        table_container = QWidget()
        table_container.setObjectName("tableContainer")
        table_layout = QGridLayout(table_container)
        table_layout.setContentsMargins(0, 0, 0, 0)
        table_layout.setSpacing(0)
        table_layout.setHorizontalSpacing(0)
        table_layout.setVerticalSpacing(0)
        table_layout.addWidget(self.pdf_table, 0, 0)
        
        self.empty_label = QLabel("")
        self.empty_label.setObjectName("emptyStateLabel")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        table_layout.addWidget(self.empty_label, 0, 0, Qt.AlignmentFlag.AlignCenter)
        
        self.splitter = ThinSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(ThinSplitterHandle.HANDLE_WIDTH)
        self.layout.addWidget(self.splitter)
        
        self.bookmarks_pane = BookmarksPane(self.vm)
        self.splitter.addWidget(self.bookmarks_pane)
        
        self.splitter.addWidget(table_container)
        
        self.preview_pane = QWidget()
        self.preview_pane.setObjectName("previewPane")
        preview_layout = QVBoxLayout(self.preview_pane)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        
        preview_header_layout = QHBoxLayout()
        preview_header_layout.setContentsMargins(5, 5, 5, 5)
        
        self.preview_label = QLabel("")
        self.preview_label.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        preview_header_layout.addWidget(self.preview_label)
        
        preview_header_layout.addStretch()
        
        self.preview_close_btn = QPushButton("✕")
        self.preview_close_btn.setObjectName("closePaneButton")
        self.preview_close_btn.setFlat(True)
        self.preview_close_btn.setFixedSize(20, 20)
        self.preview_close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        preview_header_layout.addWidget(self.preview_close_btn)
        
        preview_layout.addLayout(preview_header_layout)
        
        self.preview_list = QListWidget()
        self.preview_list.setViewMode(QListWidget.ViewMode.IconMode)
        self.preview_list.setIconSize(QSize(150, 220)) # Added 20px height for spacing
        self.preview_list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.preview_list.setUniformItemSizes(True)
        self.preview_list.setSpacing(10)
        self.preview_list.setGridSize(QSize(170, 255)) # Accommodate larger icon area + text
        preview_layout.addWidget(self.preview_list)
        
        self.splitter.addWidget(self.preview_pane)

        # Restore splitter state
        settings = QSettings("PDFMerger", "PDFMergerApp")
        splitter_state = settings.value("splitter_state_v2")
        if splitter_state:
            self.splitter.restoreState(splitter_state)
        else:
            self.splitter.setSizes([300, 500, 350])
        # Keep handle width consistent after state restore
        self.splitter.setHandleWidth(ThinSplitterHandle.HANDLE_WIDTH)
            
        preview_visible = settings.value("preview_visible", True, type=bool)
        self.preview_pane.setVisible(preview_visible)
        
        bookmarks_visible = settings.value("bookmarks_visible", True, type=bool)
        self.bookmarks_pane.setVisible(bookmarks_visible)

        # Restore window geometry
        geometry = settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

        # Restore table header state
        header_state = settings.value("header_state")
        if header_state:
            self.pdf_table.horizontalHeader().restoreState(header_state)
        self._clear_sort_indicator()

        # Buttons
        btn_layout = QHBoxLayout()
        self.add_btn = QPushButton("")
        self.add_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileIcon))
        
        self.remove_btn = QPushButton("")
        self.remove_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))
        
        self.toggle_preview_btn = QPushButton("")
        self.toggle_preview_btn.setCheckable(True)
        self.toggle_preview_btn.toggled.connect(self.on_toggle_preview)
        self.toggle_preview_btn.setChecked(preview_visible)
        
        self.toggle_bookmarks_btn = QPushButton("")
        self.toggle_bookmarks_btn.setCheckable(True)
        self.toggle_bookmarks_btn.toggled.connect(self.on_toggle_bookmarks)
        self.toggle_bookmarks_btn.setChecked(bookmarks_visible)
        self.toggle_bookmarks_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView))
        
        self.bookmarks_pane.closed.connect(lambda: self.toggle_bookmarks_btn.setChecked(False))
        self.preview_close_btn.clicked.connect(lambda: self.toggle_preview_btn.setChecked(False))
        
        self.merge_btn = QPushButton("")
        self.merge_btn.setObjectName("mergeButton")
        self.merge_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DialogApplyButton))
        
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.remove_btn)
        btn_layout.addWidget(self.toggle_bookmarks_btn)
        btn_layout.addWidget(self.toggle_preview_btn)
        btn_layout.addWidget(self.merge_btn)
        self.layout.addLayout(btn_layout)

        # Output Layout
        output_layout = QHBoxLayout()
        self.output_label = QLabel("")
        output_layout.addWidget(self.output_label)
        self.output_name = QLineEdit("")
        
        output_layout.addWidget(self.output_name)
        self.output_dir_btn = QPushButton("")
        self.output_dir_btn.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirIcon))
        output_layout.addWidget(self.output_dir_btn)
        self.layout.addLayout(output_layout)

        # Progress bar
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 0)
        self.progress_bar.hide()
        self.layout.addWidget(self.progress_bar)

        self.setStatusBar(QStatusBar(self))
        self.vm.set_output_dir(self.vm.output_dir)

    def _on_table_resize(self, event):
        self.pdf_table._original_resizeEvent(event)
        
        header = self.pdf_table.horizontalHeader()
        if header.count() == 0:
            return
            
        viewport_width = self.pdf_table.viewport().width()
        
        other_widths = 0
        for i in range(header.count()):
            if i != 0:
                other_widths += header.sectionSize(i)
                
        new_width = viewport_width - other_widths
        if new_width < header.minimumSectionSize():
            new_width = header.minimumSectionSize()
            
        self._is_resizing_header = True
        header.resizeSection(0, new_width)
        self._is_resizing_header = False

    def _on_section_resized(self, logicalIndex, oldSize, newSize):
        if self._is_resizing_header:
            return
            
        header = self.pdf_table.horizontalHeader()
        visual_index = header.visualIndex(logicalIndex)
        
        if visual_index >= header.count() - 1:
            return
            
        next_logical = header.logicalIndex(visual_index + 1)
        
        if header.sectionResizeMode(next_logical) == QHeaderView.ResizeMode.Stretch:
            return
            
        delta = newSize - oldSize
        next_old_size = header.sectionSize(next_logical)
        next_new_size = next_old_size - delta
        
        min_size = header.minimumSectionSize()
        if next_new_size < min_size:
            next_new_size = min_size
            allowed_delta = next_old_size - min_size
            newSize = oldSize + allowed_delta
            
            self._is_resizing_header = True
            header.resizeSection(logicalIndex, newSize)
            header.resizeSection(next_logical, next_new_size)
            self._is_resizing_header = False
        else:
            self._is_resizing_header = True
            header.resizeSection(next_logical, next_new_size)
            self._is_resizing_header = False

    def _bind_viewmodel(self):
        # View bindings (UI events to ViewModel methods)
        self.add_btn.clicked.connect(self.on_add_pdfs)
        self.remove_btn.clicked.connect(self.on_remove_pdfs)
        self.merge_btn.clicked.connect(self.on_merge)
        self.output_dir_btn.clicked.connect(self.on_set_output_dir)
        
        self.pdf_table.selectionModel().selectionChanged.connect(self.on_table_selection_changed)

        # ViewModel bindings (Signals to UI updates)
        self.vm.status_message.connect(self.on_status_message)
        self.vm.merge_started.connect(self.on_merge_started)
        self.vm.merge_completed.connect(self.on_merge_completed)
        self.vm.output_dir_changed.connect(self.on_output_dir_changed)
        self.vm.thumbnail_started.connect(self.on_thumbnail_started)
        self.vm.thumbnail_ready.connect(self.on_thumbnail_ready)
        self.vm.thumbnail_batch_ready.connect(self.on_thumbnail_batch_ready)
        self.vm.thumbnail_cache_ready.connect(self.on_thumbnail_cache_ready)
        self.vm.pdfs_added.connect(self.on_pdfs_added_finished)
        self.vm.sort_state_changed.connect(self._on_sort_state_changed)

        # Empty state bindings
        self.vm.pdf_list_model.rowsInserted.connect(self._on_rows_inserted)
        self.vm.pdf_list_model.rowsRemoved.connect(self._update_empty_state)
        self.vm.pdf_list_model.modelReset.connect(self._update_empty_state)
        self._update_empty_state()
        
        self.vm.pdf_list_model.order_broken.connect(self._clear_sort_indicator)

        # Project signals
        self.vm.project_loaded.connect(self._on_project_loaded)
        self.vm.project_saved.connect(self._on_project_saved)
        self.vm.project_load_warning.connect(self._on_project_load_warning)

    def _on_sort_state_changed(self, column: int, order: int):
        header = self.pdf_table.horizontalHeader()
        if column == -1:
            header.setSortIndicatorShown(False)
        else:
            header.setSortIndicatorShown(True)
            header.setSortIndicator(column, Qt.SortOrder(order))

    def _clear_sort_indicator(self):
        self.pdf_table.horizontalHeader().setSortIndicatorShown(False)

    def _on_rows_inserted(self, parent, first, last):
        self._update_empty_state()
        if first == 0 and self.vm.pdf_list_model.rowCount() > 0:
            first_pdf = self.vm.pdf_list_model.pdfs[0]
            name, ext = os.path.splitext(first_pdf.name)
            self.output_name.setText(f"{name}_merged{ext}")

    def _update_empty_state(self):
        if self.vm.pdf_list_model.rowCount() > 0:
            self.empty_label.hide()
        else:
            self.empty_label.show()

    def on_add_pdfs(self):
        files, _ = QFileDialog.getOpenFileNames(
            self, self.tr("Select PDF Files"), self.vm.last_open_dir, self.tr("PDF Files (*.pdf)")
        )
        if files:
            self.vm.set_last_open_dir(os.path.dirname(files[0]))
            self.add_btn.setEnabled(False) # Prevent multiple simultaneous loads
            self.vm.add_pdfs(files)

    def on_pdfs_added_finished(self, added: int, errors: int):
        self.add_btn.setEnabled(True)
        self._update_empty_state()

    def on_remove_pdfs(self):
        # We need to map the selected indices
        indexes = self.pdf_table.selectionModel().selectedRows()
        row_indices = [idx.row() for idx in indexes]
        if not row_indices:
            self.statusBar().showMessage(self.tr("No rows selected."), 3000)
            return
        
        self.vm.remove_pdfs_by_indices(row_indices)

    # --- Context Menu ---

    def _on_table_context_menu(self, position):
        """Show a context menu for the PDF table."""
        indexes = self.pdf_table.selectionModel().selectedRows()
        if not indexes:
            return

        menu = QMenu(self)

        # Refresh / Update PDF(s)
        if len(indexes) == 1:
            refresh_action = menu.addAction(self.tr("Update PDF from Disk"))
            refresh_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            
            relocate_action = menu.addAction(self.tr("Relocate/Change PDF..."))
            relocate_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_DirOpenIcon))
        else:
            refresh_action = menu.addAction(self.tr("Update {0} PDFs from Disk").format(len(indexes)))
            refresh_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
            relocate_action = None

        menu.addSeparator()

        menu.addSeparator()

        # Remove
        if len(indexes) == 1:
            remove_action = menu.addAction(self.tr("Remove"))
        else:
            remove_action = menu.addAction(self.tr("Remove {0} PDFs").format(len(indexes)))
        remove_action.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon))

        # Execute
        action = menu.exec(self.pdf_table.viewport().mapToGlobal(position))
        if action is None:
            return

        if action == refresh_action:
            self._on_refresh_selected_pdfs(indexes)
        elif action == relocate_action:
            self._on_change_pdf_path(indexes[0].row())
        elif action == remove_action:
            self.on_remove_pdfs()

    def _on_change_pdf_path(self, row: int):
        """Prompt user to select a new path for a PDF entry."""
        if not (0 <= row < self.vm.pdf_list_model.rowCount()):
            return
            
        pdf = self.vm.pdf_list_model.pdfs[row]
        start_dir = os.path.dirname(pdf.file_path) if os.path.exists(os.path.dirname(pdf.file_path)) else self.vm.last_open_dir
        
        new_path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Select Replacement for {0}").format(pdf.name),
            start_dir,
            self.tr("PDF Files (*.pdf)")
        )
        
        if new_path:
            self.vm.change_pdf_path(row, new_path)
            # If preview is visible, request thumbnails for the new path
            if self.preview_pane.isVisible():
                self.vm.request_thumbnails(new_path)

    def _on_refresh_selected_pdfs(self, indexes):
        """Refresh metadata for the selected PDF(s) and report changes."""
        all_changes = []
        for idx in indexes:
            row = idx.row()
            pdf = self.vm.pdf_list_model.pdfs[row]
            from project_manager import refresh_pdf_metadata
            changes = refresh_pdf_metadata(pdf)

            # Invalidate thumbnail cache
            if pdf.file_path in self.vm.thumbnail_cache:
                del self.vm.thumbnail_cache[pdf.file_path]

            # Notify model
            top_left = self.vm.pdf_list_model.index(row, 0)
            bottom_right = self.vm.pdf_list_model.index(row, self.vm.pdf_list_model.columnCount() - 1)
            self.vm.pdf_list_model.dataChanged.emit(top_left, bottom_right)

            all_changes.extend(changes)

        if all_changes:
            QMessageBox.information(
                self,
                self.tr("PDF Updated"),
                self.tr("The following changes were detected:\n\n")
                + "\n".join(f"\u2022 {c}" for c in all_changes)
                + self.tr("\n\nCustom bookmarks have been preserved."),
            )
        else:
            count = len(indexes)
            self.statusBar().showMessage(
                self.tr("{0} PDF(s) checked — no changes detected.").format(count), 3000
            )

        # Refresh preview if visible
        if self.preview_pane.isVisible() and len(indexes) == 1:
            row = indexes[0].row()
            pdf = self.vm.pdf_list_model.pdfs[row]
            if not pdf.missing:
                self.vm.request_thumbnails(pdf.file_path)

    def on_merge(self):
        if self.vm.has_missing_files():
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Warning)
            msg_box.setWindowTitle(self.tr("Missing Files"))
            msg_box.setText(self.tr("Some PDF files in the list could not be found.\n\n") +
                            self.tr("Remove or relocate the missing files (shown in red) before merging."))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg_box.button(QMessageBox.StandardButton.Ok).setText(self.tr("OK"))
            msg_box.exec()
            return

        dest_filename = self.output_name.text().strip() or self.tr("merged_output.pdf")
        output_path = os.path.join(self.vm.output_dir, dest_filename)

        if os.path.exists(output_path):
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle(self.tr("Confirm Overwrite"))
            msg_box.setText(self.tr("File exists:\n{0}\nOverwrite?").format(output_path))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            msg_box.button(QMessageBox.StandardButton.Yes).setText(self.tr("Yes"))
            msg_box.button(QMessageBox.StandardButton.No).setText(self.tr("No"))
            reply = msg_box.exec()
            
            if reply == QMessageBox.StandardButton.No:
                self.statusBar().showMessage(self.tr("Merge cancelled."), 3000)
                return

        self.vm.start_merge(dest_filename)

    def on_table_selection_changed(self, selected, deselected):
        # Trigger debounce timer
        self.selection_timer.start()

    def _on_selection_timer_timeout(self):
        indexes = self.pdf_table.selectionModel().selectedRows()
        
        if not indexes:
            self.preview_list.clear()
            return
            
        if self.preview_pane.isVisible():
            row = indexes[0].row()
            pdf = self.vm.pdf_list_model.pdfs[row]
            if pdf.missing:
                self.preview_list.clear()
            else:
                self.vm.request_thumbnails(pdf.file_path)

    def on_thumbnail_started(self, total_pages: int):
        self.preview_list.setUpdatesEnabled(False)
        self.preview_list.clear()
        self.preview_list.setGridSize(QSize(160, 245))
        # Pre-fill with placeholders to maintain order during parallel loading
        for i in range(total_pages):
            item = QListWidgetItem(self.tr("Page {0}").format(i + 1))
            item.setSizeHint(QSize(150, 235)) # Match icon area + text height
            self.preview_list.addItem(item)
        self.preview_list.setUpdatesEnabled(True)

    def on_thumbnail_ready(self, page_num: int, image: QImage):
        # Update existing placeholder item
        if 0 <= page_num < self.preview_list.count():
            item = self.preview_list.item(page_num)
            pixmap = QPixmap.fromImage(image)
            item.setIcon(QIcon(pixmap))

    def on_thumbnail_batch_ready(self, batch: list):
        # Chunky update every 100 pages, inserting into pre-filled placeholders
        self.preview_list.setUpdatesEnabled(False)
        try:
            for page_num, image in batch:
                if 0 <= page_num < self.preview_list.count():
                    item = self.preview_list.item(page_num)
                    pixmap = QPixmap.fromImage(image)
                    item.setIcon(QIcon(pixmap))
        finally:
            self.preview_list.setUpdatesEnabled(True)

    def on_thumbnail_cache_ready(self, cache: dict):
        # Update placeholders for all cached items at once
        self.preview_list.setUpdatesEnabled(False)
        try:
            for page_num in sorted(cache.keys()):
                if 0 <= page_num < self.preview_list.count():
                    image = cache[page_num]
                    item = self.preview_list.item(page_num)
                    pixmap = QPixmap.fromImage(image)
                    item.setIcon(QIcon(pixmap))
        finally:
            self.preview_list.setUpdatesEnabled(True)


        
    def on_toggle_preview(self, checked):
        self.preview_pane.setVisible(checked)
        self.toggle_preview_btn.setText(self.tr(" Hide Preview") if checked else self.tr(" Show Preview"))
        
        if checked:
            indexes = self.pdf_table.selectionModel().selectedRows()
            if indexes:
                row = indexes[0].row()
                pdf = self.vm.pdf_list_model.pdfs[row]
                self.vm.request_thumbnails(pdf.file_path)

    def on_toggle_bookmarks(self, checked):
        self.bookmarks_pane.setVisible(checked)
        self.toggle_bookmarks_btn.setText(self.tr(" Hide Bookmarks") if checked else self.tr(" Show Bookmarks"))

    def on_set_output_dir(self):
        directory = QFileDialog.getExistingDirectory(
            self, self.tr("Select Output Directory"), self.vm.output_dir
        )
        if directory:
            self.vm.set_output_dir(directory)



    def on_settings_open(self):
        dialog = SettingsDialog(self.theme_manager, self.language_manager, self)
        if self.theme_manager:
            self.theme_manager.apply_window_theme(dialog)
        dialog.exec()

    # Signal handlers
    def on_output_dir_changed(self, directory: str):
        self.output_dir_btn.setToolTip(self.tr("Current Output Dir:\n{0}").format(directory))

    def on_status_message(self, message: str, timeout: int):
        self.statusBar().showMessage(message, timeout)

    def on_merge_started(self):
        self.add_btn.setEnabled(False)
        self.remove_btn.setEnabled(False)
        self.merge_btn.setEnabled(False)
        self.pdf_table.setEnabled(False)
        
        self.progress_bar.show()

    def on_merge_completed(self, success: bool, message: str):
        self.add_btn.setEnabled(True)
        self.remove_btn.setEnabled(True)
        self.merge_btn.setEnabled(True)
        self.pdf_table.setEnabled(True)
        
        self.progress_bar.hide()
        
        if success:
            QMessageBox.information(self, self.tr("Merge Successful"), message)
        else:
            QMessageBox.critical(self, self.tr("Merge Error"), message)

    def closeEvent(self, event):
        settings = QSettings("PDFMerger", "PDFMergerApp")
        settings.setValue("splitter_state_v2", self.splitter.saveState())
        settings.setValue("preview_visible", self.preview_pane.isVisible())
        settings.setValue("bookmarks_visible", self.bookmarks_pane.isVisible())
        settings.setValue("window_geometry", self.saveGeometry())
        settings.setValue("header_state", self.pdf_table.horizontalHeader().saveState())
        super().closeEvent(event)

    # --- Project Save / Load handlers ---

    def on_save_project(self):
        """Save to current project path, or prompt Save As if none."""
        if self._current_project_path:
            self.vm.do_save_project(
                self._current_project_path,
                self.output_name.text().strip(),
            )
        else:
            self.on_save_project_as()

    def on_save_project_as(self):
        """Prompt the user for a save location."""
        start_dir = os.path.dirname(self._current_project_path) if self._current_project_path else self.vm.output_dir
        path, _ = QFileDialog.getSaveFileName(
            self,
            self.tr("Save Project As"),
            start_dir,
            self.tr("PDF Merger Project (*.pdfm)"),
        )
        if path:
            if not path.lower().endswith(".pdfm"):
                path += ".pdfm"
            self.vm.do_save_project(path, self.output_name.text().strip())

    def on_open_project(self):
        """Prompt the user for a project file to load."""
        # Warn if there are PDFs in the current list
        if self.vm.pdf_list_model.rowCount() > 0:
            msg_box = QMessageBox(self)
            msg_box.setIcon(QMessageBox.Icon.Question)
            msg_box.setWindowTitle(self.tr("Open Project"))
            msg_box.setText(self.tr("Opening a project will replace the current PDF list.\nContinue?"))
            msg_box.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            msg_box.setDefaultButton(QMessageBox.StandardButton.No)
            msg_box.button(QMessageBox.StandardButton.Yes).setText(self.tr("Yes"))
            msg_box.button(QMessageBox.StandardButton.No).setText(self.tr("No"))
            reply = msg_box.exec()
            
            if reply == QMessageBox.StandardButton.No:
                return

        start_dir = os.path.dirname(self._current_project_path) if self._current_project_path else self.vm.last_open_dir
        path, _ = QFileDialog.getOpenFileName(
            self,
            self.tr("Open Project"),
            start_dir,
            self.tr("PDF Merger Project (*.pdfm)"),
        )
        if path:
            self.vm.do_load_project(path)

    def _on_project_saved(self, project_path: str):
        self._current_project_path = project_path
        name = os.path.splitext(os.path.basename(project_path))[0]
        self.setWindowTitle(f"{self._app_title} — {name}")

    def _on_project_loaded(self, project_path: str, output_name: str):
        self._current_project_path = project_path
        name = os.path.splitext(os.path.basename(project_path))[0]
        self.setWindowTitle(f"{self._app_title} — {name}")
        if output_name:
            self.output_name.setText(output_name)
        self._update_empty_state()

    def _on_project_load_warning(self, message: str):
        QMessageBox.warning(self, self.tr("Missing Files"), message)
