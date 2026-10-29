"""
P1.2 — Chấm trang có đúng ICD không (Phụ lục D).

Khớp khi: tên giống ≥ 90 (rapidfuzz, sau bỏ dấu) VÀ ≥ 1 khóa phụ
(địa bàn / số QĐ / chủ đầu tư).

≥ 3 ICD khác được nhắc → CHỈ_KHỚP_CHUNG.
Tên khớp nhưng địa bàn thuộc ICD khác → đề xuất chuyển STT.
"""

from __future__ import annotations

import csv
import re
import sys
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz

ROOT = Path(__file__).resolve().parents[1]
KEYS_CSV = ROOT / "data" / "icd_keys.csv"

NAME_THRESHOLD = 90
OTHER_ICD_FOR_CHUNG = 3

DROP_PHRASES = (
    "cang can",
    "icd",
    "giai doan 1",
    "giai doan 2",
    "cong ty cp",
    "cong ty tnhh",
    "cong ty co phan",
    "tong cong ty",
)


@dataclass
class IcdKey:
    stt: int
    ten_chinh: str
    ten_goi_khac: list[str]
    tinh_moi: str
    tinh_cu: str
    huyen_cu: str
    khoa_dia_ban: list[str]
    so_qd: list[str]
    chu_dau_tu: str
    don_vi_khai_thac: str
    nhom_trung: str
    names_norm: list[str] = field(default_factory=list)
    dia_ban_norm: list[str] = field(default_factory=list)
    qd_norm: list[str] = field(default_factory=list)
    chu_norm: list[str] = field(default_factory=list)


@dataclass
class MatchResult:
    stt: int
    status: str  # MỞ_ĐƯỢC_KHỚP | CHỈ_KHỚP_CHUNG | MỞ_ĐƯỢC_KHÔNG_KHỚP | (rỗng nếu chưa chấm)
    name_score: float = 0.0
    name_matched: bool = False
    dia_ban_matched: bool = False
    secondary_hits: list[str] = field(default_factory=list)
    other_icd_stts: list[int] = field(default_factory=list)
    other_icd_count: int = 0
    suggested_stt: int | None = None
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def strip_accents(s: str) -> str:
    nk = unicodedata.normalize("NFD", s)
    return "".join(c for c in nk if unicodedata.category(c) != "Mn")


def normalize_text(s: str) -> str:
    s = strip_accents(s or "").lower()
    s = s.replace("–", "-").replace("—", "-")
    s = re.sub(r"[^\w\s/-]", " ", s, flags=re.UNICODE)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def normalize_name(s: str) -> str:
    s = normalize_text(s)
    for phrase in DROP_PHRASES:
        s = re.sub(rf"\b{re.escape(phrase)}\b", " ", s)
    s = re.sub(r"\bgiai doan\s*\d+\b", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _split_multi(raw: str) -> list[str]:
    if not raw:
        return []
    parts = re.split(r"[;|]", raw)
    return [p.strip() for p in parts if p.strip()]


def load_keys(path: Path = KEYS_CSV) -> dict[int, IcdKey]:
    out: dict[int, IcdKey] = {}
    with path.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            stt = int(row["stt"])
            alts = _split_multi(row.get("ten_goi_khac") or "")
            dia = _split_multi(row.get("khoa_dia_ban") or "")
            for extra in (
                row.get("tinh_moi") or "",
                row.get("tinh_cu") or "",
                row.get("huyen_cu") or "",
            ):
                if extra and extra not in dia:
                    dia.append(extra)
            qd = _split_multi(row.get("so_qd") or "")
            key = IcdKey(
                stt=stt,
                ten_chinh=row.get("ten_chinh") or "",
                ten_goi_khac=alts,
                tinh_moi=(row.get("tinh_moi") or "").strip(),
                tinh_cu=(row.get("tinh_cu") or "").strip(),
                huyen_cu=(row.get("huyen_cu") or "").strip(),
                khoa_dia_ban=dia,
                so_qd=qd,
                chu_dau_tu=(row.get("chu_dau_tu") or "").strip(),
                don_vi_khai_thac=(row.get("don_vi_khai_thac") or "").strip(),
                nhom_trung=(row.get("nhom_trung") or "").strip(),
            )
            names = [key.ten_chinh, *alts]
            # thêm token ngắn hữu ích (bỏ tỉnh trong ngoặc nếu có)
            for n in list(names):
                base = re.sub(r"\([^)]*\)", " ", n).strip()
                if base and base not in names:
                    names.append(base)
            # nhóm trùng: thêm tên nhóm (Long Bình, Tân Lập, …)
            if key.nhom_trung:
                # "Thạnh Phước/Thanh Phước" → cả hai
                for part in re.split(r"[/]", key.nhom_trung):
                    part = part.strip()
                    if part and part not in names:
                        names.append(part)
            tinh_norms = {
                normalize_text(x)
                for x in (key.tinh_moi, key.tinh_cu, key.huyen_cu)
                if x and len(normalize_text(x)) >= 3
            }
            key.names_norm = []
            seen_n: set[str] = set()
            for n in names:
                nn = normalize_name(n)
                if not nn or nn in seen_n:
                    continue
                # ten_goi_khac chỉ là tên tỉnh → bỏ (gây nhiễu footer báo)
                if nn in tinh_norms and nn == normalize_name(n):
                    # vẫn giữ nếu là cả ten_chinh (ICD đúng tên tỉnh hiếm)
                    if normalize_name(key.ten_chinh) != nn:
                        continue
                seen_n.add(nn)
                key.names_norm.append(nn)
                # dạng ngắn: 2 từ cuối (tan cang long binh → long binh)
                parts = nn.split()
                if len(parts) >= 3:
                    short = " ".join(parts[-2:])
                    if (
                        short not in seen_n
                        and len(short) >= 6
                        and short not in tinh_norms
                    ):
                        seen_n.add(short)
                        key.names_norm.append(short)
            # địa bàn: bỏ token quá chung / nhiễu
            skip_dia = {
                "",
                "dia danh",
                "dia danh cu",
                "theo tai lieu lich su",
                "ho so lich su",
                "cu",
            }
            dia_n = []
            for d in dia:
                nd = normalize_text(d)
                nd = re.sub(r"\s*\(cu\)\s*", " ", nd).strip()
                if len(nd) < 3 or nd in skip_dia:
                    continue
                if nd not in dia_n:
                    dia_n.append(nd)
            key.dia_ban_norm = dia_n
            key.qd_norm = [normalize_text(q) for q in qd if normalize_text(q)]
            chu_bits = []
            for c in (key.chu_dau_tu, key.don_vi_khai_thac):
                nc = normalize_name(c)
                if nc and len(nc) >= 6:
                    chu_bits.append(nc)
            key.chu_norm = chu_bits
            out[stt] = key
    return out


def _is_icd_catalog_page(page_norm: str) -> bool:
    compact = page_norm.replace(" ", "")
    return (
        "hethongcangcan" in compact
        or "979/qd" in compact
        or ("danh muc" in page_norm and "cang can" in page_norm)
        or ("quy hoach" in page_norm and "cang can" in page_norm and "danh muc" in page_norm)
    )


def _near_icd_context(page_norm: str, name: str, window: int = 64) -> bool:
    """Tên xuất hiện gần cụm 'cang can' / 'icd' — giảm nhiễu tên tỉnh trên footer."""
    if not name:
        return False
    if _is_icd_catalog_page(page_norm):
        return True
    for m in re.finditer(rf"(?<!\w){re.escape(name)}(?!\w)", page_norm):
        start = max(0, m.start() - window)
        end = min(len(page_norm), m.end() + window)
        ctx = page_norm[start:end]
        if "cang can" in ctx or re.search(r"(?<!\w)icd(?!\w)", ctx):
            return True
    return False


def _best_name_score(page_norm: str, key: IcdKey, *, require_context: bool = False) -> float:
    best = 0.0
    for name in key.names_norm:
        if not name or len(name) < 3:
            continue
        # exact / substring theo biên từ
        bounded = re.search(rf"(?<!\w){re.escape(name)}(?!\w)", page_norm)
        if bounded:
            if require_context and len(name.split()) <= 2 and not _near_icd_context(page_norm, name):
                continue
            best = max(best, 100.0)
            continue
        if name in page_norm:
            if require_context and len(name.split()) <= 2 and not _near_icd_context(page_norm, name):
                continue
            best = max(best, 100.0)
            continue
        if len(name) < 6:
            continue
        score = float(fuzz.partial_ratio(name, page_norm))
        if require_context and score >= NAME_THRESHOLD and len(name.split()) <= 2:
            if not _near_icd_context(page_norm, name):
                continue
        best = max(best, score)
    return best


def _token_in_page(token: str, page_norm: str) -> bool:
    if not token or len(token) < 3:
        return False
    if token in page_norm:
        return True
    # fuzzy nhẹ cho biến thể (Đồng Nai / Dong Nai đã normalize)
    if len(token) >= 6 and fuzz.partial_ratio(token, page_norm) >= 95:
        return True
    return False


def _name_tokens_to_skip_as_dia(key: IcdKey) -> set[str]:
    """Token tên ICD không dùng làm khóa địa bàn (vd. long binh), vẫn giữ tỉnh/huyện."""
    skip: set[str] = set()
    if key.nhom_trung:
        for part in re.split(r"[/]", key.nhom_trung):
            nn = normalize_name(part.strip())
            if nn:
                skip.add(nn)
    for n in key.names_norm:
        # chỉ bỏ tên ngắn 2 từ kiểu tên ICD, không bỏ tỉnh đơn
        parts = n.split()
        if len(parts) == 2 and n not in {
            normalize_text(key.tinh_moi),
            normalize_text(key.tinh_cu),
            normalize_text(key.huyen_cu),
        }:
            # nếu trùng nhom hoặc là short form của ten_chinh
            if n in skip or n == " ".join(normalize_name(key.ten_chinh).split()[-2:]):
                skip.add(n)
    return skip


def _secondary_hits(page_norm: str, key: IcdKey) -> list[str]:
    hits: list[str] = []
    skip_as_dia = _name_tokens_to_skip_as_dia(key)
    for d in key.dia_ban_norm:
        # bỏ token trùng tên ICD (vd. "long binh") — địa bàn phải là tỉnh/huyện thật
        if d in skip_as_dia:
            continue
        if _token_in_page(d, page_norm):
            hits.append(f"dia_ban:{d}")
    for q in key.qd_norm:
        # số QĐ: khớp linh hoạt 979/qd-ttg
        q_compact = re.sub(r"\s+", "", q)
        page_compact = re.sub(r"\s+", "", page_norm)
        if q_compact and q_compact in page_compact:
            hits.append(f"qd:{q}")
            continue
        # lấy số chính (979, 428, ...)
        m = re.search(r"(\d{2,5})\s*/\s*qd", q)
        if m:
            num = m.group(1)
            if re.search(rf"\b{num}\s*/\s*qd", page_norm) or f"{num}/qd" in page_compact:
                hits.append(f"qd:{q}")
    for c in key.chu_norm:
        if _token_in_page(c, page_norm) or fuzz.partial_ratio(c, page_norm) >= 90:
            hits.append(f"chu:{c}")
    # unique preserve order
    seen: set[str] = set()
    out: list[str] = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def _dia_ban_only_hits(page_norm: str, key: IcdKey) -> list[str]:
    return [h for h in _secondary_hits(page_norm, key) if h.startswith("dia_ban:")]


def find_mentioned_icds(
    text: str,
    keys: dict[int, IcdKey] | None = None,
    *,
    require_secondary: bool = True,
) -> list[tuple[int, float, list[str]]]:
    """Danh sách (stt, name_score, secondary_hits) được nhắc trên trang."""
    keys = keys or load_keys()
    page_norm = normalize_text(text)
    found: list[tuple[int, float, list[str]]] = []
    for stt, key in keys.items():
        score = _best_name_score(page_norm, key)
        if score < NAME_THRESHOLD:
            continue
        hits = _secondary_hits(page_norm, key)
        if require_secondary and not hits:
            # vẫn ghi nhận tên nếu không cần khóa phụ (đếm thô)
            continue
        found.append((stt, score, hits))
    found.sort(key=lambda x: (-x[1], x[0]))
    return found


def match_text(
    text: str,
    stt: int,
    keys: dict[int, IcdKey] | None = None,
) -> MatchResult:
    keys = keys or load_keys()
    if stt not in keys:
        return MatchResult(stt=stt, status="MỞ_ĐƯỢC_KHÔNG_KHỚP", reason=f"không có khóa STT {stt}")

    key = keys[stt]
    page_norm = normalize_text(text)
    score = _best_name_score(page_norm, key)
    hits = _secondary_hits(page_norm, key)
    dia_hits = [h for h in hits if h.startswith("dia_ban:")]
    name_ok = score >= NAME_THRESHOLD
    secondary_ok = len(hits) >= 1

    # Đếm ICD khác: tên ≥ 90 + ngữ cảnh ICD (tránh footer báo chỉ có tên tỉnh)
    others_mentioned: list[int] = []
    for other_stt, other_key in keys.items():
        if other_stt == stt:
            continue
        if _best_name_score(page_norm, other_key, require_context=True) >= NAME_THRESHOLD:
            others_mentioned.append(other_stt)

    other_count = len(set(others_mentioned))
    result = MatchResult(
        stt=stt,
        status="",
        name_score=score,
        name_matched=name_ok,
        dia_ban_matched=bool(dia_hits),
        secondary_hits=hits,
        other_icd_stts=sorted(set(others_mentioned))[:30],
        other_icd_count=other_count,
    )

    # Chống nhầm tên trùng: tên khớp nhưng địa bàn thuộc ICD khác trong cùng nhóm
    if name_ok and not dia_hits and key.nhom_trung:
        better: tuple[int, list[str]] | None = None
        for other_stt, other_key in keys.items():
            if other_stt == stt:
                continue
            if other_key.nhom_trung != key.nhom_trung:
                continue
            if _best_name_score(page_norm, other_key) < NAME_THRESHOLD:
                continue
            o_dia = _dia_ban_only_hits(page_norm, other_key)
            if o_dia:
                better = (other_stt, o_dia)
                break
        if better:
            result.suggested_stt = better[0]
            result.status = "MỞ_ĐƯỢC_KHÔNG_KHỚP"
            result.reason = (
                f"tên khớp nhưng địa bàn thuộc STT {better[0]} ({', '.join(better[1])})"
            )
            return result

    if other_count >= OTHER_ICD_FOR_CHUNG and name_ok:
        result.status = "CHỈ_KHỚP_CHUNG"
        result.reason = f"trang nhắc {other_count} ICD khác (≥{OTHER_ICD_FOR_CHUNG})"
        return result

    if name_ok and secondary_ok:
        result.status = "MỞ_ĐƯỢC_KHỚP"
        result.reason = f"tên={score:.0f}; khóa phụ={hits}"
        return result

    if name_ok and not secondary_ok:
        result.status = "MỞ_ĐƯỢC_KHÔNG_KHỚP"
        result.reason = f"tên khớp ({score:.0f}) nhưng thiếu khóa phụ"
        return result

    result.status = "MỞ_ĐƯỢC_KHÔNG_KHỚP"
    result.reason = f"không thấy tên ICD (score={score:.0f})"
    return result


# --- ca mẫu P1.2 -------------------------------------------------------------

def _sample_pages() -> list[tuple[str, int, str, str]]:
    """(id, stt, text, expected_status)."""
    return [
        (
            "longbinh_15",
            15,
            "Bộ GTVT công bố mở cảng cạn Tân Cảng Long Bình tại Biên Hòa, Đồng Nai. "
            "Chủ đầu tư Công ty CP ICD Tân Cảng Long Bình.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "longbinh_98",
            98,
            "Quy hoạch cảng cạn Long Bình thuộc TP. Hồ Chí Minh (địa bàn TP.HCM cũ), "
            "theo Quyết định 979/QĐ-TTg.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "longbinh_126",
            126,
            "Điều chỉnh quy hoạch tỉnh An Giang 2021-2030, trong đó có cảng cạn Long Bình "
            "tại An Giang theo Nghị quyết 04/NQ-HĐND.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "longbinh_15_sai_dia_ban",
            15,
            "Bài viết về cảng cạn Long Bình tại An Giang, thuộc quy hoạch tỉnh An Giang.",
            "MỞ_ĐƯỢC_KHÔNG_KHỚP",  # địa bàn An Giang → đề xuất 126
        ),
        (
            "tanlap_58",
            58,
            "Quy hoạch tỉnh Hưng Yên nêu cảng cạn Tân Lập, Hưng Yên theo QĐ 979/QĐ-TTg.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "tanlap_121",
            121,
            "Quy hoạch tỉnh Tây Ninh / Long An cũ đề cập cảng cạn Tân Lập tại Long An, "
            "Quyết định 2968/QĐ-UBND.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "thanh_phuoc_18",
            18,
            "Công bố mở cảng cạn Thạnh Phước – Bình Dương. Chủ đầu tư Công ty CP Cảng Thạnh Phước. "
            "Nay thuộc TP. Hồ Chí Minh.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "thanh_phuoc_116",
            116,
            "Quy hoạch cảng cạn Thanh Phước (Gò Dầu), tỉnh Tây Ninh theo QĐ 979/QĐ-TTg.",
            "MỞ_ĐƯỢC_KHỚP",
        ),
        (
            "thanh_phuoc_18_nham_116",
            18,
            "Bài về cảng cạn Thanh Phước tại Gò Dầu, Tây Ninh trong quy hoạch tỉnh.",
            "MỞ_ĐƯỢC_KHÔNG_KHỚP",
        ),
        (
            "qd979_chung",
            13,
            # giả lập QĐ 979 liệt kê nhiều ICD
            "Quyết định 979/QĐ-TTg phê duyệt quy hoạch phát triển hệ thống cảng cạn 2021-2030. "
            "Danh mục gồm: Long Bình, Tân Lập, Thanh Phước, Sóng Thần, TBS Tân Vạn, "
            "Phúc Lộc Ninh Bình, Tiên Sơn, Yên Mỹ, Văn Lâm, Minh Châu, và nhiều ICD khác "
            "trên cả nước theo quy hoạch ngành.",
            "CHỈ_KHỚP_CHUNG",
        ),
    ]


def run_acceptance() -> int:
    keys = load_keys()
    print(f"Loaded {len(keys)} ICD keys", flush=True)
    ok_all = True
    for case_id, stt, text, expect in _sample_pages():
        r = match_text(text, stt, keys)
        passed = r.status == expect
        # ca chuyển địa bàn: phải có suggested_stt
        if case_id == "longbinh_15_sai_dia_ban":
            passed = passed and r.suggested_stt == 126
        if case_id == "thanh_phuoc_18_nham_116":
            passed = passed and (r.suggested_stt == 116 or not r.dia_ban_matched)
        print(
            f"{'PASS' if passed else 'FAIL'} [{case_id}] stt={stt} "
            f"got={r.status} expect={expect} score={r.name_score:.0f} "
            f"others={r.other_icd_count} suggest={r.suggested_stt} "
            f"hits={r.secondary_hits[:3]} | {r.reason}",
            flush=True,
        )
        ok_all = ok_all and passed
    print("ALL PASS" if ok_all else "SOME FAILED", flush=True)
    return 0 if ok_all else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        return run_acceptance()
    if len(argv) >= 3:
        stt = int(argv[1])
        path = Path(argv[2])
        text = path.read_text(encoding="utf-8", errors="replace")
        r = match_text(text, stt)
        print(asdict(r))
        return 0
    print("Usage: python scripts/match.py test")
    print("       python scripts/match.py <stt> <file.txt>")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
