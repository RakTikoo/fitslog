# fitslog — Independent Adversarial Review

Reviewer: independent subagent (did not build this tool). Date: 2026-11-17.
Scope: the gauntlet was run locally; at review time nothing had been published or pushed.
Environment: Python 3.12.3, Astropy 8.0.2 (fresh venv), project venv Astropy
for the test battery.

## What was checked

- **(a) Adversarial probing** (~50 crafted cases, run against `scan_directory`,
  the coordinate converters, `_has_wcs`, and the CLI): empty/zero-byte files,
  truncated FITS (header-only, data-truncated, mid-block), text files with a
  `.fits` name, `.fits.gz`/`.bz2`/`.xz`/`.fz` names, upper/mixed-case suffixes,
  a file named exactly `.fits`, directories named `*.fits`, symlinked files and
  directories, duplicate keywords (primary, chosen extension, HIERARCH,
  COMMENT/HISTORY, CONTINUE long strings), bare-primary + full-extension MEFs,
  WCS only in an extension, table-only files, header-only (NAXIS=0) files,
  lowercase keywords written as raw bytes, raw `NaN` header cards, boolean
  `EXPTIME`, string/non-numeric/`nan`/`inf` numeric fields, negative exposure,
  out-of-range RA/Dec, invalid coordinate strings, DMS sexagesimal variants
  (`d`/`'`/`"` forms, `-00:30:00`), alias priority and empty-string fallthrough,
  objects with commas/quotes, empty trees, very long paths, CLI with a missing
  directory and with unwritable `--out`/`--audit` paths.
- **(b) Independent oracle**: 5 hand-crafted FITS files with hand-computed
  ground truth (sexagesimal conversions computed by hand, all three alias
  families, PC+ CDELT WCS, a bare file, a corrupt file), checked
  header-by-header against the tool's rows and audit flags: **36/36 passed**
  before the fixes and **36/36 passed** after.
- **(c) Fresh-venv install + README demo**: full `pip install` of the local
  tree into a brand-new venv succeeded (fitslog 0.1.0, Astropy 8.0.2 pulled as
  the dependency) and the README demo reproduced **exactly** — console summary,
  `nightlog.csv`, and `audit.csv` all match the README (the README shows the
  corrupt file's audit detail with a trailing `...`; the full real detail is
  the same text untruncated). Note: the venv had to live on the disk
  filesystem rather than `/tmp`, because `/tmp` is a 512 MB tmpfs that was
  >90 % full with sibling review venvs — a bare `/tmp` venv did accept the
  fitslog package itself (`--no-deps`), failing only on the Astropy download
  for space. After the fixes, a force-reinstall into the fresh venv reproduced
  the demo byte-identically.
- **(d) Test battery**: original suite **15 tests, all passing**. After fixes
  and 8 new regression tests: **23 tests, all passing**
  (`~/workspace/astro-tools/.venv/bin/python run_tests.py`).
- **(e) README honesty**: see "README assessment" below.

## Findings and fixes

### HIGH — Compressed FITS files were silently ignored
`find_fits_files` matched only the final suffix, so a tree of `.fits.gz`
files (an extremely common form for archived telescope data) scanned as
**zero files with no warning** — an empty log that looks like an empty tree.
Also missed: `.fit.gz`, `.fts.gz`, `.fits.bz2`, `.fits.xz`, `.fits.fz`, and a
file named exactly `.fits`.
**Fix:** new `_is_fits_filename()` strips one wrapper suffix
(`.gz`/`.bz2`/`.xz`/`.fz`) before the FITS-suffix check. Verified: gz/bz2/xz
fixtures scan and parse (Astropy reads them transparently); README usage line
updated.

### MEDIUM — HIERARCH duplicates were flagged despite the documented exemption
README: "`COMMENT`, `HISTORY`, and `HIERARCH` cards are exempt — they repeat
legitimately." The code exempted the literal keyword `"HIERARCH"`, but Astropy
exposes a HIERARCH card's keyword as its long key (e.g. `ESO DET CHIP`, or
`INSTRUMENT` for >8-character keywords), so the exemption was dead code: a
duplicated HIERARCH key was flagged `duplicate_keyword` with the long key as
the detail. Distinct HIERARCH keys (normal ESO/VLT usage) were correctly not
flagged.
**Fix:** `_duplicate_keywords` now also exempts cards whose Astropy hierarch
flag is set (`card._hierarch`). Regression test added.

### MEDIUM — Unparseable RA/Dec leaked raw text into the numeric columns, unflagged
A header with `RA = 'not-a-number'` produced `ra_deg = "not-a-number"` with
**no audit flag**, silently corrupting a column the README defines as decimal
degrees. Relatedly, string `"nan"`/`"inf"` values parsed as floats and were
emitted literally (`exptime_s = "nan"`), and a boolean `EXPTIME` was logged
as `1` (Python `bool` is an `int` subclass).
**Fix:** new audit flag `invalid_coordinate` (detail names the axis and raw
value); the column is left empty on parse failure. `_as_float` and both
coordinate converters now reject booleans and non-finite values
(`nan`/`inf` count as "wasn't a number", so `missing_exptime` fires for them,
matching the README's existing wording). Regression tests added; README audit
table documents the new flag.

### LOW — Sexagesimal parser missed common DMS spellings
Dec forms `-05d23m27s`, `-05 23' 27"` and `-05:23'27"` failed to parse (the
parser only knew `h`/`m`/`s` and `:`/space separators), landing in the
raw-passthrough path above. A value with >3 components silently dropped the
extras.
**Fix:** `d`/`D`, `'`, `"` (and Unicode prime marks) are now accepted as
separators; >3 components now raise instead of truncating. All previously
supported forms verified unchanged, including `-00:30:00` → −0.5°.

### LOW — WCS detection matched non-WCS keywords and missed the legacy matrix form
`_has_wcs` accepted any keyword starting `CD`/`PC` containing `_` (a
hypothetical `CDS_1` counted as WCS), and missed the legacy IRAF packed forms
`CD001001`/`PC001001`.
**Fix:** anchored regex `^(CD|PC)(\d+_\d+|\d{6})$`. Regression test added.

### LOW — CLI crashed with a traceback on an unwritable output path
`fitslog scan … --out /nonexistent/out.csv` raised an unhandled
`FileNotFoundError` (exit 1 with traceback), unlike the clean exit-2 error for
a missing input directory.
**Fix:** `cli.main` catches `OSError` from the CSV writers, prints a clean
message to stderr, and returns 2. Regression test added.

## Observed, not fixed (documented design or out of scope)

- **Primary-header-wins is documented design.** If the primary header carries
  even one recognised keyword (e.g. only `FILTER`), a fuller extension header
  is ignored, and a file whose WCS lives only in an extension is flagged
  `no_wcs`. This follows README "Which header is used" / "One row per file,
  from one header", so it was left as-is.
- **Data-section corruption is undetectable by design** (headers only): a
  file with an intact header but truncated data scans cleanly. The README's
  intro claim about flagging "corrupt files" is broader than this; a sentence
  was added to Honest limits to state it explicitly, plus a note that values
  are not range-checked (negative exposure / out-of-range coordinates are
  logged as written). No code change.
- **`image_type` substring matching** (`SLIGHT` → science via "light",
  `risky` → science via "sky") is literally what the README specifies
  ("values containing … count as science"), so it was left as-is.
- **`os.walk` silently skips unreadable directories** — a scan can return a
  partial log with no signal if a subdirectory cannot be read. The
  `scan_directory` API has no error channel for this; noted here rather than
  changing the API.
- Raw `NaN` header *cards* (crafted bytes) make Astropy raise `VerifyError`,
  which the tool already flags as `unreadable` — acceptable.
- Symlinked FITS files are logged once per link name (normal filesystem
  semantics); symlinked directories are not descended into (no loop risk).

## README assessment

Mostly honest, and the demo is exactly reproducible. Specifics:

- ✅ Demo output, test count (15 at review time), alias table, header-choice
  rule, and audit-flag definitions all matched the code (except HIERARCH,
  below).
- ⚠️ **Overstated:** "`COMMENT`, `HISTORY`, and `HIERARCH` cards are exempt"
  — the HIERARCH part was not true of the code (dead exemption). Now fixed in
  code, so the sentence is true as written.
- ⚠️ **Overstated by omission:** the intro's "flags the files that would have
  silently corrupted your log: corrupt files…" did not hold for (i) compressed
  files (silently *absent*, worse than corrupted), (ii) unparseable
  coordinates (raw text in numeric columns, no flag), or (iii) data-corrupt /
  data-truncated files (scan cleanly). (i) and (ii) are fixed in code;
  (iii) is now stated in Honest limits.
- ⚠️ Minor: the usage line listed only `.fits`/`.fit`/`.fts` while the tool
  now also scans compressed forms — updated. The limits section did not
  mention the lack of range checking — added.
- ✅ Honest as written: headers-only limit, `date_obs` not normalised,
  one-header-per-file scope, alias-table coverage caveat, and "WCS detection
  is a presence check … not a validity check".
- Not verifiable locally: the `pip install git+https://github.com/RakTikoo/fitslog`
  URL (no network publishing in scope for this review).

## Files changed by this review

- `fitslog/core.py` — compressed-name discovery, HIERARCH exemption,
  `invalid_coordinate` flag + finite/bool guards, sexagesimal separators,
  WCS regex, exported `FLAG_INVALID_COORDINATE`.
- `fitslog/cli.py` — clean exit-2 error on unwritable output paths.
- `tests/test_fitslog.py` — 8 new regression tests (`TestReviewRegressions`).
- `README.md` — compressed forms in Usage, `invalid_coordinate` in the audit
  table, two Honest-limits sentences, test count 15 → 23, DMS example.
- `REVIEW.md` — this file.

Final state: **23/23 tests pass**, oracle **36/36**, fresh-install demo
byte-identical to the README demo.
