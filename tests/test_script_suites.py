"""Bọc các bộ test inline (`<script> test`) để pytest thu thập, chạy offline."""
from __future__ import annotations

import pytest

from extract_tra_cuu import ExtractTraCuuTests  # noqa: F401
from pick_links import PickLinksTests  # noqa: F401
from propose_status import (  # noqa: F401
    FinalTableTests,
    MatchedGateTests,
    ProposeStatusTests,
    V4Tests,
)


def test_match_acceptance(capsys):
    import match
    assert match.run_acceptance() == 0, capsys.readouterr().out


def test_verify_website_unit(monkeypatch, tmp_path, capsys):
    import verify_website as vw
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(vw, "ROOT", tmp_path)  # không ghi file mẫu vào data/
    assert vw.run_unit_tests() == 0, capsys.readouterr().out
    assert (tmp_path / "data" / "website_verify_test.csv").exists()


def test_check_links_stability(offline_fetch, monkeypatch, tmp_path, capsys):
    import check_links
    monkeypatch.setattr(check_links, "fetch", offline_fetch.fetch)
    monkeypatch.setattr(check_links, "ROOT", tmp_path)
    (tmp_path / "data").mkdir(exist_ok=True)
    assert check_links.run_stability_test() == 0, capsys.readouterr().out
