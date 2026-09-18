p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()

# --- 1. Replace the _TIME_RANGE_RE with explicit named groups ---------------
old_re = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\b(?:(\\d{1,2})\\s*([ap])\\.?m\\.?\\b|(noon|midday|midnight))\\s*"\n'
    '    r"(?:until|to|through|til|-|\\u2013|\\u2014)\\s*"\n'
    '    r"(?:(?:(\\d{1,2})\\s*([ap])\\.?m\\.?\\b)|(noon|midday|midnight))",\n'
    '    re.IGNORECASE,\n'
    ')'
)
new_re = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\b(?:(?:(?P<sh>\\d{1,2})\\s*(?P<sap>[ap])\\.?m\\.?\\b)|(?:(?P<sn>noon|midday|midnight)))\\s*"\n'
    '    r"(?:until|to|through|til|-|\\u2013|\\u2014)\\s*"\n'
    '    r"(?:(?:(?P<eh>\\d{1,2})\\s*(?P<eap>[ap])\\.?m\\.?\\b)|(?:(?P<en>noon|midday|midnight)))\\b",\n'
    '    re.IGNORECASE,\n'
    ')'
)
assert old_re in s, 'old _TIME_RANGE_RE marker not found'
s = s.replace(old_re, new_re)

# --- 2. Replace the buggy group-indexed loop with named-group helpers ---------
old_loop = (
    '    for m in _TIME_RANGE_RE.finditer(text_l):\n'
    '        sh, sap, en, eap = m.group(1), m.group(2), m.group(3), m.group(4)\n'
    '        s_named, e_named = m.group(5), m.group(6)\n'
    '        if sh is not None and sap is not None:\n'
    '            start = _to_24h(int(sh), sap)\n'
    '        elif s_named is not None:\n'
    '            start = 12 if s_named.lower().startswith(("n", "midday")) else 0\n'
    '        else:\n'
    '            continue\n'
    '        if en is not None and eap is not None:\n'
    '            end = _to_24h(int(en), eap)\n'
    '        elif e_named is not None:\n'
    '            end = 12 if e_named.lower().startswith(("n", "midday")) else 0\n'
    '        else:\n'
    '            continue\n'
    '        if start <= end:\n'
    '            hours.update(range(start, end))\n'
    '        else:\n'
    '            # Wrap-around midnight, e.g. 10 PM until 1 AM\n'
    '            hours.update(range(start, 24))\n'
    '            hours.update(range(0, end))'
)
new_loop = (
    '    for m in _TIME_RANGE_RE.finditer(text_l):\n'
    '        start = _start_hour(m)\n'
    '        end = _end_hour(m)\n'
    '        if start is None or end is None:\n'
    '            continue\n'
    '        if start <= end:\n'
    '            hours.update(range(start, end))\n'
    '        else:\n'
    '            # Wrap-around midnight, e.g. 10 PM until 1 AM\n'
    '            hours.update(range(start, 24))\n'
    '            hours.update(range(0, end))'
)
assert old_loop in s, 'old loop marker not found'
s = s.replace(old_loop, new_loop)

# --- 3. Insert _start_hour / _end_hour helpers above _parse_noon_or -----------
helper_block = (
    'def _start_hour(m) -> Optional[int]:\n'
    '    """Resolve the start hour from a _TIME_RANGE_RE match."""\n'
    '    if m.group("sh") is not None and m.group("sap") is not None:\n'
    '        return _to_24h(int(m.group("sh")), m.group("sap"))\n'
    '    sn = m.group("sn")\n'
    '    if sn is not None:\n'
    '        return 0 if sn.lower().startswith("mid") else 12\n'
    '    return None\n'
    '\n'
    '\n'
    'def _end_hour(m) -> Optional[int]:\n'
    '    """Resolve the end hour from a _TIME_RANGE_RE match (half-open)."""\n'
    '    if m.group("eh") is not None and m.group("eap") is not None:\n'
    '        return _to_24h(int(m.group("eh")), m.group("eap"))\n'
    '    en = m.group("en")\n'
    '    if en is not None:\n'
    '        return 0 if en.lower().startswith("mid") else 12\n'
    '    return None\n'
    '\n'
    '\n'
    'def _parse_noon_or(hour_token: str, ap_token: str) -> int:\n'
    '    """Helper for the rare \'noon\' / \'midnight\' end-of-range token."""\n'
    '    if hour_token is None:\n'
    '        # Noon = 12, midnight = 0\n'
    '        return 12 if ap_token.lower().startswith("n") else 0\n'
    '    return _to_24h(int(hour_token), ap_token)'
)
anchor = (
    'def _parse_noon_or(hour_token: str, ap_token: str) -> int:\n'
    '    """Helper for the rare \'noon\' / \'midnight\' end-of-range token."""\n'
    '    if hour_token is None:\n'
    '        # Noon = 12, midnight = 0\n'
    '        return 12 if ap_token.lower().startswith("n") else 0\n'
    '    return _to_24h(int(hour_token), ap_token)'
)
assert anchor in s, '_parse_noon_or anchor not found'
s = s.replace(anchor, helper_block)

open(p, 'w', encoding='utf-8').write(s)
print('OK: fallback_parser.py patched (regex + loop + helpers).')
