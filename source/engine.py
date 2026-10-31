import os
import fitz
import traceback
from typing import List, Tuple

from PySide6.QtCore import QCoreApplication
from model import PDFDocument, BookmarkItem
from utils import check_fitz_toc_for_first_page, adjust_toc_pages_and_levels, sanitize_dest_dict

def merge_pdfs_engine(pdf_list: List[PDFDocument], output_path: str, global_toc: List[BookmarkItem] = None) -> Tuple[bool, str]:
    """
    Core engine to merge PDF files.
    Returns (success_bool, message).
    """
    if not pdf_list:
        return False, QCoreApplication.translate("engine", "No PDFs to merge.")

    merged_doc = fitz.open()
    final_toc = []
    current_page_offset = 0
    success_count = 0
    error_files = []
    pdf_offsets = {}

    try:
        for pdf_item in pdf_list:
            pdf_path = pdf_item.file_path
            name = pdf_item.name
            doc_to_add = None
            try:
                # Force a GIL release to ensure the main thread can process UI/paint events smoothly
                import time
                time.sleep(0.01)

                doc_to_add = fitz.open(pdf_path)
                num_pages_in_source = doc_to_add.page_count
                if num_pages_in_source == 0:
                    error_files.append(QCoreApplication.translate("engine", "{0} (no pages)").format(name))
                    doc_to_add.close()
                    continue

                pdf_offsets[id(pdf_item)] = current_page_offset

                # Insert pages
                merged_doc.insert_pdf(
                    doc_to_add,
                    from_page=0,
                    to_page=num_pages_in_source - 1,
                    start_at=current_page_offset,
                )
                doc_to_add.close()
                success_count += 1
                current_page_offset += num_pages_in_source

            except Exception as process_error:
                traceback.print_exc()
                error_files.append(QCoreApplication.translate("engine", "{0} ({1})").format(name, type(process_error).__name__))
                if doc_to_add and not getattr(doc_to_add, "is_closed", True):
                    try:
                        doc_to_add.close()
                    except:
                        pass

        if success_count > 0:
            if global_toc:
                for bm in global_toc:
                    if bm.source_pdf is None:
                        continue
                    # Robust lookup for source_pdf's offset by identity, equality, or file_path comparison
                    offset = pdf_offsets.get(id(bm.source_pdf))
                    if offset is None:
                        for pdf_item in pdf_list:
                            if pdf_item == bm.source_pdf or (bm.source_pdf.file_path and os.path.abspath(pdf_item.file_path) == os.path.abspath(bm.source_pdf.file_path)):
                                offset = pdf_offsets.get(id(pdf_item))
                                break
                                
                    if offset is not None:
                        abs_page = max(1, min(offset + bm.page, merged_doc.page_count))
                        if bm.dest:
                            dest = sanitize_dest_dict(bm.dest)
                            if dest.get("kind") in (fitz.LINK_GOTO, 4):
                                dest["page"] = abs_page - 1
                                if dest.get("kind") == 4:
                                    dest["kind"] = fitz.LINK_GOTO
                            if "to" in dest and isinstance(dest["to"], list) and len(dest["to"]) == 2:
                                dest["to"] = fitz.Point(dest["to"][0], dest["to"][1])
                            elif "to" not in dest or not isinstance(dest["to"], fitz.Point):
                                dest["to"] = fitz.Point(0, 0)
                        else:
                            dest = {
                                "kind": fitz.LINK_GOTO,
                                "page": abs_page - 1,
                                "to": fitz.Point(0, 0),
                                "zoom": 0.0,
                            }
                        final_toc.append([bm.level, bm.title, abs_page, dest])

            if final_toc:
                # Sanitize hierarchy levels to ensure PyMuPDF set_toc() succeeds:
                # 1. First entry must be level 1.
                # 2. Every subsequent entry's level must be <= previous level + 1.
                # 3. Sibling headings with the same level do not stair-step.
                stack = []
                for entry in final_toc:
                    orig_lvl = entry[0]
                    while stack and stack[-1][0] >= orig_lvl:
                        stack.pop()
                    
                    if not stack:
                        mapped_lvl = 1
                    else:
                        mapped_lvl = stack[-1][1] + 1
                        
                    stack.append((orig_lvl, mapped_lvl))
                    entry[0] = mapped_lvl

                try:
                    merged_doc.set_toc(final_toc)
                except Exception as e:
                    traceback.print_exc()

            try:
                merged_doc.save(output_path, garbage=4, deflate=True)
                final_msg = QCoreApplication.translate("engine", "Merged {0} PDF(s) to {1}").format(success_count, output_path)
                if error_files:
                    final_msg += " " + QCoreApplication.translate("engine", "({0} error(s)).").format(len(error_files))
                return True, final_msg
            except Exception as save_error:
                traceback.print_exc()
                return False, QCoreApplication.translate("engine", "ERROR saving merged file: {0}").format(save_error)

        elif error_files:
            return False, QCoreApplication.translate("engine", "Merge failed. {0} file(s) had errors.").format(len(error_files))
        else:
            return False, QCoreApplication.translate("engine", "No valid PDFs were available to merge.")

    except Exception as merge_error:
        traceback.print_exc()
        return False, QCoreApplication.translate("engine", "FATAL Merge Error: {0}").format(merge_error)
    finally:
        if merged_doc is not None:
            try:
                if not getattr(merged_doc, "is_closed", True):
                    merged_doc.close()
            except Exception:
                pass
