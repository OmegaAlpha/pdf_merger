import os
import pytest
import fitz
from PySide6.QtWidgets import QMessageBox
from viewmodel import MainViewModel
from view import MainWindow


@pytest.fixture
def real_pdf(tmp_path):
    file_path = tmp_path / "test.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(file_path))
    doc.close()
    return str(file_path)


def test_on_merge_overwrite_prompt_without_pdf_extension(qtbot, tmp_path, real_pdf, mocker):
    """Verify that overwrite prompt is triggered when destination file exists, even if user omits .pdf."""
    vm = MainViewModel()
    vm.output_dir = str(tmp_path)
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)

    # Create the target output file on disk
    target_file = tmp_path / "my_merged.pdf"
    target_file.write_text("existing content")

    window = MainWindow(vm)
    qtbot.addWidget(window)

    # User enters output name WITHOUT .pdf
    window.output_name.setText("my_merged")

    # Mock QMessageBox.exec to simulate clicking "No" (cancel)
    mock_exec = mocker.patch.object(QMessageBox, "exec", return_value=QMessageBox.StandardButton.No)
    mock_start_merge = mocker.patch.object(vm, "start_merge")

    window.on_merge()

    assert mock_exec.called
    assert not mock_start_merge.called

    # Now simulate clicking "Yes" (confirm overwrite)
    mock_exec.return_value = QMessageBox.StandardButton.Yes
    window.on_merge()

    assert mock_start_merge.called
    mock_start_merge.assert_called_with("my_merged.pdf")


def test_on_merge_no_overwrite_prompt_when_file_does_not_exist(qtbot, tmp_path, real_pdf, mocker):
    """Verify that no overwrite prompt appears if the destination file does not exist."""
    vm = MainViewModel()
    vm.output_dir = str(tmp_path)
    vm.add_pdfs([real_pdf])
    qtbot.waitUntil(lambda: len(vm.pdf_list_model.pdfs) == 1, timeout=3000)

    window = MainWindow(vm)
    qtbot.addWidget(window)

    window.output_name.setText("new_file")

    mock_exec = mocker.patch.object(QMessageBox, "exec")
    mock_start_merge = mocker.patch.object(vm, "start_merge")

    window.on_merge()

    assert not mock_exec.called
    assert mock_start_merge.called
    mock_start_merge.assert_called_with("new_file.pdf")
