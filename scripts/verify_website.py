"""
P3.4 — Xác minh website chính chủ theo plan-3 §10.5 / Phụ lục F.

Tín hiệu mạnh: S1 (MST), S2 (tên + địa chỉ), S3 (tập đoàn mẹ / VB nhà nước trỏ tới).
Tín hiệu phụ: P1 (tên miền chứa thương hiệu), P2 (nội dung ICD + cập nhật gần).
Loại ngay: danh bạ doanh nghiệp, tin tổng hợp, giả mạo (MST/địa chỉ lệch).

Kết luận:
  chính thức – đã xác minh  → ≥2 mạnh, hoặc 1 mạnh + 2 phụ  (cột G)
  có khả năng – cần xác nhận → 1 mạnh, hoặc chỉ phụ         (cột I)
  loại                       → danh bạ / aggregator / lệch
"""

from __future__ import annotations

import csv
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from fetch import fetch  # noqa: E402
from match import (  # noqa: E402
    IcdKey,
    load_keys,
    normalize_name,
    normalize_text,
    strip_accents,
)

OUT_CSV = ROOT / "data" / "website_verify.csv"
KEYS_CSV = ROOT / "data" / "icd_keys.csv"
HIEN_TRANG = ROOT / "data" / "icd_hien_trang.csv"
UNG_VIEN = ROOT / "data" / "ung_vien.csv"

CONCLUSION_VERIFIED = "chính thức – đã xác minh"
CONCLUSION_POSSIBLE = "có khả năng – cần xác nhận"
CONCLUSION_REJECT = "loại"

# Danh bạ / hồ sơ công ty — loại ngay
DIRECTORY_DOMAINS = (
    "masothue.com",
    "masothue.vn",
    "trangvangvietnam.com",
    "trangvang.com.vn",
    "hosocongty.vn",
    "hosocongty.com",
    "infodoanhnghiep.com",
    "infodoanhnghiep.vn",
    "thongtincongty.com",
    "yellowpages.com.vn",
    "hsct.vn",
    "congty.vn",
)

# Tin tổng hợp / rao vặt (không phải website doanh nghiệp ICD)
AGGREGATOR_DOMAINS = (
    "muaban.net",
    "chotot.com",
    "vieclam24h.vn",
    "careerbuilder.vn",
    "vietnamworks.com",
)

# Cụm nội dung khai thác ICD (P2)
ICD_OPS_HINTS = (
    "cang can",
    "icd",
    "bieu gia",
    "bang gia",
    "dich vu",
    "khai thac",
    "container",
    "teu",
    "depot",
    "thu tuc hai quan",
    "hai quan",
    "bai container",
    "lien he khai thac",
    "lich tau",
    "hang tau",
    "van tai da phuong thuc",
)

# Nguồn nhà nước / tập đoàn (gợi ý S3 khi URL thuộc các miền này)
GOV_DOMAIN_HINTS = (
    ".gov.vn",
    "chinhphu.vn",
    "vimawa.gov.vn",
    "mt.gov.vn",
    "thuvienphapluat.vn",
    "luatvietnam.vn",
    "baochinhphu.vn",
)

PARENT_OPERATOR_HINTS = (
    "tancang",
    "saigonnewport",
    "gemadept",
    "vimc",
    "tbsgroup",
    "transimex",
    "hateco",
    "sotrans",
)

COLUMNS = [
    "stt",
    "url",
    "domain",
    "conclusion",
    "s1",
    "s2",
    "s3",
    "p1",
    "p2",
    "strong_count",
    "weak_count",
    "reject_reason",
    "signals_detail",
    "legal_name_ref",
    "address_ref",
    "mst_ref",
    "mst_found",
    "title",
    "text_path",
    "fetched_at",
]


@dataclass
class IndependentRef:
    """Nguồn độc lập để đối chiếu (không lấy từ chính website đang chấm)."""

    mst: str = ""
    legal_name: str = ""  # chủ đầu tư / đơn vị khai thác
    address: str = ""  # vị trí / địa chỉ QĐ mở cảng
    brand_tokens: list[str] = field(default_factory=list)
    # S3: đã biết tập đoàn mẹ / VB nhà nước trỏ tới tên miền này
    parent_points_to_domain: bool = False
    parent_note: str = ""


@dataclass
class VerifyResult:
    stt: str
    url: str
    domain: str = ""
    conclusion: str = ""
    s1: bool = False
    s2: bool = False
    s3: bool = False
    p1: bool = False
    p2: bool = False
    strong_count: int = 0
    weak_count: int = 0
    reject_reason: str = ""
    signals_detail: str = ""
    legal_name_ref: str = ""
    address_ref: str = ""
    mst_ref: str = ""
    mst_found: str = ""
    title: str = ""
    text_path: str = ""
    fetched_at: str = ""
    meta: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("meta", None)
        return {k: d.get(k, "") for k in COLUMNS}

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _domain(url: str) -> str:
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return ""
    if host.startswith("www."):
        host = host[4:]
    return host


def _host_matches(domain: str, needle: str) -> bool:
    d = (domain or "").lower()
    n = needle.lower().lstrip(".")
    return d == n or d.endswith("." + n) or n in d


def is_directory_domain(url_or_domain: str) -> bool:
    d = _domain(url_or_domain) if "://" in url_or_domain else url_or_domain.lower()
    return any(_host_matches(d, x) for x in DIRECTORY_DOMAINS)


def is_aggregator_domain(url_or_domain: str) -> bool:
    d = _domain(url_or_domain) if "://" in url_or_domain else url_or_domain.lower()
    return any(_host_matches(d, x) for x in AGGREGATOR_DOMAINS)


def normalize_mst(raw: str) -> str:
    """Chuẩn hoá MST VN: chỉ giữ chữ số (10 hoặc 13)."""
    digits = re.sub(r"\D", "", raw or "")
    if len(digits) in (10, 13):
        return digits
    return digits


def extract_msts(text: str) -> list[str]:
    """Lấy các MST khả dĩ từ văn bản (ưu tiên gần nhãn thuế)."""
    found: list[str] = []
    seen: set[str] = set()

    # Gần nhãn: Mã số thuế / MST / Tax code
    labeled = re.finditer(
        r"(?:mã\s*số\s*thuế|ma\s*so\s*thue|mst|tax\s*code|tax\s*id)"
        r"\s*[:：]?\s*([0-9][0-9\s.\-]{8,18})",
        text or "",
        flags=re.I,
    )
    for m in labeled:
        mst = normalize_mst(m.group(1))
        if len(mst) in (10, 13) and mst not in seen:
            seen.add(mst)
            found.append(mst)

    # Fallback: chuỗi 10/13 số đứng độc lập (tránh năm / QĐ)
    for m in re.finditer(r"(?<!\d)(\d{10}|\d{13})(?!\d)", text or ""):
        mst = m.group(1)
        # bỏ số QĐ kiểu năm+... thô; vẫn chấp nhận nếu đã có nhãn
        if mst.startswith("20") and len(mst) == 10:
            continue
        if mst not in seen:
            seen.add(mst)
            found.append(mst)
    return found


def _brand_tokens_from_name(*names: str) -> list[str]:
    """Token thương hiệu để chấm P1 (bỏ từ pháp lý chung)."""
    drop = {
        "cong",
        "ty",
        "cp",
        "tnhh",
        "co",
        "phan",
        "tong",
        "congty",
        "cang",
        "can",
        "icd",
        "giai",
        "doan",
        "theo",
        "ho",
        "so",
        "lich",
        "su",
        "can",
        "xac",
        "nhan",
        "hien",
        "hanh",
        "he",
        "thong",
        "phap",
        "nhan",
        "truc",
        "tiep",
    }
    tokens: list[str] = []
    seen: set[str] = set()
    for name in names:
        nn = normalize_name(name)
        if not nn:
            continue
        parts = [p for p in nn.split() if p not in drop and len(p) >= 3]
        # cụm 1–2 từ có nghĩa
        for p in parts:
            if p not in seen:
                seen.add(p)
                tokens.append(p)
        if len(parts) >= 2:
            bigram = "".join(parts[:2])
            if bigram not in seen and len(bigram) >= 6:
                seen.add(bigram)
                tokens.append(bigram)
            spaced = " ".join(parts[:2])
            if spaced not in seen:
                seen.add(spaced)
                tokens.append(spaced)
    return tokens


def load_independent_ref(
    stt: str | int,
    *,
    mst: str = "",
    legal_name: str = "",
    address: str = "",
    parent_points_to_domain: bool = False,
    parent_note: str = "",
    keys: dict[int, IcdKey] | None = None,
) -> IndependentRef:
    """Ghép tham chiếu độc lập từ CLI / icd_keys / hien_trang."""
    ref = IndependentRef(
        mst=normalize_mst(mst),
        legal_name=legal_name.strip(),
        address=address.strip(),
        parent_points_to_domain=parent_points_to_domain,
        parent_note=parent_note,
    )
    stt_i: int | None
    try:
        stt_i = int(str(stt).strip())
    except ValueError:
        stt_i = None

    key: IcdKey | None = None
    if stt_i is not None:
        keys = keys if keys is not None else load_keys()
        key = keys.get(stt_i)

    if key:
        if not ref.legal_name:
            # ưu tiên đơn vị khai thác, rồi chủ đầu tư
            ref.legal_name = (key.don_vi_khai_thac or key.chu_dau_tu or "").strip()
        brands = _brand_tokens_from_name(
            key.ten_chinh,
            *key.ten_goi_khac,
            key.chu_dau_tu,
            key.don_vi_khai_thac,
        )
        ref.brand_tokens = brands

    # Bổ sung vi_tri / tên từ icd_keys.csv + hien_trang
    if stt_i is not None:
        _fill_from_keys_csv(stt_i, ref)
        if not ref.address or not ref.legal_name:
            _fill_from_hien_trang(stt_i, ref)

    if not ref.brand_tokens:
        ref.brand_tokens = _brand_tokens_from_name(
            ref.legal_name,
            key.ten_chinh if key else "",
        )
    return ref


def _fill_from_keys_csv(stt: int, ref: IndependentRef) -> None:
    if not KEYS_CSV.exists():
        return
    with KEYS_CSV.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("stt") or "").strip() != str(stt):
                continue
            if not ref.legal_name:
                ref.legal_name = (
                    (row.get("don_vi_khai_thac") or row.get("chu_dau_tu") or "").strip()
                )
            if not ref.address:
                ref.address = (row.get("vi_tri") or "").strip()
            # MST nếu có cột (tương lai)
            if not ref.mst:
                for col in ("mst", "ma_so_thue", "tax_id"):
                    if row.get(col):
                        ref.mst = normalize_mst(row[col])
                        break
            break


def _fill_from_hien_trang(stt: int, ref: IndependentRef) -> None:
    if not HIEN_TRANG.exists():
        return
    want = {
        "Vị trí": "address",
        "Chủ đầu tư": "legal_name",
        "Đơn vị khai thác": "legal_name",
    }
    with HIEN_TRANG.open(encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            if str(row.get("stt") or "").strip() != str(stt):
                continue
            if (row.get("loai") or "") != "chi_tiet":
                continue
            hm = (row.get("hang_muc") or "").strip()
            if hm not in want:
                continue
            val = (row.get("noi_dung") or "").strip()
            if not val:
                continue
            field_name = want[hm]
            if field_name == "address" and not ref.address:
                ref.address = val
            elif field_name == "legal_name":
                # Đơn vị khai thác ghi đè Chủ đầu tư nếu có
                if hm == "Đơn vị khai thác" or not ref.legal_name:
                    ref.legal_name = val


def _address_tokens(address: str) -> list[str]:
    """Token địa chỉ có ích để khớp (bỏ cụm chung)."""
    n = normalize_text(address)
    drop = {
        "lo",
        "kcn",
        "khu",
        "vuc",
        "dia",
        "danh",
        "theo",
        "qd",
        "ho",
        "so",
        "lich",
        "su",
        "truoc",
        "sap",
        "xep",
        "va",
        "mot",
        "phan",
        "cu",
        "tai",
        "lieu",
        "quy",
        "hoach",
    }
    parts = [p for p in n.split() if len(p) >= 3 and p not in drop]
    # giữ cụm có ý nghĩa ≥ 4 ký tự
    return [p for p in parts if len(p) >= 4][:12]


def _name_on_page(legal_name: str, page_norm: str) -> bool:
    if not legal_name:
        return False
    nn = normalize_name(legal_name)
    if not nn or len(nn) < 6:
        return False
    if nn in page_norm:
        return True
    # bỏ tiền tố pháp lý còn sót
    compact = re.sub(
        r"\b(cong ty|cong ty cp|cong ty tnhh|tong cong ty|he thong)\b",
        " ",
        nn,
    )
    compact = re.sub(r"\s+", " ", compact).strip()
    if compact and len(compact) >= 6 and compact in page_norm:
        return True
    # fuzzy nhẹ: ≥ 2 token liên tiếp
    tokens = [t for t in compact.split() if len(t) >= 3]
    if len(tokens) >= 2:
        for i in range(len(tokens) - 1):
            pair = f"{tokens[i]} {tokens[i + 1]}"
            if pair in page_norm:
                return True
    return False


def _address_on_page(address: str, page_norm: str) -> tuple[bool, list[str]]:
    tokens = _address_tokens(address)
    if not tokens:
        return False, []
    hits = [t for t in tokens if t in page_norm]
    # cần ≥ 2 token địa bàn, hoặc 1 token dài (≥ 8) kiểu tên khu
    if len(hits) >= 2:
        return True, hits
    if len(hits) == 1 and len(hits[0]) >= 8:
        return True, hits
    return False, hits


def _looks_aggregator_content(text: str, title: str) -> bool:
    """Trang tin tổng hợp / dump nhiều bài không chuyên ICD."""
    blob = normalize_text(f"{title}\n{text[:4000]}")
    newsy = (
        "tin tuc",
        "thoi su",
        "rao vat",
        "dang tin",
        "muc luc bai viet",
        "bai viet lien quan",
        "tin moi nhat",
        "breaking news",
    )
    if sum(1 for h in newsy if h in blob) >= 2 and "cang can" not in blob and "icd" not in blob:
        return True
    return False


def check_s1(text: str, ref: IndependentRef) -> tuple[bool, str, str]:
    """(hit, mst_found, detail)."""
    found = extract_msts(text)
    mst_found = found[0] if found else ""
    if not ref.mst:
        return False, mst_found, "không có MST độc lập để đối chiếu"
    if not found:
        return False, "", "không thấy MST trên trang"
    if ref.mst in found:
        return True, ref.mst, f"MST khớp {ref.mst}"
    return False, mst_found, f"MST trang={mst_found} ≠ ref={ref.mst}"


def check_s2(text: str, ref: IndependentRef) -> tuple[bool, str]:
    page_norm = normalize_text(text)
    name_ok = _name_on_page(ref.legal_name, page_norm)
    addr_ok, addr_hits = _address_on_page(ref.address, page_norm)
    if name_ok and addr_ok:
        return True, f"tên+địa chỉ khớp (địa={addr_hits[:3]})"
    parts = []
    if name_ok:
        parts.append("tên khớp")
    else:
        parts.append("thiếu tên pháp nhân")
    if addr_ok:
        parts.append(f"địa chỉ khớp ({addr_hits[:3]})")
    else:
        parts.append("thiếu địa chỉ")
    return False, "; ".join(parts)


def check_s3(url: str, ref: IndependentRef, *, loai_nguon: str = "") -> tuple[bool, str]:
    """S3: tập đoàn mẹ / VB nhà nước trỏ tới domain — thường truyền từ ngữ cảnh ung_vien."""
    if ref.parent_points_to_domain:
        return True, ref.parent_note or "nguồn thẩm quyền trỏ tới tên miền"
    loai = (loai_nguon or "").lower()
    if loai in ("operator", "operator_network", "tap_doan", "parent", "mang_luoi"):
        return True, f"loai_nguon={loai_nguon} (trang mạng lưới / tập đoàn)"
    if loai in ("van_ban", "gov", "nha_nuoc", "quyet_dinh"):
        # URL đang chấm là VB nhà nước — không phải website DN; S3 không áp cho chính URL này
        # (S3 là "được trỏ tới", không phải "chính URL là VB")
        return False, "URL là văn bản nhà nước, không dùng làm S3 cho chính trang đó"
    return False, "chưa có bằng chứng nguồn thẩm quyền trỏ tới"


def check_p1(url: str, ref: IndependentRef) -> tuple[bool, str]:
    domain = _domain(url)
    host = domain.replace("-", "").replace(".", "")
    host_l = domain.lower()
    for tok in ref.brand_tokens:
        t = strip_accents(tok).lower().replace(" ", "")
        if len(t) < 4:
            continue
        if t in host or t in host_l.replace("-", "").replace(".", ""):
            return True, f"tên miền chứa thương hiệu {tok!r}"
        # dạng có gạch: tan-cang
        dashed = strip_accents(tok).lower().replace(" ", "-")
        if dashed and dashed in host_l:
            return True, f"tên miền chứa thương hiệu {tok!r}"
    return False, "tên miền không chứa thương hiệu"


def check_p2(text: str, title: str = "") -> tuple[bool, str]:
    page_norm = normalize_text(f"{title}\n{text}")
    ops_hits = [h for h in ICD_OPS_HINTS if h in page_norm]
    ops_ok = len(ops_hits) >= 2

    # Ngày cập nhật trong 12 tháng
    now = datetime.now(timezone.utc).astimezone()
    recent = False
    date_note = "không thấy ngày cập nhật"
    # ISO / VN dates
    patterns = [
        r"(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})",
        r"(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})",
        r"(?:cập nhật|cap nhat|ngày|ngay|updated?)\s*[:：]?\s*"
        r"(\d{1,2})[-/.](\d{1,2})[-/.](20\d{2})",
    ]
    candidates: list[datetime] = []
    for pat in patterns:
        for m in re.finditer(pat, text or "", flags=re.I):
            g = m.groups()
            try:
                if len(g[0]) == 4:  # yyyy-mm-dd
                    y, mo, d = int(g[0]), int(g[1]), int(g[2])
                else:
                    d, mo, y = int(g[0]), int(g[1]), int(g[2])
                if mo > 12 and d <= 12:
                    mo, d = d, mo
                dt = datetime(y, mo, d, tzinfo=now.tzinfo)
                candidates.append(dt)
            except ValueError:
                continue
    if candidates:
        newest = max(candidates)
        delta_days = (now - newest).days
        if 0 <= delta_days <= 365:
            recent = True
            date_note = f"cập nhật gần ({newest.date().isoformat()})"
        else:
            date_note = f"ngày cũ nhất/mới={newest.date().isoformat()} (ngoài 12 tháng)"

    if ops_ok and recent:
        return True, f"nội dung ICD ({ops_hits[:3]}) + {date_note}"
    if ops_ok and not recent:
        # vẫn cho P2 nếu nội dung ICD rõ và trang đủ dài (nhiều site DN không ghi ngày)
        if len(re.sub(r"\s+", "", text or "")) > 800:
            return True, f"nội dung ICD rõ ({ops_hits[:3]}); {date_note} — chấp nhận theo độ dài"
        return False, f"có nội dung ICD nhưng chưa đủ tín hiệu cập nhật: {date_note}"
    return False, f"thiếu nội dung khai thác ICD (hits={ops_hits[:2]})"


def _mismatch_reject(
    text: str,
    ref: IndependentRef,
    *,
    s1: bool,
    s2: bool,
) -> str:
    """Loại nếu MST hoặc địa chỉ lệch rõ (nghi giả mạo)."""
    found = extract_msts(text)
    if ref.mst and found and ref.mst not in found and not s1:
        return f"MST lệch (trang có {found[0]}, độc lập {ref.mst})"
    if ref.legal_name and ref.address:
        page_norm = normalize_text(text)
        name_ok = _name_on_page(ref.legal_name, page_norm)
        addr_ok, _ = _address_on_page(ref.address, page_norm)
        # Có tên pháp nhân khác rõ + địa chỉ không khớp → nghi giả mạo
        if not s2 and name_ok and not addr_ok and len(_address_tokens(ref.address)) >= 2:
            # chỉ loại khi trang cũng lộ địa chỉ khác (có số nhà / KCN khác)
            other_addr = bool(
                re.search(
                    r"(kcn|khu công nghiệp|địa chỉ|dia chi)\s*[:：]?",
                    text or "",
                    flags=re.I,
                )
            )
            if other_addr:
                return "tên khớp nhưng địa chỉ không khớp nguồn độc lập (nghi giả mạo)"
    return ""


def conclude(
    *,
    s1: bool,
    s2: bool,
    s3: bool,
    p1: bool,
    p2: bool,
    reject_reason: str = "",
) -> tuple[str, int, int]:
    if reject_reason:
        return CONCLUSION_REJECT, int(s1) + int(s2) + int(s3), int(p1) + int(p2)
    strong = int(s1) + int(s2) + int(s3)
    weak = int(p1) + int(p2)
    if strong >= 2 or (strong >= 1 and weak >= 2):
        return CONCLUSION_VERIFIED, strong, weak
    if strong == 1 or (strong == 0 and weak >= 1):
        return CONCLUSION_POSSIBLE, strong, weak
    if strong == 0 and weak == 0:
        return CONCLUSION_REJECT, strong, weak
    return CONCLUSION_POSSIBLE, strong, weak


def load_text_file(path: Path) -> tuple[str, str]:
    """Đọc evidence/cache text; bỏ header fetch nếu có."""
    raw = path.read_text(encoding="utf-8", errors="replace")
    title = ""
    if raw.startswith("URL:") and "=" * 10 in raw:
        header, _, body = raw.partition("\n" + "=" * 60 + "\n")
        for line in header.splitlines():
            if line.startswith("Title:"):
                title = line[len("Title:") :].strip()
        return body.lstrip("\n"), title
    return raw, title


def verify_text(
    text: str,
    *,
    stt: str = "",
    url: str = "",
    ref: IndependentRef | None = None,
    title: str = "",
    loai_nguon: str = "",
    text_path: str = "",
    fetched_at: str = "",
) -> VerifyResult:
    """Chấm xác minh từ sẵn text (không fetch)."""
    ref = ref or IndependentRef()
    domain = _domain(url) if url else ""
    result = VerifyResult(
        stt=str(stt),
        url=url,
        domain=domain,
        legal_name_ref=ref.legal_name,
        address_ref=ref.address,
        mst_ref=ref.mst,
        title=title,
        text_path=text_path,
        fetched_at=fetched_at or _now_iso(),
    )

    # Loại ngay: danh bạ / aggregator
    if url and is_directory_domain(url):
        result.conclusion = CONCLUSION_REJECT
        result.reject_reason = f"danh bạ doanh nghiệp ({domain})"
        result.signals_detail = result.reject_reason
        return result
    if url and is_aggregator_domain(url):
        result.conclusion = CONCLUSION_REJECT
        result.reject_reason = f"trang rao vặt / aggregator ({domain})"
        result.signals_detail = result.reject_reason
        return result
    if _looks_aggregator_content(text, title):
        result.conclusion = CONCLUSION_REJECT
        result.reject_reason = "nội dung dạng tin tổng hợp / dump, không phải website DN"
        result.signals_detail = result.reject_reason
        return result

    s1, mst_found, d1 = check_s1(text, ref)
    s2, d2 = check_s2(text, ref)
    s3, d3 = check_s3(url, ref, loai_nguon=loai_nguon)
    p1, dp1 = check_p1(url, ref)
    p2, dp2 = check_p2(text, title)

    result.s1, result.s2, result.s3 = s1, s2, s3
    result.p1, result.p2 = p1, p2
    result.mst_found = mst_found

    mismatch = _mismatch_reject(text, ref, s1=s1, s2=s2)
    details = [f"S1:{d1}", f"S2:{d2}", f"S3:{d3}", f"P1:{dp1}", f"P2:{dp2}"]
    result.signals_detail = " | ".join(details)

    conclusion, strong, weak = conclude(
        s1=s1, s2=s2, s3=s3, p1=p1, p2=p2, reject_reason=mismatch
    )
    result.conclusion = conclusion
    result.strong_count = strong
    result.weak_count = weak
    result.reject_reason = mismatch
    return result


def verify_url(
    stt: str | int,
    url: str,
    *,
    ref: IndependentRef | None = None,
    mst: str = "",
    legal_name: str = "",
    address: str = "",
    parent_points_to_domain: bool = False,
    parent_note: str = "",
    text_path: str | Path | None = None,
    loai_nguon: str = "",
    use_cache: bool = True,
    keys: dict[int, IcdKey] | None = None,
) -> VerifyResult:
    """Fetch (hoặc đọc file text) rồi chấm xác minh."""
    if ref is None:
        ref = load_independent_ref(
            stt,
            mst=mst,
            legal_name=legal_name,
            address=address,
            parent_points_to_domain=parent_points_to_domain,
            parent_note=parent_note,
            keys=keys,
        )
    else:
        if parent_points_to_domain:
            ref.parent_points_to_domain = True
            ref.parent_note = parent_note or ref.parent_note

    title = ""
    fetched_at = ""
    tpath = ""

    if text_path:
        path = Path(text_path)
        text, title = load_text_file(path)
        tpath = str(path.relative_to(ROOT)) if path.is_absolute() and ROOT in path.parents else str(path)
        fetched_at = _now_iso()
    else:
        # Loại sớm theo domain — không cần fetch
        if is_directory_domain(url) or is_aggregator_domain(url):
            return verify_text(
                "",
                stt=str(stt),
                url=url,
                ref=ref,
                loai_nguon=loai_nguon,
            )
        fr = fetch(url, stt=str(stt), use_cache=use_cache)
        text = fr.text or ""
        title = fr.title or ""
        tpath = fr.text_path or ""
        fetched_at = fr.fetched_at or _now_iso()
        if fr.status not in ("MỞ_ĐƯỢC", "LỖI_SSL_MỞ_ĐƯỢC"):
            result = VerifyResult(
                stt=str(stt),
                url=url,
                domain=_domain(url),
                conclusion=CONCLUSION_REJECT,
                reject_reason=f"không mở được trang: {fr.status} ({fr.reason})",
                signals_detail=f"fetch={fr.status}",
                legal_name_ref=ref.legal_name,
                address_ref=ref.address,
                mst_ref=ref.mst,
                title=title,
                text_path=tpath,
                fetched_at=fetched_at,
            )
            return result

    return verify_text(
        text,
        stt=str(stt),
        url=url,
        ref=ref,
        title=title,
        loai_nguon=loai_nguon,
        text_path=tpath,
        fetched_at=fetched_at,
    )


def append_csv(rows: list[VerifyResult], path: Path = OUT_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new_file = not path.exists()
    with path.open("a" if not new_file else "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        if new_file:
            w.writeheader()
        for row in rows:
            w.writerow(row.to_dict())


def write_csv(rows: list[VerifyResult], path: Path = OUT_CSV) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        for row in rows:
            w.writerow(row.to_dict())


def verify_from_ung_vien(
    path: Path = UNG_VIEN,
    *,
    out_path: Path = OUT_CSV,
    use_cache: bool = True,
    limit: int | None = None,
) -> list[VerifyResult]:
    """Chạy trên data/ung_vien.csv. Bỏ qua nếu file không tồn tại."""
    if not path.exists():
        print(f"Bỏ qua: không có {path}", flush=True)
        return []

    keys = load_keys()
    rows: list[VerifyResult] = []
    with path.open(encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        items = list(reader)
    if limit is not None:
        items = items[:limit]

    for row in items:
        stt = (row.get("stt") or "").strip()
        url = (row.get("url") or "").strip()
        if not url:
            continue
        loai = (row.get("loai_nguon") or "").strip()
        parent = loai.lower() in (
            "operator",
            "operator_network",
            "tap_doan",
            "parent",
            "mang_luoi",
        )
        print(f"→ [{stt}] {url}", flush=True)
        vr = verify_url(
            stt,
            url,
            loai_nguon=loai,
            parent_points_to_domain=parent,
            parent_note=f"ứng viên từ {loai}" if parent else "",
            use_cache=use_cache,
            keys=keys,
        )
        print(
            f"  {vr.conclusion} S={vr.strong_count} P={vr.weak_count} "
            f"[{int(vr.s1)}{int(vr.s2)}{int(vr.s3)}/{int(vr.p1)}{int(vr.p2)}] "
            f"{vr.reject_reason or vr.signals_detail[:80]}",
            flush=True,
        )
        rows.append(vr)

    write_csv(rows, out_path)
    print(f"Wrote {len(rows)} rows → {out_path}", flush=True)
    return rows


# --- ca thử tổng hợp (≥5) ----------------------------------------------------


def _synthetic_cases() -> list[tuple[str, dict[str, Any], str]]:
    """(id, kwargs cho verify_text, expected conclusion)."""
    cases: list[tuple[str, dict[str, Any], str]] = []

    # 1) verified: S1 + S2
    cases.append(
        (
            "verified_s1_s2",
            {
                "stt": "4",
                "url": "https://www.tancang-haiphong.vn/",
                "title": "ICD Tân Cảng Hải Phòng",
                "text": (
                    "Công ty CP ICD Tân Cảng Hải Phòng\n"
                    "Mã số thuế: 0200123456\n"
                    "Địa chỉ: Lô CN 3.2.F, KCN Đình Vũ, Hải Phòng\n"
                    "Dịch vụ khai thác cảng cạn, biểu giá container TEU, "
                    "liên hệ khai thác và thủ tục hải quan.\n"
                    "Cập nhật: 15/03/2026"
                ),
                "ref": IndependentRef(
                    mst="0200123456",
                    legal_name="Công ty CP ICD Tân Cảng Hải Phòng",
                    address="Lô CN 3.2.F, KCN Đình Vũ, Hải Phòng",
                    brand_tokens=["tancang", "hai phong", "dinh vu"],
                ),
            },
            CONCLUSION_VERIFIED,
        )
    )

    # 2) verified: S3 + P1 + P2 (1 mạnh + 2 phụ)
    cases.append(
        (
            "verified_s3_p1_p2",
            {
                "stt": "15",
                "url": "https://longbinh.tancang.com.vn/icd",
                "title": "ICD Tân Cảng Long Bình",
                "text": (
                    "Trang ICD Long Bình thuộc hệ thống Tân Cảng. "
                    "Dịch vụ khai thác bãi container, biểu giá TEU, "
                    "thủ tục hải quan và lịch tàu. Cập nhật 01/08/2026."
                ),
                "ref": IndependentRef(
                    legal_name="Công ty CP ICD Tân Cảng Long Bình",
                    address="Biên Hòa, Đồng Nai",
                    brand_tokens=["longbinh", "long binh", "tancang"],
                    parent_points_to_domain=True,
                    parent_note="trang mạng lưới Tân Cảng trỏ tới",
                ),
            },
            CONCLUSION_VERIFIED,
        )
    )

    # 3) possible: chỉ 1 mạnh (S2)
    cases.append(
        (
            "possible_s2_only",
            {
                "stt": "2",
                "url": "https://example-logistics.vn/gioi-thieu",
                "title": "Giới thiệu",
                "text": (
                    "Công ty TNHH Hải Linh trụ sở tại xã Sông Lô, TP Việt Trì. "
                    "Chúng tôi cung cấp dịch vụ kho bãi."
                ),
                "ref": IndependentRef(
                    legal_name="Công ty TNHH Hải Linh",
                    address="xã Sông Lô, TP Việt Trì",
                    brand_tokens=["hailinh", "hai linh"],
                ),
            },
            CONCLUSION_POSSIBLE,
        )
    )

    # 4) reject directory
    cases.append(
        (
            "reject_directory",
            {
                "stt": "1",
                "url": "https://masothue.com/0200123456-cong-ty-cp-vimc",
                "title": "Tra cứu mã số thuế",
                "text": "Hồ sơ doanh nghiệp trên masothue. Mã số thuế 0200123456.",
                "ref": IndependentRef(mst="0200123456", legal_name="VIMC", address="Lào Cai"),
            },
            CONCLUSION_REJECT,
        )
    )

    # 5) reject mismatch MST
    cases.append(
        (
            "reject_mismatch_mst",
            {
                "stt": "4",
                "url": "https://fake-tancang-hp.vn/",
                "title": "Tân Cảng Hải Phòng (giả)",
                "text": (
                    "Công ty CP ICD Tân Cảng Hải Phòng\n"
                    "Mã số thuế: 9999999999\n"
                    "Địa chỉ khác: 123 Đường Fake, Quận 1, TP.HCM\n"
                ),
                "ref": IndependentRef(
                    mst="0200123456",
                    legal_name="Công ty CP ICD Tân Cảng Hải Phòng",
                    address="Lô CN 3.2.F, KCN Đình Vũ, Hải Phòng",
                    brand_tokens=["tancang"],
                ),
            },
            CONCLUSION_REJECT,
        )
    )

    # 6) S3 parent-link only → possible (1 mạnh)
    cases.append(
        (
            "possible_s3_parent",
            {
                "stt": "107",
                "url": "https://depot.example.vn/tbs-tan-van",
                "title": "Depot",
                "text": "Trang giới thiệu ngắn về bãi.",
                "ref": IndependentRef(
                    legal_name="TBS",
                    address="Tân Vạn",
                    brand_tokens=["tbs"],
                    parent_points_to_domain=True,
                    parent_note="TBS network page links here",
                ),
                "loai_nguon": "operator",
            },
            CONCLUSION_POSSIBLE,
        )
    )

    return cases


def run_unit_tests() -> int:
    print("=== P3.4 verify_website unit tests ===", flush=True)
    ok_all = True
    for case_id, kwargs, expect in _synthetic_cases():
        r = verify_text(**kwargs)
        passed = r.conclusion == expect
        # ca directory phải có reject_reason danh bạ
        if case_id == "reject_directory":
            passed = passed and "danh bạ" in (r.reject_reason or "").lower()
        if case_id == "reject_mismatch_mst":
            passed = passed and "MST" in (r.reject_reason or "")
        if case_id == "verified_s3_p1_p2":
            passed = passed and r.s3 and r.p1 and r.p2
        if case_id == "possible_s3_parent":
            passed = passed and r.s3 and r.strong_count == 1
        print(
            f"{'PASS' if passed else 'FAIL'} [{case_id}] "
            f"got={r.conclusion!r} expect={expect!r} "
            f"S1={int(r.s1)} S2={int(r.s2)} S3={int(r.s3)} "
            f"P1={int(r.p1)} P2={int(r.p2)} "
            f"reject={r.reject_reason!r}",
            flush=True,
        )
        ok_all = ok_all and passed

    # Ghi CSV mẫu để kiểm tra schema
    sample_rows = [verify_text(**kw) for _, kw, _ in _synthetic_cases()]
    sample_out = ROOT / "data" / "website_verify_test.csv"
    write_csv(sample_rows, sample_out)
    print(f"Wrote sample → {sample_out}", flush=True)
    print("ALL PASS" if ok_all else "SOME FAILED", flush=True)
    return 0 if ok_all else 1


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "test":
        return run_unit_tests()

    if len(argv) >= 3 and argv[1] == "from-csv":
        path = Path(argv[2])
        if not path.is_absolute():
            path = ROOT / path
        limit = None
        if "--limit" in argv:
            limit = int(argv[argv.index("--limit") + 1])
        use_cache = "--no-cache" not in argv
        verify_from_ung_vien(path, use_cache=use_cache, limit=limit)
        return 0

    if len(argv) >= 3 and argv[1] != "from-csv":
        stt, url = argv[1], argv[2]
        text_file = None
        if "--text" in argv:
            text_file = Path(argv[argv.index("--text") + 1])
        mst = ""
        if "--mst" in argv:
            mst = argv[argv.index("--mst") + 1]
        parent = "--s3" in argv
        loai = ""
        if "--loai" in argv:
            loai = argv[argv.index("--loai") + 1]
        write = "--write" in argv
        vr = verify_url(
            stt,
            url,
            mst=mst,
            parent_points_to_domain=parent,
            parent_note="CLI --s3" if parent else "",
            text_path=text_file,
            loai_nguon=loai,
            use_cache="--no-cache" not in argv,
        )
        print(vr.to_json())
        if write:
            append_csv([vr])
            print(f"Appended → {OUT_CSV}", flush=True)
        return 0 if vr.conclusion != CONCLUSION_REJECT else 1

    print("Usage: python3 scripts/verify_website.py test")
    print("       python3 scripts/verify_website.py <stt> <url> [--mst MST] [--s3] [--text FILE] [--loai LOAI] [--write] [--no-cache]")
    print("       python3 scripts/verify_website.py from-csv data/ung_vien.csv [--limit N] [--no-cache]")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
