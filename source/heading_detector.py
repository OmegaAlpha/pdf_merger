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


DIVISION_WORDS = (
    r'(?:chapter|section|subsection|subsubsection|appendix|appendiks|part|volume|book|'
    r'kapitel|kapittel|kap|seksjon|del|vedlegg|tillegg|avsnitt|underavsnitt|underseksjon|bilaga|'
    r'abschnitt|anhang|teil|band|buch|'
    r'chapitre|annexe|partie|livre|'
    r'capítulo|capitulo|sección|seccion|anexo|apéndice|apendice|volumen|libro|'
    r'capitolo|sezione|appendice|sommario)'
)



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
    word_prefix_match = re.match(r'^' + DIVISION_WORDS + r'\.?\s+([A-Za-z0-9]+(?:\.[0-9]+)*)(?:[\.\)]|\b|\s|$)', text, re.IGNORECASE)
    if word_prefix_match:
        numbering = word_prefix_match.group(1)
        if re.match(valid_prefix_pattern, numbering) and _is_valid_numbering(numbering):
            return numbering

    # 2. Dotted hierarchical numbering: e.g. "1.1", "1.1.1", "A.1.2"
    dotted_match = re.match(r'^([A-Za-z0-9]+(?:\.[0-9]+)+)(?:[\.\)]|\b|\s|$)', text)
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


TOC_KEYWORD_RE = re.compile(
    r'\b(?:table\s+of\s+contents|contents|brief\s+contents|detailed\s+contents|'
    r'indhold|innhold|innholdsfortegnelse|indholdsfortegnelse|inneh[åa]ll|inneh[åa]llsf[öo]rteckning|'
    r'inhaltsverzeichnis|inhalt|table\s+des\s+mati[èe]res|sommaire|'
    r'[ií]ndice(?:\s+general)?|tabla\s+de\s+contenido|sommario|'
    r'spis\s+tre[śs]ci|inhoudsopgave|sis[äa]llysluettelo)\b',
    re.IGNORECASE
)


def _is_running_toc_header(text: str) -> bool:
    t = text.strip()
    cleaned = re.sub(r'^(?:[ivxlcdm]+|\d+)[\s\.\-–—]+|[\s\.\-–—]+(?:[ivxlcdm]+|\d+)$', '', t, flags=re.IGNORECASE).strip()
    return bool(TOC_KEYWORD_RE.search(cleaned)) or cleaned.lower() in [
        'contents', 'table of contents', 'indhold', 'innhold', 'innholdsfortegnelse', 'indholdsfortegnelse', 'inhalt'
    ]


def _find_toc_pages(doc) -> List[int]:
    """Find the 1-based page numbers that contain the Table of Contents."""
    toc_pages = []
    max_search = min(50, doc.page_count)
    first_toc_page = None

    # Pass 1: Keyword-guided search in front matter
    for page_idx in range(max_search):
        page = doc.load_page(page_idx)
        raw_text = page.get_text()
        first_lines = [l.strip() for l in raw_text.split('\n') if l.strip()][:6]
        if any(TOC_KEYWORD_RE.search(l) for l in first_lines):
            first_toc_page = page_idx + 1
            toc_pages.append(first_toc_page)
            break

    # Pass 2: Structural fallback when no keyword is found anywhere
    if first_toc_page is None:
        for page_idx in range(max_search):
            page = doc.load_page(page_idx)
            lines = [l.strip() for l in page.get_text().split('\n') if l.strip()]
            if len(lines) < 5:
                continue
            entries = _extract_toc_entries(doc, [page_idx + 1])
            if len(entries) >= 5 and len(entries) >= len(lines) * 0.20:
                first_toc_page = page_idx + 1
                toc_pages.append(first_toc_page)
                break

    # Check subsequent pages for continuation
    if first_toc_page is not None:
        curr_page = first_toc_page + 1
        while curr_page <= min(max_search + 15, doc.page_count):
            entries = _extract_toc_entries(doc, [curr_page])
            p = doc.load_page(curr_page - 1)
            p_lines = [l.strip() for l in p.get_text().split('\n') if l.strip()]
            total_lines = len(p_lines)
            if len(entries) >= 3 and (total_lines == 0 or len(entries) >= total_lines * 0.20):
                toc_pages.append(curr_page)
                curr_page += 1
            else:
                break

    return toc_pages


def _clean_toc_title(title: str) -> str:
    """Clean spaced dots and raw trailing/leading dots from TOC title."""
    title = title.strip()
    title = re.sub(r'(?:\s*\.\s*){2,}$', '', title).strip()
    title = re.sub(r'^\.*|\.*$', '', title).strip()
    return title


def _extract_toc_entries(doc, toc_pages: List[int]) -> List[Dict]:
    """
    Extract TOC entries (title, page, prefix, level) from the specified TOC pages.
    """
    entries = []
    page_pattern_str = r'(?:[A-Za-z0-9]+[\-–][0-9]+|[0-9]+|[ivxlcdmIVXLCDM]+)'
    page_num_pattern = re.compile(f'^{page_pattern_str}$')
    toc_pg_re = re.compile(
        r'(?:'
        r'(?:\s*\.\s*){2,}'       # dot leader
        r'|\s*,\s*'               # comma
        r'|\s{2,}'                # two or more spaces
        r'|\s+'                   # single space before number
        r')'
        r'(' + page_pattern_str + r')\s*$',
        re.IGNORECASE
    )
    division_pattern = re.compile(r'^' + DIVISION_WORDS + r'\s+\d+', re.IGNORECASE)

    for page_num in toc_pages:
        page = doc.load_page(page_num - 1)
        raw_dict = page.get_text("dict")
        
        # Extract all spans on the page
        spans = []
        for block in raw_dict.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                line_y = line.get("bbox", [0, 0, 0, 0])[1]
                for span in line.get("spans", []):
                    bbox = span.get("bbox", line.get("bbox", [0, 0, 0, 0]))
                    y_pos = span.get("origin", [0, 0])[1] if "origin" in span else bbox[1]
                    if not y_pos:
                        y_pos = line_y
                    clean_text = _clean_ligatures(span.get("text", ""))
                    spans.append({
                        "text": clean_text,
                        "x0": bbox[0],
                        "x1": bbox[2],
                        "y": y_pos,
                    })

        # Group spans by vertical y-band (tolerance 3.0), then sort each line by x0 left-to-right
        spans.sort(key=lambda s: s["y"])
        line_groups = []
        for s in spans:
            placed = False
            for group in line_groups:
                avg_y = sum(item["y"] for item in group) / len(group)
                if abs(s["y"] - avg_y) <= 3.0:
                    group.append(s)
                    placed = True
                    break
            if not placed:
                line_groups.append([s])

        line_groups.sort(key=lambda g: sum(item["y"] for item in g) / len(g))

        lines = []
        for g in line_groups:
            g.sort(key=lambda s: s["x0"])
            merged_text = g[0]["text"]
            curr_x1 = g[0]["x1"]
            for s in g[1:]:
                gap = s["x0"] - curr_x1
                if gap > 2.0 and not merged_text.endswith(" ") and not s["text"].startswith(" "):
                    merged_text += " " + s["text"]
                else:
                    merged_text += s["text"]
                curr_x1 = max(curr_x1, s["x1"])
            merged_text = merged_text.strip()
            if merged_text:
                lines.append({"text": merged_text, "x0": g[0]["x0"], "y": g[0]["y"]})

        i = 0
        while i < len(lines):
            line_data = lines[i]
            token = line_data["text"]
            x0 = line_data["x0"]

            if not token or _is_running_toc_header(token):
                i += 1
                continue

            # Normalize spaced numbers like '2. 7' -> '2.7', '3 .1' -> '3.1'
            token = re.sub(r'(\d+)\s*\.\s*(\d+)', r'\1.\2', token)
            token = re.sub(r'^(CHAPTER|SECTION)\s*([A-Z0-9]+)', r'\1 \2', token, flags=re.IGNORECASE)
            token = re.sub(r'[\-~_=–—\.]{3,}\s*$', '', token).strip()

            # Fix common OCR leading substitution like 'J 2.2.2' -> '12.2.2'
            token = re.sub(r'^[JIjl]\s*(\d+\.\d+)', r'1\1', token)

            # Match trailing page number on single line
            m = toc_pg_re.search(token)
            if m:
                pg_str = m.group(1)
                raw_title = token[:m.start()].strip()
                raw_title = re.sub(r'[\s\.,\-–—]+$', '', raw_title).strip()

                pref = None
                pref_m = re.match(r'^([A-Za-z0-9\.]+)\s+(.*)$', raw_title)
                if pref_m and (_get_numbering_prefix(pref_m.group(1)) is not None or pref_m.group(1).replace('.', '').isdigit()):
                    pref = pref_m.group(1)
                    title = pref_m.group(2)
                else:
                    title = raw_title

                title = _clean_toc_title(title)
                if len(title) >= 2:
                    entries.append({
                        "prefix": pref,
                        "title": title,
                        "page_str": pg_str,
                        "x0": x0
                    })
                i += 1
                continue

            # Multi-line lookahead: current line is title or chapter banner, next line(s) have page number
            combined_text = token
            j = i + 1
            matched_combined = None
            while j < min(i + 4, len(lines)):
                next_t = lines[j]["text"]
                if _is_running_toc_header(next_t):
                    j += 1
                    continue
                next_t = re.sub(r'(\d+)\s*\.\s*(\d+)', r'\1.\2', next_t)
                next_t = re.sub(r'[\-~_=–—\.]{3,}\s*$', '', next_t).strip()

                # If next line looks like a completely new chapter or section starting, stop lookahead
                if re.match(r'^(CHAPTER|SECTION|\d+\.\d+)', next_t, re.IGNORECASE):
                    break

                combined_text += " " + next_t
                m_comb = toc_pg_re.search(combined_text)
                if m_comb:
                    matched_combined = (combined_text, m_comb, j)
                    break
                j += 1

            if matched_combined:
                comb_str, m_comb, end_idx = matched_combined
                pg_str = m_comb.group(1)
                raw_title = comb_str[:m_comb.start()].strip()
                raw_title = re.sub(r'[\s\.,\-–—]+$', '', raw_title).strip()
                raw_title = re.sub(r'^(CHAPTER\s+[A-Za-z0-9]+)\s+', r'\1: ', raw_title, flags=re.IGNORECASE)

                pref = None
                pref_m = re.match(r'^([A-Za-z0-9\.]+)\s+(.*)$', raw_title)
                if pref_m and (_get_numbering_prefix(pref_m.group(1)) is not None or pref_m.group(1).replace('.', '').isdigit()):
                    pref = pref_m.group(1)
                    title = pref_m.group(2)
                else:
                    title = raw_title

                title = _clean_toc_title(title)
                if len(title) >= 2:
                    entries.append({
                        "prefix": pref,
                        "title": title,
                        "page_str": pg_str,
                        "x0": x0
                    })
                i = end_idx + 1
                continue

            # Chapter/division line or section without a page number
            if division_pattern.match(token) or token.strip().lower().startswith("chapter"):
                pref = None
                title_clean = token
                pref_match = re.match(r'^([A-Za-z0-9\.]+)\s+', title_clean)
                if pref_match and _get_numbering_prefix(pref_match.group(1)) is not None:
                    pref = pref_match.group(1)
                    title_clean = title_clean[len(pref):].strip()

                entries.append({
                    "prefix": pref,
                    "title": _clean_toc_title(title_clean),
                    "page_str": None,
                    "x0": x0
                })
                i += 1
                continue

            i += 1

    # Level assignment
    if entries:
        x0_values = sorted(list(set(round(e["x0"], 1) for e in entries)))
        grouped_x0 = []
        for x in x0_values:
            found = False
            for group in grouped_x0:
                if abs(x - group[0]) <= 3.0:
                    group.append(x)
                    found = True
                    break
            if not found:
                grouped_x0.append([x])

        x0_to_level = {}
        for idx, group in enumerate(grouped_x0):
            level = idx + 1
            for val in group:
                x0_to_level[val] = level

        for e in entries:
            t = e["title"]
            if re.match(r'^(CHAPTER|PART)\b', t, re.IGNORECASE):
                e["level"] = 1
            elif e["prefix"]:
                dots = e["prefix"].count('.')
                e["level"] = min(6, dots + 1)
            elif t.lower() in [
                'preface', 'forord', 'foreword', 'contents', 'indhold', 'innhold',
                'index', 'references', 'bibliography', 'appendix'
            ]:
                e["level"] = 1
            else:
                e["level"] = x0_to_level.get(round(e["x0"], 1), 2)

    return entries


def _normalize_title_for_matching(text: str) -> str:
    """Normalize heading titles for lookup matching against TOC."""
    text = text.strip().lower()
    # Remove numbering prefixes at the start
    text = re.sub(r'^(?:[0-9]+(?:\.[0-9]+)*|[a-z](?:\.[0-9]+)*|[ivxlcdm]+(?:\.[0-9]+)*)\s+', '', text)
    # Remove division words at the start
    text = re.sub(r'^' + DIVISION_WORDS + r'\.?\s+', '', text, flags=re.IGNORECASE)
    # Remove all non-alphanumeric characters
    text = re.sub(r'[^a-z0-9]', '', text)
    return text


def _filter_headings_with_toc(headings: List[Dict], toc_entries: List[Dict]) -> List[Dict]:
    """Filter candidates using Table of Contents data to eliminate metadata and noise, and assign levels."""
    if not toc_entries:
        return headings

    toc_by_norm_title = {}
    for entry in toc_entries:
        norm = _normalize_title_for_matching(entry["title"])
        if norm:
            toc_by_norm_title.setdefault(norm, []).append(entry)
            
    toc_by_prefix = {}
    for entry in toc_entries:
        if entry["prefix"]:
            toc_by_prefix.setdefault(entry["prefix"], []).append(entry)

    SPECIAL_UNNUMBERED = {
        "contents", "table of contents", "indhold", "innhold", "innholdsfortegnelse", "indholdsfortegnelse",
        "preface", "foreword", "forord",
        "introduction", "innledning", "introduksjon",
        "conclusion", "konklusjon",
        "references", "bibliography", "litteratur", "bibliografi",
        "index", "indeks", "stikkordregister", "register",
        "acknowledgements", "takk", "anerkjennelse",
        "abstract", "sammendrag", "summary",
        "appendix", "appendiks", "vedlegg", "tillegg",
        "inhaltsverzeichnis", "inhalt", "vorwort", "einleitung", "fazit", "schlussfolgerung", "literaturverzeichnis", "literatur", "index", "anhang",
        "table des matières", "sommaire", "préface", "introduction", "conclusion", "références", "bibliographie", "index", "annexe",
        "índice", "indice", "tabla de contenido", "prólogo", "prologo", "introducción", "introduccion", "conclusión", "conclusion", "referencias", "bibliografía", "bibliografia", "anexo", "apéndice", "apendice",
        "prefazione", "sezione", "bibliografia", "appendice"
    }

    filtered = []
    for h in headings:
        title = h["title"]
        norm_h = _normalize_title_for_matching(title)
        
        matched_entry = None
        if norm_h in toc_by_norm_title:
            matched_entry = toc_by_norm_title[norm_h][0]
            
        if not matched_entry:
            pref_match = re.match(r'^([A-Za-z0-9\.]+)\s+', title)
            pref = pref_match.group(1) if pref_match and _get_numbering_prefix(pref_match.group(1)) else None
            if pref and pref in toc_by_prefix:
                for entry in toc_by_prefix[pref]:
                    norm_entry = _normalize_title_for_matching(entry["title"])
                    if norm_h in norm_entry or norm_entry in norm_h:
                        matched_entry = entry
                        break
                        
        if matched_entry:
            if "level" in matched_entry:
                h["level"] = matched_entry["level"]
            filtered.append(h)
            continue
            
        title_lower = title.lower()
        has_page_num = re.search(r'(^\d+\s+|\s+\d+$)', title)
        if not has_page_num and len(title) <= 60:
            for word in SPECIAL_UNNUMBERED:
                if re.search(r'\b' + re.escape(word) + r'\b', title_lower):
                    # Try to assign level from corresponding entry in TOC if possible
                    for norm, entries in toc_by_norm_title.items():
                        if norm_h in norm or norm in norm_h:
                            if "level" in entries[0]:
                                h["level"] = entries[0]["level"]
                            break
                    filtered.append(h)
                    break
            
    return filtered


def _determine_page_offset(doc, toc_pages: List[int], entries: List[Dict]) -> Optional[int]:
    """Determine the offset between printed TOC page numbers and physical PDF page numbers."""
    if not toc_pages or not entries:
        return None
    last_toc_page = max(toc_pages)
    numeric_entries = [e for e in entries if e.get("page_str") and e["page_str"].isdigit() and int(e["page_str"]) >= 1]
    if len(numeric_entries) < 2:
        return None

    candidate_offsets = {}
    tested = 0
    for e in numeric_entries:
        if tested >= 15:
            break
        target_page = int(e["page_str"])
        tokens = []
        if e.get("prefix"):
            tokens.append(e["prefix"])
        words = [w for w in re.split(r'\W+', e["title"]) if len(w) >= 3]
        if words:
            tokens.append(words[0].lower())
            if len(words) > 1:
                tokens.append(words[1].lower())

        if not tokens:
            continue
        tested += 1

        search_start = last_toc_page
        search_end = min(doc.page_count, last_toc_page + max(target_page + 30, 80))

        for pno in range(search_start, search_end):
            text = _clean_ligatures(doc[pno].get_text()).lower()
            if all(t.lower() in text for t in tokens):
                diff = (pno + 1) - target_page
                if diff >= 0:
                    candidate_offsets[diff] = candidate_offsets.get(diff, 0) + 1
                    break

    if candidate_offsets:
        best_offset = max(candidate_offsets, key=candidate_offsets.get)
        if candidate_offsets[best_offset] >= 2 or (len(numeric_entries) <= 3 and candidate_offsets[best_offset] >= 1):
            return best_offset
    return None


def _build_headings_from_toc(doc, toc_pages: List[int], entries: List[Dict], offset: int) -> List[Dict]:
    """Construct final heading bookmarks directly from parsed TOC entries using page offset."""
    headings = []
    first_toc = toc_pages[0]
    last_toc = max(toc_pages)

    toc_pages_set = set(toc_pages)
    front_matter_pages = {}
    for pno in range(0, min(last_toc + offset + 5, doc.page_count)):
        if (pno + 1) not in toc_pages_set:
            p_text = _clean_ligatures(doc[pno].get_text()).lower()
            front_matter_pages[pno + 1] = p_text

    for e in entries:
        title = e["title"]
        if e.get("prefix") and not title.startswith(e["prefix"]):
            title = f"{e['prefix']} {title}"

        lvl = e.get("level", 1)

        pg_str = e.get("page_str")
        target_page = None
        if pg_str and pg_str.isdigit():
            target_page = int(pg_str) + offset
        elif pg_str:
            t_words = [w.lower() for w in re.split(r'\W+', e["title"]) if len(w) >= 3]
            for p_num, p_text in front_matter_pages.items():
                if t_words and all(w in p_text for w in t_words[:2]):
                    target_page = p_num
                    break
            if target_page is None:
                target_page = first_toc
        else:
            target_page = first_toc

        target_page = max(1, min(doc.page_count, target_page))
        headings.append({
            "title": title,
            "page": target_page,
            "level": lvl
        })
    return headings


def detect_headings(pdf_path: str, max_levels: int = 6) -> List[Dict]:
    """
    Scan a PDF and infer headings using a two-phase approach.

    Algorithm:
        1. Parse the Table of Contents (TOC) if present and determine page offset.
        2. If TOC entries map directly to document pages, generate bookmarks directly.
        3. Otherwise, extract text spans and infer headings by font statistics and TOC cross-referencing.
    """
    doc = fitz.open(pdf_path)
    try:
        toc_pages = _find_toc_pages(doc)
        toc_entries = _extract_toc_entries(doc, toc_pages) if toc_pages else []
        offset = _determine_page_offset(doc, toc_pages, toc_entries)
        if offset is not None and len(toc_entries) >= 5:
            headings = _build_headings_from_toc(doc, toc_pages, toc_entries, offset)
            return headings
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
    filtered_lines = _filter_heading_lines(merged_lines, page_count)

    if not filtered_lines:
        return []

    # Identify TOC pages and filter them out (keep only TOC titles)
    toc_pages_set = set(toc_pages) if 'toc_pages' in locals() else set()

    final_lines = []
    for line in filtered_lines:
        if line["page"] in toc_pages_set:
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
        SPECIAL_UNNUMBERED = {
            "contents", "table of contents", "indhold", "innhold", "innholdsfortegnelse", "indholdsfortegnelse",
            "preface", "foreword", "forord",
            "introduction", "innledning", "introduksjon",
            "conclusion", "konklusjon",
            "references", "bibliography", "litteratur", "bibliografi",
            "index", "indeks", "stikkordregister", "register",
            "acknowledgements", "takk", "anerkjennelse",
            "abstract", "sammendrag", "summary",
            "appendix", "vedlegg", "tillegg"
        }
        
        # Step 1: Sequence DP to clean up outliers
        numbered_indices = []
        prefixes = []
        for i, h in enumerate(headings):
            pref_str = _get_numbering_prefix(h["title"])
            pref_tup = _parse_prefix_to_tuple(pref_str) if pref_str else None
            if pref_tup:
                numbered_indices.append(i)
                prefixes.append(pref_tup)

        n_pref = len(prefixes)
        if n_pref > 0:
            dp = [1] * n_pref
            parent = [-1] * n_pref
            for i in range(n_pref):
                for j in range(i):
                    if _is_valid_sequence_transition(prefixes[j], prefixes[i]):
                        if dp[j] + 1 > dp[i]:
                            dp[i] = dp[j] + 1
                            parent[i] = j

            max_len = max(dp)
            max_idx = dp.index(max_len)

            curr = max_idx
            chosen_indices = []
            while curr != -1:
                chosen_indices.append(curr)
                curr = parent[curr]
            chosen_indices.reverse()

            chosen_set = set(numbered_indices[idx] for idx in chosen_indices)
        else:
            chosen_set = set()

        # Step 2: Keep only numbered headings that are in the chosen subsequence,
        # OR unnumbered headings that are in the SPECIAL_UNNUMBERED list, provided they
        # don't start or end with a number (running headers/footers).
        # However, if the document is only partially numbered (ratio <= 0.80),
        # we don't strictly filter out other unnumbered headings.
        total_numbered_candidates = sum(1 for h in headings if _get_numbering_prefix(h["title"]) is not None)
        numbered_ratio = total_numbered_candidates / len(headings) if headings else 0.0

        filtered_headings = []
        for i, h in enumerate(headings):
            pref_str = _get_numbering_prefix(h["title"])
            if pref_str:
                if i in chosen_set:
                    filtered_headings.append(h)
            else:
                title_lower = h["title"].lower()
                has_page_num = re.search(r'(^\d+\s+|\s+\d+$)', h["title"])
                if not has_page_num:
                    if numbered_ratio > 0.80:
                        if any(word in title_lower for word in SPECIAL_UNNUMBERED):
                            filtered_headings.append(h)
                    else:
                        filtered_headings.append(h)
        headings = filtered_headings
        _assign_levels_by_numbering(headings)
    else:
        _assign_levels_by_style(headings)

    # Apply TOC-based filtering if TOC entries were found
    if 'toc_entries' in locals() and toc_entries:
        headings = _filter_headings_with_toc(headings, toc_entries)

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
# Sequence DP validation helpers
# ---------------------------------------------------------------------------

def _roman_to_int(s: str) -> Optional[int]:
    """Helper to convert a Roman numeral string to an integer."""
    if not s:
        return None
    s = s.upper()
    roman_map = {'I': 1, 'V': 5, 'X': 10, 'L': 50, 'C': 100, 'D': 500, 'M': 1000}
    if not all(c in roman_map for c in s):
        return None
    val = 0
    prev_val = 0
    for char in reversed(s):
        curr_val = roman_map[char]
        if curr_val >= prev_val:
            val += curr_val
        else:
            val -= curr_val
        prev_val = curr_val
    return val if val > 0 else None


def _parse_prefix_to_tuple(prefix: str) -> Optional[Tuple[int, ...]]:
    """Helper to parse a prefix string (e.g. "2.1.3", "A", "IV") into a tuple of integers."""
    if not prefix:
        return None
    parts = prefix.split('.')
    result = []
    for part in parts:
        part = part.strip()
        if not part:
            continue
        if part.isdigit():
            result.append(int(part))
        else:
            # Roman numerals I, V, X represent 1, 5, 10
            if part.upper() in ("I", "V", "X"):
                val = _roman_to_int(part)
                if val is not None:
                    result.append(val)
                else:
                    return None
            elif len(part) == 1 and part.isalpha():
                result.append(ord(part.lower()) - ord('a') + 1)
            else:
                val = _roman_to_int(part)
                if val is not None:
                    result.append(val)
                else:
                    return None
    return tuple(result) if result else None


def _is_valid_sequence_transition(prev_tup: Tuple[int, ...], curr_tup: Tuple[int, ...]) -> bool:
    """
    Check if transitioning from prev_tup to curr_tup is a valid step in a numbered sequence.
    """
    if curr_tup == (1,):
        return True
    p = len(prev_tup)
    q = len(curr_tup)
    
    # Descendant/Child transition
    if q > p and curr_tup[:p] == prev_tup:
        return all(x == 1 for x in curr_tup[p:])
        
    limit = min(p, q)
    diff_idx = -1
    for i in range(limit):
        if curr_tup[i] != prev_tup[i]:
            diff_idx = i
            break
            
    if diff_idx != -1:
        if curr_tup[diff_idx] == prev_tup[diff_idx] + 1:
            return all(x == 1 for x in curr_tup[diff_idx + 1:])
            
    return False


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
    replacements = {
        "\ufb00": "ff",
        "\ufb01": "fi",
        "\ufb02": "fl",
        "\ufb03": "ffi",
        "\ufb04": "ffl",
        "\ufb05": "ft",
        "\ufb06": "st",
        "\x1b": "ff",
        "\x1c": "fi",
        "\x1d": "fl",
        "\x1e": "ffi",
        "\x1f": "ffl",
    }
    for k, v in replacements.items():
        text = text.replace(k, v)
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
                    x_pos = span.get("origin", [0, 0])[0] if "origin" in span else span.get("bbox", [0, 0, 0, 0])[0]
                    x1_pos = span.get("bbox", [0, 0, 0, 0])[2]

                    spans.append({
                        "text": text,
                        "size": font_size,
                        "bold": is_bold,
                        "font": span.get("font", ""),
                        "page": page_idx + 1,  # 1-based
                        "y": round(y_pos, 1),
                        "x0": x_pos,
                        "x1": x1_pos,
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

    if not char_counts or sum(char_counts.values()) == 0:
        return 10.0, False, ""

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


def _filter_heading_lines(lines: List[Dict], total_pages: Optional[int] = None) -> List[Dict]:
    """
    Filter out merged lines that:
        - Are shorter than 3 characters (e.g. solitary bullets, page numbers)
        - Are purely numeric (e.g. page numbers like "42")
        - Have an average word length <= 2.0 (likely math equations or variables)
        - Are Table of Contents entries referencing future pages
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
            if avg_len <= 1.5:
                continue
        else:
            continue

        # TOC line heuristic: ends with a number P where current_page < P <= total_pages
        if total_pages is not None:
            toc_match = re.search(r'\s+(\d+)$', text)
            if toc_match:
                page_val = int(toc_match.group(1))
                if line["page"] < page_val <= total_pages:
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

    # Sort by document order: page, then y-position, then horizontal position x0
    sorted_spans = sorted(spans, key=lambda s: (s["page"], s["y"], s.get("x0", 0.0)))

    lines = []
    current = {
        "text": sorted_spans[0]["text"],
        "page": sorted_spans[0]["page"],
        "y": sorted_spans[0]["y"],
        "size": sorted_spans[0]["size"],
        "bold": sorted_spans[0]["bold"],
        "font": sorted_spans[0].get("font", ""),
        "x0": sorted_spans[0].get("x0", 0.0),
        "x1": sorted_spans[0].get("x1", sorted_spans[0].get("x0", 0.0)),
    }

    Y_TOLERANCE = 2.0  # points — spans within this vertical distance are on the same line

    for span in sorted_spans[1:]:
        same_page = span["page"] == current["page"]
        same_y = abs(span["y"] - current["y"]) < Y_TOLERANCE
        same_style = span["size"] == current["size"] and span["bold"] == current["bold"] and span.get("font", "") == current["font"]

        if same_page and same_y and same_style:
            # Check gap and insert space if needed
            gap = span["x0"] - current["x1"]
            if gap > 2.0 and not current["text"].endswith(" ") and not span["text"].startswith(" "):
                current["text"] += " " + span["text"]
            else:
                current["text"] += span["text"]
            current["x1"] = max(current["x1"], span.get("x1", span["x0"]))
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
                "x0": span.get("x0", 0.0),
                "x1": span.get("x1", span["x0"]),
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

    division_words = (
        r'(?:chapter|section|subsection|subsubsection|appendix|part|volume|book|'
        r'kapitel|kapittel|kap|seksjon|del|vedlegg|tillegg|avsnitt|underavsnitt|underseksjon|bilaga|'
        r'abschnitt|anhang|teil|band|buch|'
        r'chapitre|annexe|partie|livre|'
        r'capítulo|capitulo|sección|seccion|anexo|apéndice|apendice|volumen|libro|'
        r'capitolo|sezione|appendice|sommario)'
    )
    word_prefix_pattern = r'^' + division_words + r'\.?\s+(?:[0-9]+(?:\.[0-9]+)*|[A-Za-z](?:\.[0-9]+)*|[IVXLCDMivxlcdm]+(?:\.[0-9]+)*)$'
    if re.match(word_prefix_pattern, text, re.IGNORECASE):
        return True

    return False


def _merge_multiline_headings(lines: list) -> list:
    """
    Merge consecutive heading lines on the same page if they share the same style
    and are visually close vertically, provided the next line is not itself numbered.
    
    If the first line is only a numbering prefix, we allow merging even if the
    styles differ, keeping the style parameters of the larger line.
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

        if same_page and (same_style or _is_only_prefix(current["text"])) and small_gap and not is_second_numbered:
            current["text"] += " " + next_line["text"]
            if next_line["size"] > current["size"]:
                current["size"] = next_line["size"]
                current["bold"] = next_line["bold"]
                current["font"] = next_line.get("font", "")
            elif next_line["size"] == current["size"]:
                current["bold"] = current["bold"] or next_line["bold"]
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
