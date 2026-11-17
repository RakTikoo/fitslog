"""Command-line interface for fitslog.

Usage:
    fitslog scan /data/night1 --out nightlog.csv [--audit audit.csv]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .core import scan_directory, summarise, write_audit_csv, write_log_csv


def build_parser():
    parser = argparse.ArgumentParser(
        prog="fitslog",
        description=(
            "Turn a folder tree of telescope FITS files into one clean "
            "night-log CSV, with header keywords normalised across "
            "instruments, plus an audit of problem files."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    scan = sub.add_parser("scan", help="Scan a folder tree of FITS files.")
    scan.add_argument("path", help="Root folder to scan (recursed).")
    scan.add_argument(
        "--out",
        default="nightlog.csv",
        help="Where to write the night-log CSV (default: nightlog.csv).",
    )
    scan.add_argument(
        "--audit",
        default=None,
        help="Optional: also write the audit (one row per flag) to this CSV.",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.command == "scan":
        root = Path(args.path)
        if not root.is_dir():
            print(f"fitslog: not a directory: {root}", file=sys.stderr)
            return 2

        rows, audits = scan_directory(root)
        try:
            write_log_csv(rows, args.out)
            if args.audit:
                write_audit_csv(audits, args.audit)
        except OSError as exc:
            print(f"fitslog: cannot write output: {exc}", file=sys.stderr)
            return 2

        summary, _flag_counts, _flagged = summarise(rows, audits)
        print(summary)
        print(f"Night log: {args.out}")
        if args.audit:
            print(f"Audit: {args.audit}")
        if audits:
            print("\nFlagged files:")
            by_file = {}
            for entry in audits:
                key = str(Path(entry["folder"]) / entry["file"]) if entry["folder"] else entry["file"]
                by_file.setdefault(key, []).append(entry["flag"])
            for name in sorted(by_file):
                print(f"  {name}: {', '.join(by_file[name])}")
        return 0

    return 2


if __name__ == "__main__":
    raise SystemExit(main())
