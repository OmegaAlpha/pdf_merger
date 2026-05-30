import pytest
from PySide6.QtCore import Qt, QPoint
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

def test_bookmarks_context_menu_cancel_with_multiple_selected(qtbot, real_pdf, mocker):
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    pane = BookmarksPane(vm)
    pdf = vm.pdf_list_model.pdfs[0]
    
    # Create 2 bookmark items
    b1 = BookmarkItem("B1", 1, 1, pdf)
    b2 = BookmarkItem("B2", 1, 2, pdf)
    vm.global_toc = [b1, b2]
    vm.global_toc_changed.emit()
    
    pdf_root = pane.tree.topLevelItem(0) 
    item_b1 = pdf_root.child(0)
    item_b2 = item_b1.child(0)
    
    # Select both
    item_b1.setSelected(True)
    item_b2.setSelected(True)
    
    # Mock QMenu class in bookmarks_pane to avoid C++ exec blocking and COM exceptions
    mock_menu = mocker.patch('bookmarks_pane.QMenu')
    mock_menu.return_value.exec.return_value = None
    
    # Trigger context menu on the first item
    # Get a point on the viewport inside the item
    pos = pane.tree.visualItemRect(item_b1).center()
    pane.show_context_menu(pos)
    
    # Verify that NO new bookmark is added (len should still be 2)
    assert len(vm.global_toc) == 2
