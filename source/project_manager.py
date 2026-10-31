"""
Project file manager for PDF Merger.

Handles saving and loading .pdfm project files (JSON format).
Each project captures the PDF list order, bookmark data, file locations
(both absolute and relative to the project file), output directory, and
output filename.
"""

import json
import os
from datetime import datetime
from typing import List, Tuple, Dict, Any, Optional

from PySide6.QtCore import QCoreApplication
from model import PDFDocument, BookmarkItem
from utils import sanitize_dest_dict

PROJECT_VERSION = 1
PROJECT_EXTENSION = ".pdfm"


def save_project(
    project_path: str,
    pdf_list: List[PDFDocument],
    output_dir: str,
    output_name: str,
    global_toc: List[BookmarkItem] = None,
) -> None:
    """
    Save the current merge session to a .pdfm JSON file.

    Relative paths are computed relative to the project file's directory
    so that moving a folder of PDFs + project file together preserves
    portability.
    """
    project_dir = os.path.dirname(os.path.abspath(project_path))

    pdf_entries = []
    for pdf in pdf_list:
        entry: Dict[str, Any] = {
            "absolute_path": os.path.abspath(pdf.file_path),
            "relative_path": _safe_relpath(pdf.file_path, project_dir),
            "name": pdf.name,
            "size_kb": pdf.size_kb,
            "modified_dt": pdf.modified_dt.isoformat(),
            "pages": pdf.pages,
        }
        if pdf.custom_toc is not None:
            # Defensively sanitize custom_toc to only include JSON-serializable types
            sanitized_custom_toc = []
            for item in pdf.custom_toc:
                cleaned_item = list(item)
                if len(cleaned_item) >= 4 and isinstance(cleaned_item[3], dict):
                    cleaned_item[3] = sanitize_dest_dict(cleaned_item[3])
                sanitized_custom_toc.append(cleaned_item)
            entry["custom_toc"] = sanitized_custom_toc
        pdf_entries.append(entry)

    # Serialize global_toc
    serialized_toc = []
    if global_toc is not None:
        for bm in global_toc:
            # We reference the source_pdf by its index in the pdf_list
            pdf_idx = -1
            if bm.source_pdf in pdf_list:
                pdf_idx = pdf_list.index(bm.source_pdf)
                
            # Serialize host_pdf by its index in the pdf_list
            host_idx = -1
            if bm.host_pdf is not None and bm.host_pdf in pdf_list:
                host_idx = pdf_list.index(bm.host_pdf)
                
            serialized_toc.append({
                "title": bm.title,
                "page": bm.page,
                "level": bm.level,
                "pdf_index": pdf_idx,
                "host_pdf_index": host_idx,
                "dest": sanitize_dest_dict(bm.dest) if bm.dest else None,
            })

    project_data = {
        "version": PROJECT_VERSION,
        "output_dir_absolute": os.path.abspath(output_dir) if output_dir else "",
        "output_dir_relative": _safe_relpath(output_dir, project_dir) if output_dir else "",
        "output_name": output_name,
        "pdfs": pdf_entries,
        "global_toc": serialized_toc,
    }

    with open(project_path, "w", encoding="utf-8") as f:
        json.dump(project_data, f, indent=2, ensure_ascii=False)


def load_project(
    project_path: str,
) -> Dict[str, Any]:
    """
    Load a .pdfm project file.

    Returns a dict with keys:
        - pdfs: List[PDFDocument]  (with .missing flag set on each)
        - output_dir: str
        - output_name: str
        - missing_files: List[str]  (names of files that could not be found)
        - global_toc: List[BookmarkItem]
    """
    with open(project_path, "r", encoding="utf-8") as f:
        data = json.load(f)

    project_dir = os.path.dirname(os.path.abspath(project_path))

    pdfs: List[PDFDocument] = []
    missing_files: List[str] = []

    for entry in data.get("pdfs", []):
        resolved_path, found = _resolve_path(
            entry.get("absolute_path", ""),
            entry.get("relative_path", ""),
            project_dir,
        )

        modified_dt = _parse_datetime(entry.get("modified_dt", ""))

        pdf = PDFDocument(
            file_path=resolved_path,
            name=entry.get("name", os.path.basename(resolved_path)),
            size_kb=entry.get("size_kb", 0.0),
            modified_dt=modified_dt,
            pages=entry.get("pages", 0),
            custom_toc=entry.get("custom_toc", None),
            missing=not found,
        )

        if not found:
            missing_files.append(pdf.name)

        pdfs.append(pdf)

    # Resolve output directory
    output_dir, _ = _resolve_path(
        data.get("output_dir_absolute", ""),
        data.get("output_dir_relative", ""),
        project_dir,
    )
    # If the output dir doesn't exist, fall back to the project file's directory
    if not os.path.isdir(output_dir):
        output_dir = project_dir

    output_name = data.get("output_name", "")

    global_toc: List[BookmarkItem] = []
    
    # Load global_toc if present (new format)
    if "global_toc" in data:
        for bm_data in data["global_toc"]:
            pdf_idx = bm_data.get("pdf_index", -1)
            if 0 <= pdf_idx < len(pdfs):
                source_pdf = pdfs[pdf_idx]
                
                host_pdf_idx = bm_data.get("host_pdf_index", -1)
                host_pdf = None
                if 0 <= host_pdf_idx < len(pdfs):
                    host_pdf = pdfs[host_pdf_idx]
                    
                bm = BookmarkItem(
                    title=bm_data.get("title", QCoreApplication.translate("project_manager", "Untitled")),
                    page=bm_data.get("page", 1),
                    level=bm_data.get("level", 1),
                    source_pdf=source_pdf,
                    host_pdf=host_pdf,
                    dest=bm_data.get("dest", None)
                )
                global_toc.append(bm)
    else:
        # Legacy format: construct global_toc from individual custom_toc
        for pdf in pdfs:
            if pdf.custom_toc:
                for item in pdf.custom_toc:
                    if len(item) >= 3:
                        lvl, title, page = item[0], item[1], item[2]
                        dest_dict = item[3] if len(item) >= 4 else None
                        global_toc.append(BookmarkItem(title=title, page=page, level=lvl, source_pdf=pdf, dest=dest_dict))
            else:
                global_toc.append(BookmarkItem(title=os.path.splitext(pdf.name)[0], page=1, level=1, source_pdf=pdf))

    return {
        "pdfs": pdfs,
        "output_dir": output_dir,
        "output_name": output_name,
        "missing_files": missing_files,
        "global_toc": global_toc,
    }


def _resolve_path(
    absolute_path: str,
    relative_path: str,
    project_dir: str,
) -> Tuple[str, bool]:
    """
    Try to locate a file using absolute path first, then relative path
    as a fallback. Returns (resolved_path, found_bool).
    """
    # Try absolute path first
    if absolute_path and os.path.exists(absolute_path):
        return absolute_path, True

    # Try relative path
    if relative_path:
        candidate = os.path.normpath(os.path.join(project_dir, relative_path))
        if os.path.exists(candidate):
            return candidate, True

    # Not found — return whichever path we have for display purposes
    return absolute_path or relative_path or "", False


def _safe_relpath(path: str, base: str) -> str:
    """
    Compute a relative path, returning the absolute path as fallback
    if relpath fails (e.g. different drives on Windows).
    """
    try:
        return os.path.relpath(path, base)
    except ValueError:
        return os.path.abspath(path)


def _parse_datetime(dt_str: str) -> datetime:
    """Parse an ISO 8601 datetime string, returning a fallback on failure."""
    if not dt_str:
        return datetime.now()
    try:
        return datetime.fromisoformat(dt_str)
    except (ValueError, TypeError):
        return datetime.now()


def refresh_pdf_metadata(pdf: PDFDocument) -> List[str]:
    """
    Re-read a PDF's file metadata from disk, updating in place.
    Preserves custom_toc. Returns a list of human-readable change descriptions.
    If the file cannot be read, marks it as missing and returns an error message.
    """
    import fitz

    changes: List[str] = []
    file_path = pdf.file_path

    if not os.path.exists(file_path):
        if not pdf.missing:
            pdf.missing = True
            changes.append(QCoreApplication.translate("project_manager", "{0}: file no longer found").format(pdf.name))
        return changes

    doc = None
    try:
        file_stats = os.stat(file_path)
        new_size_kb = file_stats.st_size / 1024.0
        new_modified_dt = datetime.fromtimestamp(file_stats.st_mtime)

        doc = fitz.open(file_path)
        new_pages = doc.page_count
        doc.close()
        doc = None
    except Exception as e:
        pdf.missing = True
        changes.append(QCoreApplication.translate("project_manager", "{0}: error reading file — {1}").format(pdf.name, e))
        return changes
    finally:
        if doc is not None:
            try:
                if not getattr(doc, "is_closed", True):
                    doc.close()
            except Exception:
                pass

    # Compare and collect changes
    if pdf.pages != new_pages:
        changes.append(QCoreApplication.translate("project_manager", "{0}: page count changed ({1} → {2})").format(pdf.name, pdf.pages, new_pages))
    if abs(pdf.size_kb - new_size_kb) > 0.1:
        changes.append(QCoreApplication.translate("project_manager", "{0}: file size changed ({1:.1f} KB → {2:.1f} KB)").format(pdf.name, pdf.size_kb, new_size_kb))
    if pdf.modified_dt != new_modified_dt:
        changes.append(QCoreApplication.translate("project_manager", "{0}: modified date changed").format(pdf.name))

    # Apply updates
    pdf.pages = new_pages
    pdf.size_kb = new_size_kb
    pdf.modified_dt = new_modified_dt
    pdf.missing = False

    return changes


def verify_all_pdf_metadata(pdfs: List[PDFDocument]) -> List[str]:
    """
    Verify metadata for all non-missing PDFs in the list.
    Returns a combined list of change descriptions across all files.
    """
    all_changes: List[str] = []
    for pdf in pdfs:
        if not pdf.missing:
            all_changes.extend(refresh_pdf_metadata(pdf))
    return all_changes

