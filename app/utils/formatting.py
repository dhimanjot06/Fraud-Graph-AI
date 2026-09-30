"""Jinja filters for money, dates and risk levels."""
from datetime import datetime

from flask import current_app


def indian_group(n: int) -> str:
    s = str(abs(int(n)))
    if len(s) <= 3:
        out = s
    else:
        head, tail = s[:-3], s[-3:]
        parts = []
        while len(head) > 2:
            parts.insert(0, head[-2:])
            head = head[:-2]
        if head:
            parts.insert(0, head)
        out = ",".join(parts + [tail])
    return ("-" if n < 0 else "") + out


def money(value, decimals=None):
    if value is None:
        return "–"
    symbol = current_app.config["DETECTION"].get("currency_symbol", "₹")
    value = float(value)
    if decimals is None:
        decimals = 0 if abs(value) >= 1000 or value == int(value) else 2
    whole = indian_group(int(value))
    if decimals:
        frac = f"{abs(value) - int(abs(value)):.{decimals}f}"[1:]
        return f"{symbol}{whole}{frac}"
    return f"{symbol}{indian_group(round(value))}"


def number(value):
    return "–" if value is None else indian_group(int(value))


def when(value, fmt="%d %b %Y, %H:%M"):
    if not value:
        return "–"
    try:
        return datetime.fromisoformat(str(value).replace(" ", "T")).strftime(fmt)
    except ValueError:
        return str(value)


def day(value):
    return when(value, "%d %b %Y")


def pct(value, digits=0):
    return "–" if value is None else f"{float(value) * 100:.{digits}f}%"


def level_label(level):
    return {"high": "High risk", "medium": "Medium risk", "low": "Low risk"}.get(level, level)


def ring_type_label(ring_type):
    return {"cycle": "Circular money movement", "collector_hub": "Collector account",
            "dense_cluster": "Dense account cluster"}.get(ring_type, ring_type)


def init_app(app):
    app.jinja_env.filters.update(money=money, number=number, when=when, day=day, pct=pct,
                                 level_label=level_label, ring_type_label=ring_type_label)
