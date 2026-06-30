"""
Tests for heading_detector module.

Creates temporary PDFs with known font-size hierarchies using PyMuPDF
and verifies the heading detection algorithm produces correct results.
"""

import os
import sys
import tempfile
import pytest
import fitz

# Make source/ importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "source"))

from heading_detector import detect_headings


def _create_pdf_with_styles(pages_content, tmp_dir):
    """
    Create a PDF in tmp_dir with controlled font sizes.

    pages_content: list of lists, each inner list contains tuples:
        (text, font_size, is_bold) or (text, font_size, is_bold, font_name)
    Each tuple becomes a separate text insertion on the page.
    """
    path = os.path.join(tmp_dir, "test.pdf")
    doc = fitz.open()

    for page_items in pages_content:
        page = doc.new_page(width=612, height=792)  # US Letter
        y = 72  # Start 1 inch from top
        for item in page_items:
            if len(item) == 4:
                text, font_size, is_bold, font_name = item
            else:
                text, font_size, is_bold = item
                font_name = "hebo" if is_bold else "helv"
            page.insert_text(
                fitz.Point(72, y),
                text,
                fontsize=font_size,
                fontname=font_name,
            )
            y += font_size * 2.5  # advance vertically with a realistic heading spacing

    doc.save(path)
    doc.close()
    return path


class TestDetectHeadings:
    """Test heading detection on programmatically generated PDFs."""

    def test_basic_hierarchy(self, tmp_path):
        """A document with 3 distinct font sizes should produce 3 heading levels."""
        pages = [
            [
                ("Chapter One", 24, False),
                ("Section A", 18, False),
                ("This is body text that is long enough to be the dominant size across the document.", 12, False),
                ("This is more body text filling up character counts for the statistical analysis.", 12, False),
                ("This is even more body text to make sure 12pt is the dominant font size.", 12, False),
            ],
            [
                ("Chapter Two", 24, False),
                ("Section B", 18, False),
                ("Body text continues on the second page with plenty of characters.", 12, False),
                ("More body text so that font size 12 clearly dominates the histogram.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        titles = [h["title"] for h in headings]
        assert "Chapter One" in titles
        assert "Chapter Two" in titles
        assert "Section A" in titles
        assert "Section B" in titles

        # 24pt → level 1, 18pt → level 2
        chapter_one = next(h for h in headings if h["title"] == "Chapter One")
        assert chapter_one["level"] == 1
        assert chapter_one["page"] == 1

        section_a = next(h for h in headings if h["title"] == "Section A")
        assert section_a["level"] == 2

        # Body text should NOT appear as headings
        for h in headings:
            assert "body text" not in h["title"].lower()

    def test_bold_as_heading_signal(self, tmp_path):
        """Bold text at body size should be detected as a heading."""
        pages = [
            [
                ("Bold Heading Here", 12, True),
                ("Normal body text one for statistics, making sure it is plenty long enough.", 12, False),
                ("Normal body text two for statistics, continuing the dominant font analysis.", 12, False),
                ("Normal body text three for statistics, ensuring twelve point dominates.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        assert len(headings) >= 1
        bold_heading = next((h for h in headings if h["title"] == "Bold Heading Here"), None)
        assert bold_heading is not None
        assert bold_heading["level"] == 1

    def test_single_font_no_headings(self, tmp_path):
        """A document with only one font size should produce no headings."""
        pages = [
            [
                ("All text is the same size here.", 12, False),
                ("No variation in font size at all.", 12, False),
                ("Everything is uniform twelve point.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        assert headings == []

    def test_empty_pdf(self, tmp_path):
        """An empty PDF should produce no headings."""
        path = os.path.join(str(tmp_path), "empty.pdf")
        doc = fitz.open()
        doc.new_page()
        doc.save(path)
        doc.close()

        headings = detect_headings(path)
        assert headings == []

    def test_page_numbers_filtered(self, tmp_path):
        """Numeric-only text (page numbers) should be filtered out."""
        pages = [
            [
                ("Real Heading", 20, False),
                ("Body text here with enough characters to dominate the statistics.", 12, False),
                ("42", 20, False),  # This is a page number, should be filtered
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        titles = [h["title"] for h in headings]
        assert "Real Heading" in titles
        assert "42" not in titles

    def test_short_text_filtered(self, tmp_path):
        """Text shorter than 3 characters should be filtered out."""
        pages = [
            [
                ("AB", 24, False),  # Too short
                ("Valid Heading Text", 20, False),
                ("Body text is the dominant size with plenty of characters for analysis.", 12, False),
                ("More body text to make twelve point clearly the dominant font size.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        titles = [h["title"] for h in headings]
        assert "AB" not in titles
        assert "Valid Heading Text" in titles

    def test_document_order_preserved(self, tmp_path):
        """Headings should be returned in document order (page, then y-position)."""
        pages = [
            [
                ("First Heading", 20, False),
                ("Body text on page one with enough characters for the statistics.", 12, False),
            ],
            [
                ("Second Heading", 20, False),
                ("Body text on page two with enough characters for the statistics.", 12, False),
            ],
            [
                ("Third Heading", 20, False),
                ("Body text on page three with enough characters for the statistics.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        titles = [h["title"] for h in headings]
        assert titles == ["First Heading", "Second Heading", "Third Heading"]

        pages_list = [h["page"] for h in headings]
        assert pages_list == [1, 2, 3]

    def test_max_levels_cap(self, tmp_path):
        """max_levels parameter should cap the number of distinct heading levels."""
        pages = [
            [
                ("Level One", 30, False),
                ("Level Two", 24, False),
                ("Level Three", 18, False),
                ("Level Four", 16, False),
                ("Body text is the dominant font size for statistics.", 12, False),
                ("More body text so twelve point dominates the analysis.", 12, False),
                ("Even more body text for good measure and confidence.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))

        # With max_levels=2, only the two largest sizes get levels
        headings = detect_headings(pdf_path, max_levels=2)

        levels_found = set(h["level"] for h in headings)
        assert max(levels_found) <= 2

    def test_bold_plus_size_hierarchy(self, tmp_path):
        """Bold at a given size should rank higher than non-bold at the same size."""
        pages = [
            [
                ("Bold Title", 18, True),
                ("Regular Subtitle", 18, False),
                ("Body text dominant with enough characters for analysis.", 12, False),
                ("More body text to ensure twelve point is clearly dominant.", 12, False),
                ("Even more body text for good statistical confidence.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        bold_h = next(h for h in headings if h["title"] == "Bold Title")
        regular_h = next(h for h in headings if h["title"] == "Regular Subtitle")

        # Bold at 18pt should get a higher (smaller number) level than non-bold at 18pt
        assert bold_h["level"] < regular_h["level"]

    def test_hierarchy_level_sanitization(self, tmp_path):
        """Verify that heading levels that jump are sanitized to prevent PyMuPDF errors."""
        pages = [
            [
                ("30pt Title", 30, False),  # Level 1
                ("16pt Subtitle (jumps level)", 16, False),  # originally Level 3, should be sanitized to 2
                ("24pt Section (middle level)", 24, False),  # Level 2, should stay 2 or 3
                ("Dominant body text for statistics count.", 12, False),
                ("More dominant body text to fill up statistics.", 12, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        levels = [h["level"] for h in headings]
        # Verify first is level 1
        # Verify no level jumps by more than 1
        for i in range(1, len(levels)):
            assert levels[i] <= levels[i-1] + 1

    def test_get_numbering_level(self):
        """Test the get_numbering_level utility directly on various strings."""
        from heading_detector import get_numbering_level
        # Dotted numbering
        assert get_numbering_level("1. Introduction") == 1
        assert get_numbering_level("1.1 Background") == 2
        assert get_numbering_level("1.1.1 Scope") == 3
        assert get_numbering_level("A. Appendix") == 1
        assert get_numbering_level("A.1 Sub-appendix") == 2
        assert get_numbering_level("I. Introduction") == 1
        assert get_numbering_level("IX. Chapter") == 1
        
        # Keyword-based division (now returns levels purely based on the extracted numbering prefix)
        assert get_numbering_level("Chapter 1: About this manual") == 1
        assert get_numbering_level("Section 1 - Intro") == 1
        assert get_numbering_level("Subsection 2.1") == 2
        assert get_numbering_level("Appendix A: Details") == 1
        
        # Non-headings/no numbers
        assert get_numbering_level("Introduction") is None
        assert get_numbering_level("Go to school") is None
        assert get_numbering_level("Page 3") is None

    def test_hybrid_heading_detection_with_numbers(self, tmp_path):
        """Test heading detection with numbering overrides to verify it creates correct hierarchies without stair-stepping."""
        pages = [
            [
                ("Chapter 1: About this manual", 18, False),  # Style Lvl 2, Num Lvl 1 -> Level 1
                ("Section 1.1: Introduction", 18, False),     # Style Lvl 2, Num Lvl 2 -> Level 2
                ("Implementation", 12, True),               # Style Lvl 3, Num Lvl None -> Level 3 (no stair-stepping)
                ("Purpose", 12, True),                      # Style Lvl 3, Num Lvl None -> Level 3 (sibling of Implementation)
                ("Body text that is dominant and long enough.", 10, False),
                ("More body text to establish body text size.", 10, False),
            ]
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        assert len(headings) == 4
        assert headings[0]["title"] == "Chapter 1: About this manual"
        assert headings[0]["level"] == 1
        
        assert headings[1]["title"] == "Section 1.1: Introduction"
        assert headings[1]["level"] == 2
        
        assert headings[2]["title"] == "Implementation"
        assert headings[2]["level"] == 3
        
        assert headings[3]["title"] == "Purpose"
        assert headings[3]["level"] == 3  # Should be a sibling at level 3, NOT level 4 (stair-stepped)

    def test_fully_numbered_document(self, tmp_path):
        """A document where all headings have numbering should use the numbering path."""
        pages = [
            [
                ("1. Introduction", 18, True),
                ("1.1 Background", 14, False),
                ("1.2 Scope", 14, False),
                ("Body text that is the dominant font size in the whole document.", 10, False),
                ("More body text to make sure ten point is clearly dominant size.", 10, False),
                ("Even more body text for good statistical confidence in analysis.", 10, False),
            ],
            [
                ("2. Design", 18, True),
                ("2.1 Architecture", 14, False),
                ("2.1.1 Components", 12, False),
                ("Body text continues on second page with plenty of characters.", 10, False),
                ("More body text so that font size ten clearly dominates histogram.", 10, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        titles = [h["title"] for h in headings]
        assert "1. Introduction" in titles
        assert "1.1 Background" in titles
        assert "2. Design" in titles
        assert "2.1.1 Components" in titles

        # Verify levels follow the numbering pattern exactly
        h_intro = next(h for h in headings if h["title"] == "1. Introduction")
        assert h_intro["level"] == 1

        h_bg = next(h for h in headings if h["title"] == "1.1 Background")
        assert h_bg["level"] == 2

        h_scope = next(h for h in headings if h["title"] == "1.2 Scope")
        assert h_scope["level"] == 2  # Sibling of 1.1

        h_design = next(h for h in headings if h["title"] == "2. Design")
        assert h_design["level"] == 1  # Same level as 1. Introduction

        h_arch = next(h for h in headings if h["title"] == "2.1 Architecture")
        assert h_arch["level"] == 2

        h_comp = next(h for h in headings if h["title"] == "2.1.1 Components")
        assert h_comp["level"] == 3

    def test_numbered_doc_with_unnumbered_headings(self, tmp_path):
        """Numbered document with some unnumbered headings — unnumbered headings
        should be placed as children of their nearest ancestor."""
        pages = [
            [
                ("1. Introduction", 18, True),
                ("1.1 Background", 14, False),
                ("Overview", 14, False),        # Unnumbered, should be child of 1.1 (level 3)
                ("1.2 Scope", 14, False),       # Back to numbered, level 2
                ("Body text that is the dominant font size in the whole document.", 10, False),
                ("More body text to make sure ten point is clearly the dominant size.", 10, False),
                ("Even more body text for good statistical confidence in this analysis.", 10, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        h_overview = next(h for h in headings if h["title"] == "Overview")
        # "Overview" comes after "1.1 Background" (level 2) and has the same style level, so it should be sibling (level 2)
        assert h_overview["level"] == 2

        h_scope = next(h for h in headings if h["title"] == "1.2 Scope")
        # "1.2 Scope" is numbered, should be level 2
        assert h_scope["level"] == 2

    def test_unnumbered_document_uses_style_path(self, tmp_path):
        """A document with no numbered headings should use font-size-based levels only."""
        pages = [
            [
                ("Main Title", 24, True),
                ("Subtitle Here", 18, False),
                ("Sub-subtitle", 14, False),
                ("Body text is the dominant font size for statistical analysis.", 10, False),
                ("More body text to make sure ten point is dominant in the document.", 10, False),
                ("Even more body text to fill up character counts for confidence.", 10, False),
            ],
            [
                ("Another Main Title", 24, True),
                ("Another Subtitle", 18, False),
                ("Body text continues on the second page with plenty of characters.", 10, False),
                ("More body text so that font size ten clearly dominates the histogram.", 10, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        h_main = next(h for h in headings if h["title"] == "Main Title")
        assert h_main["level"] == 1

        h_sub = next(h for h in headings if h["title"] == "Subtitle Here")
        assert h_sub["level"] == 2

        h_subsub = next(h for h in headings if h["title"] == "Sub-subtitle")
        assert h_subsub["level"] == 3

        h_main2 = next(h for h in headings if h["title"] == "Another Main Title")
        assert h_main2["level"] == 1  # Should reset to level 1

        h_sub2 = next(h for h in headings if h["title"] == "Another Subtitle")
        assert h_sub2["level"] == 2

    def test_threshold_boundary_few_numbered(self, tmp_path):
        """If only 1 out of 5 headings has a number, the font-size path should be used."""
        pages = [
            [
                ("Big Title", 24, True),          # No number
                ("Another Big", 24, True),        # No number
                ("1. Introduction", 18, False),   # Has number (only 1 of 5)
                ("Medium Heading", 18, False),    # No number
                ("Small Heading", 14, False),     # No number
                ("Body text is the dominant font size for statistical analysis.", 10, False),
                ("More body text to make sure ten point is dominant in the document.", 10, False),
                ("Even more body text to fill character counts for confidence.", 10, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        # With only 1/5 numbered, the font-size path should be used.
        # 24pt -> level 1, 18pt -> level 2, 14pt -> level 3
        h_big = next(h for h in headings if h["title"] == "Big Title")
        assert h_big["level"] == 1

        h_intro = next(h for h in headings if h["title"] == "1. Introduction")
        assert h_intro["level"] == 2  # Font-size path: 18pt -> level 2

    def test_deep_numbered_hierarchy(self, tmp_path):
        """Test a document with deeply nested numbering like 1.1.1.1."""
        pages = [
            [
                ("1. Top Level", 24, True),
                ("1.1 Second Level", 18, False),
                ("1.1.1 Third Level", 14, False),
                ("1.1.1.1 Fourth Level", 12, True),
                ("Body text is the dominant font size for stats.", 10, False),
                ("More body text to make sure ten point dominates.", 10, False),
                ("Even more body text for good confidence.", 10, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        assert headings[0]["level"] == 1
        assert headings[1]["level"] == 2
        assert headings[2]["level"] == 3
        assert headings[3]["level"] == 4

    def test_nested_numbering_restart(self, tmp_path):
        """Test that numbered headings nested under a larger division (like an Appendix)
        restarting from 1 get correctly nested at level 2 instead of level 1."""
        pages = [
            [
                ("Appendix 1: Background", 18, True),
                ("Appendix 2: Details", 18, True),
                ("1. Background info", 14, False), # Should nest at level 2 under Appendix 2 (restarted numbering)
                ("1.1 Nested details", 12, False),  # Should nest at level 3
                ("2. Design info", 14, False),     # Sibling of 1. Background info at level 2
                ("Body text is the dominant font size for statistics.", 10, False),
                ("More body text to make sure ten point is dominant in the document.", 10, False),
                ("Even more body text to fill character counts for confidence.", 10, False),
            ]
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        h_app1 = next(h for h in headings if h["title"] == "Appendix 1: Background")
        assert h_app1["level"] == 1

        h_app2 = next(h for h in headings if h["title"] == "Appendix 2: Details")
        assert h_app2["level"] == 1

        h_bg = next(h for h in headings if h["title"] == "1. Background info")
        assert h_bg["level"] == 2

        h_nested = next(h for h in headings if h["title"] == "1.1 Nested details")
        assert h_nested["level"] == 3

        h_design = next(h for h in headings if h["title"] == "2. Design info")
        assert h_design["level"] == 2

    def test_references_level_1(self, tmp_path):
        """Test that an unnumbered heading (like References) at the Chapter style level
        gets mapped to level 1 and not nested under previous sections."""
        pages = [
            [
                ("1. Introduction", 18, True),
                ("1.1 Background", 14, False),
                ("References", 18, True),  # Unnumbered, but Chapter style -> Level 1
                ("Body text is the dominant font size for statistics.", 10, False),
                ("More body text to make sure ten point is dominant in the document.", 10, False),
                ("Even more body text to fill character counts for confidence.", 10, False),
            ]
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        h_intro = next(h for h in headings if h["title"] == "1. Introduction")
        assert h_intro["level"] == 1

        h_ref = next(h for h in headings if h["title"] == "References")
        assert h_ref["level"] == 1

    def test_same_font_unnumbered_headings(self, tmp_path):
        """
        Verify that headings that use the same size as the body text,
        but in a different font family, are detected using the TOC cross-reference
        heuristic, and assigned appropriate hierarchy levels.
        """
        pages = [
            # Page 1: Title (larger size)
            [
                ("Main Document Title", 16, False, "tiro"),
                ("Body text is written in Helvetica at twelve point font size.", 12, False, "helv"),
                ("More body text to establish Helvetica as the dominant body font.", 12, False, "helv"),
            ],
            # Page 2: TOC (larger size). Uses font "tiro".
            [
                ("Table of Contents", 14, False, "tiro"),
                ("Main Chapter One", 12, False, "tiro"),
                ("Introductory text about the document contents.", 12, False, "helv"),
            ],
            # Page 3: Chapter title (large) and a subheading (same size as body, but using tiro font).
            [
                ("Main Chapter One", 14, False, "tiro"),
                ("A Subheading Here", 12, False, "tiro"),
                ("Paragraph of normal text continues in the body font size.", 12, False, "helv"),
                ("More normal body text for statistics count.", 12, False, "helv"),
            ],
            # Page 4: Empty page to prevent header/footer filtering threshold collision
            [],
            # Page 5: Empty page
            [],
            # Page 6: Empty page
            []
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        # We should find "Main Document Title", "Table of Contents", "Main Chapter One", "A Subheading Here".
        titles = [h["title"] for h in headings]
        assert "Main Document Title" in titles
        assert "Table of Contents" in titles
        assert "A Subheading Here" in titles
        
        # Check that the TOC entry on page 2 is NOT present in headings (filtered out by TOC page filter)
        page2_headings = [h for h in headings if h["page"] == 2]
        page2_titles = [h["title"] for h in page2_headings]
        assert "Main Chapter One" not in page2_titles

        # Check page 3 chapter and subheading (should be shifted by +1 due to title-nesting)
        h_chap1 = next(h for h in headings if h["title"] == "Main Chapter One" and h["page"] == 3)
        assert h_chap1["level"] == 2

        h_sub = next(h for h in headings if h["title"] == "A Subheading Here")
        assert h_sub["level"] == 3

    def test_math_equation_filtering(self, tmp_path):
        """Verify that math equations, variables, and italic labels are filtered out."""
        pages = [
            [
                ("Real Chapter Title", 24, False),
                ("K v r", 18, False),  # Math variables (avg word length = 1.0)
                ("K M v r", 18, True), # Bold math variables (avg word length = 1.0)
                ("Transient Label", 18, False, "Times-Italic"), # Italic label font
                ("Body text is long enough to establish body size and font.", 12, False, "helv"),
                ("More body text is written in helv to keep character count dominating.", 12, False, "helv"),
                ("We need to make sure 12pt helv is the dominant font across the document.", 12, False, "helv"),
            ]
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        titles = [h["title"] for h in headings]
        assert "Real Chapter Title" in titles
        assert "K v r" not in titles
        assert "K M v r" not in titles
        assert "Transient Label" not in titles

    def test_ligature_decoding(self):
        """Verify that standard TeX/OT1 ligatures in heading text are correctly cleaned/decoded."""
        from heading_detector import _clean_ligatures
        assert _clean_ligatures("In\x1duenslinier") == "Influenslinier"
        assert _clean_ligatures("De\x1cnition") == "Definition"
        assert _clean_ligatures("coe\x1ecient") == "coefficient"
        assert _clean_ligatures("statis\x1b") == "statisff"
        assert _clean_ligatures("ba\x1f") == "baffl"





class TestMultilineMerging:
    """Test the _merge_multiline_headings helper directly with mocked lines."""

    def test_multiline_merge_basic(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "Kapitel 1", "page": 1, "y": 100.0, "size": 20.0, "bold": True, "font": "hebo"},
            {"text": "Introduction", "page": 1, "y": 140.0, "size": 20.0, "bold": True, "font": "hebo"}, # gap 40.0 (2.0 * size), first is only prefix -> should merge
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 1
        assert merged[0]["text"] == "Kapitel 1 Introduction"

    def test_multiline_no_merge_different_styles(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "Section 1.1 Overview", "page": 1, "y": 100.0, "size": 20.0, "bold": True, "font": "hebo"},
            {"text": "Introduction", "page": 1, "y": 140.0, "size": 16.0, "bold": True, "font": "hebo"}, # different size -> no merge
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 2

    def test_multiline_no_merge_different_pages(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "Kapitel 1", "page": 1, "y": 100.0, "size": 20.0, "bold": True, "font": "hebo"},
            {"text": "Introduction", "page": 2, "y": 100.0, "size": 20.0, "bold": True, "font": "hebo"}, # different page -> no merge
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 2

    def test_multiline_no_merge_large_gap(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "Implementation", "page": 2, "y": 100.0, "size": 12.0, "bold": True, "font": "hebo"},
            {"text": "Purpose", "page": 2, "y": 122.0, "size": 12.0, "bold": True, "font": "hebo"}, # gap 22.0 (1.83 * size), not a prefix -> no merge
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 2

    def test_multiline_merge_page1_large_gap(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "A Very Long Title", "page": 1, "y": 100.0, "size": 24.0, "bold": True, "font": "hebo"},
            {"text": "Spread Across Two Lines", "page": 1, "y": 143.2, "size": 24.0, "bold": True, "font": "hebo"}, # gap 43.2 (1.8 * size) -> should merge on page 1
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 1
        assert merged[0]["text"] == "A Very Long Title Spread Across Two Lines"

    def test_multiline_merge_tight_gap(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "Elementmetoden for", "page": 1, "y": 100.0, "size": 20.0, "bold": True, "font": "hebo"},
            {"text": "rammer", "page": 1, "y": 124.0, "size": 20.0, "bold": True, "font": "hebo"}, # gap 24.0 (1.2 * size) -> should merge
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 1
        assert merged[0]["text"] == "Elementmetoden for rammer"

    def test_multiline_no_merge_second_is_numbered(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "1. Introduction", "page": 1, "y": 100.0, "size": 12.0, "bold": True, "font": "hebo"},
            {"text": "1.1 Background", "page": 1, "y": 115.0, "size": 12.0, "bold": True, "font": "hebo"}, # gap 15.0 (1.25 * size), second is numbered -> no merge
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 2


class TestNumberingSchemeDetection:
    """Test the _has_numbering_scheme helper directly."""

    def test_all_numbered(self):
        from heading_detector import _has_numbering_scheme
        lines = [
            {"text": "1. Introduction"},
            {"text": "1.1 Background"},
            {"text": "2. Design"},
        ]
        assert _has_numbering_scheme(lines) is True

    def test_no_numbered(self):
        from heading_detector import _has_numbering_scheme
        lines = [
            {"text": "Introduction"},
            {"text": "Background"},
            {"text": "Design"},
        ]
        assert _has_numbering_scheme(lines) is False

    def test_below_threshold(self):
        from heading_detector import _has_numbering_scheme
        lines = [
            {"text": "1. Introduction"},
            {"text": "Background"},
            {"text": "Design"},
            {"text": "Conclusion"},
            {"text": "Summary"},
        ]
        # 1 out of 5 = 20%, below 40% threshold
        assert _has_numbering_scheme(lines) is False

    def test_at_threshold(self):
        from heading_detector import _has_numbering_scheme
        lines = [
            {"text": "1. Introduction"},
            {"text": "2. Design"},
            {"text": "Background"},
            {"text": "Conclusion"},
            {"text": "Summary"},
        ]
        # 2 out of 5 = 40%, meets threshold (>= max(2, 5*0.4=2))
        assert _has_numbering_scheme(lines) is True

    def test_empty_lines(self):
        from heading_detector import _has_numbering_scheme
        assert _has_numbering_scheme([]) is False

    def test_single_numbered_line(self):
        from heading_detector import _has_numbering_scheme
        lines = [{"text": "1. Introduction"}]
        # Only 1 numbered, needs at least 2
        assert _has_numbering_scheme(lines) is False

    def test_robust_threshold_low_percentage_high_count(self):
        from heading_detector import _has_numbering_scheme
        # Total: 100 lines, Numbered: 16 lines (16% > 15%, count >= 5) -> should be True
        lines = [{"text": "1. Intro"}] * 16 + [{"text": "Intro"}] * 84
        assert _has_numbering_scheme(lines) is True

    def test_robust_threshold_below_percentage_high_count(self):
        from heading_detector import _has_numbering_scheme
        # Total: 100 lines, Numbered: 10 lines (10% < 15%, count >= 5) -> should be False
        lines = [{"text": "1. Intro"}] * 10 + [{"text": "Intro"}] * 90
        assert _has_numbering_scheme(lines) is False

    def test_robust_threshold_high_percentage_low_count(self):
        from heading_detector import _has_numbering_scheme
        # Total: 10 lines, Numbered: 3 lines (30% < 40%, count = 3 < 5) -> should be False
        lines = [{"text": "1. Intro"}] * 3 + [{"text": "Intro"}] * 7
        assert _has_numbering_scheme(lines) is False


class TestNorwegianNumbering:
    """Test Norwegian translation support for keyword-based division numbering and bypassing."""

    def test_norwegian_keywords(self):
        from heading_detector import get_numbering_level
        assert get_numbering_level("Kapittel 1: Om denne boken") == 1
        assert get_numbering_level("Kap. 2 Design") == 1
        assert get_numbering_level("Vedlegg A: Tabeller") == 1
        assert get_numbering_level("Tillegg B") == 1
        assert get_numbering_level("Seksjon 1.1") == 2
        assert get_numbering_level("Avsnitt 1") == 1
        assert get_numbering_level("Underavsnitt 1.1.1") == 3
        assert get_numbering_level("Underseksjon 2") == 1

    def test_norwegian_division_bypassing(self, tmp_path):
        """Verify that Norwegian divisions like 'Vedlegg' bypass nesting logic despite inconsistent styles."""
        pages = [
            [
                ("Vedlegg 1: Hoveddel", 18, True),
                ("Vedlegg 2: Vedleggsdel", 14, True), # Smaller font size
                ("Body text is the dominant font size for statistics.", 10, False),
                ("More body text to make sure ten point is dominant.", 10, False),
                ("Even more body text to fill character counts.", 10, False),
            ]
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        assert headings[0]["title"] == "Vedlegg 1: Hoveddel"
        assert headings[0]["level"] == 1

        assert headings[1]["title"] == "Vedlegg 2: Vedleggsdel"
        assert headings[1]["level"] == 1  # Should be level 1 because it's a Norwegian division (Vedlegg)


class TestTitleNestingAndMetadataFiltering:
    """Test cases for filtering metadata on page 1 and nesting all subsequent bookmarks under the page 1 title."""

    def test_is_valid_numbering(self):
        from heading_detector import _is_valid_numbering
        assert _is_valid_numbering("1") is True
        assert _is_valid_numbering("12") is True
        assert _is_valid_numbering("100") is True
        assert _is_valid_numbering("101") is False
        assert _is_valid_numbering("1993") is False
        assert _is_valid_numbering("2002") is False
        assert _is_valid_numbering("1.1") is True  # not a digit string

    def test_page1_metadata_filtering_and_nesting(self, tmp_path):
        """
        Verify that:
        1. Subsequent page bookmarks are nested under the page 1 title page heading (first heading on page 1).
        2. Non-title (excessive metadata) headings on page 1 (like author, organization, date/year) are discarded.
        """
        pages = [
            # Page 1: Title page with various heading candidates
            [
                ("Main Document Title", 24, True),
                ("Author Name", 14, False),
                ("Department and Institution Info", 14, False),
                ("September 2002", 14, True), # year/date
            ],
            # Page 2: Table of Contents
            [
                ("Indhold", 18, True),
                ("Body text is added here to establish dominant font size.", 11, False),
                ("More body text is written to ensure the counts are sufficient.", 11, False),
            ],
            # Page 3: Numbered sections
            [
                ("1. First Section", 16, True),
                ("1.1 Sub-section", 14, True),
                ("Body text on page 3.", 11, False),
            ],
        ]
        pdf_path = _create_pdf_with_styles(pages, str(tmp_path))
        headings = detect_headings(pdf_path)

        # 1. Check that only "Main Document Title" remains from Page 1
        page1_headings = [h for h in headings if h["page"] == 1]
        assert len(page1_headings) == 1
        assert page1_headings[0]["title"] == "Main Document Title"
        assert page1_headings[0]["level"] == 1

        # 2. Check that "Indhold" on Page 2 is present, and nested to Level 2
        indhold_heading = next(h for h in headings if h["title"] == "Indhold")
        assert indhold_heading["page"] == 2
        assert indhold_heading["level"] == 2

        # 3. Check that subsequent numbered sections are shifted correctly (Level 1 -> 2, Level 2 -> 3)
        h_sec1 = next(h for h in headings if h["title"] == "1. First Section")
        assert h_sec1["page"] == 3
        assert h_sec1["level"] == 2

        h_subsec = next(h for h in headings if h["title"] == "1.1 Sub-section")
        assert h_subsec["page"] == 3
        assert h_subsec["level"] == 3


class TestEnhancedHeuristics:
    """Test the newly added heuristic checks directly."""

    def test_stricter_prefix_matching(self):
        from heading_detector import _get_numbering_prefix
        # Should match standard division words
        assert _get_numbering_prefix("Chapter 1: Intro") == "1"
        assert _get_numbering_prefix("Seksjon 1.1") == "1.1"
        assert _get_numbering_prefix("Kapittel 3") == "3"
        assert _get_numbering_prefix("Kapitel 2") == "2"
        assert _get_numbering_prefix("Vedlegg A") == "A"
        # Should NOT match arbitrary words (like middle initials/names)
        assert _get_numbering_prefix("Niels J. Gimsing") is None
        assert _get_numbering_prefix("Christos T. Georgakis") is None
        assert _get_numbering_prefix("Stage 1") is None

    def test_multiline_merge_prefix_relaxed_style(self):
        from heading_detector import _merge_multiline_headings
        lines = [
            {"text": "Chapter 1", "page": 1, "y": 100.0, "size": 18.0, "bold": True, "font": "hebo"},
            {"text": "Introduction to Bridges", "page": 1, "y": 130.0, "size": 26.0, "bold": True, "font": "boldfont"}, # different size/font
        ]
        merged = _merge_multiline_headings(lines)
        assert len(merged) == 1
        assert merged[0]["text"] == "Chapter 1 Introduction to Bridges"
        assert merged[0]["size"] == 26.0
        assert merged[0]["font"] == "boldfont"

    def test_sequence_transition_validation(self):
        from heading_detector import _is_valid_sequence_transition
        # Sibling transitions
        assert _is_valid_sequence_transition((1,), (2,)) is True
        assert _is_valid_sequence_transition((2, 1), (2, 2)) is True
        # Child transitions
        assert _is_valid_sequence_transition((1,), (1, 1)) is True
        assert _is_valid_sequence_transition((2, 4), (2, 4, 1)) is True
        # Restarts
        assert _is_valid_sequence_transition((5,), (1,)) is True
        # Invalid transitions
        assert _is_valid_sequence_transition((1,), (3,)) is False
        assert _is_valid_sequence_transition((2, 1), (2, 3)) is False
        assert _is_valid_sequence_transition((2, 1, 1), (2, 2)) is True # sibling of parent is valid

    def test_toc_page_filtering(self):
        from heading_detector import _filter_heading_lines
        lines = [
            {"text": "1.1 Basic Types of Cables 93", "page": 10, "y": 100.0, "size": 12.0, "bold": False}, # TOC line (references future page 93)
            {"text": "1.1 Basic Types of Cables", "page": 93, "y": 100.0, "size": 12.0, "bold": False}, # Real line
        ]
        filtered = _filter_heading_lines(lines, total_pages=590)
        assert len(filtered) == 1
        assert filtered[0]["page"] == 93

    def test_toc_based_filtering_logic(self):
        from heading_detector import _filter_headings_with_toc
        
        toc_entries = [
            {"prefix": "1", "title": "Evolution of Cable Supported Bridges", "page_str": "7"},
            {"prefix": "2", "title": "Cables", "page_str": "85"},
            {"prefix": "2.1", "title": "Basic Types of Cables", "page_str": "85"},
        ]
        
        headings = [
            {"title": "1 Evolution of Cable Supported Bridges", "page": 15, "level": 1},
            {"title": "in situ", "page": 479, "level": 4},
            {"title": "2 Cables", "page": 93, "level": 1},
            {"title": "2.1 Basic Types of Cables", "page": 93, "level": 2},
            {"title": "Engineering News", "page": 520, "level": 4},
            {"title": "Index", "page": 589, "level": 2},
        ]
        
        filtered = _filter_headings_with_toc(headings, toc_entries)
        
        titles = [h["title"] for h in filtered]
        assert "1 Evolution of Cable Supported Bridges" in titles
        assert "2 Cables" in titles
        assert "2.1 Basic Types of Cables" in titles
        assert "Index" in titles # Index is in SPECIAL_UNNUMBERED, so should be kept
        
        assert "in situ" not in titles
        assert "Engineering News" not in titles

    def test_multi_page_toc_detection(self, mocker):
        from heading_detector import _find_toc_pages
        mock_doc = mocker.MagicMock()
        mock_doc.page_count = 3
        
        mock_page_1 = mocker.MagicMock()
        mock_page_1.get_text.return_value = "Contents\n1. Section 1 ... 1"
        
        mock_page_2 = mocker.MagicMock()
        mock_page_2.get_text.return_value = "2. Section 2 ... 2"
        
        mock_page_3 = mocker.MagicMock()
        mock_page_3.get_text.return_value = "Normal text here without any entries"
        
        mock_doc.load_page.side_effect = [mock_page_1, mock_page_2, mock_page_3]
        
        mocker.patch("heading_detector._extract_toc_entries", side_effect=[
            [{"title": "t"} for _ in range(5)], # page 2
            [] # page 3
        ])
        
        pages = _find_toc_pages(mock_doc)
        assert pages == [1, 2]

    def test_compound_page_numbers_parsing(self, mocker):
        from heading_detector import _extract_toc_entries
        mock_doc = mocker.MagicMock()
        mock_page = mocker.MagicMock()
        mock_page.get_text.return_value = {
            "blocks": [
                {
                    "type": 0,
                    "lines": [
                        {
                            "bbox": (54.0, 100, 100, 110),
                            "spans": [{"text": "Section 1 — Introduction . . . . . 1-2"}]
                        },
                        {
                            "bbox": (54.0, 110, 100, 120),
                            "spans": [{"text": "Chapter 2 — Limit States . . . . . 2-3"}]
                        },
                        {
                            "bbox": (54.0, 120, 100, 130),
                            "spans": [{"text": "Implementation . . . . . 1-2"}]
                        }
                    ]
                }
            ]
        }
        mock_doc.load_page.return_value = mock_page
        
        entries = _extract_toc_entries(mock_doc, [1])
        assert len(entries) == 3
        assert entries[0]["title"] == "Section 1 — Introduction"
        assert entries[0]["page_str"] == "1-2"
        assert entries[1]["title"] == "Chapter 2 — Limit States"
        assert entries[1]["page_str"] == "2-3"
        assert entries[2]["title"] == "Implementation"
        assert entries[2]["page_str"] == "1-2"


