"""Tests for the LivePix donation area and the official QR asset.

Everything runs against real code paths: the real static file, the real
FastAPI routes and the real release helpers. The QR image is verified by
hashing the shipped asset (the exact file the user provided) and, when a QR
decoder is available, by decoding it back to the donation URL.
"""
from __future__ import annotations

import hashlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_TMP = tempfile.mkdtemp(prefix="openhud-donation-")
os.environ["OPENHUD_DATA_DIR"] = str(Path(_TMP) / "data")
os.environ["OPENHUD_WORKSPACE"] = str(Path(_TMP) / "workspace")
os.environ["OPENHUD_PASSWORD"] = "test-password"
os.environ.pop("OPENHUD_DONATION_URL", None)

from fastapi.testclient import TestClient  # noqa: E402

from openhud.core import release as release_mod  # noqa: E402
from openhud.web.app import app  # noqa: E402

client = TestClient(app)

LIVEPIX_URL = "https://livepix.gg/supimpa2"
# SHA-256 of the official QR image exactly as supplied (unmodified).
QR_SHA256 = "2980a0babe5c52144f88b806bdc32185b01ff82b0d48049b923c2336a03535ec"
QR_FILE = Path(__file__).resolve().parents[1] / "openhud/web/static/site/assets/livepix-qr.png"


def test_donation_url_defaults_to_livepix():
    assert release_mod.donation_url() == LIVEPIX_URL


def test_donation_url_override(monkeypatch):
    monkeypatch.setenv("OPENHUD_DONATION_URL", "https://example.org/donate")
    assert release_mod.donation_url() == "https://example.org/donate"


def test_donation_url_empty_disables(monkeypatch):
    monkeypatch.setenv("OPENHUD_DONATION_URL", "   ")
    assert release_mod.donation_url() is None


def test_site_config_exposes_livepix():
    d = client.get("/api/site/config").json()
    assert d["donation_url"] == LIVEPIX_URL
    assert d["donation_provider"] == "LivePix"
    assert d["donation_handle"] == "livepix.gg/supimpa2"
    assert d["donation_qr"] == "/static/site/assets/livepix-qr.png"


def test_qr_asset_present_and_served():
    r = client.get("/static/site/assets/livepix-qr.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_qr_asset_is_the_official_unmodified_file():
    assert QR_FILE.is_file(), "o QR oficial deve existir como asset estático"
    digest = hashlib.sha256(QR_FILE.read_bytes()).hexdigest()
    assert digest == QR_SHA256


def test_qr_asset_decodes_to_livepix_url():
    """Decode the shipped QR with a real decoder when one is installed."""
    zxingcpp = __import__("pytest").importorskip("zxingcpp")
    import cv2

    img = cv2.imread(str(QR_FILE))
    assert img is not None
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    results = zxingcpp.read_barcodes(gray)
    assert results, "o QR deve ser legível"
    assert results[0].text == LIVEPIX_URL


def test_pricing_page_has_active_button_and_link():
    html = client.get("/pricing").text
    assert LIVEPIX_URL in html
    assert "APOIAR O PROJETO" in html
    assert 'href="https://livepix.gg/supimpa2"' in html
    assert 'target="_blank"' in html and "noopener" in html


def test_pricing_page_shows_qr_with_alt_text():
    html = client.get("/pricing").text
    assert '/static/site/assets/livepix-qr.png' in html
    assert 'alt="QR Code do LivePix' in html
    assert "Aponte a câmera" in html


def test_pricing_page_has_textual_fallback():
    html = client.get("/pricing").text
    assert "Ou acesse:" in html
    assert "livepix.gg/supimpa2" in html


def test_pricing_hides_button_when_disabled(monkeypatch):
    monkeypatch.setenv("OPENHUD_DONATION_URL", "")
    html = client.get("/pricing").text
    assert "disabled" in html
    assert "Apoio desativado neste servidor" in html
    # No QR and no link when the operator disabled donations.
    assert "livepix-qr.png" not in html


def test_support_section_is_responsive_css():
    css = (Path(__file__).resolve().parents[1]
           / "openhud/web/static/site/site.css").read_text(encoding="utf-8")
    assert ".support-grid" in css
    assert ".support .qr" in css
    # The grid must collapse to a single column on small screens.
    idx = css.index(".support-grid { grid-template-columns: 1fr;")
    assert idx > 0
