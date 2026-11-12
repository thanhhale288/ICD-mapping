"""phase3_summary.py: summary khớp dữ liệu CSV hiện tại (không ghi file)."""
import json

import phase3_summary as ps


def test_summary_matches_data():
    s = ps.build_summary()
    assert s["trang_thai_rows"] == 128
    assert sum(s["trang_thai_distribution"].values()) == 128
    assert s["unchecked_urls"] == 0
    assert s["qd428_missing"] == []
    assert s["link_chon_with_url"] + s["link_chon_empty"] == 128


def test_committed_summary_up_to_date():
    saved = json.loads(ps.SUMMARY.read_text(encoding="utf-8"))
    fresh = ps.build_summary(saved)
    for k in ("trang_thai_distribution", "ung_vien_check_status", "link_chon_with_url", "unchecked_urls"):
        assert saved[k] == fresh[k], f"{k} lệch: chạy lại python scripts/phase3_summary.py"


def test_render_html():
    assert "Báo cáo Phase 3" in ps.render_html(ps.build_summary())
