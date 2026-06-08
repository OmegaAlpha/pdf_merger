"""
Heading detector for PDFs.

Scans a PDF using PyMuPDF, extracts text spans with font metadata,
and uses a two-phase approach to infer a hierarchical heading structure:

    Phase 1 — Check if heading candidates use a numbering scheme
              (e.g. "1.", "1.1", "Chapter 2").  If yes, the numbering
              pattern drives the hierarchy.
    Phase 2 — If no numbering scheme is found, fall back to pure
              font-size / bold statistical ranking.
"""

import fitz
import re
from collections import Counter
from typing import List, Dict, Tuple, Optional


def _is_valid_numbering(num_str: str) -> bool:
    """Helper to check if a numbering prefix string is valid (e.g. not a year)."""
    if num_str.isdigit():
        if int(num_str) > 100:
            return False
    return True


def _get_numbering_prefix(text: str) -> Optional[str]:
    """
    Extract the numbering prefix (e.g. "1.1", "1", "A", "I") from the heading text,
    ignoring any leading word (e.g. "Chapter 1" -> "1").
    """
    text = text.strip()
    if not text:
        return None

    # Valid numbering pattern validator
    # Matches digits, dotted digits, single letters, roman numerals, or letters followed by dotted digits
    valid_prefix_pattern = r'^(?:[0-9]+(?:\.[0-9]+)*|[A-Za-z](?:\.[0-9]+)*|[IVXLCDMivxlcdm]+(?:\.[0-9]+)*)$'

    # 1. Word followed by a number/dotted-number: e.g. "Chapter 1", "Section 1.1", "Kap. 2", "Vedlegg A"
    word_prefix_match = re.match(r'^[A-Za-z]+\.?\s+([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)(?:[\.\)]|\b|\s|$)', text)
    if word_prefix_match:
        numbering = word_prefix_match.group(1)
        if re.match(valid_prefix_pattern, numbering) and _is_valid_numbering(numbering):
            return numbering

    # 2. Dotted hierarchical numbering: e.g. "1.1", "1.1.1", "A.1.2"
    dotted_match = re.match(r'^([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)+)(?:[\.\)]|\b|\s|$)', text)
    if dotted_match:
        numbering = dotted_match.group(1)
        if re.match(valid_prefix_pattern, numbering) and _is_valid_numbering(numbering):
            return numbering

    # 3. Single level numbering: e.g. "1.", "A.", "I.", "1)"
    single_match = re.match(r'^([0-9]+|[A-Za-z]{1,4})(?:[\.\)])(?:\s|$)', text)
    if single_match:
        numbering = single_match.group(1)
        if re.match(valid_prefix_pattern, numbering) and _is_valid_numbering(numbering):
            return numbering

    # 4. Bare number followed by space(s) and an uppercase letter (e.g. "1 Introduction")
    bare_num_match = re.match(r'^([0-9]+)\s+[A-Z]', text)
    if bare_num_match:
        numbering = bare_num_match.group(1)
        if _is_valid_numbering(numbering):
            return numbering

    return None


def get_numbering_level(text: str) -> Optional[int]:
    """
    Extract the hierarchy level from heading text if it has a numbering prefix.

    Supports:
        - "Chapter 1", "Section 1", "Subsection 1"
        - "1.1", "1.1.1", "A.1.2" (hierarchical dotted numbering)
        - "1.", "A.", "I.", "1)" (single-level numbering)
        - "1 Introduction" (bare number + space + uppercase word)
    """
    prefix = _get_numbering_prefix(text)
    if prefix is None:
        return None
        
    parts = prefix.split('.')
    return len(parts)


def detect_headings(pdf_path: str, max_levels: int = 6) -> List[Dict]:
    """
    Scan a PDF and infer headings using a two-phase approach.

    Algorithm:
        1. Extract every text span with (font_size, is_bold, text, page, y_pos).
        2. Identify the "body" font size as the size carrying the most characters.
        3. Keep spans matching candidate heading styles (larger or bold body size).
        4. Remove repeated headers/footers.
        5. Merge adjacent same-style spans on the same line.
        6. Filter out short or purely numeric lines (page numbers).
        7. Build a font-size/style level map.
        8. Two-phase level assignment:
           a. If the document uses a numbering scheme (>= 40% of heading candidates
              have number prefixes), use numbering as the primary hierarchy signal.
           b. Otherwise, use font-size/bold ranking exclusively.
        9. Sanitize levels (no jumps > 1, no stair-steps).
    """
    doc = fitz.open(pdf_path)
    try:
        spans = _extract_spans(doc)
        page_count = doc.page_count
    finally:
        doc.close()

    if not spans:
        return []

    body_size, body_is_bold, body_font = _identify_body_style(spans)

    # Identify "large headings" (size > body_size)
    large_headings = []
    for s in spans:
        if s["size"] > body_size:
            text = s["text"].strip()
            if len(text) >= 3 and not text.isdigit():
                large_headings.append(text.lower())
    large_headings_set = set(large_headings)

    # Build heading_fonts set
    heading_fonts = set()

    # Add fonts used for size > body_size, excluding math/italic/symbols
    for s in spans:
        if s["size"] > body_size and s["font"] != body_font:
            text = s["text"].strip()
            if len(text) >= 3 and not text.isdigit():
                font_lower = s["font"].lower()
                if not any(x in font_lower for x in ["italic", "oblique", "math", "symbol", "cmsy", "cmmi", "cmex"]):
                    heading_fonts.add(s["font"])

    # Add fonts at body_size that match large heading texts (TOC/cross-reference)
    for s in spans:
        if s["size"] == body_size and s["font"] != body_font:
            text = s["text"].strip().lower()
            if text in large_headings_set and len(text) >= 4:
                heading_fonts.add(s["font"])

    heading_spans = _filter_heading_spans(spans, body_size, body_is_bold, body_font, heading_fonts)

    if not heading_spans:
        return []

    heading_spans = _remove_repeated_headers_footers(heading_spans, page_count)
    if not heading_spans:
        return []

    lines = _merge_spans_into_lines(heading_spans)
    merged_lines = _merge_multiline_headings(lines)
    filtered_lines = _filter_heading_lines(merged_lines)

    if not filtered_lines:
        return []

    # Identify TOC pages and filter them out (keep only TOC titles)
    toc_pages = set()
    for line in filtered_lines:
        t_lower = line["text"].strip().lower()
        if t_lower in ["indhold", "contents", "table of contents", "innhold", "innholdsfortegnelse", "indholdsfortegnelse"]:
            toc_pages.add(line["page"])

    final_lines = []
    for line in filtered_lines:
        if line["page"] in toc_pages:
            t_lower = line["text"].strip().lower()
            if t_lower in ["indhold", "contents", "table of contents", "innhold", "innholdsfortegnelse", "indholdsfortegnelse"]:
                final_lines.append(line)
        else:
            final_lines.append(line)

    if not final_lines:
        return []

    level_map = _build_level_map(final_lines, max_levels)

    headings = []
    for line in final_lines:
        style_key = (line["size"], line["bold"], line.get("font", ""))
        style_lvl = level_map.get(style_key, max_levels)
        num_lvl = get_numbering_level(line["text"])
        
        headings.append({
            "title": line["text"],
            "page": line["page"],
            "style_lvl": style_lvl,
            "num_lvl": num_lvl,
            "level": 1, # placeholder
        })

    # Two-phase level assignment:
    # Phase 1: Check if the document uses a numbering scheme.
    # Phase 2: Assign levels accordingly.
    has_numbering = _has_numbering_scheme(final_lines)

    if has_numbering:
        # When the document uses numbered headings, unnumbered entries at the
        # weakest (highest-number) style level are almost always noise:
        # bold body text, table headers, figure captions, etc.  Remove them
        # so the bookmark tree stays clean.
        # Only filter out if the weakest style level is deep/weak enough (e.g. style_lvl > 2)
        # to avoid filtering out valid section headings in simple/short documents.
        if level_map:
            weakest_style_lvl = max(level_map.values())
            if weakest_style_lvl > 2:
                headings = [
                    h for h in headings
                    if h["num_lvl"] is not None or h["style_lvl"] < weakest_style_lvl
                ]
        _assign_levels_by_numbering(headings)
    else:
        _assign_levels_by_style(headings)

    # Nest under document title logic
    if headings:
        # 1. Find the page of the first content heading
        first_content_page = None
        for h in headings:
            is_numbered = h["num_lvl"] is not None
            is_special = h["title"].strip().lower() in [
                "indhold", "contents", "table of contents", "innhold",
                "innholdsfortegnelse", "indholdsfortegnelse", "forord", "preface"
            ]
            if is_numbered or is_special:
                first_content_page = h["page"]
                break

        # 2. If first content page is > 1, we treat page 1 as a title page
        if first_content_page is not None and first_content_page > 1:
            # Find the first heading on page 1
            first_pg1_idx = None
            for idx, h in enumerate(headings):
                if h["page"] == 1:
                    first_pg1_idx = idx
                    break

            if first_pg1_idx is not None:
                new_headings = []
                doc_title_item = headings[first_pg1_idx]
                doc_title_item["level"] = 1

                for idx, h in enumerate(headings):
                    if h["page"] == 1:
                        if idx == first_pg1_idx:
                            new_headings.append(doc_title_item)
                    else:
                        h["level"] = h["level"] + 1
                        new_headings.append(h)
                headings = new_headings

    return headings


# ---------------------------------------------------------------------------
# Level-assignment strategies
# ---------------------------------------------------------------------------

def _has_numbering_scheme(lines: List[Dict]) -> bool:
    """
    Check whether heading candidates predominantly use a numbering scheme.

    Returns True if:
        - At least 40% of the heading lines (and at least 2) have a number prefix, OR
        - There is a substantial number of numbered headings (>= 5) making up at least 15% of candidate lines.
    """
    if not lines:
        return False
    numbered_count = sum(1 for line in lines if get_numbering_level(line["text"]) is not None)
    return (numbered_count >= max(2, len(lines) * 0.4)) or (numbered_count >= 5 and numbered_count >= len(lines) * 0.15)


def _is_restart_start_token(text: str) -> bool:
    """
    Check if the heading text starts with a numbering prefix that represents a restart
    (e.g., starts with "1", "A", or Roman numeral "I").
    """
    prefix = _get_numbering_prefix(text)
    if not prefix:
        return False
        
    first_part = prefix.split('.')[0].upper()
    return first_part in ("1", "A", "I")


def _assign_levels_by_numbering(headings: List[Dict]) -> None:
    """
    Assign heading levels primarily from the numbering prefix.

    Numbered headings (e.g. "1.1", "Chapter 2") get their level directly
    from the number pattern.  Unnumbered headings that appear inside a
    numbered document are placed as children/siblings of the most recent heading
    based on style levels.

    A stack is used to track ancestry:
    (num_lvl, mapped_level, style_lvl, level_offset, page)
    """
    stack: List[Tuple[Optional[int], int, int, int, int]] = []  # (num_lvl, mapped_level, style_lvl, level_offset, page)

    for h in headings:
        num_lvl = h["num_lvl"]
        style_lvl = h["style_lvl"]
        page = h["page"]

        # Pop unnumbered page 1 elements (like title page titles/subtitles)
        # once we transition to page 2 or later, since nothing on page 2+
        # is subordinate to them.
        if page > 1:
            stack = [x for x in stack if not (x[4] == 1 and x[0] is None)]

        # Pop stack entries that have a strictly weaker font style (larger style_lvl) than h
        while stack and stack[-1][2] > style_lvl:
            stack.pop()

        if num_lvl is not None:
            # Numbered heading — decide if it's nested
            if stack:
                top_num_lvl, top_mapped_lvl, top_style_lvl, top_offset, _ = stack[-1]
                # If h has same/higher numbering index (lower num_lvl) but strictly weaker font style,
                # it's a nested numbering hierarchy (e.g. sections starting at "1." under Appendix 2).
                # We only transition to a nested hierarchy if the heading represents a sequence restart
                # (starts with 1, A, or I).
                if num_lvl <= (top_num_lvl or 1) and style_lvl > top_style_lvl and _is_restart_start_token(h["title"]):
                    active_offset = top_mapped_lvl
                else:
                    active_offset = top_offset
            else:
                active_offset = 0

            mapped_lvl = num_lvl + active_offset

            # Pop stack entries with mapped_lvl >= candidate mapped_lvl
            while stack and stack[-1][1] >= mapped_lvl:
                stack.pop()

            stack.append((num_lvl, mapped_lvl, style_lvl, active_offset, page))
        else:
            # Unnumbered heading
            if not stack:
                mapped_lvl = 1
                active_offset = 0
            else:
                top_num_lvl, top_mapped_lvl, top_style_lvl, top_offset, _ = stack[-1]
                if style_lvl == top_style_lvl:
                    # Same style level -> sibling. Pop stack top to replace it as active sibling.
                    mapped_lvl = top_mapped_lvl
                    active_offset = top_offset
                    stack.pop()
                else:
                    # Weaker style level -> child.
                    mapped_lvl = top_mapped_lvl + 1
                    active_offset = top_offset

            stack.append((None, mapped_lvl, style_lvl, active_offset, page))

        h["level"] = mapped_lvl


def _assign_levels_by_style(headings: List[Dict]) -> None:
    """
    Assign heading levels using font-size / bold ranking only.

    The ``style_lvl`` (derived from the font-size level map) is treated as a
    comparable priority: lower number = higher importance.  A stack-based
    compressor ensures sibling headings share the same level and no level
    jumps by more than 1.
    """
    stack: List[Tuple[int, int]] = []  # list of (style_lvl, page) on the stack

    for h in headings:
        style_lvl = h["style_lvl"]
        page = h["page"]
        t_lower = h["title"].strip().lower()
        is_special = t_lower in ["indhold", "contents", "table of contents", "innhold", "innholdsfortegnelse", "indholdsfortegnelse", "litteratur", "references", "bibliografi", "forord"]

        # Pop page 1 elements if we are on page 2+
        if page > 1:
            stack = [x for x in stack if x[1] > 1]

        # Pop entries that are at the same or lower priority (>= style_lvl)
        while stack and stack[-1][0] >= style_lvl:
            stack.pop()

        mapped_lvl = len(stack) + 1
        
        # Only push onto stack if it is NOT a special heading
        if not is_special:
            stack.append((style_lvl, page))
            
        h["level"] = mapped_lvl


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _clean_ligatures(text: str) -> str:
    """Replace TeX/OT1 ligature control characters with their corresponding character pairs."""
    text = text.replace("\x1b", "ff")
    text = text.replace("\x1c", "fi")
    text = text.replace("\x1d", "fl")
    text = text.replace("\x1e", "ffi")
    text = text.replace("\x1f", "ffl")
    return text


def _extract_spans(doc) -> List[Dict]:
    """Extract all text spans from every page, recording font metadata."""
    spans = []
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        raw_dict = page.get_text("rawdict")

        for block in raw_dict.get("blocks", []):
            if block.get("type") != 0:  # skip image blocks
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    chars = span.get("chars", [])
                    text = "".join(c.get("c", "") for c in chars)
                    text = _clean_ligatures(text)
                    text = text.strip()
                    if not text:
                        continue

                    font_size = round(span.get("size", 0), 1)
                    flags = span.get("flags", 0)
                    is_bold = bool(flags & (1 << 4))  # bit 4 = bold in PyMuPDF

                    # y-position: use the origin y of the span for ordering
                    y_pos = span.get("origin", [0, 0])[1] if "origin" in span else span.get("bbox", [0, 0, 0, 0])[1]

                    spans.append({
                        "text": text,
                        "size": font_size,
                        "bold": is_bold,
                        "font": span.get("font", ""),
                        "page": page_idx + 1,  # 1-based
                        "y": round(y_pos, 1),
                    })
    return spans


def _identify_body_style(spans: List[Dict]) -> Tuple[float, bool, str]:
    """
    Identify the dominant "body text" font size and font name.

    The body size is defined as the font size that carries the most total
    characters across the document.  The bold flag for body text is determined
    by which variant (bold vs non-bold) carries more characters at that size.
    The body font is the font name carrying the most characters at body_size.
    """
    char_counts: Counter = Counter()
    for span in spans:
        char_counts[span["size"]] += len(span["text"])

    body_size = char_counts.most_common(1)[0][0]

    # Determine if the dominant variant at body_size is bold or not
    bold_chars = sum(len(s["text"]) for s in spans if s["size"] == body_size and s["bold"])
    non_bold_chars = sum(len(s["text"]) for s in spans if s["size"] == body_size and not s["bold"])
    body_is_bold = bold_chars > non_bold_chars

    # Determine the body font name
    body_fonts_at_size = Counter()
    for s in spans:
        if s["size"] == body_size and "font" in s:
            body_fonts_at_size[s["font"]] += len(s["text"])
    body_font = body_fonts_at_size.most_common(1)[0][0] if body_fonts_at_size else ""

    return body_size, body_is_bold, body_font


def _filter_heading_spans(spans: List[Dict], body_size: float, body_is_bold: bool, body_font: str, heading_fonts: set) -> List[Dict]:
    """
    Keep only spans that qualify as heading candidates based on style and font.

    A span is a heading candidate if:
        - Its font size is strictly larger than body_size, OR
        - Its font size equals body_size, it is bold, and body text is not bold, OR
        - Its font size equals body_size, its font is different from body_font, and its font is in heading_fonts.
    """
    candidates = []
    for span in spans:
        is_heading_size = (span["size"] > body_size and (span.get("font") == body_font or span.get("font") in heading_fonts))
        is_bold_heading = (span["size"] == body_size and span["bold"] and not body_is_bold)
        is_alt_heading_font = (span["size"] == body_size and span.get("font") != body_font and span.get("font") in heading_fonts)

        if is_heading_size or is_bold_heading or is_alt_heading_font:
            candidates.append(span)

    return candidates


def _filter_heading_lines(lines: List[Dict]) -> List[Dict]:
    """
    Filter out merged lines that:
        - Are shorter than 3 characters (e.g. solitary bullets, page numbers)
        - Are purely numeric (e.g. page numbers like "42")
        - Have an average word length <= 2.0 (likely math equations or variables)
    """
    filtered = []
    for line in lines:
        text = line["text"].strip()
        if len(text) < 3:
            continue
        stripped = text.replace("-", "").replace(".", "").replace(",", "").strip()
        if stripped.isdigit():
            continue

        # Calculate average word length (ignoring numbers and punctuation)
        word_lens = [sum(1 for c in w if c.isalpha()) for w in text.split()]
        word_lens = [l for l in word_lens if l > 0]
        if word_lens:
            avg_len = sum(word_lens) / len(word_lens)
            if avg_len <= 2.0:
                continue
        else:
            continue

        filtered.append(line)
    return filtered


def _remove_repeated_headers_footers(spans: List[Dict], page_count: int) -> List[Dict]:
    """
    Remove text that appears identically on many pages (likely headers/footers).

    If the same text appears on more than 40% of pages, it's probably a
    running header or footer and should be excluded.
    """
    if page_count < 3:
        return spans

    threshold = max(2, page_count * 0.4)

    # Count on how many distinct pages each text appears
    text_pages: Dict[str, set] = {}
    for span in spans:
        key = span["text"].strip().lower()
        if key not in text_pages:
            text_pages[key] = set()
        text_pages[key].add(span["page"])

    repeated = {text for text, pages in text_pages.items() if len(pages) >= threshold}

    return [s for s in spans if s["text"].strip().lower() not in repeated]


def _merge_spans_into_lines(spans: List[Dict]) -> List[Dict]:
    """
    Merge consecutive spans that belong to the same visual line.

    Spans on the same page, at the same y-position, and with the same font
    size / bold flag / font name are concatenated into a single heading line.
    """
    if not spans:
        return []

    # Sort by document order: page, then y-position
    sorted_spans = sorted(spans, key=lambda s: (s["page"], s["y"]))

    lines = []
    current = {
        "text": sorted_spans[0]["text"],
        "page": sorted_spans[0]["page"],
        "y": sorted_spans[0]["y"],
        "size": sorted_spans[0]["size"],
        "bold": sorted_spans[0]["bold"],
        "font": sorted_spans[0].get("font", ""),
    }

    Y_TOLERANCE = 2.0  # points — spans within this vertical distance are on the same line

    for span in sorted_spans[1:]:
        same_page = span["page"] == current["page"]
        same_y = abs(span["y"] - current["y"]) < Y_TOLERANCE
        same_style = span["size"] == current["size"] and span["bold"] == current["bold"] and span.get("font", "") == current["font"]

        if same_page and same_y and same_style:
            # Merge: append text
            current["text"] += " " + span["text"]
        else:
            # Flush previous line
            current["text"] = current["text"].strip()
            if current["text"]:
                lines.append(current)
            current = {
                "text": span["text"],
                "page": span["page"],
                "y": span["y"],
                "size": span["size"],
                "bold": span["bold"],
                "font": span.get("font", ""),
            }

    # Flush last line
    current["text"] = current["text"].strip()
    if current["text"]:
        lines.append(current)

    return lines


def _is_only_prefix(text: str) -> bool:
    """
    Check if the text represents only a heading numbering prefix
    (e.g., "1", "1.1", "Kapitel 1", "Chapter A") with no other content.
    """
    text = text.strip()
    text = re.sub(r'[\.\:\-\)\s]+$', '', text)

    valid_prefix_pattern = r'^(?:[0-9]+(?:\.[0-9]+)*|[A-Za-z](?:\.[0-9]+)*|[IVXLCDMivxlcdm]+(?:\.[0-9]+)*)$'
    if re.match(valid_prefix_pattern, text):
        return True

    word_prefix_pattern = r'^[A-Za-z]+\.?\s+(?:[0-9]+(?:\.[0-9]+)*|[A-Za-z](?:\.[0-9]+)*|[IVXLCDMivxlcdm]+(?:\.[0-9]+)*)$'
    if re.match(word_prefix_pattern, text):
        return True

    return False


def _merge_multiline_headings(lines: list) -> list:
    """
    Merge consecutive heading lines on the same page if they share the same style
    and are visually close vertically, provided the next line is not itself numbered.
    """
    if not lines:
        return []

    merged = []
    current = lines[0].copy()
    last_y = current["y"]

    is_first_heading_on_page = True
    current_page = current["page"]

    for next_line in lines[1:]:
        same_page = next_line["page"] == current["page"]
        if not same_page:
            is_first_heading_on_page = True
            current_page = next_line["page"]

        same_style = (next_line["size"] == current["size"] and
                      next_line["bold"] == current["bold"] and
                      next_line.get("font", "") == current.get("font", ""))

        vertical_gap = next_line["y"] - last_y

        # If current line is only a prefix, allow a larger gap to the title.
        # Otherwise, require a tight wrap spacing.
        if _is_only_prefix(current["text"]):
            small_gap = vertical_gap < current["size"] * 3.0
        else:
            # Allow a larger gap on the front page (page 1) for the first heading block (the title)
            # because titles are often large and have more generous leading.
            mult = 2.0 if (current["page"] == 1 and is_first_heading_on_page) else 1.4
            small_gap = vertical_gap < current["size"] * mult

        # Second line must not start with a numbering prefix
        is_second_numbered = get_numbering_level(next_line["text"]) is not None

        if same_page and same_style and small_gap and not is_second_numbered:
            current["text"] += " " + next_line["text"]
            last_y = next_line["y"]
        else:
            merged.append(current)
            current = next_line.copy()
            last_y = current["y"]
            if same_page:
                is_first_heading_on_page = False

    merged.append(current)
    return merged



def _build_level_map(lines: List[Dict], max_levels: int) -> Dict[Tuple[float, bool, str], int]:
    """
    Build a mapping from (font_size, is_bold, font_name) → heading level.

    Sorting order (highest priority = level 1):
        1. Larger font size first.
        2. At the same font size, bold before non-bold.
        3. If same size and bold status, differentiate by font name.

    Only the top `max_levels` distinct style keys are assigned levels.
    """
    # Collect unique style keys
    style_keys = set()
    for line in lines:
        style_keys.add((line["size"], line["bold"], line.get("font", "")))

    # Sort: larger size first, then bold before non-bold, then font name alphabetically
    sorted_keys = sorted(style_keys, key=lambda k: (-k[0], not k[1], k[2]))

    level_map = {}
    for i, key in enumerate(sorted_keys):
        if i >= max_levels:
            break
        level_map[key] = i + 1

    return level_map
