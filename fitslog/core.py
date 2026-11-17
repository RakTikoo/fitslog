"""Core scanning logic for fitslog.

Reads FITS *headers only* (image data is never loaded) from every FITS file
under a directory tree and normalises the handful of keywords a night log
needs into one fixed set of columns, even though every observatory /
instrument / capture program spells those keywords differently.

THE ALIAS TABLE lives in ``ALIASES`` below -- it is the single documented
place where keyword spellings are mapped to normalised columns.  Lookup is
case-insensitive and the first alias in each list that is present (and
non-empty) wins.
"""

from __future__ import annotations

import csv
import math
import os
import re
import warnings
from collections import Counter
from pathlib import Path

from astropy.io import fits

__all__ = [
    "ALIASES",
    "COLUMNS",
    "AUDIT_COLUMNS",
    "FLAG_UNREADABLE",
    "FLAG_MISSING_OBJECT",
    "FLAG_MISSING_DATE",
    "FLAG_MISSING_EXPTIME",
    "FLAG_DUPLICATE_KEYWORD",
    "FLAG_NO_WCS",
    "FLAG_INVALID_COORDINATE",
    "scan_directory",
    "write_log_csv",
    "write_audit_csv",
    "summarise",
]

# ---------------------------------------------------------------------------
# THE ALIAS TABLE.
#
# Normalised column -> FITS keywords to try, in priority order.
# Every observatory spells these differently; add new spellings here and
# nowhere else.  Matching is case-insensitive.
# ---------------------------------------------------------------------------
ALIASES = {
    "date_obs":   ["DATE-OBS", "DATE_OBS"],
    "object":     ["OBJECT", "TARGET", "OBJNAME"],
    "filter":     ["FILTER", "FILTER1", "FILTER2", "FILTNAME"],
    "exptime":    ["EXPTIME", "EXPOSURE", "EXPT"],
    "instrument": ["INSTRUME", "INSTRUMENT"],
    "telescope":  ["TELESCOP", "TELESCOPE"],
    "ra":         ["RA", "OBJRA", "RA_OBJ"],
    "dec":        ["DEC", "OBJDEC", "DEC_OBJ"],
    "airmass":    ["AIRMASS"],
    "observer":   ["OBSERVER", "OBSERV"],
    "imagetyp":   ["IMAGETYP"],
}

COLUMNS = [
    "file", "folder", "date_obs", "object", "filter", "exptime_s",
    "instrument", "telescope", "ra_deg", "dec_deg", "airmass",
    "observer", "image_type",
]

AUDIT_COLUMNS = ["file", "folder", "flag", "detail"]

FLAG_UNREADABLE = "unreadable"
FLAG_MISSING_OBJECT = "missing_object"
FLAG_MISSING_DATE = "missing_date"
FLAG_MISSING_EXPTIME = "missing_exptime"
FLAG_DUPLICATE_KEYWORD = "duplicate_keyword"
FLAG_NO_WCS = "no_wcs"
FLAG_INVALID_COORDINATE = "invalid_coordinate"

FITS_SUFFIXES = {".fits", ".fit", ".fts"}

# Trailing wrappers stripped (one layer) before the suffix check, so the
# very common compressed forms (``name.fits.gz`` etc.) are discovered too.
# Astropy opens gzip/bzip2/xz-compressed FITS transparently.  ``.fz`` is
# the fpack tile-compression suffix (``name.fits.fz``), also read by
# Astropy directly.
_WRAPPER_SUFFIXES = (".gz", ".bz2", ".xz", ".fz")


def _is_fits_filename(name):
    """True if *name* names a FITS file, incl. compressed wrappers."""
    n = name.lower()
    for wrapper in _WRAPPER_SUFFIXES:
        if n.endswith(wrapper):
            n = n[: -len(wrapper)]
            break
    return any(n.endswith(suffix) for suffix in FITS_SUFFIXES)

# Keywords that legitimately repeat in a header and are never "duplicates".
_REPEATABLE = {"", "COMMENT", "HISTORY", "HIERARCH", "CONTINUE"}


# ---------------------------------------------------------------------------
# Value helpers
# ---------------------------------------------------------------------------

def _sexagesimal_to_float(text):
    """Convert '12:34:56.7' / '12 34 56.7' / '12h34m56.7s' to a float.

    The result is in units of the first component (hours for RA, degrees
    for Dec).  A leading '-' applies to the whole value, as FITS Dec
    strings require.
    """
    s = str(text).strip()
    sign = -1.0 if s.startswith("-") else 1.0
    s = s.lstrip("+-").strip()
    s = s.replace("°", ":")
    # Unit letters / symbols used as component separators: hours or
    # degrees first (h/d), then minutes (m or '), then seconds (s or ").
    s = re.sub(r"[hHdD]", ":", s)
    s = re.sub(r"[mM'′]", ":", s)
    s = re.sub(r"[sS\"″]", "", s)
    parts = [p for p in re.split(r"[:\s]+", s) if p]
    if not parts:
        raise ValueError("empty sexagesimal value")
    if len(parts) > 3:
        raise ValueError("too many sexagesimal components")
    total = 0.0
    weight = 1.0
    for part in parts:
        total += float(part) * weight
        weight /= 60.0
    return sign * total


def _looks_sexagesimal(text):
    s = str(text).strip()
    if any(ch in s for ch in ":hH°dD'\"′″mMsS"):
        # 'm'/'s' alone could appear in a plain word, but a coordinate
        # value that is a plain word is unparseable either way, so
        # treating it as a sexagesimal attempt (and failing) is fine.
        return True
    # '12 34 56' style: more than one numeric component separated by spaces.
    return len([p for p in re.split(r"\s+", s) if p]) > 1


def ra_to_degrees(value):
    """RA value (degrees number, or sexagesimal hours string) -> degrees."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a coordinate")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        s = str(value).strip()
        if not s:
            return None
        if _looks_sexagesimal(s):
            result = _sexagesimal_to_float(s) * 15.0
        else:
            result = float(s)
    if not math.isfinite(result):
        raise ValueError("non-finite coordinate")
    return result


def dec_to_degrees(value):
    """Dec value (degrees number, or sexagesimal degrees string) -> degrees."""
    if value is None:
        return None
    if isinstance(value, bool):
        raise ValueError("boolean is not a coordinate")
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        s = str(value).strip()
        if not s:
            return None
        if _looks_sexagesimal(s):
            result = _sexagesimal_to_float(s)
        else:
            result = float(s)
    if not math.isfinite(result):
        raise ValueError("non-finite coordinate")
    return result


def _fmt_number(value):
    if value is None:
        return ""
    s = f"{float(value):.8f}".rstrip("0").rstrip(".")
    return s if s not in ("", "-0") else "0"


def _clean_str(value):
    if value is None:
        return ""
    return str(value).strip()


def classify_image_type(raw):
    """Map an IMAGETYP value to science/flat/dark/bias when recognisable."""
    v = _clean_str(raw).lower()
    if not v:
        return ""
    if "flat" in v:
        return "flat"
    if "dark" in v:
        return "dark"
    if "bias" in v or "zero" in v:
        return "bias"
    if any(word in v for word in ("object", "science", "light", "sky", "target")):
        return "science"
    return v


# ---------------------------------------------------------------------------
# Header handling
# ---------------------------------------------------------------------------

def _header_map(header):
    """Upper-case keyword -> first value, from the header's raw cards."""
    mapping = {}
    for card in header.cards:
        key = (card.keyword or "").upper()
        if key and key not in mapping:
            mapping[key] = card.value
    return mapping


def _is_hierarch_card(card):
    # Astropy exposes HIERARCH cards with the long key as ``card.keyword``
    # (e.g. "ESO DET CHIP", or "INSTRUMENT" for >8-char keywords), never
    # the literal string "HIERARCH" -- the exemption in _REPEATABLE would
    # therefore never fire.  The card's hierarch flag is the real signal.
    return bool(getattr(card, "_hierarch", False))


def _duplicate_keywords(header):
    counts = Counter(
        (card.keyword or "").upper()
        for card in header.cards
        if (card.keyword or "").upper() not in _REPEATABLE
        and not _is_hierarch_card(card)
    )
    return sorted(k for k, n in counts.items() if n > 1)


def _first(mapping, normalised_name):
    for keyword in ALIASES[normalised_name]:
        if keyword in mapping:
            value = mapping[keyword]
            if value is not None and _clean_str(value) != "":
                return value
    return None


def _header_score(mapping):
    return sum(1 for name in ALIASES if _first(mapping, name) is not None)


def _choose_header(hdul):
    """Pick the header to log.

    The primary header wins whenever it carries any recognised keyword.
    If it carries none (e.g. a bare primary in front of the real header),
    the first extension header that carries any recognised keyword is
    used instead.  If no header carries anything, the primary is used
    (and the file will be flagged for its missing fields).
    """
    primary = hdul[0].header
    primary_map = _header_map(primary)
    if _header_score(primary_map) > 0 or len(hdul) == 1:
        return primary, primary_map
    for hdu in hdul[1:]:
        mapping = _header_map(hdu.header)
        if _header_score(mapping) > 0:
            return hdu.header, mapping
    return primary, primary_map


_WCS_MATRIX_RE = re.compile(r"^(?:CD|PC)(?:\d+_\d+|\d{6})$")


def _has_wcs(mapping):
    keys = set(mapping)
    if "CDELT1" in keys or "CDELT2" in keys:
        return True
    # Modern CDi_j / PCi_j, plus the legacy IRAF CD001001 / PC001001
    # packed forms.  Anchored so unrelated CD*/PC* keywords (e.g. a
    # hypothetical CDS_1) do not count as a WCS matrix.
    return any(_WCS_MATRIX_RE.match(k) for k in keys)


def _as_float(value):
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    else:
        try:
            result = float(str(value).strip())
        except (TypeError, ValueError):
            return None
    # 'nan'/'inf' strings parse as floats but are not usable numbers:
    # treat them as absent so the missing-field flag fires.
    return result if math.isfinite(result) else None


# ---------------------------------------------------------------------------
# Scanning
# ---------------------------------------------------------------------------

def _scan_one(path, root):
    """Return (row_dict, [audit_dict, ...]) for one file.  Never raises."""
    rel_folder = os.path.relpath(path.parent, root)
    folder = "" if rel_folder == "." else rel_folder
    row = {col: "" for col in COLUMNS}
    row["file"] = path.name
    row["folder"] = folder
    audits = []

    def flag(name, detail=""):
        audits.append(
            {"file": path.name, "folder": folder, "flag": name, "detail": detail}
        )

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with fits.open(path, memmap=False) as hdul:
                header, mapping = _choose_header(hdul)
                duplicates = _duplicate_keywords(header)
    except Exception as exc:  # corrupt / unreadable: audit it, never crash
        flag(FLAG_UNREADABLE, f"{type(exc).__name__}: {exc}"[:200])
        return row, audits

    row["date_obs"] = _clean_str(_first(mapping, "date_obs"))
    row["object"] = _clean_str(_first(mapping, "object"))
    row["filter"] = _clean_str(_first(mapping, "filter"))
    row["instrument"] = _clean_str(_first(mapping, "instrument"))
    row["telescope"] = _clean_str(_first(mapping, "telescope"))
    row["observer"] = _clean_str(_first(mapping, "observer"))
    row["image_type"] = classify_image_type(_first(mapping, "imagetyp"))

    exptime = _as_float(_first(mapping, "exptime"))
    row["exptime_s"] = _fmt_number(exptime)
    row["airmass"] = _fmt_number(_as_float(_first(mapping, "airmass")))

    # An unparseable coordinate must not leak raw text into the numeric
    # ra_deg/dec_deg columns (that silently corrupts a sorted log); the
    # column is left empty and the file is flagged instead.
    ra_raw = _first(mapping, "ra")
    try:
        row["ra_deg"] = _fmt_number(ra_to_degrees(ra_raw))
    except (TypeError, ValueError):
        row["ra_deg"] = ""
        if ra_raw is not None:
            flag(FLAG_INVALID_COORDINATE, f"RA: {_clean_str(ra_raw)}")
    dec_raw = _first(mapping, "dec")
    try:
        row["dec_deg"] = _fmt_number(dec_to_degrees(dec_raw))
    except (TypeError, ValueError):
        row["dec_deg"] = ""
        if dec_raw is not None:
            flag(FLAG_INVALID_COORDINATE, f"DEC: {_clean_str(dec_raw)}")

    if not row["object"]:
        flag(FLAG_MISSING_OBJECT)
    if not row["date_obs"]:
        flag(FLAG_MISSING_DATE)
    if exptime is None:
        flag(FLAG_MISSING_EXPTIME)
    if duplicates:
        flag(FLAG_DUPLICATE_KEYWORD, ", ".join(duplicates))
    if not _has_wcs(mapping):
        flag(FLAG_NO_WCS)

    return row, audits


def find_fits_files(root):
    """All FITS files under *root*, recursively, in sorted order."""
    root = Path(root)
    found = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames.sort()
        for name in sorted(filenames):
            if _is_fits_filename(name):
                found.append(Path(dirpath) / name)
    return found


def scan_directory(root):
    """Scan *root* recursively.  Returns (rows, audits)."""
    root = Path(root)
    rows, audits = [], []
    for path in find_fits_files(root):
        row, file_audits = _scan_one(path, root)
        rows.append(row)
        audits.extend(file_audits)
    return rows, audits


def write_log_csv(rows, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerows(rows)


def write_audit_csv(audits, out_path):
    with open(out_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=AUDIT_COLUMNS)
        writer.writeheader()
        writer.writerows(audits)


def summarise(rows, audits):
    """Plain-text summary: counts plus the top flag counts."""
    flagged_files = {(a["folder"], a["file"]) for a in audits}
    flag_counts = Counter(a["flag"] for a in audits)
    lines = [
        f"Files scanned: {len(rows)}",
        f"Rows written: {len(rows)}",
        f"Flagged files: {len(flagged_files)}",
    ]
    if flag_counts:
        lines.append("Top flags:")
        for name, count in flag_counts.most_common():
            lines.append(f"  {name}: {count}")
    return "\n".join(lines), flag_counts, flagged_files
