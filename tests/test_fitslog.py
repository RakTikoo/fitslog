"""Tests for fitslog.  All fixtures are synthetic FITS files built with
astropy in temporary directories -- no real data needed."""

import csv
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from astropy.io import fits

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fitslog.core import (  # noqa: E402
    FLAG_DUPLICATE_KEYWORD,
    FLAG_MISSING_DATE,
    FLAG_MISSING_EXPTIME,
    FLAG_MISSING_OBJECT,
    FLAG_NO_WCS,
    FLAG_UNREADABLE,
    dec_to_degrees,
    ra_to_degrees,
    scan_directory,
)

CD_WCS = {
    "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
    "CRVAL1": 83.8221, "CRVAL2": -5.3911,
    "CRPIX1": 32.0, "CRPIX2": 32.0,
    "CD1_1": -0.001, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 0.001,
}


def write_fits(path, header_dict):
    header = fits.Header()
    for key, value in header_dict.items():
        header[key] = value
    hdu = fits.PrimaryHDU(header=header, data=np.zeros((4, 4), dtype=np.uint8))
    hdu.writeto(path, overwrite=True)


def flags_for(audits, filename):
    return {a["flag"] for a in audits if a["file"] == filename}


def row_for(rows, filename):
    for row in rows:
        if row["file"] == filename:
            return row
    raise AssertionError(f"no row for {filename}")


class TempTreeTestCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()


class TestAliasNormalisation(TempTreeTestCase):
    """(1) Three files, three keyword spellings, identical columns."""

    def test_three_spellings_normalise_identically(self):
        common = {
            "INSTRUME": "CamA", "TELESCOP": "ScopeA", "AIRMASS": 1.21,
            "IMAGETYP": "object", **CD_WCS,
        }
        write_fits(self.root / "a.fits", {
            **common,
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 30.0, "FILTER": "R",
            "RA": 83.8221, "DEC": -5.3911, "OBSERVER": "Jo",
        })
        write_fits(self.root / "b.fits", {
            **common,
            "TARGET": "M42", "DATE_OBS": "2026-01-01T22:00:00",
            "EXPOSURE": 30.0, "FILTER1": "R",
            "OBJRA": 83.8221, "OBJDEC": -5.3911, "OBSERVER": "Jo",
        })
        write_fits(self.root / "c.fits", {
            **common,
            "OBJNAME": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPT": 30.0, "FILTNAME": "R",
            "RA": "05:35:17.304", "DEC": "-05:23:27.96", "OBSERV": "Jo",
        })

        rows, audits = scan_directory(self.root)
        self.assertEqual(len(rows), 3)
        self.assertEqual(audits, [])

        rows = sorted(rows, key=lambda r: r["file"])
        shared_keys = [k for k in rows[0] if k not in ("file", "folder")]
        for key in shared_keys:
            values = [r[key] for r in rows]
            if key in ("ra_deg", "dec_deg"):
                floats = [float(v) for v in values]
                for v in floats:
                    self.assertAlmostEqual(v, floats[0], places=5, msg=key)
            else:
                self.assertEqual(values, [values[0]] * 3, msg=key)

        row = rows[0]
        self.assertEqual(row["object"], "M42")
        self.assertEqual(row["filter"], "R")
        self.assertEqual(float(row["exptime_s"]), 30.0)
        self.assertEqual(row["image_type"], "science")


class TestCorruptFile(TempTreeTestCase):
    """(2) A corrupt file is audited, not crashed on."""

    def test_corrupt_file_is_audited_not_fatal(self):
        (self.root / "broken.fits").write_bytes(b"definitely not FITS\n" * 50)
        write_fits(self.root / "good.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, **CD_WCS,
        })
        rows, audits = scan_directory(self.root)
        self.assertEqual(len(rows), 2)
        self.assertIn(FLAG_UNREADABLE, flags_for(audits, "broken.fits"))
        detail = [a["detail"] for a in audits if a["file"] == "broken.fits"][0]
        self.assertTrue(detail)  # the error is recorded
        self.assertEqual(row_for(rows, "good.fits")["object"], "M42")


class TestDuplicateKeyword(TempTreeTestCase):
    """(3) A header with a duplicate keyword is flagged."""

    def test_duplicate_keyword_flagged(self):
        header = fits.Header()
        header["OBJECT"] = "M42"
        header.append(("OBJECT", "M43"))
        header["DATE-OBS"] = "2026-01-01T22:00:00"
        header["EXPTIME"] = 10.0
        for key, value in CD_WCS.items():
            header[key] = value
        fits.PrimaryHDU(
            header=header, data=np.zeros((4, 4), dtype=np.uint8)
        ).writeto(self.root / "dup.fits", overwrite=True)

        rows, audits = scan_directory(self.root)
        self.assertIn(FLAG_DUPLICATE_KEYWORD, flags_for(audits, "dup.fits"))
        detail = [
            a["detail"] for a in audits
            if a["file"] == "dup.fits" and a["flag"] == FLAG_DUPLICATE_KEYWORD
        ][0]
        self.assertIn("OBJECT", detail)
        # First value wins for the logged row.
        self.assertEqual(row_for(rows, "dup.fits")["object"], "M42")


class TestWCSFlag(TempTreeTestCase):
    """(4) No WCS keywords -> flagged; CD matrix -> not flagged."""

    def test_no_wcs_flagged_cd_matrix_not(self):
        write_fits(self.root / "nowcs.fits", {
            "OBJECT": "flat", "DATE-OBS": "2026-01-01T21:00:00",
            "EXPTIME": 5.0, "IMAGETYP": "flat",
        })
        write_fits(self.root / "wcs.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 5.0, **CD_WCS,
        })
        rows, audits = scan_directory(self.root)
        self.assertIn(FLAG_NO_WCS, flags_for(audits, "nowcs.fits"))
        self.assertNotIn(FLAG_NO_WCS, flags_for(audits, "wcs.fits"))


class TestSexagesimal(TempTreeTestCase):
    """(5) Sexagesimal RA converts to the correct degrees."""

    def test_ra_sexagesimal_degrees(self):
        self.assertAlmostEqual(ra_to_degrees("10:30:00"), 157.5, places=9)
        self.assertAlmostEqual(ra_to_degrees("05:35:17.304"), 83.8221, places=6)
        self.assertAlmostEqual(ra_to_degrees("10h30m00s"), 157.5, places=9)
        self.assertAlmostEqual(ra_to_degrees(157.5), 157.5, places=9)
        self.assertAlmostEqual(ra_to_degrees("157.5"), 157.5, places=9)

    def test_dec_sexagesimal_degrees(self):
        self.assertAlmostEqual(dec_to_degrees("-20:30:00"), -20.5, places=9)
        self.assertAlmostEqual(dec_to_degrees("-05:23:27.96"), -5.3911, places=6)
        self.assertAlmostEqual(dec_to_degrees("20:30:00"), 20.5, places=9)

    def test_sexagesimal_file_row(self):
        write_fits(self.root / "sexa.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, "RA": "10:30:00", "DEC": "-20:30:00", **CD_WCS,
        })
        rows, _audits = scan_directory(self.root)
        row = row_for(rows, "sexa.fits")
        self.assertAlmostEqual(float(row["ra_deg"]), 157.5, places=6)
        self.assertAlmostEqual(float(row["dec_deg"]), -20.5, places=6)


class TestMissingFields(TempTreeTestCase):
    def test_missing_object_date_exptime_flagged(self):
        write_fits(self.root / "bare.fits", {"FILTER": "V", **CD_WCS})
        rows, audits = scan_directory(self.root)
        flags = flags_for(audits, "bare.fits")
        self.assertIn(FLAG_MISSING_OBJECT, flags)
        self.assertIn(FLAG_MISSING_DATE, flags)
        self.assertIn(FLAG_MISSING_EXPTIME, flags)


class TestAdversarial(TempTreeTestCase):
    def test_empty_directory(self):
        rows, audits = scan_directory(self.root)
        self.assertEqual(rows, [])
        self.assertEqual(audits, [])

    def test_table_only_file(self):
        """A FITS file whose only HDU content is a table must scan cleanly."""
        primary = fits.PrimaryHDU()
        table = fits.BinTableHDU.from_columns(
            [fits.Column(name="FLUX", array=[1.0, 2.0], format="D")]
        )
        fits.HDUList([primary, table]).writeto(
            self.root / "table.fits", overwrite=True
        )
        rows, audits = scan_directory(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["file"], "table.fits")
        self.assertIn(FLAG_MISSING_OBJECT, flags_for(audits, "table.fits"))
        self.assertNotIn(FLAG_UNREADABLE, flags_for(audits, "table.fits"))

    def test_extension_header_used_when_primary_is_bare(self):
        primary = fits.PrimaryHDU()
        header = fits.Header()
        header["OBJECT"] = "M42"
        header["DATE-OBS"] = "2026-01-01T22:00:00"
        header["EXPTIME"] = 12.0
        for key, value in CD_WCS.items():
            header[key] = value
        image = fits.ImageHDU(header=header, data=np.zeros((4, 4)))
        fits.HDUList([primary, image]).writeto(
            self.root / "ext.fits", overwrite=True
        )
        rows, audits = scan_directory(self.root)
        self.assertEqual(row_for(rows, "ext.fits")["object"], "M42")
        self.assertEqual(audits, [])

    def test_extremely_long_path(self):
        deep = self.root
        for i in range(4):
            deep = deep / ("very_long_subdirectory_name_number_%02d_abcdefghij" % i)
        deep.mkdir(parents=True)
        name = "an_extremely_long_fits_file_name_for_a_single_exposure_frame_0001.fits"
        write_fits(deep / name, {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, **CD_WCS,
        })
        self.assertGreater(len(str(deep / name)), 240)
        rows, audits = scan_directory(self.root)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["file"], name)
        self.assertEqual(audits, [])

    def test_non_fits_files_ignored(self):
        (self.root / "notes.txt").write_text("hello")
        (self.root / "data.csv").write_text("a,b\n1,2\n")
        rows, audits = scan_directory(self.root)
        self.assertEqual(rows, [])


class TestReviewRegressions(TempTreeTestCase):
    """Regression tests for the independent adversarial review (REVIEW.md)."""

    def test_hierarch_duplicate_not_flagged(self):
        header = fits.Header()
        header["OBJECT"] = "M42"
        header["DATE-OBS"] = "2026-01-01T22:00:00"
        header["EXPTIME"] = 10.0
        for key, value in CD_WCS.items():
            header[key] = value
        header["HIERARCH ESO DET CHIP"] = "A"
        header.append(("HIERARCH ESO DET CHIP", "B"))
        fits.PrimaryHDU(
            header=header, data=np.zeros((4, 4), dtype=np.uint8)
        ).writeto(self.root / "h.fits", overwrite=True)
        _rows, audits = scan_directory(self.root)
        self.assertNotIn(FLAG_DUPLICATE_KEYWORD, flags_for(audits, "h.fits"))

    def test_gzipped_fits_is_scanned(self):
        import gzip

        write_fits(self.root / "tmp.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, **CD_WCS,
        })
        data = (self.root / "tmp.fits").read_bytes()
        (self.root / "tmp.fits").unlink()
        (self.root / "real.fits.gz").write_bytes(gzip.compress(data))
        (self.root / "notes.gz").write_bytes(gzip.compress(b"not fits"))
        rows, audits = scan_directory(self.root)
        self.assertEqual([r["file"] for r in rows], ["real.fits.gz"])
        self.assertEqual(rows[0]["object"], "M42")
        self.assertEqual(audits, [])

    def test_invalid_coordinate_flagged_and_column_empty(self):
        from fitslog.core import FLAG_INVALID_COORDINATE

        write_fits(self.root / "bad.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, "RA": "not-a-number", "DEC": "-05d23m27.96s",
            **CD_WCS,
        })
        rows, audits = scan_directory(self.root)
        row = row_for(rows, "bad.fits")
        self.assertEqual(row["ra_deg"], "")
        # The d/m/s sexagesimal form must convert, not be flagged.
        self.assertAlmostEqual(float(row["dec_deg"]), -5.3911, places=4)
        inv = [a for a in audits if a["flag"] == FLAG_INVALID_COORDINATE]
        self.assertEqual(len(inv), 1)
        self.assertIn("RA", inv[0]["detail"])

    def test_dms_symbol_forms_convert(self):
        self.assertAlmostEqual(
            dec_to_degrees("-05 23' 27.96\""), -5.3911, places=4)
        self.assertAlmostEqual(
            dec_to_degrees("-05d23m27.96s"), -5.3911, places=4)
        self.assertAlmostEqual(ra_to_degrees("05h35m17.304s"), 83.8221, places=4)

    def test_boolean_exptime_is_missing_not_one(self):
        write_fits(self.root / "b.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": True, **CD_WCS,
        })
        rows, audits = scan_directory(self.root)
        self.assertEqual(row_for(rows, "b.fits")["exptime_s"], "")
        self.assertIn(FLAG_MISSING_EXPTIME, flags_for(audits, "b.fits"))

    def test_wcs_legacy_and_fake_keywords(self):
        write_fits(self.root / "legacy.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, "CD001001": 1.0,
        })
        write_fits(self.root / "fake.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, "CDS_1": 1.0,
        })
        _rows, audits = scan_directory(self.root)
        self.assertNotIn(FLAG_NO_WCS, flags_for(audits, "legacy.fits"))
        self.assertIn(FLAG_NO_WCS, flags_for(audits, "fake.fits"))

    def test_nan_inf_strings_are_not_numbers(self):
        from fitslog.core import FLAG_INVALID_COORDINATE

        write_fits(self.root / "n.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": "nan", "RA": "inf", "AIRMASS": "nan", **CD_WCS,
        })
        rows, audits = scan_directory(self.root)
        row = row_for(rows, "n.fits")
        self.assertEqual(row["exptime_s"], "")
        self.assertEqual(row["ra_deg"], "")
        self.assertEqual(row["airmass"], "")
        self.assertIn(FLAG_MISSING_EXPTIME, flags_for(audits, "n.fits"))
        self.assertIn(FLAG_INVALID_COORDINATE, flags_for(audits, "n.fits"))

    def test_cli_unwritable_out_is_clean_error(self):
        from fitslog.cli import main

        write_fits(self.root / "one.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, **CD_WCS,
        })
        rc = main(["scan", str(self.root), "--out",
                   str(self.root / "no-such-dir" / "log.csv")])
        self.assertEqual(rc, 2)


class TestCLI(TempTreeTestCase):
    def test_cli_scan_writes_csvs(self):
        from fitslog.cli import main

        write_fits(self.root / "one.fits", {
            "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
            "EXPTIME": 10.0, **CD_WCS,
        })
        out = self.root / "log.csv"
        audit = self.root / "audit.csv"
        rc = main(["scan", str(self.root), "--out", str(out),
                   "--audit", str(audit)])
        self.assertEqual(rc, 0)
        with open(out, newline="") as fh:
            rows = list(csv.DictReader(fh))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["object"], "M42")
        self.assertTrue(audit.exists())

    def test_cli_missing_directory_is_clean_error(self):
        from fitslog.cli import main

        rc = main(["scan", str(self.root / "does-not-exist")])
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
