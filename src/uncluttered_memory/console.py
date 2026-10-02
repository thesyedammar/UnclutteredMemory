"""Console encoding for reports: explicit UTF-8, explicit error handler.

A cp1252 console (or a pipe decoded as cp1252) must never mangle a
report line: UTF-8 is forced on the report streams and unencodable
characters degrade to visible escapes instead of mojibake or a crash.
The success line is pinned byte-for-byte by tests.
"""
from __future__ import annotations

import sys

ENCODING = "utf-8"
ERRORS = "backslashreplace"


def configure_console() -> None:
    """Force UTF-8 with the named error handler on stdout and stderr.

    Streams without reconfigure keep working but fall back to the
    platform default encoding: a loud stderr warning names the
    cp1252-mangle risk instead of failing silently mid-report.
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            try:
                sys.stderr.write(
                    "WARNING uncluttered_memory.console: stream "
                    "encoding=%r has no reconfigure; report falls back "
                    "to the platform default and a cp1252 console may "
                    "mangle non-ASCII output\n"
                    % (getattr(stream, "encoding", None),))
            except Exception:
                pass
            continue
        try:
            reconfigure(encoding=ENCODING, errors=ERRORS)
        except (ValueError, OSError):
            pass
