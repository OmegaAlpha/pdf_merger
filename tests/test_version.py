import pytest
from version import __version__
from view import MainWindow
from viewmodel import MainViewModel

def test_version_string():
    assert __version__ == "0.2.0"

def test_main_window_title_contains_version(qtbot):
    vm = MainViewModel()
    window = MainWindow(vm)
    qtbot.addWidget(window)
    
    assert __version__ in window._app_title
    assert "0.2.0" in window._app_title
    assert window.windowTitle().startswith(f"PDF Merger v{__version__}")
