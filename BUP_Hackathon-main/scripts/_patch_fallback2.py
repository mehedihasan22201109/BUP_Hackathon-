p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()

old_re_block = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\b(\\d{1,2})\\s*([ap])\\.?m\\.?\\b\\s*"\n'
    '    r"(?:until|to|through|til|-|\\u2013|\\u2014)\\s*"\n'
    '    r"(?:(?:noon|midday|midnight)|(?:(\\d{1,2})\\s*([ap])\\.?m\\.?\\b))",\n'
    '    re.IGNORECASE,\n'
    ')'
)
new_re_block = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\b(?:(\\d{1,2})\\s*([ap])\\.?m\\.?\\b|(noon|midday|midnight))\\s*"\n'
    '    r"(?:until|to|through|til|-|\\u2013|\\u2014)\\s*"\n'
    '    r"(?:(?:(\\d{1,2})\\s*([ap])\\.?m\\.?\\b)|(noon|midday|midnight))",\n'
    '    re.IGNORECASE,\n'
    ')'
)
assert old_re_block in s, 're block marker not found'
s = s.replace(old_re_block, new_re_block)

old_loop = (
    '    for m in _TIME_RANGE_RE.finditer(text_l):\n'
    '        h1, ap1, h2, ap2 = m.group(1), m.group(2), m.group(3), m.group(4)\n'
    '        start = _to_24h(int(h1), ap1)\n'
    '        end = _parse_noon_or(h2, ap2)\n'
    '        if end == 0 and not (h2 and ap2 and ap2.lower().startswith("m")):\n'
    '            # If no explicit end and token was just "noon/midnight", we already\n'
    '            # handled it via _parse_noon_or.\n'
    '            pass\n'
    '        if start <= end:\n'
    '            hours.update(range(start, end))\n'
    '        else:\n'
    '            # Wrap-around midnight, e.g. 10 PM until 1 AM\n'
    '            hours.update(range(start, 24))\n'
    '            hours.update(range(0, end))\n'
)
new_loop = (
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
    '            hours.update(range(0, end))\n'
)
assert old_loop in s, 'loop marker not found'
s = s.replace(old_loop, new_loop)

open(p, 'w', encoding='utf-8').write(s)
print('OK patched fallback_parser')
