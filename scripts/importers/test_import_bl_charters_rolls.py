"""Tests for the BL charters/rolls importer's pure logic.

The two units worth testing in isolation are manifest extraction (unwrapping the
BL universal-viewer link to a bare IIIF manifest URL) and collection
classification (native shelfmark -> one of the four collections).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from import_bl_charters_rolls import classify_collection, extract_manifest_url


# --- extract_manifest_url -------------------------------------------------

def test_unwraps_universal_viewer_fragment():
    # The on-Rails digitised_url is a UV viewer wrapping the real manifest in a
    # #?manifest= fragment. We want the bare digirati manifest.
    url = ("https://iiif.bl.uk/uv/#?manifest="
           "https://bl.digirati.io/iiif/ark:/81055/vdc_100165170242.0x000001")
    assert extract_manifest_url(url) == (
        "https://bl.digirati.io/iiif/ark:/81055/vdc_100165170242.0x000001"
    )


def test_passes_through_bare_digirati_manifest():
    url = "https://bl.digirati.io/iiif/ark:/81055/vdc_100176154946.0x000001"
    assert extract_manifest_url(url) == url


def test_url_encoded_manifest_param_is_decoded():
    url = ("https://iiif.bl.uk/uv/#?manifest="
           "https%3A%2F%2Fbl.digirati.io%2Fiiif%2Fark%3A%2F81055%2F"
           "vdc_100165170242.0x000001")
    assert extract_manifest_url(url) == (
        "https://bl.digirati.io/iiif/ark:/81055/vdc_100165170242.0x000001"
    )


def test_legacy_fulldisplay_viewer_has_no_manifest():
    url = "http://www.bl.uk/manuscripts/FullDisplay.aspx?ref=Cotton_Ch_IV_5"
    assert extract_manifest_url(url) is None


def test_legacy_access_bl_uk_viewer_has_no_manifest():
    url = "https://access.bl.uk/item/viewer/ark:/81055/vdc_100000000000.0x000001"
    assert extract_manifest_url(url) is None


def test_none_and_empty_yield_none():
    assert extract_manifest_url(None) is None
    assert extract_manifest_url("") is None


# --- classify_collection --------------------------------------------------

def test_cotton_charter():
    assert classify_collection("Cotton Charter IV 5") == "Cotton Charters"


def test_cotton_roll():
    assert classify_collection("Cotton Roll XIV 8") == "Cotton Rolls"


def test_harley_charter():
    assert classify_collection("Harley Charter 43 C 1") == "Harley Charters"


def test_harley_roll():
    assert classify_collection("Harley Roll Y 6") == "Harley Rolls"


def test_non_charter_roll_is_unclassified():
    # Defensive: a plain codex shelfmark is not one of our four buckets.
    assert classify_collection("Cotton MS Nero D IV") is None
