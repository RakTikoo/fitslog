"""fitslog: one clean night-log CSV from a tree of telescope FITS files."""

from .core import (
    ALIASES,
    COLUMNS,
    scan_directory,
    summarise,
    write_audit_csv,
    write_log_csv,
)

__version__ = "0.1.0"

__all__ = [
    "ALIASES",
    "COLUMNS",
    "scan_directory",
    "summarise",
    "write_audit_csv",
    "write_log_csv",
    "__version__",
]
