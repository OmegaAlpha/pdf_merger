import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QKeyEvent
from viewmodel import MainViewModel
from model import BookmarkItem
from bookmarks_pane import BookmarksPane
import fitz

@pytest.fixture
def real_pdf(tmp_path):
    file_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(file_path))
    doc.close()
    return str(file_path)

def test_bookmarks_pane_keyboard_navigation(qtbot, real_pdf):
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    pane = BookmarksPane(vm)
    pdf = vm.pdf_list_model.pdfs[0]
    
    # Create 3 child bookmark items
    b1 = BookmarkItem("B1", 1, 1, pdf)
    b2 = BookmarkItem("B2", 1, 1, pdf)
    b3 = BookmarkItem("B3", 1, 1, pdf)
    vm.global_toc = [b1, b2, b3]
    vm.global_toc_changed.emit()
    
    # The PDF root is top-level item 0
    pdf_root = pane.tree.topLevelItem(0) 
    item_b1 = pdf_root.child(0)
    item_b2 = pdf_root.child(1)
    item_b3 = pdf_root.child(2)
    
    assert item_b1.text(0) == "B1"
    assert item_b2.text(0) == "B2"
    assert item_b3.text(0) == "B3"
    
    # Set current item to B2
    pane.tree.setCurrentItem(item_b2)
    assert pane.tree.currentItem() is item_b2
    
    # Simulate standard Up Arrow key press on the tree widget
    event_up = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Up, Qt.KeyboardModifier.NoModifier)
    pane.tree.keyPressEvent(event_up)
    
    # The current item should now be B1
    assert pane.tree.currentItem() is item_b1
    
    # Simulate standard Down Arrow key press on the tree widget
    event_down = QKeyEvent(QKeyEvent.Type.KeyPress, Qt.Key.Key_Down, Qt.KeyboardModifier.NoModifier)
    pane.tree.keyPressEvent(event_down)
    
    # The current item should now be B2
    assert pane.tree.currentItem() is item_b2
