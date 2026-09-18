p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()
# Replace the broken regex with a clearer one: the time-range pattern is any of
# (digit am/pm) | (noon/midnight), twice, separated by a range token.
old = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\\\b(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b|(noon|midday|midnight))\\\\s*"\n'
    '    r"(?:until|to|through|til|-|\\\\u2013|\\\\u2014)\\\\s*"\n'
    '    r"(?:(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b)|(noon|midday|midnight))",\n'
    '    re.IGNORECASE,\n'
    ')'
)
new = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\\\b(?:(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b)|(?:noon|midday|midnight))\\\\s*"\n'
    '    r"(?:until|to|through|til|-|\\\\u2013|\\\\u2014)\\\\s*"\n'
    '    r"(?:(?:(\\\\d{1,2})\\\\s*([ap])\\\\.?m\\\\.?\\\\b)|(?:noon|midday|midnight))\\\\b",\n'
    '    re.IGNORECASE,\n'
    ')'
)
assert old in s, 'time_range_re marker not found'
s = s.replace(old, new)
open(p, 'w', encoding='utf-8').write(s)
print('OK')
