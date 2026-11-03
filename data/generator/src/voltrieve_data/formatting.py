def fmt_int(n: int) -> str:
    """Format an integer with a normal space as thousands separator, e.g. 2 100."""
    return f"{n:,}".replace(",", " ")
