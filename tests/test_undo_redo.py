import os
import fitz
import pytest
from PySide6.QtCore import Qt
from viewmodel import MainViewModel
from model import BookmarkItem, PDFDocument
from datetime import datetime

@pytest.fixture
def real_pdf(tmp_path):
    file_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(file_path))
    doc.close()
    return str(file_path)

def test_undo_redo_remove_pdf(qtbot, real_pdf):
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    # Add a bookmark to the PDF
    pdf = vm.pdf_list_model.pdfs[0]
    vm.global_toc = [BookmarkItem("B1", 1, 1, pdf)]
    vm.global_toc_changed.emit()
    vm.undo_stack.clear() # Clear the "Add" actions
    
    # Remove PDF
    vm.remove_pdfs_by_indices([0])
    assert len(vm.pdf_list_model.pdfs) == 0
    assert len(vm.global_toc) == 0
    
    # Undo
    vm.undo_stack.undo()
    assert len(vm.pdf_list_model.pdfs) == 1
    assert len(vm.global_toc) == 1
    assert vm.global_toc[0].title == "B1"
    # CRITICAL: CHECK IDENTITY PRESERVATION
    # The source_pdf reference must point to the EXACT SAME object in the list
    assert vm.global_toc[0].source_pdf is vm.pdf_list_model.pdfs[0]
    
    # Redo
    vm.undo_stack.redo()
    assert len(vm.pdf_list_model.pdfs) == 0
    assert len(vm.global_toc) == 0

def test_undo_redo_bookmark_edit(qtbot, real_pdf):
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    pdf = vm.pdf_list_model.pdfs[0]
    vm.global_toc = [BookmarkItem("Original", 1, 1, pdf)]
    vm.global_toc_changed.emit()
    vm.undo_stack.clear()
    
    # Edit bookmark
    new_toc = [BookmarkItem("Edited", 1, 1, pdf)]
    vm.update_global_toc(new_toc, "Edit")
    
    assert vm.global_toc[0].title == "Edited"
    
    # Undo
    vm.undo_stack.undo()
    assert vm.global_toc[0].title == "Original"
    assert vm.global_toc[0].source_pdf is vm.pdf_list_model.pdfs[0]
    
    # Redo
    vm.undo_stack.redo()
    assert vm.global_toc[0].title == "Edited"

def test_undo_redo_add_pdfs_batch(qtbot, tmp_path):
    # Create 2 PDFs
    p1 = tmp_path / "1.pdf"
    p2 = tmp_path / "2.pdf"
    for p in [p1, p2]:
        doc = fitz.open()
        doc.new_page()
        doc.save(str(p))
        doc.close()
        
    vm = MainViewModel()
    vm.add_pdfs([str(p1), str(p2)])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 2, timeout=3000)
    
    # Undo should remove BOTH in one step
    vm.undo_stack.undo()
    assert len(vm.pdf_list_model.pdfs) == 0
    
    # Redo should bring BOTH back
    vm.undo_stack.redo()
    assert len(vm.pdf_list_model.pdfs) == 2

def test_undo_redo_move_rows(qtbot):
    vm = MainViewModel()
    from datetime import datetime
    
    # Add dummy manually
    docs = [
        PDFDocument(f"p{i}", f"F{i}.pdf", 1.0, datetime.now(), 1)
        for i in range(3) # F0, F1, F2
    ]
    vm.pdf_list_model.pdfs = docs
    vm.undo_stack.clear()
    
    # Move F0 to end
    vm.move_rows(0, 1, 3)
    assert vm.pdf_list_model.pdfs[0].name == "F1.pdf"
    assert vm.pdf_list_model.pdfs[2].name == "F0.pdf"
    
    # Undo
    vm.undo_stack.undo()
    assert vm.pdf_list_model.pdfs[0].name == "F0.pdf"
    assert vm.pdf_list_model.pdfs[1].name == "F1.pdf"
    
    # Redo
    vm.undo_stack.redo()
    assert vm.pdf_list_model.pdfs[0].name == "F1.pdf"
    assert vm.pdf_list_model.pdfs[2].name == "F0.pdf"
def test_undo_redo_bookmark_deletion(qtbot, real_pdf):
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    pdf = vm.pdf_list_model.pdfs[0]
    # B1 -> B2 (nested)
    b1 = BookmarkItem("B1", 1, 1, pdf)
    b2 = BookmarkItem("B2", 1, 2, pdf)
    vm.global_toc = [b1, b2]
    vm.global_toc_changed.emit()
    vm.undo_stack.clear()
    
    # Simulate deletion of B1 (which should remove B2 too if it's a child in the tree)
    # In the ViewModel, we just provide a new list without them.
    vm.update_global_toc([], "Delete B1")
    
    assert len(vm.global_toc) == 0
    
    # Undo
    vm.undo_stack.undo()
    assert len(vm.global_toc) == 2
    assert vm.global_toc[0].title == "B1"
    assert vm.global_toc[1].title == "B2"

def test_undo_redo_bookmark_rename_mutations(qtbot, real_pdf):
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    pdf = vm.pdf_list_model.pdfs[0]
    b1 = BookmarkItem("Original", 1, 1, pdf)
    vm.global_toc = [b1]
    vm.global_toc_changed.emit()
    vm.undo_stack.clear()
    
    # This simulates the mutation bug in BookmarksPane._sync_to_viewmodel
    # 1. Capture state BEFORE mutation (Corrected pattern)
    old_state = vm.get_state()
    
    # 2. Capture bookmark object
    target_bm = vm.global_toc[0]
    
    # 3. Mutate it
    target_bm.title = "Mutated"
    
    # 4. Call update_global_toc with the captured state
    vm.update_global_toc([target_bm], "Rename", old_state)
    
    # 5. Undo
    vm.undo_stack.undo()
    
    assert vm.global_toc[0].title == "Original"

def test_undo_redo_bookmark_complex_deletion(qtbot, real_pdf):
    from bookmarks_pane import BookmarksPane
    vm = MainViewModel()
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)
    
    pane = BookmarksPane(vm)
    pdf = vm.pdf_list_model.pdfs[0]
    
    # Setup complex tree
    # PDF Root
    #   B1
    #     B2
    #       B3
    b1 = BookmarkItem("B1", 1, 1, pdf)
    b2 = BookmarkItem("B2", 1, 2, pdf)
    b3 = BookmarkItem("B3", 1, 3, pdf)
    vm.global_toc = [b1, b2, b3]
    vm.global_toc_changed.emit()
    vm.undo_stack.clear()
    
    # Find B1 in tree
    # The PDF root is top-level item 0
    it = pane.tree.topLevelItem(0) 
    # B1 is the first child of the PDF root
    item_b1 = it.child(0)
    assert item_b1.text(0) == "B1"
    
    # Delete B1 via Pane method
    pane._delete_item(item_b1)
    
    assert len(vm.global_toc) == 0
    assert it.childCount() == 0
    
    # Undo
    vm.undo_stack.undo()
    
    assert len(vm.global_toc) == 3
    
    # Re-fetch the PDF root as the previous one was deleted during tree.clear()
    it = pane.tree.topLevelItem(0)
    assert it.childCount() == 1
    assert it.child(0).text(0) == "B1"
    assert it.child(0).child(0).text(0) == "B2"
    assert it.child(0).child(0).child(0).text(0) == "B3"

def test_undo_stack_empty_after_load_project(tmp_path):
    # Save a temporary project with a specific output dir
    p1 = tmp_path / "1.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(p1))
    doc.close()
    
    diff_dir = tmp_path / "different_dir"
    diff_dir.mkdir()
    
    project_path = str(tmp_path / "test_load_undo.pdfm")
    from project_manager import save_project
    save_project(project_path, [], str(diff_dir), "out.pdf")
    
    vm = MainViewModel()
    # Set current output dir to something else
    vm.output_dir = str(tmp_path)
    
    # Load project
    vm.do_load_project(project_path)
    
    # The output directory should be loaded correctly
    assert vm.output_dir == str(diff_dir)
    
    # Crucially, the undo stack must be completely empty!
    assert not vm.undo_stack.canUndo()

def test_undo_action_dynamic_translation(qtbot):
    from PySide6.QtCore import QTranslator, QCoreApplication
    vm = MainViewModel()
    
    # Commit state with a key in context MainViewModel
    old_state = vm.get_state()
    vm.output_dir = "/new/dir/for/test"  # Mutate state so states differ
    vm.commit_state("Change Output Directory", old_state)
    
    # Assert initial untranslated text
    assert vm.undo_stack.undoText() == "Change Output Directory"
    
    # Create and install the Norwegian Bokmål translator
    translator = QTranslator()
    qm_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "translations", "pdf_merger_nb.qm"))
    if os.path.exists(qm_path):
        translator.load(qm_path)
        QCoreApplication.installTranslator(translator)
        try:
            # Manually trigger translation update on the stack (as MainWindow.retranslateUi does)
            for idx in range(vm.undo_stack.count()):
                cmd = vm.undo_stack.command(idx)
                if hasattr(cmd, 'description_key') and hasattr(cmd, 'context'):
                    cmd.setText(QCoreApplication.translate(cmd.context, cmd.description_key))

            # Under Norwegian translation, the undo text should be translated dynamically
            translated_text = QCoreApplication.translate("MainViewModel", "Change Output Directory")
            assert vm.undo_stack.undoText() == translated_text
            
            # If we uninstall the translator, it goes back to English key after manual update
            QCoreApplication.removeTranslator(translator)
            for idx in range(vm.undo_stack.count()):
                cmd = vm.undo_stack.command(idx)
                if hasattr(cmd, 'description_key') and hasattr(cmd, 'context'):
                    cmd.setText(QCoreApplication.translate(cmd.context, cmd.description_key))
            assert vm.undo_stack.undoText() == "Change Output Directory"
        finally:
            QCoreApplication.removeTranslator(translator)
