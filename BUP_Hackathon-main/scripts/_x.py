p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()

old_re_block = (
    '_TIME_RANGE_RE = re.compile(\n'
    '    r"\\b(\\d{1,2})\\s*([ap])\\.?m\\.?\\b\\s*"\n'
    '    r"(?:until|to|through|til|-|\\u2013|\\u2014)\\s*"\n'
    '    r"(?:(?:noon|midday|midnight)|(?:(\\d{1,2})\\s*([ap])\\.?m\\.?\\b))",\n'
    '    re.IGNORECASE,\n'
    ')'
