import os
import sys
import fitz


def sanitize_dest_dict(dest):
    """
    Sanitize a PyMuPDF destination dictionary for JSON serialization and set_toc().

    - Removes non-serializable keys (xref, parent, id, nameddest, named)
    - Converts fitz.Point / tuple 'to' values to a plain [x, y] list
    - Normalizes kind=4 (LINK_NAMED) to fitz.LINK_GOTO (1)

    Returns a new dict; does not modify the original.
    """
    dest = dest.copy()
    dest.pop("xref", None)
    dest.pop("parent", None)
    dest.pop("id", None)
    dest.pop("nameddest", None)
    dest.pop("named", None)

    if dest.get("kind") == 4:
        dest["kind"] = fitz.LINK_GOTO

    if "to" in dest:
        to_val = dest["to"]
        if hasattr(to_val, "x") and hasattr(to_val, "y"):
            dest["to"] = [to_val.x, to_val.y]
        elif isinstance(to_val, (tuple, list)):
            dest["to"] = list(to_val)

    return dest


def get_source_asset_path(filename):
    """
    Resolve the path to a file in the source/ directory.

    Handles both Nuitka-compiled executables (where assets sit next to
    the .exe under source/) and normal development runs (where __file__
    points at the source directory).
    """
    if "__compiled__" in globals():
        return os.path.join(os.path.dirname(sys.executable), "source", filename)
    return os.path.join(os.path.dirname(__file__), filename)


def check_fitz_toc_for_first_page(toc):
    """Checks a PyMuPDF ToC list for an item pointing to page 1 (1-based index)."""
    if not toc:
        return False
    for item in toc:
        if len(item) >= 3 and isinstance(item[2], int) and item[2] == 1:
            return True
    return False

def adjust_toc_pages_and_levels(toc, page_offset_0based, source_doc, level_increase=0):
    """
    Adjusts page numbers and destination dictionary page indices in a PyMuPDF TOC list.
    Resolves named destinations to explicit destinations and ensures valid entries.
    """
    if not toc:
        return []

    named_dest_dict = source_doc.resolve_names()
    new_toc = []

    for i, item in enumerate(toc):
        if not (isinstance(item, list) and len(item) >= 3):
            continue

        new_item = list(item)
        valid_entry = True

        # Level
        if isinstance(new_item[0], int):
            new_item[0] = max(1, new_item[0] + level_increase)
        else:
            valid_entry = False

        # Title
        if not isinstance(new_item[1], str) or not new_item[1].strip():
            valid_entry = False

        # Page number
        if isinstance(new_item[2], int):
            new_page_1based = new_item[2] + page_offset_0based
            if new_page_1based < 1:
                valid_entry = False
            new_item[2] = new_page_1based
        else:
            valid_entry = False

        # Destination Dictionary
        dest_dict = new_item[3] if len(new_item) > 3 and isinstance(new_item[3], dict) else {}

        if dest_dict.get("kind") == fitz.LINK_NAMED:
            named = dest_dict.get("nameddest") or dest_dict.get("named")
            if named and named in named_dest_dict:
                resolved_dest = named_dest_dict[named]
                if resolved_dest and "page" in resolved_dest:
                    original_page_0based = resolved_dest["page"]
                    new_dest_page_0based = original_page_0based + page_offset_0based
                    if new_dest_page_0based < 0:
                        valid_entry = False
                    else:
                        raw_to = resolved_dest.get("to")
                        to_point = fitz.Point(0, 0)
                        if raw_to:
                            try:
                                page_height = source_doc[original_page_0based].rect.height
                                if hasattr(raw_to, "x") and hasattr(raw_to, "y"):
                                    to_x = raw_to.x
                                    to_y = raw_to.y
                                else:
                                    to_x = raw_to[0]
                                    to_y = raw_to[1]
                                # Convert from bottom-left PDF space to top-left PyMuPDF space
                                to_point = fitz.Point(to_x, page_height - to_y)
                            except Exception:
                                to_point = fitz.Point(0, 0)

                        new_dest_dict = {
                            "kind": fitz.LINK_GOTO,
                            "page": new_dest_page_0based,
                            "to": to_point,
                            "zoom": resolved_dest.get("zoom", 0.0),
                        }
                        for key in resolved_dest:
                            if key not in ["kind", "page", "to", "zoom"]:
                                new_dest_dict[key] = resolved_dest[key]
                        new_item[3] = new_dest_dict
                        new_item[2] = new_dest_page_0based + 1
                else:
                    valid_entry = False
            elif "page" in dest_dict and isinstance(dest_dict["page"], str):
                try:
                    original_page_0based = int(dest_dict["page"]) - 1
                    new_dest_page_0based = original_page_0based + page_offset_0based
                    if new_dest_page_0based < 0:
                        valid_entry = False
                    else:
                        new_dest_dict = {
                            "kind": fitz.LINK_GOTO,
                            "page": new_dest_page_0based,
                            "to": fitz.Point(0, 0),
                            "zoom": dest_dict.get("zoom", 0.0),
                        }
                        for key in dest_dict:
                            if key not in ["kind", "page", "to", "zoom"]:
                                new_dest_dict[key] = dest_dict[key]
                        new_item[3] = new_dest_dict
                        new_item[2] = new_dest_page_0based + 1
                except ValueError:
                    valid_entry = False
            else:
                valid_entry = False

        elif dest_dict.get("kind") == fitz.LINK_GOTO:
            original_page_0based = dest_dict.get("page", item[2] - 1)
            if isinstance(original_page_0based, int):
                new_dest_page_0based = original_page_0based + page_offset_0based
                if new_dest_page_0based < 0:
                    valid_entry = False
                else:
                    new_dest_dict = {
                        "kind": fitz.LINK_GOTO,
                        "page": new_dest_page_0based,
                        "to": dest_dict.get("to", fitz.Point(0, 0)),
                        "zoom": dest_dict.get("zoom", 0.0),
                    }
                    for key in dest_dict:
                        if key not in ["kind", "page", "to", "zoom"]:
                            new_dest_dict[key] = dest_dict[key]
                    new_item[3] = new_dest_dict
                    new_item[2] = new_dest_page_0based + 1
            else:
                valid_entry = False

        else:
            # Default
            original_page_0based = item[2] - 1
            new_dest_page_0based = original_page_0based + page_offset_0based
            if new_dest_page_0based < 0:
                valid_entry = False
            else:
                new_dest_dict = {
                    "kind": fitz.LINK_GOTO,
                    "page": new_dest_page_0based,
                    "to": fitz.Point(0, 0),
                    "zoom": 0.0,
                }
                if len(new_item) > 3:
                    new_item[3] = new_dest_dict
                else:
                    new_item.append(new_dest_dict)
                new_item[2] = new_dest_page_0based + 1

        if valid_entry:
            new_toc.append(new_item)

    return new_toc
