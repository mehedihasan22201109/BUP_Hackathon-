p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()

# Fix 1: regex should accept standalone "noon" / "midnight" as the end token
old = """_TIME_RANGE_RE = re.compile(
    r\"\\\\b(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b\\\\s*\"
    r\"(?:until|to|through|til|-|\\\\u2013|\\\\u2014)\\\\s*\"
    r\"(?:(?:noon|midday|midnight)|(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b))\",
    re.IGNORECASE,
)"""
new = """_TIME_RANGE_RE = re.compile(
    r\"\\\\b(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b|(noon|midnight|midday))\\\\s*\"
    r\"(?:until|to|through|til|-|\\\\u2013|\\\\u2014)\\\\s*\"
    r\"(?:(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b)|(noon|midnight|midday))\",
    re.IGNORECASE,
)"""
assert old in s, 'time_range_re marker not found'
s = s.replace(old, new)

# Fix 2: rewrite _to_24h_pair and the start-block to support noon/midnight
old2 = '''def _parse_noon_or(hour_token: str, ap_token: str) -> int:
    """Helper for the rare \\'noon\\' / \\'midnight\\' end-of-range token."""
    if hour_token is None:
        # Noon = 12, midnight = 0
        return 12 if ap_token.lower().startswith("n") else 0
    return _to_24h(int(hour_token), ap_token)'''
new2 = '''def _parse_noon_or(hour_token, ap_token) -> int:
    """Convert a (hour_token, ap_token) pair or \\'noon\\'/\\'midnight\\' into 24h.
    Either (hour_token, ap_token) is a (digits, ap) pair, or \\'noon\\'/\\'midnight\\' was
    captured in the noon_token slot. The two are mutually exclusive.
    """
    if hour_token is None and ap_token is None:
        # Should never happen given the regex below, but be defensive.
        return 12
    if hour_token is not None and ap_token is not None:
        return _to_24h(int(hour_token), ap_token)
    return 12  # pragma: no cover -- defensive'''
assert old2 in s
s = s.replace(old2, new2)

# Fix 3: rewrite the range loop in extract_hours to handle the new (start_named, end_named) groups
old3 = '''    # ----- Multi-hour 12h ranges ---------------------------------------------
    for m in _TIME_RANGE_RE.finditer(text_l):
        h1, ap1, h2, ap2 = m.group(1), m.group(2), m.group(3), m.group(4)
        start = _to_24h(int(h1), ap1)
        end = _parse_noon_or(h2, ap2)
        if end == 0 and not (h2 and ap2 and ap2.lower().startswith("m")):
            # If no explicit end and token was just "noon/midnight", we already
            # handled it via _parse_noon_or.
            pass
        if start <= end:
            hours.update(range(start, end))
        else:
            # Wrap-around midnight, e.g. 10 PM until 1 AM
            hours.update(range(start, 24))
            hours.update(range(0, end))'''
new3 = '''    # ----- Multi-hour 12h ranges (incl. noon/midnight) ----------------------
    for m in _TIME_RANGE_RE.finditer(text_l):
        sh, sap, en, eap, e_named, s_named = (
            m.group(1), m.group(2), m.group(3), m.group(4), m.group(5), m.group(6),
        )
        if sh is not None and sap is not None:
            start = _to_24h(int(sh), sap)
        elif s_named:
            start = 12 if s_named.lower().startswith(("n", "midday")) else 0
        else:
            continue
        if en is not None and eap is not None:
            end = _to_24h(int(en), eap)
        elif e_named:
            end = 12 if e_named.lower().startswith(("n", "midday")) else 0
        else:
            continue
        if start <= end:
            hours.update(range(start, end))
        else:
            # Wrap-around midnight, e.g. 10 PM until 1 AM
            hours.update(range(start, 24))
            hours.update(range(0, end))'''
assert old3 in s
s = s.replace(old3, new3)

open(p, 'w', encoding='utf-8').write(s)
print('OK rewrote parser time-range block')
