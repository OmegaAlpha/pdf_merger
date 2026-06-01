import pytest
import fitz
from utils import check_fitz_toc_for_first_page, adjust_toc_pages_and_levels

def test_check_fitz_toc_for_first_page():
    # Empty toc
    assert not check_fitz_toc_for_first_page([])
    
    # Missing page 1
    toc_without_page_1 = [
        [1, "Chapter 1", 2],
        [2, "Section 1", 3]
    ]
    assert not check_fitz_toc_for_first_page(toc_without_page_1)
    
    # Valid page 1
    toc_with_page_1 = [
        [1, "Title Page", 1],
        [1, "Chapter 1", 2]
    ]
    assert check_fitz_toc_for_first_page(toc_with_page_1)
    
    # Invalid structure silently ignored/returns False
    invalid_toc = [
        [1, "Title"], # missing page index
        "Not a list"
    ]
    assert not check_fitz_toc_for_first_page(invalid_toc)

def test_adjust_toc_pages_and_levels_simple(mocker):
    # Mocking source_doc to return empty names logic
    mock_doc = mocker.Mock()
    mock_doc.resolve_names.return_value = {}

    toc = [
        [1, "Section 1", 1, {"kind": fitz.LINK_GOTO, "page": 0, "to": fitz.Point(0,0)}],
        [2, "Subsection 1", 2, {"kind": fitz.LINK_GOTO, "page": 1, "to": fitz.Point(0,0)}]
    ]

    # Adjust by 5 pages, 1 level increase
    adjusted = adjust_toc_pages_and_levels(toc, page_offset_0based=5, source_doc=mock_doc, level_increase=1)
    
    # Check new length
    assert len(adjusted) == 2
    
    # Check levels (1 -> 2, 2 -> 3)
    assert adjusted[0][0] == 2
    assert adjusted[1][0] == 3
    
    # Check titles
    assert adjusted[0][1] == "Section 1"
    assert adjusted[1][1] == "Subsection 1"
    
    # Check 1-based page numbers in ToC (1 -> 6, 2 -> 7)
    assert adjusted[0][2] == 6
    assert adjusted[1][2] == 7
    
    # Check 0-based page numbers in destination dict (0 -> 5, 1 -> 6)
    assert adjusted[0][3]["page"] == 5
    assert adjusted[1][3]["page"] == 6

def test_adjust_toc_pages_and_levels_no_dict(mocker):
    mock_doc = mocker.Mock()
    mock_doc.resolve_names.return_value = {}

    # PyMuPDF ToCs sometimes don't have the 4th element (dest dict)
    toc = [
        [1, "Cover", 1],
        [1, "Content", 5]
    ]

    adjusted = adjust_toc_pages_and_levels(toc, page_offset_0based=10, source_doc=mock_doc, level_increase=0)
    
    assert len(adjusted) == 2
    assert adjusted[0][2] == 11
    assert adjusted[1][2] == 15
    assert adjusted[1][3]["kind"] == fitz.LINK_GOTO
    assert adjusted[1][3]["page"] == 14 # 0-based target page

def test_adjust_toc_pages_and_levels_discrepancy(mocker):
    """
    Verify that when there is a discrepancy between the 1-based page number in the
    TOC item and the 0-based page number in the destination dictionary, the 1-based
    page number in the TOC item is synchronized to match the destination dictionary.
    """
    mock_doc = mocker.Mock()
    mock_doc.resolve_names.return_value = {}

    # Discrepancy:
    # Bookmark 1: Outline page number is 5, but dest page is 1 (representing page 2).
    # Bookmark 2: Outline page number is 10, but dest page is 0 (representing page 1).
    toc = [
        [1, "Mismatch 1", 5, {"kind": fitz.LINK_GOTO, "page": 1, "to": fitz.Point(0,0)}],
        [2, "Mismatch 2", 10, {"kind": fitz.LINK_GOTO, "page": 0, "to": fitz.Point(0,0)}]
    ]

    adjusted = adjust_toc_pages_and_levels(toc, page_offset_0based=0, source_doc=mock_doc, level_increase=0)

    assert len(adjusted) == 2
    # Mismatch 1: Outline page is synchronized to 2
    assert adjusted[0][2] == 2
    assert adjusted[0][3]["page"] == 1

    # Mismatch 2: Outline page is synchronized to 1
    assert adjusted[1][2] == 1
    assert adjusted[1][3]["page"] == 0

