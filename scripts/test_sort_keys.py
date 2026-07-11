"""Tests for the shelfmark sort-key helper.

The sort key only has to order shelfmarks *within* one collection, where the
non-numeric scaffolding is consistent — so the transform is deliberately
minimal: zero-pad every digit run, change nothing else.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from sort_keys import compute_sort_key


def test_pads_digit_runs():
    assert compute_sort_key("Harley MS 913") == "Harley MS 000913"
    assert compute_sort_key("Harley MS 2253") == "Harley MS 002253"


def test_harley_orders_numerically():
    shelfmarks = ["Harley MS 913", "Harley MS 2253", "Harley MS 12",
                  "Harley MS 1117", "Harley MS 7653"]
    ordered = sorted(shelfmarks, key=compute_sort_key)
    assert ordered == ["Harley MS 12", "Harley MS 913", "Harley MS 1117",
                       "Harley MS 2253", "Harley MS 7653"]


def test_multiple_digit_runs():
    # Durham-style dotted shelfmarks: every run pads independently.
    assert compute_sort_key("Cosin MS V.v.18") == "Cosin MS V.v.000018"
    assert compute_sort_key("DCL MS. A.III.2") == "DCL MS. A.III.000002"


def test_cosin_orders_numerically():
    ordered = sorted(["Cosin MS V.v.18", "Cosin MS V.v.2", "Cosin MS V.v.15"],
                     key=compute_sort_key)
    assert ordered == ["Cosin MS V.v.2", "Cosin MS V.v.15", "Cosin MS V.v.18"]


def test_no_digits_is_identity():
    assert compute_sort_key("Cotton Charter Roll") == "Cotton Charter Roll"


def test_parenthesized_suffixes_survive():
    assert compute_sort_key("MS. Gr. class. e. 121 (P)") == "MS. Gr. class. e. 000121 (P)"


def test_already_long_numbers_unpadded():
    # Runs at or beyond the pad width pass through unchanged.
    assert compute_sort_key("Add MS 1234567") == "Add MS 1234567"
