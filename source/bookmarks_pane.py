import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTreeWidget, QTreeWidgetItem, QTreeWidgetItemIterator,
    QAbstractItemView, QHeaderView, QMenu, QHBoxLayout, QLabel, QPushButton, QStyle, QStyledItemDelegate
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QAction, QKeySequence, QFont, QColor, QBrush, QIcon

from model import BookmarkItem
from utils import get_source_asset_path

# Cached icons — constructed once on first use
_bookmark_icon_cache = None
_bookmark_linked_icon_cache = None

def _bookmark_icon():
    global _bookmark_icon_cache
    if _bookmark_icon_cache is None:
        _bookmark_icon_cache = QIcon(get_source_asset_path("bookmark.svg"))
    return _bookmark_icon_cache

def _bookmark_linked_icon():
    global _bookmark_linked_icon_cache
    if _bookmark_linked_icon_cache is None:
        _bookmark_linked_icon_cache = QIcon(get_source_asset_path("bookmark_linked.svg"))
    return _bookmark_linked_icon_cache

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
        # 1. Call super first so Qt calculates the correct drop indicator position
        super().dragMoveEvent(event)
        
        target_item = self.itemAt(event.pos())
        dragged_item = self.currentItem()
        
        # Prevent dropping in empty space
        if target_item is None:
            event.ignore()
            return
            
        # Prevent placing guest bookmarks directly under another PDF container root
        if dragged_item:
            from model import BookmarkItem, PDFDocument
            indicator = self.dropIndicatorPosition()
            proposed_parent_pdf = None
            
            if indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
                target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(target_data, PDFDocument):
                    proposed_parent_pdf = target_data
            elif indicator in (QAbstractItemView.DropIndicatorPosition.AboveItem, QAbstractItemView.DropIndicatorPosition.BelowItem):
                target_parent = target_item.parent()
                if target_parent is None:
                    # Dropping above/below a top-level PDF root (escaping to top level) - not allowed!
                    event.ignore()
                    return
                else:
                    # If the parent is a PDFDocument, this drop will create a Level-1 bookmark
                    target_parent_data = target_parent.data(0, Qt.ItemDataRole.UserRole)
                    if isinstance(target_parent_data, PDFDocument):
                        proposed_parent_pdf = target_parent_data
                
            if proposed_parent_pdf is not None:
                bm = dragged_item.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(bm, BookmarkItem) and bm.source_pdf.file_path != proposed_parent_pdf.file_path:
                    event.ignore()
                    return

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

        # Prevent placing guest bookmarks directly under another PDF container root
        indicator = self.dropIndicatorPosition()
        proposed_parent_pdf = None
        
        if indicator == QAbstractItemView.DropIndicatorPosition.OnItem:
            target_data = target_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(target_data, PDFDocument):
                proposed_parent_pdf = target_data
        elif indicator in (QAbstractItemView.DropIndicatorPosition.AboveItem, QAbstractItemView.DropIndicatorPosition.BelowItem):
            target_parent = target_item.parent()
            if target_parent is None:
                # Dropping above/below a top-level PDF root (escaping to top level) - not allowed!
                event.ignore()
                return
            else:
                # If the parent is a PDFDocument, this drop will create a Level-1 bookmark
                target_parent_data = target_parent.data(0, Qt.ItemDataRole.UserRole)
                if isinstance(target_parent_data, PDFDocument):
                    proposed_parent_pdf = target_parent_data
            
        if proposed_parent_pdf is not None:
            bm = dragged_item.data(0, Qt.ItemDataRole.UserRole)
            if isinstance(bm, BookmarkItem) and bm.source_pdf.file_path != proposed_parent_pdf.file_path:
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

    def event(self, event):
        from PySide6.QtCore import QEvent
        # Intercept Tab and Shift+Tab before Qt uses them for widget focus switching
        if event.type() == QEvent.Type.KeyPress:
            if event.key() in (Qt.Key.Key_Tab, Qt.Key.Key_Backtab):
                self.keyPressEvent(event)
                return True
        return super().event(event)


    def keyPressEvent(self, event):
        item = self.currentItem()
        if not item or item.parent() is None: # Don't allow modifying PDF root nodes
            super().keyPressEvent(event)
            return
            
        # Alt modifier check
        has_alt = bool(event.modifiers() & Qt.KeyboardModifier.AltModifier)
        
        # Locate the parent BookmarksPane to trigger functions
        pane = self.parent()
        while pane and not hasattr(pane, "_promote_item"):
            pane = pane.parent()
            
        if pane:
            if event.key() == Qt.Key.Key_Delete or event.key() == Qt.Key.Key_Backspace:
                pane._delete_items()
                event.accept()
                return
            elif (event.key() == Qt.Key.Key_Left and has_alt) or event.key() == Qt.Key.Key_Backtab: # Alt + Left Arrow to Promote
                if len(pane._get_selected_bookmarks()) > 1:
                    pane._promote_items()
                else:
                    pane._promote_item(item)
                event.accept()
                return
            elif (event.key() == Qt.Key.Key_Right and has_alt) or event.key() == Qt.Key.Key_Tab: # Alt + Right Arrow to Demote
                if len(pane._get_selected_bookmarks()) > 1:
                    pane._demote_items()
                else:
                    pane._demote_item(item)
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Up and has_alt: # Alt + Up Arrow to Move Up
                if len(pane._get_selected_bookmarks()) > 1:
                    pane._move_items_up()
                else:
                    pane._move_item_up(item)
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Down and has_alt: # Alt + Down Arrow to Move Down
                if len(pane._get_selected_bookmarks()) > 1:
                    pane._move_items_down()
                else:
                    pane._move_item_down(item)
                event.accept()
                return
            elif event.key() == Qt.Key.Key_Insert:
                pane._add_sibling(item)
                event.accept()
                return
        
        super().keyPressEvent(event)


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
        
        # Apply custom delegate for page column
        self.page_delegate = PageDelegate(self.tree)
        self.tree.setItemDelegateForColumn(1, self.page_delegate)
        
        # Drag and drop for reordering and reparenting
        self.tree.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.tree.setAlternatingRowColors(False)
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

    def show_context_menu(self, pos):
        item = self.tree.itemAt(pos)
        menu = QMenu()
        global_pos = self.tree.viewport().mapToGlobal(pos)

        multiple_selected = len(self._get_selected_bookmarks()) > 1
        
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
                # Initialize actions to None to prevent UnboundLocalError if multiple bookmarks are selected
                add_action = None
                add_child_action = None

                # Bookmark Node
                if (len(self._get_selected_bookmarks()) == 1):
                    add_action = menu.addAction(self.tr("Add Bookmark Below"))
                    add_child_action = menu.addAction(self.tr("Add Child Bookmark"))

                menu.addSeparator()
                promote_action = menu.addAction(self.tr("Promote (Shift+Tab)"))
                demote_action = menu.addAction(self.tr("Demote (Tab)"))
                menu.addSeparator()
                remove_action = menu.addAction(self.tr("Remove"))

                independent_items = self._get_independent_selected_items()

                # Check promote validity
                can_promote = True
                for it in independent_items:
                    parent = it.parent()
                    if not parent or parent.parent() is None:
                        can_promote = False
                        break

                    # --- Guest Bookmark Guard ---
                    # Block promoting a guest bookmark if it would become a Level-1 bookmark
                    grandparent = parent.parent()
                    if grandparent.parent() is None:  # grandparent is the PDF root container
                        from model import BookmarkItem, PDFDocument
                        bm = it.data(0, Qt.ItemDataRole.UserRole)
                        proposed_pdf = grandparent.data(0, Qt.ItemDataRole.UserRole)
                        if (isinstance(bm, BookmarkItem) and 
                            isinstance(proposed_pdf, PDFDocument) and 
                            bm.source_pdf.file_path != proposed_pdf.file_path):
                            can_promote = False
                            break

                promote_action.setEnabled(can_promote)

                # Check demote validity
                can_demote = True
                for it in independent_items:
                    parent = it.parent()
                    if parent:
                        index = parent.indexOfChild(it)
                        if index == 0: # First child cannot be demoted
                            can_demote = False
                            break
                    else: # No parent means it is a top-level bookmark, cannot be demoted
                        can_demote = False
                        break
                
                demote_action.setEnabled(can_demote)
                
                action = menu.exec(global_pos)
                if add_action and action == add_action:
                    self._add_sibling(item)
                elif add_child_action and action == add_child_action:
                    self._add_child(item)
                elif action == promote_action:
                    if multiple_selected:
                        self._promote_items()
                    else:
                        self._promote_item(item)
                elif action == demote_action:
                    if multiple_selected:
                        self._demote_items()
                    else:
                        self._demote_item(item)
                elif action == remove_action:
                    self._delete_items()
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
        self.tree.blockSignals(True)
        try:
            self.tree.clear()
            
            pdf_list = self.vm.pdf_list_model.pdfs
            if not pdf_list:
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
                pdf = bm.host_pdf if bm.host_pdf is not None else bm.source_pdf
                root_item = pdf_root_nodes.get(id(pdf))
                if root_item is None:
                    # Robust fallback matching by equality or file_path comparison
                    for pdf_item in pdf_list:
                        if pdf_item == pdf or os.path.abspath(pdf_item.file_path) == os.path.abspath(pdf.file_path):
                            root_item = pdf_root_nodes[id(pdf_item)]
                            break
                if root_item is None:
                    continue
                
                item = QTreeWidgetItem([bm.title, str(bm.page)])
                
                item.setIcon(0, _bookmark_icon())
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
                    
                    if root_pdf.file_path != bm.source_pdf.file_path:
                        italic_font = item.font(0)
                        italic_font.setItalic(True)
                        item.setFont(0, italic_font)
                        item.setFont(1, italic_font)
                        
                        source_name = bm.source_pdf.name if bm.source_pdf else self.tr("Unknown")
                        tooltip = self.tr("Source: {0}").format(source_name)
                        item.setToolTip(0, tooltip)
                        item.setToolTip(1, tooltip)
                        
                        item.setIcon(0, _bookmark_linked_icon())
                it += 1
        finally:
            self.tree.blockSignals(False)
            self._is_populating = False

    def _on_item_changed(self, item, column):
        if self._is_populating:
            return
        self._sync_to_viewmodel()

    def _sync_to_viewmodel(self):
        if self._is_populating:
            return
            
        self._is_populating = True
        self.tree.blockSignals(True)
        try:
            # Capture state BEFORE we start traversing and potentially mutating bookmark objects
            old_state = self.vm.get_state()
            new_toc = []
            
            def traverse(item, parent_pdf, level, container_pdf):
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
                    bm.host_pdf = container_pdf  # track which tree it's displayed in
                    new_toc.append(bm)
                    current_pdf = bm.host_pdf
                else:
                    # Newly created item inherits PDF from parent/ancestor
                    bm = BookmarkItem(title=title, page=page, level=level, source_pdf=parent_pdf, host_pdf=container_pdf)
                    item.setData(0, Qt.ItemDataRole.UserRole, bm)
                    new_toc.append(bm)
                    current_pdf = parent_pdf

                # Apply Guest bookmark visualization (italics + tooltip)
                # Find the top-level PDF root this item is attached to
                top_root = item
                while top_root.parent():
                    top_root = top_root.parent()
                root_pdf = top_root.data(0, Qt.ItemDataRole.UserRole)
                
                if bm.source_pdf.file_path != container_pdf.file_path:
                    italic_font = item.font(0)
                    italic_font.setItalic(True)
                    item.setFont(0, italic_font)
                    item.setFont(1, italic_font)
                    
                    source_name = bm.source_pdf.name if bm.source_pdf else self.tr("Unknown")
                    tooltip = self.tr("Source: {0}").format(source_name)
                    item.setToolTip(0, tooltip)
                    item.setToolTip(1, tooltip)
                    
                    item.setIcon(0, _bookmark_linked_icon())
                else:
                    # Revert to normal if it's no longer a guest
                    normal_font = item.font(0)
                    normal_font.setItalic(False)
                    item.setFont(0, normal_font)
                    item.setFont(1, normal_font)
                    item.setToolTip(0, "")
                    item.setToolTip(1, "")
                    
                    item.setIcon(0, _bookmark_icon())
                    
                for i in range(item.childCount()):
                    traverse(item.child(i), current_pdf, level + 1, container_pdf)
                    
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
                        traverse(root_item.child(j), data, 1, data)
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
                        target_pdf_data = target_pdf_root.data(0, Qt.ItemDataRole.UserRole)
                        traverse(root_item, target_pdf_data, 1, target_pdf_data)
                    else:
                        # No PDF roots at all? Just process as is.
                        traverse(root_item, data.source_pdf, 1, data.source_pdf)
                        i += 1
                
            # Update viewmodel without triggering _populate_tree
            self.vm.global_toc_changed.disconnect(self._populate_tree)
            try:
                self.vm.update_global_toc(new_toc, self.tr("Edit Bookmarks"), old_state, "BookmarksPane")
            finally:
                self.vm.global_toc_changed.connect(self._populate_tree)
        finally:
            self.tree.blockSignals(False)
            self._is_populating = False

    def _get_selected_bookmarks(self):
        """Returns a list of selected QTreeWidgetItem objects that represent actual bookmarks."""
        from model import BookmarkItem
        selected_items = self.tree.selectedItems()

        # Filter out items that have no parent (the PDF root containers)
        # and verify their user data is indeed a BookmarkItem
        return [
            item for item in selected_items 
            if item.parent() is not None 
            and isinstance(item.data(0, Qt.ItemDataRole.UserRole), BookmarkItem)
        ]

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

    def _delete_items(self):
        selected_bookmarks = self._get_selected_bookmarks()
        
        if not selected_bookmarks:
            return
        
        self.vm.undo_stack.beginMacro(self.tr("Delete Bookmark") if len(selected_bookmarks) == 1 else self.tr("Delete Bookmarks"))
        try:
            for item in selected_bookmarks:
                parent = item.parent()
                if parent:
                    parent.removeChild(item)
            self._sync_to_viewmodel()
        finally:
            self.vm.undo_stack.endMacro()

    def _get_sorted_selected_items(self):
        selected = self._get_selected_bookmarks()
        if not selected:
            return []
        
        # 1. Collect all items in their visual top-to-bottom order
        visual_order = []
        it = QTreeWidgetItemIterator(self.tree)
        while it.value():
            visual_order.append(it.value())
            it += 1
        # 2. Map each item to its index for O(1) lookups
        index_map = {item: i for i, item in enumerate(visual_order)}
        # 3. Sort your selected items list using the index map
        # (Use reverse=True if you ever need bottom-to-top sorting!)
        return sorted(selected, key=lambda item: index_map.get(item, 0))

    def _get_independent_selected_items(self):
        selected = self._get_sorted_selected_items()
        selected_set = set(selected)
        independent_items = []
    
        for item in selected:
            # Walk up the parent tree of this item
            ancestor = item.parent()
            has_selected_ancestor = False
        
            while ancestor is not None:
                if ancestor in selected_set:
                    has_selected_ancestor = True
                    break
                ancestor = ancestor.parent()
            
            # If no ancestor is selected, this is a top-level root of the selection block!
            if not has_selected_ancestor:
                independent_items.append(item)
            
        return independent_items


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

    def _demote_items(self):
        # 1. Save the selection models
        selected_model_ids = {
            id(item.data(0, Qt.ItemDataRole.UserRole)) 
            for item in self._get_selected_bookmarks()
        }
        self.vm.undo_stack.beginMacro(self.tr("Demote Bookmarks"))
        try:
            items = self._get_independent_selected_items()
            for item in items:
                self._demote_item(item)
            self._sync_to_viewmodel()
        
            # 2. Restore the selection
            self.tree.blockSignals(True)
            try:
                # Clear current selection first
                self.tree.clearSelection()
                
                it = QTreeWidgetItemIterator(self.tree)
                while it.value():
                    tree_item = it.value()
                    model = tree_item.data(0, Qt.ItemDataRole.UserRole)
                    if id(model) in selected_model_ids:
                        tree_item.setSelected(True)
                    it += 1
            finally:
                self.tree.blockSignals(False)
        finally: 
            self.vm.undo_stack.endMacro()

    def _promote_item(self, item):
        parent = item.parent()
        if not parent or parent.parent() is None:
            return # Already top level bookmark (child of PDF root)
            
        grandparent = parent.parent()

        # Guard: Prevent promoting a guest bookmark if it would become a Level-1 bookmark
        if grandparent.parent() is None: 
            from model import BookmarkItem, PDFDocument
            bm = item.data(0, Qt.ItemDataRole.UserRole)
            proposed_pdf = grandparent.data(0, Qt.ItemDataRole.UserRole)
            if (isinstance(bm, BookmarkItem) and 
            isinstance(proposed_pdf, PDFDocument) and
            bm.source_pdf.file_path != proposed_pdf.file_path):
                return # block guest bookmark promotion
        
        parent.takeChild(parent.indexOfChild(item))
        
        index = grandparent.indexOfChild(parent)
        grandparent.insertChild(index + 1, item)
            
        self.tree.setCurrentItem(item)
        self._sync_to_viewmodel()

    def _promote_items(self):
        # 1. Save the selection models
        selected_model_ids = {
            id(item.data(0, Qt.ItemDataRole.UserRole)) 
            for item in self._get_selected_bookmarks()
        }
        self.vm.undo_stack.beginMacro(self.tr("Promote Bookmarks"))
        try:
            items = reversed(self._get_independent_selected_items())
            for item in items:
                self._promote_item(item)
            self._sync_to_viewmodel()
        
            # 2. Restore the selection
            self.tree.blockSignals(True)
            try:
                # Clear current selection first
                self.tree.clearSelection()
                
                it = QTreeWidgetItemIterator(self.tree)
                while it.value():
                    tree_item = it.value()
                    model = tree_item.data(0, Qt.ItemDataRole.UserRole)
                    if id(model) in selected_model_ids:
                        tree_item.setSelected(True)
                    it += 1
            finally:
                self.tree.blockSignals(False)
        finally: 
            self.vm.undo_stack.endMacro()


    def _move_item_up(self, item):
        parent = item.parent()
        if not parent:
            return  # Don't move PDF root containers
            
        index = parent.indexOfChild(item)
        if index > 0:
            parent.takeChild(index)
            parent.insertChild(index - 1, item)
            self.tree.setCurrentItem(item)
            self._sync_to_viewmodel()

    def _move_items_up(self):
        # 1. Save the selection models
        selected_model_ids = {
            id(item.data(0, Qt.ItemDataRole.UserRole)) 
            for item in self._get_selected_bookmarks()
        }
        self.vm.undo_stack.beginMacro(self.tr("Move Bookmarks Up"))
        try:
            items = self._get_independent_selected_items()
            for item in items:
                self._move_item_up(item)
            self._sync_to_viewmodel()
        
            # 2. Restore the selection
            self.tree.blockSignals(True)
            try:
                # Clear current selection first
                self.tree.clearSelection()
                
                it = QTreeWidgetItemIterator(self.tree)
                while it.value():
                    tree_item = it.value()
                    model = tree_item.data(0, Qt.ItemDataRole.UserRole)
                    if id(model) in selected_model_ids:
                        tree_item.setSelected(True)
                    it += 1
            finally:
                self.tree.blockSignals(False)
        finally: 
            self.vm.undo_stack.endMacro()

    def _move_item_down(self, item):
        parent = item.parent()
        if not parent:
            return  # Don't move PDF root containers
            
        index = parent.indexOfChild(item)
        if index < parent.childCount() - 1:
            parent.takeChild(index)
            parent.insertChild(index + 1, item)
            self.tree.setCurrentItem(item)
            self._sync_to_viewmodel()

    def _move_items_down(self):
        # 1. Save the selection models
        selected_model_ids = {
            id(item.data(0, Qt.ItemDataRole.UserRole)) 
            for item in self._get_selected_bookmarks()
        }
        self.vm.undo_stack.beginMacro(self.tr("Move Bookmarks Down"))
        try:
            items = reversed(self._get_independent_selected_items())
            for item in items:
                self._move_item_down(item)
            self._sync_to_viewmodel()
        
            # 2. Restore the selection
            self.tree.blockSignals(True)
            try:
                # Clear current selection first
                self.tree.clearSelection()
                
                it = QTreeWidgetItemIterator(self.tree)
                while it.value():
                    tree_item = it.value()
                    model = tree_item.data(0, Qt.ItemDataRole.UserRole)
                    if id(model) in selected_model_ids:
                        tree_item.setSelected(True)
                    it += 1
            finally:
                self.tree.blockSignals(False)
        finally: 
            self.vm.undo_stack.endMacro()

    def _create_new_item(self, source_pdf):
        new_bm = BookmarkItem(title=self.tr("New Bookmark"), page=1, level=1, source_pdf=source_pdf)
        item = QTreeWidgetItem([new_bm.title, str(new_bm.page)])
        item.setIcon(0, _bookmark_icon())
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
