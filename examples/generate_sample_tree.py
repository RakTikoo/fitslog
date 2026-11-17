#!/usr/bin/env python3
"""Generate the small synthetic FITS tree used by the fitslog demo and tests.

Usage:
    python3 examples/generate_sample_tree.py [output_dir]

Default output_dir is ./sample_data.  The tree deliberately mixes keyword
spellings from different "instruments" and includes problem files (a corrupt
file, a duplicate keyword, a file with no WCS, a file missing fields) so the
audit output has something to show.
"""

import sys
from pathlib import Path

import numpy as np
from astropy.io import fits

CD_WCS = {
    "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
    "CRVAL1": 83.8221, "CRVAL2": -5.3911,
    "CRPIX1": 32.0, "CRPIX2": 32.0,
    "CD1_1": -0.001, "CD1_2": 0.0, "CD2_1": 0.0, "CD2_2": 0.001,
}

PC_WCS = {
    "CTYPE1": "RA---TAN", "CTYPE2": "DEC--TAN",
    "CRVAL1": 83.8221, "CRVAL2": -5.3911,
    "CRPIX1": 32.0, "CRPIX2": 32.0,
    "PC1_1": 1.0, "PC1_2": 0.0, "PC2_1": 0.0, "PC2_2": 1.0,
    "CDELT1": -0.001, "CDELT2": 0.001,
}


def _write(path, header_dict):
    header = fits.Header()
    for key, value in header_dict.items():
        header[key] = value
    hdu = fits.PrimaryHDU(header=header, data=np.zeros((8, 8), dtype=np.uint8))
    hdu.writeto(path, overwrite=True)


def build_tree(root):
    root = Path(root)
    night = root / "night1"
    raw = root / "raw"
    night.mkdir(parents=True, exist_ok=True)
    raw.mkdir(parents=True, exist_ok=True)

    # 1. "Standard" spellings + CD-matrix WCS.
    _write(night / "m42_r.fits", {
        "OBJECT": "M42", "DATE-OBS": "2026-01-01T22:00:00",
        "EXPTIME": 30.0, "FILTER": "R",
        "INSTRUME": "CamA", "TELESCOP": "ScopeA",
        "RA": 83.8221, "DEC": -5.3911, "AIRMASS": 1.21,
        "OBSERVER": "Jo", "IMAGETYP": "object", **CD_WCS,
    })

    # 2. Different spellings for the same fields + PC-matrix WCS.
    _write(night / "m42_ha.fits", {
        "TARGET": "M42", "DATE_OBS": "2026-01-01T22:05:00",
        "EXPOSURE": 300.0, "FILTER1": "Ha",
        "INSTRUMENT": "CamA", "TELESCOPE": "ScopeA",
        "OBJRA": 83.8221, "OBJDEC": -5.3911, "AIRMASS": 1.19,
        "OBSERVER": "Jo", "IMAGETYP": "object", **PC_WCS,
    })

    # 3. A flat: no WCS keywords at all -> flagged no_wcs.
    _write(night / "flat_r.fits", {
        "OBJECT": "flat", "DATE-OBS": "2026-01-01T21:00:00",
        "EXPTIME": 5.0, "FILTER": "R",
        "INSTRUME": "CamA", "TELESCOP": "ScopeA", "IMAGETYP": "flat",
    })

    # 4. Third set of spellings + sexagesimal coordinates, in a subfolder.
    _write(raw / "bias_001.fits", {
        "OBJNAME": "bias", "DATE-OBS": "2026-01-01T20:00:00",
        "EXPT": 0.0, "FILTNAME": "none",
        "INSTRUME": "CamB", "TELESCOP": "ScopeA",
        "RA": "05:35:17.304", "DEC": "-05:23:27.96",
        "OBSERV": "Jo", "IMAGETYP": "bias",
    })

    # 5. Missing object and missing date -> flagged.
    _write(raw / "mystery.fits", {
        "EXPTIME": 60.0, "FILTER": "V",
        "INSTRUME": "CamB", "TELESCOP": "ScopeA", "IMAGETYP": "object",
        **CD_WCS,
    })

    # 6. Duplicate OBJECT keyword -> flagged.
    dup_header = fits.Header()
    dup_header["OBJECT"] = "M42"
    dup_header.append(("OBJECT", "M43"))
    dup_header["DATE-OBS"] = "2026-01-01T23:00:00"
    dup_header["EXPTIME"] = 45.0
    for key, value in CD_WCS.items():
        dup_header[key] = value
    fits.PrimaryHDU(
        header=dup_header, data=np.zeros((8, 8), dtype=np.uint8)
    ).writeto(raw / "dup.fits", overwrite=True)

    # 7. A corrupt "FITS" file: plain text with a .fits name -> audited.
    (raw / "broken.fits").write_bytes(b"this is not a FITS file at all\n" * 40)

    return root


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("sample_data")
    build_tree(out)
    print(f"Sample tree written to {out}")
