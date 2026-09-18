p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()

old = """    for m in _TIME_RANGE_RE.finditer(text_l):
        start = _start_hour(m)
        end = _end_hour(m)
        if start is None or end is None:
            continue
        if start <= end:
            hours.update(range(start, end))
        else:
            # Wrap-around midnight, e.g. 10 PM until 1 AM
            hours.update(range(start, 24))
            hours.update(range(0, end))

    # ----- 24h ranges \"22:00 until 23:00\" -----------------------------------
    for m in _TIME_RANGE_24H_RE.finditer(text_l):
        s = int(m.group(1))
        e = int(m.group(3))
        if s <= e:
            hours.update(range(s, e))
        else:
            hours.update(range(s, 24))
            hours.update(range(0, e))

    # ----- Single 12h mentions (after ranges to avoid double-counting) --------
    for m in _HOUR12_RE.finditer(text_l):
        h, ap = int(m.group(1)), m.group(2)
        hours.add(_to_24h(h, ap))

    # ----- 24h \"22:00\" -------------------------------------------------------
    for m in _HOUR24_RE.finditer(text_l):
        hours.add(int(m.group(1)))

    # ----- \"hour N\" ----------------------------------------------------------
    for m in _HOUR_WORD_RE.finditer(text_l):
        h = int(m.group(1))
        if 0 <= h <= 23:
            hours.add(h)
"""

new = """    # Char spans covered by range matches so the single-hour scanners below
    # do not double-count tokens like \"2 PM\" that are already part of a range.
    covered: List[tuple] = []
    for m in _TIME_RANGE_RE.finditer(text_l):
        covered.append((m.start(), m.end()))
        start = _start_hour(m)
        end = _end_hour(m)
        if start is None or end is None:
            continue
        if start <= end:
            hours.update(range(start, end))
        else:
            # Wrap-around midnight, e.g. 10 PM until 1 AM
            hours.update(range(start, 24))
            hours.update(range(0, end))

    for m in _TIME_RANGE_24H_RE.finditer(text_l):
        covered.append((m.start(), m.end()))
        s = int(m.group(1))
        e = int(m.group(3))
        if s <= e:
            hours.update(range(s, e))
        else:
            hours.update(range(s, 24))
            hours.update(range(0, e))

    # ----- Single 12h mentions (skip tokens already inside a range) ---------
    for m in _HOUR12_RE.finditer(text_l):
        if any(a <= m.start() < b for a, b in covered):
            continue
        h, ap = int(m.group(1)), m.group(2)
        hours.add(_to_24h(h, ap))

    # ----- 24h \"22:00\" -------------------------------------------------------
    for m in _HOUR24_RE.finditer(text_l):
        if any(a <= m.start() < b for a, b in covered):
            continue
        hours.add(int(m.group(1)))

    # ----- \"hour N\" ----------------------------------------------------------
    for m in _HOUR_WORD_RE.finditer(text_l):
        if any(a <= m.start() < b for a, b in covered):
            continue
        h = int(m.group(1))
        if 0 <= h <= 23:
            hours.add(h)
"""

assert old in s, 'single-block marker not found'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('OK: covered-span guard installed across all hour scanners.')
