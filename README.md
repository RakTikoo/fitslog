# fitslog

**Point fitslog at a folder tree of telescope FITS files and get one clean night-log CSV — header keywords normalised across instruments — plus an audit of the problem files.**

Every observatory, instrument, and capture program spells the same header keywords differently: exposure time is `EXPTIME` here, `EXPOSURE` there, `EXPT` somewhere else; the target is `OBJECT`, `TARGET`, or `OBJNAME`. Building a night log by hand means re-learning those spellings for every folder. fitslog knows the spellings, reads **headers only** (image data is never loaded), recurses the whole tree, and writes one spreadsheet with the same columns for every file — and flags the files that would have silently corrupted your log: corrupt files, missing fields, duplicated keywords, headers with no WCS.

Free and open source (MIT). No account, no uploads, everything runs on your machine.

## Install

```console
$ pip install git+https://github.com/RakTikoo/fitslog
```

Requires Python 3.10+ and Astropy.

## Demo

The sample tree below is synthetic — regenerate it any time with
`python3 examples/generate_sample_tree.py demo_data`. It mixes three
"instruments'" keyword spellings and includes a corrupt file, a duplicated
keyword, and files with missing fields on purpose:

```console
$ fitslog scan demo_data --out nightlog.csv --audit audit.csv
Files scanned: 7
Rows written: 7
Flagged files: 5
Top flags:
  no_wcs: 2
  unreadable: 1
  duplicate_keyword: 1
  missing_object: 1
  missing_date: 1
Night log: nightlog.csv
Audit: audit.csv

Flagged files:
  night1/flat_r.fits: no_wcs
  raw/bias_001.fits: no_wcs
  raw/broken.fits: unreadable
  raw/dup.fits: duplicate_keyword
  raw/mystery.fits: missing_object, missing_date
```

`nightlog.csv` — note how `EXPTIME`/`EXPOSURE`/`EXPT` and
`OBJECT`/`TARGET`/`OBJNAME` all land in the same columns, and the
sexagesimal RA/Dec in `bias_001.fits` came out as degrees:

```csv
file,folder,date_obs,object,filter,exptime_s,instrument,telescope,ra_deg,dec_deg,airmass,observer,image_type
flat_r.fits,night1,2026-01-01T21:00:00,flat,R,5,CamA,ScopeA,,,,,flat
m42_ha.fits,night1,2026-01-01T22:05:00,M42,Ha,300,CamA,ScopeA,83.8221,-5.3911,1.19,Jo,science
m42_r.fits,night1,2026-01-01T22:00:00,M42,R,30,CamA,ScopeA,83.8221,-5.3911,1.21,Jo,science
bias_001.fits,raw,2026-01-01T20:00:00,bias,none,0,CamB,ScopeA,83.8221,-5.3911,,Jo,bias
broken.fits,raw,,,,,,,,,,,
dup.fits,raw,2026-01-01T23:00:00,M42,,45,,,,,,,
mystery.fits,raw,,,V,60,CamB,ScopeA,,,,,science
```

`audit.csv` has one row per flag (a file can have several), with a detail
column — the duplicated keyword's name, or the read error for a corrupt file:

```csv
file,folder,flag,detail
flat_r.fits,night1,no_wcs,
bias_001.fits,raw,no_wcs,
broken.fits,raw,unreadable,"OSError: No SIMPLE card found, this file does not appear to be a valid FITS file. ..."
dup.fits,raw,duplicate_keyword,OBJECT
mystery.fits,raw,missing_object,
mystery.fits,raw,missing_date,
```

## Usage

```console
$ fitslog scan /data/night1 --out nightlog.csv [--audit audit.csv]
```

- Recurses all subfolders. Files ending in `.fits`, `.fit`, or `.fts` (any case) are scanned, in sorted order — including the common compressed forms `.fits.gz` / `.fit.gz` / `.fts.gz` (also `.bz2`, `.xz`, and fpack `.fits.fz`), which Astropy reads transparently.
- One row per file in the night log — including corrupt files, which appear as a mostly-empty row and are explained in the audit. A corrupt file never stops the scan.
- `folder` is the file's directory relative to the folder you scanned (empty for files at the top level).
- `--audit` is optional; the summary and the flagged-file list are always printed either way.

### Which header is used

The primary header, whenever it carries any recognised keyword. If the primary header carries none (a bare primary in front of the real header), the first extension header that carries any recognised keyword is used instead. If no header carries anything, the primary is used and the file is flagged for its missing fields.

### Output columns

`file, folder, date_obs, object, filter, exptime_s, instrument, telescope, ra_deg, dec_deg, airmass, observer, image_type`

- `date_obs` is copied as written in the header (no re-formatting — check the audit if you need uniform dates).
- `ra_deg` / `dec_deg` are decimal degrees. Sexagesimal strings (`05:35:17.304`, `05 35 17.3`, `5h35m17s`, `-05d23m27s`, `-05 23' 27"`) are converted; for RA the sexagesimal value is read as hours and multiplied by 15.
- `image_type` comes from `IMAGETYP`, normalised to `science` / `flat` / `dark` / `bias` when recognisable (values containing "object", "science", "light", "sky", or "target" count as science; "zero" counts as bias); anything else is passed through lower-cased.

### Audit flags

| Flag | Meaning |
|---|---|
| `unreadable` | The file could not be opened as FITS at all. The error is in the audit's detail column. |
| `missing_object` | No object/target keyword found. |
| `missing_date` | No `DATE-OBS`/`DATE_OBS` found. |
| `missing_exptime` | No exposure-time keyword found (or it wasn't a number). |
| `duplicate_keyword` | A keyword appears more than once in the header (detail names it). `COMMENT`, `HISTORY`, and `HIERARCH` cards are exempt — they repeat legitimately. The first value is the one logged. |
| `no_wcs` | No WCS in the header: no CD matrix, no PC matrix, and no `CDELT`. |
| `invalid_coordinate` | An RA or Dec value was present but could not be parsed as a number or sexagesimal (detail names the axis and the raw value). The `ra_deg`/`dec_deg` column is left empty for that axis rather than carrying raw text. |

## The alias table

Lookup is case-insensitive; the first spelling present (and non-empty) wins. This table is the single place spellings are defined — in the code it is `ALIASES` in `fitslog/core.py`.

| Column | Keywords tried, in order |
|---|---|
| `date_obs` | `DATE-OBS`, `DATE_OBS` |
| `object` | `OBJECT`, `TARGET`, `OBJNAME` |
| `filter` | `FILTER`, `FILTER1`, `FILTER2`, `FILTNAME` |
| `exptime_s` | `EXPTIME`, `EXPOSURE`, `EXPT` |
| `instrument` | `INSTRUME`, `INSTRUMENT` |
| `telescope` | `TELESCOP`, `TELESCOPE` |
| `ra_deg` | `RA`, `OBJRA`, `RA_OBJ` |
| `dec_deg` | `DEC`, `OBJDEC`, `DEC_OBJ` |
| `airmass` | `AIRMASS` |
| `observer` | `OBSERVER`, `OBSERV` |
| `image_type` | `IMAGETYP` |

Missing a spelling your instrument uses? It's a one-line addition to `ALIASES` — pull requests welcome.

## Tests

```console
$ python3 run_tests.py
```

23 tests, all on synthetic FITS files generated with Astropy: three keyword spellings normalising identically, corrupt-file handling, duplicate-keyword and no-WCS flags, sexagesimal conversion, table-only files, empty directories, and very long paths — plus regression tests from an independent adversarial review (gzipped files, HIERARCH duplicates, invalid coordinates, DMS-style sexagesimal, non-numeric exposure values).

## Honest limits

- Headers only: fitslog never looks at image data, so it cannot tell you a frame is clouded out or out of focus — only that its header is complete or not. For the same reason a file whose *data* section is truncated or corrupt but whose header is intact will scan cleanly; only files that cannot be opened as FITS at all are flagged `unreadable`.
- Values are not range-checked: a negative exposure time or an out-of-range coordinate is logged as written (only unparseable coordinates are flagged, as `invalid_coordinate`).
- `date_obs` is not normalised beyond choosing between the two spellings; two instruments can still write different date *formats*.
- One row per file, from one header (see "Which header is used" above). Multi-extension mosaics logged per-extension are out of scope.
- The alias table covers common spellings, not every observatory that ever existed. If your instrument's spelling is missing, the file shows up with empty columns — the audit's missing-field flags make that visible rather than silent.
- WCS detection is a presence check (CD, PC, or CDELT keywords), not a validity check — a header can carry WCS keywords that are still wrong.

## License

MIT — see `LICENSE`.
