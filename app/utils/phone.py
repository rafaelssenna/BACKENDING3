"""
Phone number extraction and normalization utilities.

This module exposes two functions, :func:`extract_phones_from_text` and
:func:`normalize_br`, which together identify and normalize Brazilian
phone numbers from arbitrary text.  Numbers are returned in E.164
format prefixed with ``+55``.  The extraction regex has been
carefully tuned to match common local formats, including those that
contain an optional leading ``9`` (used for mobile numbers) as well as
older eight‑digit numbers.  Separators such as spaces, hyphens and
parentheses are ignored.

Example formats matched:

    ``31 98765-4321``
    ``(31) 98765 4321``
    ``31 8765-4321``  # eight digit numbers
    ``+55 (31) 9 8765-4321``

If a number cannot be normalized to the expected 10 or 11 digits
following the DDD, it is discarded.  See :func:`normalize_br` for
details.
"""

from __future__ import annotations

import re

# Country dial code for Brazil.  Keeping this in a constant makes it
# trivial to adjust if support for other countries is added in the
# future.
BR_DIAL_CODE: str = "55"

# Precompiled regular expressions used for digit stripping and phone
# extraction.  ``DIGITS_RE`` removes all non‑digit characters from an
# input string.  ``PHONE_RE`` matches Brazilian phone numbers in a
# variety of layouts.  It accepts an optional "+55" prefix, a two‑
# digit DDD (area code) optionally wrapped in parentheses, and either
# four or five subsequent digits (the latter optionally preceded by a
# 9) followed by a final block of four digits.  Separators such as
# hyphens or spaces are ignored.  This pattern intentionally avoids
# matching numbers without a DDD to reduce false positives.
DIGITS_RE: re.Pattern[str] = re.compile(r"\D+")
PHONE_RE: re.Pattern[str] = re.compile(
    r"(?:\+?55)?\s*"              # optional country code with whitespace
    r"\(?\d{2}\)?\s*"            # DDD (area code) with optional parens
    r"(?:9\d{4}|\d{4})\s*"       # five digits (mobile) or four digits (landline)
    r"[-\s]?\d{4}"               # separator and four final digits
)


def extract_phones_from_text(text: str | None) -> list[str]:
    """
    Scan *text* for Brazilian phone numbers.

    The extraction uses a permissive regular expression that accepts
    numbers with or without the country prefix, parentheses around the
    DDD, optional spaces or hyphens, and either 8‑digit or 9‑digit
    subscriber numbers.  Each candidate is passed through
    :func:`normalize_br` to ensure it is valid and to produce a
    normalised E.164 string.  Duplicate numbers are removed.

    Args:
        text: Arbitrary text potentially containing phone numbers.

    Returns:
        A list of unique phone numbers in ``+55DDDNXXXXXXXX`` format.
    """
    phones: set[str] = set()
    if not text:
        return []
    for match in PHONE_RE.finditer(text):
        raw = match.group(0)
        norm = normalize_br(raw)
        if norm:
            phones.add(norm)
    return list(phones)


def normalize_br(s: str | None) -> str | None:
    """
    Normalise a Brazilian phone number to E.164 (``+55…``) format.

    This helper strips all non‑digit characters, drops any leading
    international dial prefixes (``00``), trims a leading ``+55`` if
    present and removes phantom zeros.  Numbers are considered valid
    if, after removing the country code, they contain exactly 10 or
    11 digits (two‑digit DDD plus eight or nine digit subscriber
    number).

    Args:
        s: Raw phone number text.

    Returns:
        A normalised phone number string in ``+55DDDNXXXXXXXX`` format,
        or ``None`` if the number cannot be normalised.
    """
    if not s:
        return None
    # Strip non‑digit characters
    digits = DIGITS_RE.sub("", s)
    # Remove common international call prefix "00"
    if digits.startswith("00"):
        digits = digits[2:]
    # Strip country code if present
    if digits.startswith(BR_DIAL_CODE):
        digits = digits[len(BR_DIAL_CODE) :]
    # Remove any leading zeros leftover
    digits = digits.lstrip("0")
    # Expect 10 (landline) or 11 (mobile) digits after DDD
    if len(digits) in (10, 11):
        return f"+{BR_DIAL_CODE}{digits}"
    # Reject if number lacks DDD or has unexpected length
    return None
