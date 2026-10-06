"""Strict manual quantity parsing; blank is the only default-selection input."""
import math


def quantity(value, label="Qty"):
    if value is None or isinstance(value, str) and not value.strip():
        return None
    try:
        number = float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        raise ValueError("%s: enter a whole non-negative number, or leave blank" % label)
    if isinstance(value, bool) or not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError("%s: enter a whole non-negative number, or leave blank" % label)
    return int(number)
