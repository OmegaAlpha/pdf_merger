import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
    QAbstractItemView, QHeaderView, QMenu, QHBoxLayout, QLabel, QPushButton, QStyle, QStyledItemDelegate
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QFont, QColor, QBrush, QIcon

from model import BookmarkItem

class PageDelegate(QStyledItemDelegate):
    def displayText(self, value, locale):
        text = str(value)
        if not text:
            return ""
        return f"→ {text}"

class BookmarksTreeWidget(QTreeWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMouseTracking(True)
        self._is_resizing = False
        self._resize_margin = 6
        
    def mouseMoveEvent(self, event):
        # The boundary is where the second column starts
        boundary_x = self.header().sectionViewportPosition(1)
        is_near_boundary = abs(event.pos().x() - boundary_x) < self._resize_margin
        
        if self._is_resizing:
            viewport_width = self.viewport().width()
            new_page_width = viewport_width - event.pos().x()
            if new_page_width > 40: # Minimum width to show at least some page info
                self.setColumnWidth(1, new_page_width)
            event.accept()
            return

        if is_near_boundary:
            self.setCursor(Qt.CursorShape.SizeHorCursor)
        else:
            self.unsetCursor()
            
        super().mouseMoveEvent(event)

    def mousePressEvent(self, event):
        boundary_x = self.header().sectionViewportPosition(1)
        if abs(event.pos().x() - boundary_x) < self._resize_margin:
            self._is_resizing = True
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        if self._is_resizing:
            self._is_resizing = False
            event.accept()
            return
        super().mouseReleaseEvent(event)

    def dragMoveEvent(self, event):
        target_item = self.itemAt(event.pos())
        dragged_item = self.currentItem()
        
        # Prevent dropping in empty space
        if target_item is None:
            event.ignore()
            return
            
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        dragged_item = self.currentItem()
        target_item = self.itemAt(event.pos())
        
        if not dragged_item:
            return super().dropEvent(event)
            
        # Is it a root item (PDF)? We don't allow dragging PDFs here.
        # However, we DO allow dragging if it's a BookmarkItem that somehow became top-level
        from model import PDFDocument, BookmarkItem
        data = dragged_item.data(0, Qt.ItemDataRole.UserRole)
        if dragged_item.parent() is None and isinstance(data, PDFDocument):
            event.ignore()
            return
            
        # If dropping in empty space, ignore
        if target_item is None:
            event.ignore()
            return

        super().dropEvent(event)
        
        # Manually trigger sync because rowsMoved signal might not fire 
        # reliably for internal moves in some Qt versions/platforms.
        parent_pane = self.parent()
        while parent_pane and not hasattr(parent_pane, "_sync_to_viewmodel"):
            parent_pane = parent_pane.parent()
        if parent_pane:
            parent_pane._sync_to_viewmodel()

class BookmarksPane(QWidget):
    closed = Signal()

    def __init__(self, viewmodel, parent=None):
        super().__init__(parent)
        self.vm = viewmodel
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        
        # Header with close button
        header_layout = QHBoxLayout()
        header_layout.setContentsMargins(5, 5, 5, 5)
        
        self.title_label = QLabel(self.tr("Bookmarks"))
        font = self.title_label.font()
        font.setBold(True)
        self.title_label.setFont(font)
        
        self.close_btn = QPushButton("✕")
        self.close_btn.setObjectName("closePaneButton")
        self.close_btn.setFlat(True)
        self.close_btn.setFixedSize(20, 20)
        self.close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_btn.clicked.connect(self.closed.emit)
        
        header_layout.addWidget(self.title_label)
        header_layout.addStretch()
        header_layout.addWidget(self.close_btn)
        self.layout.addLayout(header_layout)
        
        self.tree = BookmarksTreeWidget()
        self.tree.setHeaderLabels([self.tr("Title"), self.tr("Page")])
        self.tree.setHeaderHidden(True)
        
        # Title column stretches, Page column is compact but resizable
        self.tree.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.tree.header().setSectionResizeMode(1, QHeaderView.ResizeMode.Interactive)
        self.tree.header().setStretchLastSection(False)
        self.tree.setColumnWidth(1, 65) # Fits "→ 9999" comfortably
        
        self.tree.setIndentation(12)
        
        self.tree.setObjectName("bookmarksTree")
        self.tree.setStyleSheet("""
            #bookmarksTree {
                font-size: 11px !important;
                font-family: "Segoe UI Variable", "Segoe UI", "-apple-system", "BlinkMacSystemFont", "Roboto", "Helvetica Neue", sans-serif !important;
            }
            QTreeView::item { 
                padding: 1px; 
                min-height: 22px; 
            }
            QTreeView QLineEdit { 
                padding: 0px; 
                margin: 0px; 
                border: 1px solid #0078D4;
                background-color: palette(base);
                font-size: 11px !important;
                font-family: "Segoe UI Variable", "Segoe UI", "-apple-system", "BlinkMacSystemFont", "Roboto", "Helvetica Neue", sans-serif !important;
            }
        """)
        
        # Apply custom delegate for page column
        self.page_delegate = PageDelegate(self.tree)
        self.tree.setItemDelegateForColumn(1, self.page_delegate)
        
        # Drag and drop for reordering and reparenting
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.setAlternatingRowColors(True)
        self.tree.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.layout.addWidget(self.tree)
        
        # Connect signals
        self.vm.global_toc_changed.connect(self._populate_tree)
        self.tree.itemChanged.connect(self._on_item_changed)
        self.tree.model().rowsMoved.connect(self._sync_to_viewmodel)
        
        self.tree.customContextMenuRequested.connect(self.show_context_menu)
        self.tree.itemSelectionChanged.connect(self._on_selection_changed)
        
        self._is_populating = False
        self._populate_tree()

    def retranslateUi(self):
        self.title_label.setText(self.tr("Bookmarks"))
        self.tree.setHeaderLabels([self.tr("Title"), self.tr("Page")])

    def keyPressEvent(self, event):
        item = self.tree.currentItem()
        if not item or item.parent() is None: # Don't allow modifying PDF root nodes
            super().keyPressEvent(event)
            return
            
        if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
            self._delete_item(item)
            event.accept()
        elif event.key() == Qt.Key.Key_Tab:
            self._demote_item(item)
            event.accept()
        elif event.key() == Qt.Key.Key_Backtab: # Shift+Tab
            self._promote_item(item)
            event.accept()
        elif event.key() == Qt.Key.Key_Insert:
            self._add_sibling(item)
            event.accept()
        else:
            super().keyPressEvent(event)

    def show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu()
        global_pos = self.tree.viewport().mapToGlobal(pos)
        
        if item:
            data = item.data(0, Qt.ItemDataRole.UserRole)
            from model import PDFDocument, BookmarkItem
            
            if isinstance(data, PDFDocument):
                # PDF Root Node
                add_child_action = menu.addAction(self.tr("Add Bookmark"))
                action = menu.exec(global_pos)
                if action == add_child_action:
                    self._add_child(item)
            elif isinstance(data, BookmarkItem):
                # Bookmark Node
                add_action = menu.addAction(self.tr("Add Bookmark Below"))
                add_child_action = menu.addAction(self.tr("Add Child Bookmark"))
                menu.addSeparator()
                promote_action = menu.addAction(self.tr("Promote (Shift+Tab)"))
                demote_action = menu.addAction(self.tr("Demote (Tab)"))
                menu.addSeparator()
                remove_action = menu.addAction(self.tr("Remove"))
                
                action = menu.exec(global_pos)
                if action == add_action:
                    self._add_sibling(item)
                elif action == add_child_action:
                    self._add_child(item)
                elif action == promote_action:
                    self._promote_item(item)
                elif action == demote_action:
                    self._demote_item(item)
                elif action == remove_action:
                    self._delete_item(item)
        else:
            # Clicked empty space
            if self.tree.topLevelItemCount() > 0:
                add_action = menu.addAction(self.tr("Add Bookmark to Last PDF"))
                action = menu.exec(global_pos)
                if action == add_action:
                    # Find the last PDF root item
                    last_pdf_item = None
                    for i in range(self.tree.topLevelItemCount() - 1, -1, -1):
                        it = self.tree.topLevelItem(i)
                        from model import PDFDocument
                        if isinstance(it.data(0, Qt.ItemDataRole.UserRole), PDFDocument):
                            last_pdf_item = it
                            break
                    
                    if last_pdf_item:
                        self._add_child(last_pdf_item)

    def _populate_tree(self):
        self._is_populating = True
        self.tree.clear()
        
        pdf_list = self.vm.pdf_list_model.pdfs
        if not pdf_list:
            self._is_populating = False
            return
            
        # Create a root node for each PDF
        pdf_root_nodes = {}
        for pdf in pdf_list:
            root_item = QTreeWidgetItem([pdf.name, ""])
            
            # Make faint and non-editable
            font = root_item.font(0)
            font.setBold(True)
            root_item.setFont(0, font)
            
            faint_brush = QBrush(QColor(150, 150, 150))
            root_item.setForeground(0, faint_brush)
            
            # Remove editable flag
            flags = root_item.flags()
            flags &= ~Qt.ItemFlag.ItemIsEditable
            flags &= ~Qt.ItemFlag.ItemIsDragEnabled
            root_item.setFlags(flags)
            
            root_item.setData(0, Qt.ItemDataRole.UserRole, pdf) # Store PDF directly
            
            self.tree.addTopLevelItem(root_item)
            root_item.setExpanded(True)
            pdf_root_nodes[id(pdf)] = root_item
            
        # Insert bookmarks
        last_item_at_level = {}
        for bm in self.vm.global_toc:
            pdf = bm.source_pdf
            if id(pdf) not in pdf_root_nodes:
                continue
                
            root_item = pdf_root_nodes[id(pdf)]
            
            item = QTreeWidgetItem([bm.title, str(bm.page)])
            if "__compiled__" in globals():
                import sys
                bookmark_icon_path = os.path.join(os.path.dirname(sys.executable), "source", "bookmark.svg")
            else:
                bookmark_icon_path = os.path.join(os.path.dirname(__file__), "bookmark.svg")
            item.setIcon(0, QIcon(bookmark_icon_path))
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(0, Qt.ItemDataRole.UserRole, bm)
            
            level = bm.level
            if level <= 1:
                root_item.addChild(item)
                last_item_at_level = {1: item} # Reset levels for this PDF branch
            else:
                parent = last_item_at_level.get(level - 1)
                if parent:
                    parent.addChild(item)
                else:
                    fallback_parent = None
                    for l in range(level - 2, 0, -1):
                        if l in last_item_at_level:
                            fallback_parent = last_item_at_level[l]
                            break
                    if fallback_parent:
                        fallback_parent.addChild(item)
                    else:
                        root_item.addChild(item)
                last_item_at_level[level] = item
                
            item.setExpanded(True)
            
        # Re-run italics/tooltip check for all items now that the tree is fully built
        # This is necessary because nesting across PDFs depends on the relative positions 
        # of items which might be processed in any order.
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            item = it.value()
            bm = item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(bm, BookmarkItem):
                # Find the top-level PDF root this item is attached to
                root_item = item
                while root_item.parent():
                    root_item = root_item.parent()
                root_pdf = root_item.data(0, Qt.ItemDataRole.UserRole)
                
                if root_pdf != bm.source_pdf:
                    italic_font = item.font(0)
                    italic_font.setItalic(True)
                    item.setFont(0, italic_font)
                    item.setFont(1, italic_font)
                    
                    source_name = bm.source_pdf.name if bm.source_pdf else self.tr("Unknown")
                    tooltip = self.tr("Source: {0}").format(source_name)
                    item.setToolTip(0, tooltip)
                    item.setToolTip(1, tooltip)
            it += 1

        self._is_populating = False

    def _on_item_changed(self, item, column):
        if self._is_populating:
            return
        self._sync_to_viewmodel()

    def _sync_to_viewmodel(self):
        if self._is_populating:
            return
            
        new_toc = []
        
        def traverse(item, parent_pdf, level):
            title = item.text(0).strip() or self.tr("Untitled")
            
            try:
                page = int(item.text(1))
                if page < 1: page = 1
            except ValueError:
                page = 1
                
            bm = item.data(0, Qt.ItemDataRole.UserRole)
            if bm and isinstance(bm, BookmarkItem):
                bm.title = title
                bm.page = page
                bm.level = level
                # bm.source_pdf is preserved from the object itself
                new_toc.append(bm)
                current_pdf = bm.source_pdf
            else:
                # Newly created item inherits PDF from parent/ancestor
                bm = BookmarkItem(title=title, page=page, level=level, source_pdf=parent_pdf)
                item.setData(0, Qt.ItemDataRole.UserRole, bm)
                new_toc.append(bm)
                current_pdf = parent_pdf

            # Apply Guest bookmark visualization (italics + tooltip)
            # Find the top-level PDF root this item is attached to
            top_root = item
            while top_root.parent():
                top_root = top_root.parent()
            root_pdf = top_root.data(0, Qt.ItemDataRole.UserRole)
            
            if root_pdf != bm.source_pdf:
                italic_font = item.font(0)
                italic_font.setItalic(True)
                item.setFont(0, italic_font)
                item.setFont(1, italic_font)
                
                source_name = bm.source_pdf.name if bm.source_pdf else self.tr("Unknown")
                tooltip = self.tr("Source: {0}").format(source_name)
                item.setToolTip(0, tooltip)
                item.setToolTip(1, tooltip)
            else:
                # Revert to normal if it's no longer a guest
                normal_font = item.font(0)
                normal_font.setItalic(False)
                item.setFont(0, normal_font)
                item.setFont(1, normal_font)
                item.setToolTip(0, "")
                item.setToolTip(1, "")
                
            for i in range(item.childCount()):
                traverse(item.child(i), current_pdf, level + 1)
                
        current_container_pdf_root = None
        from model import PDFDocument, BookmarkItem
        
        # We use a while loop because we might be modifying the top-level items (reparenting)
        i = 0
        while i < self.tree.topLevelItemCount():
            root_item = self.tree.topLevelItem(i)
            data = root_item.data(0, Qt.ItemDataRole.UserRole)
            
            if isinstance(data, PDFDocument):
                current_container_pdf_root = root_item
                for j in range(root_item.childCount()):
                    traverse(root_item.child(j), data, 1)
                i += 1
            elif isinstance(data, BookmarkItem):
                # Bookmark escaped to top level! Snap it into the nearest PDF.
                target_pdf_root = current_container_pdf_root
                if not target_pdf_root:
                    # Find the first PDF root below us if none above
                    for k in range(i + 1, self.tree.topLevelItemCount()):
                        cand = self.tree.topLevelItem(k).data(0, Qt.ItemDataRole.UserRole)
                        if isinstance(cand, PDFDocument):
                            target_pdf_root = self.tree.topLevelItem(k)
                            break
                
                if target_pdf_root:
                    # Move it in the tree
                    self.tree.invisibleRootItem().takeChild(i)
                    if target_pdf_root == current_container_pdf_root:
                        target_pdf_root.addChild(root_item)
                    else:
                        target_pdf_root.insertChild(0, root_item)
                    # Don't increment i, as we removed the current item
                    traverse(root_item, target_pdf_root.data(0, Qt.ItemDataRole.UserRole), 1)
                else:
                    # No PDF roots at all? Just process as is.
                    traverse(root_item, data.source_pdf, 1)
                    i += 1
            
        # Update viewmodel without triggering _populate_tree
        self.vm.global_toc_changed.disconnect(self._populate_tree)
        self.vm.global_toc = new_toc
        self.vm.global_toc_changed.connect(self._populate_tree)

    def _on_selection_changed(self):
        item = self.tree.currentItem()
        if not item:
            return
            
        data = item.data(0, Qt.ItemDataRole.UserRole)
        from model import PDFDocument
        if isinstance(data, PDFDocument):
            self.vm.status_message.emit(self.tr("Source PDF: {0}").format(data.name), 3000)
        elif isinstance(data, BookmarkItem):
            source_name = data.source_pdf.name if data.source_pdf else self.tr("Unknown")
            self.vm.status_message.emit(self.tr("Source PDF: {0}").format(source_name), 3000)

    def _delete_item(self, item):
        parent = item.parent()
        if parent:
            parent.removeChild(item)
        self._sync_to_viewmodel()

    def _demote_item(self, item):
        parent = item.parent()
        if parent:
            index = parent.indexOfChild(item)
            if index > 0:
                prev_sibling = parent.child(index - 1)
                parent.takeChild(index)
                prev_sibling.addChild(item)
                prev_sibling.setExpanded(True)
                self.tree.setCurrentItem(item)
                self._sync_to_viewmodel()

    def _promote_item(self, item):
        parent = item.parent()
        if not parent or parent.parent() is None:
            return # Already top level bookmark (child of PDF root)
            
        grandparent = parent.parent()
        parent.takeChild(parent.indexOfChild(item))
        
        index = grandparent.indexOfChild(parent)
        grandparent.insertChild(index + 1, item)
            
        self.tree.setCurrentItem(item)
        self._sync_to_viewmodel()

    def _create_new_item(self, source_pdf):
        new_bm = BookmarkItem(title=self.tr("New Bookmark"), page=1, level=1, source_pdf=source_pdf)
        item = QTreeWidgetItem([new_bm.title, str(new_bm.page)])
        if "__compiled__" in globals():
            import sys
            bookmark_icon_path = os.path.join(os.path.dirname(sys.executable), "source", "bookmark.svg")
        else:
            bookmark_icon_path = os.path.join(os.path.dirname(__file__), "bookmark.svg")
        item.setIcon(0, QIcon(bookmark_icon_path))
        item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
        item.setData(0, Qt.ItemDataRole.UserRole, new_bm)
        return item

    def _add_sibling(self, item):
        parent = item.parent()
        if not parent: return
        
        pdf = self._get_pdf_for_item(item)
        new_item = self._create_new_item(pdf)
        
        index = parent.indexOfChild(item)
        parent.insertChild(index + 1, new_item)
        
        self.tree.setCurrentItem(new_item)
        self.tree.editItem(new_item, 0)
        self._sync_to_viewmodel()

    def _add_child(self, item):
        pdf = self._get_pdf_for_item(item)
        new_item = self._create_new_item(pdf)
        item.addChild(new_item)
        item.setExpanded(True)
        
        self.tree.setCurrentItem(new_item)
        self.tree.editItem(new_item, 0)
        self._sync_to_viewmodel()
        
    def _get_pdf_for_item(self, item):
        data = item.data(0, Qt.ItemDataRole.UserRole)
        from model import PDFDocument
        if isinstance(data, PDFDocument):
            return data
        elif isinstance(data, BookmarkItem):
            return data.source_pdf
        return None
