"""Tests for project_manager.py — save/load .pdfm project files."""

import json
import os
import pytest
from datetime import datetime

from project_manager import save_project, load_project, PROJECT_VERSION
from project_manager import refresh_pdf_metadata, verify_all_pdf_metadata
from model import PDFDocument


@pytest.fixture
def sample_pdfs(tmp_path):
    """Create real (empty) PDF-like files and return PDFDocument objects."""
    files = []
    for i in range(3):
        p = tmp_path / f"doc{i}.pdf"
        p.write_bytes(b"%PDF-1.4 fake")
        files.append(
            PDFDocument(
                file_path=str(p),
                name=f"doc{i}.pdf",
                size_kb=1.0 + i,
                modified_dt=datetime(2026, 5, 10, 12, 0, i),
                pages=i + 1,
                custom_toc=[[1, f"Chapter {i}", 1]] if i == 1 else None,
            )
        )
    return files


@pytest.fixture
def project_path(tmp_path):
    return str(tmp_path / "test_project.pdfm")


# ---------- Round-trip save/load ----------

def test_save_load_roundtrip(sample_pdfs, project_path):
    """Save a project and reload it — PDFs, output dir, and output name should match."""
    output_dir = os.path.dirname(sample_pdfs[0].file_path)
    output_name = "merged_output.pdf"

    save_project(project_path, sample_pdfs, output_dir, output_name)
    assert os.path.exists(project_path)

    result = load_project(project_path)

    assert result["output_name"] == output_name
    assert result["output_dir"] == output_dir
    assert len(result["pdfs"]) == 3
    assert result["missing_files"] == []

    for orig, loaded in zip(sample_pdfs, result["pdfs"]):
        assert loaded.name == orig.name
        assert loaded.pages == orig.pages
        assert loaded.size_kb == orig.size_kb
        assert loaded.custom_toc == orig.custom_toc
        assert loaded.missing is False


def test_roundtrip_preserves_order(sample_pdfs, project_path):
    """The order of PDFs in the list must be preserved through save/load."""
    reversed_pdfs = list(reversed(sample_pdfs))
    save_project(project_path, reversed_pdfs, "", "out.pdf")
    result = load_project(project_path)
    loaded_names = [p.name for p in result["pdfs"]]
    assert loaded_names == [p.name for p in reversed_pdfs]


def test_roundtrip_custom_toc(sample_pdfs, project_path):
    """Custom TOC data round-trips correctly."""
    save_project(project_path, sample_pdfs, "", "out.pdf")
    result = load_project(project_path)
    assert result["pdfs"][0].custom_toc is None
    assert result["pdfs"][1].custom_toc == [[1, "Chapter 1", 1]]
    assert result["pdfs"][2].custom_toc is None


# ---------- Project file format ----------

def test_project_file_is_valid_json(sample_pdfs, project_path):
    """The saved project file should be parseable JSON with expected keys."""
    save_project(project_path, sample_pdfs, "/some/dir", "output.pdf")
    with open(project_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["version"] == PROJECT_VERSION
    assert "pdfs" in data
    assert "output_dir_absolute" in data
    assert "output_dir_relative" in data
    assert data["output_name"] == "output.pdf"


def test_absolute_and_relative_paths_stored(sample_pdfs, project_path):
    """Each PDF entry should have both absolute_path and relative_path."""
    save_project(project_path, sample_pdfs, "", "out.pdf")
    with open(project_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for entry in data["pdfs"]:
        assert "absolute_path" in entry
        assert "relative_path" in entry
        assert os.path.isabs(entry["absolute_path"])


# ---------- Missing file handling ----------

def test_missing_files_flagged(sample_pdfs, project_path, tmp_path):
    """If a PDF no longer exists on disk, it should be loaded with missing=True."""
    save_project(project_path, sample_pdfs, str(tmp_path), "out.pdf")

    # Delete one file
    os.remove(sample_pdfs[1].file_path)

    result = load_project(project_path)
    assert len(result["pdfs"]) == 3  # All entries loaded
    assert result["pdfs"][0].missing is False
    assert result["pdfs"][1].missing is True
    assert result["pdfs"][2].missing is False
    assert "doc1.pdf" in result["missing_files"]


def test_all_files_missing(sample_pdfs, project_path, tmp_path):
    """If all PDFs are gone, all should be flagged as missing."""
    save_project(project_path, sample_pdfs, str(tmp_path), "out.pdf")
    for pdf in sample_pdfs:
        os.remove(pdf.file_path)

    result = load_project(project_path)
    assert all(p.missing for p in result["pdfs"])
    assert len(result["missing_files"]) == 3


# ---------- Relative path resolution ----------

def test_relative_path_fallback(sample_pdfs, project_path, tmp_path):
    """
    If the absolute path is broken (e.g. different drive), the loader should
    fall back to the relative path.
    """
    save_project(project_path, sample_pdfs, str(tmp_path), "out.pdf")

    # Manually tamper with the absolute paths to simulate drive change
    with open(project_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    for entry in data["pdfs"]:
        entry["absolute_path"] = "Z:\\nonexistent\\" + entry["absolute_path"].split(os.sep)[-1]
    with open(project_path, "w", encoding="utf-8") as f:
        json.dump(data, f)

    result = load_project(project_path)
    # Files should resolve via relative path since they're in the same tmp dir
    assert all(not p.missing for p in result["pdfs"])


# ---------- Output directory fallback ----------

def test_output_dir_fallback(sample_pdfs, project_path, tmp_path):
    """If the saved output dir no longer exists, fall back to project dir."""
    fake_dir = str(tmp_path / "nonexistent_output_dir")
    save_project(project_path, sample_pdfs, fake_dir, "out.pdf")

    result = load_project(project_path)
    # Should fall back to the project file's directory
    assert result["output_dir"] == os.path.dirname(os.path.abspath(project_path))


# ---------- Error handling ----------

def test_load_invalid_json(tmp_path):
    """Loading a corrupted file should raise an appropriate error."""
    bad_file = tmp_path / "bad.pdfm"
    bad_file.write_text("not valid json {{{", encoding="utf-8")
    with pytest.raises(json.JSONDecodeError):
        load_project(str(bad_file))


def test_load_nonexistent_file():
    """Loading a file that doesn't exist should raise OSError."""
    with pytest.raises(OSError):
        load_project("Z:\\does_not_exist.pdfm")


def test_save_empty_list(project_path):
    """Saving with no PDFs should produce a valid project with empty list."""
    save_project(project_path, [], "/some/dir", "out.pdf")
    result = load_project(project_path)
    assert result["pdfs"] == []
    assert result["output_name"] == "out.pdf"


# ---------- Refresh / Verify Metadata ----------

@pytest.fixture
def real_pdf(tmp_path):
    """Create a real minimal PDF using fitz."""
    import fitz
    path = tmp_path / "real.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.save(str(path))
    doc.close()
    
    stats = os.stat(str(path))
    return PDFDocument(
        file_path=str(path),
        name="real.pdf",
        size_kb=stats.st_size / 1024.0,
        modified_dt=datetime.fromtimestamp(stats.st_mtime),
        pages=1,
        custom_toc=[[1, "My Bookmark", 1]],
    )


def test_refresh_no_changes(real_pdf):
    """Refreshing a PDF that hasn't changed should return no changes."""
    changes = refresh_pdf_metadata(real_pdf)
    assert changes == []
    assert real_pdf.missing is False


def test_refresh_detects_page_change(real_pdf):
    """If the page count changed on disk, refresh should detect it."""
    import fitz
    # Add a page to the file
    doc = fitz.open(real_pdf.file_path)
    doc.new_page()
    doc.save(real_pdf.file_path, incremental=True, encryption=0)
    doc.close()
    
    changes = refresh_pdf_metadata(real_pdf)
    assert any("page count changed" in c for c in changes)
    assert real_pdf.pages == 2


def test_refresh_preserves_custom_toc(real_pdf):
    """Custom TOC must survive a refresh."""
    import fitz
    original_toc = real_pdf.custom_toc
    
    # Modify the file
    doc = fitz.open(real_pdf.file_path)
    doc.new_page()
    doc.save(real_pdf.file_path, incremental=True, encryption=0)
    doc.close()
    
    refresh_pdf_metadata(real_pdf)
    assert real_pdf.custom_toc == original_toc


def test_refresh_missing_file(tmp_path):
    """Refreshing a PDF whose file was deleted should flag it as missing."""
    pdf = PDFDocument(
        file_path=str(tmp_path / "gone.pdf"),
        name="gone.pdf",
        size_kb=10.0,
        modified_dt=datetime.now(),
        pages=5,
    )
    changes = refresh_pdf_metadata(pdf)
    assert pdf.missing is True
    assert any("no longer found" in c for c in changes)


def test_refresh_clears_missing_flag(real_pdf):
    """If a PDF was marked missing but the file now exists, refresh should clear the flag."""
    real_pdf.missing = True
    changes = refresh_pdf_metadata(real_pdf)
    assert real_pdf.missing is False


def test_verify_all_batch(real_pdf, tmp_path):
    """verify_all_pdf_metadata should process all non-missing PDFs."""
    import fitz
    
    # Create a second PDF
    path2 = tmp_path / "second.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(path2))
    doc.close()
    stats2 = os.stat(str(path2))
    
    pdf2 = PDFDocument(
        file_path=str(path2),
        name="second.pdf",
        size_kb=stats2.st_size / 1024.0,
        modified_dt=datetime.fromtimestamp(stats2.st_mtime),
        pages=2,
    )
    
    # No changes expected
    changes = verify_all_pdf_metadata([real_pdf, pdf2])
    assert changes == []


def test_verify_skips_missing(tmp_path):
    """verify_all_pdf_metadata should skip PDFs already flagged as missing."""
    pdf = PDFDocument(
        file_path=str(tmp_path / "gone.pdf"),
        name="gone.pdf",
        size_kb=10.0,
        modified_dt=datetime.now(),
        pages=5,
        missing=True,
    )
    changes = verify_all_pdf_metadata([pdf])
    assert changes == []
    assert pdf.missing is True


def test_save_load_with_advanced_destinations(sample_pdfs, project_path):
    """Verify that complex bookmark destinations (zoom, coords, URIs) round-trip perfectly."""
    from model import BookmarkItem
    
    # Create internal bookmark with specific sub-page zoom/coordinates
    bm1 = BookmarkItem(
        title="Chapter 1 Header",
        page=2,
        level=2,
        source_pdf=sample_pdfs[0],
        dest={"kind": 1, "page": 1, "to": [100.0, 200.0], "zoom": 1.5}
    )
    
    # Create external web link bookmark
    bm2 = BookmarkItem(
        title="More Info Online",
        page=1,
        level=1,
        source_pdf=sample_pdfs[1],
        dest={"kind": 2, "uri": "https://example.com"}
    )
    
    save_project(project_path, sample_pdfs, "", "out.pdf", [bm1, bm2])
    
    result = load_project(project_path)
    loaded_toc = result["global_toc"]
    
    assert len(loaded_toc) == 2
    assert loaded_toc[0].title == "Chapter 1 Header"
    assert loaded_toc[0].dest == {"kind": 1, "page": 1, "to": [100.0, 200.0], "zoom": 1.5}
    
    assert loaded_toc[1].title == "More Info Online"
    assert loaded_toc[1].dest == {"kind": 2, "uri": "https://example.com"}


def test_save_load_preserves_host_pdf(sample_pdfs, project_path):
    """Verify that guest bookmarks (with host_pdf) preserve their layout nesting after reload."""
    from model import BookmarkItem
    
    # bm belongs to sample_pdfs[0] (source) but is nested under sample_pdfs[1] (host)
    guest_bm = BookmarkItem(
        title="Nested Guest",
        page=1,
        level=1,
        source_pdf=sample_pdfs[0],
        host_pdf=sample_pdfs[1]
    )
    
    save_project(project_path, sample_pdfs, "", "out.pdf", [guest_bm])
    
    result = load_project(project_path)
    loaded_toc = result["global_toc"]
    
    assert len(loaded_toc) == 1
    loaded_bm = loaded_toc[0]
    
    assert loaded_bm.source_pdf.name == sample_pdfs[0].name
    assert loaded_bm.host_pdf is not None
    assert loaded_bm.host_pdf.name == sample_pdfs[1].name


