"""Small standalone scripts for the orbital core.

Not part of the importable library and not on the screening path — these are
operator conveniences: fetch a single TLE, dump an ephemeris to CSV, eyeball
a TEME->GCRS conversion against an external reference. Each tool is runnable
as `python -m prahari_orbital.tools.<name>` or as a plain script.

Rules from ../CLAUDE.md still apply here: km / km/s / timezone-aware UTC,
frame conversions only via prahari_orbital.frames, and every function
states its input units, output units, and output frame.
"""
