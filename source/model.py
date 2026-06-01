from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

@dataclass
class PDFDocument:
    file_path: str
    name: str
    size_kb: float
    modified_dt: datetime
    pages: int
    custom_toc: Optional[List] = field(default=None) # Kept for legacy project loading
    missing: bool = field(default=False)

@dataclass
class BookmarkItem:
    title: str
    page: int
    level: int
    source_pdf: PDFDocument
    host_pdf: PDFDocument = None  # Which PDF's tree it's displayed under (None = same as source_pdf)
    dest: Optional[dict] = None  # Stores PyMuPDF destination parameters (sanitized to standard JSON types)

@dataclass
class ProjectState:
    pdfs: List[PDFDocument]
    global_toc: List[BookmarkItem]
    output_dir: str
    output_name: str
    sort_column: int = -1
    sort_order: int = 0 # 0 = Ascending, 1 = Descending
