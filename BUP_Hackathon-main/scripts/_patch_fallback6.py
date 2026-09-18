p = 'app/llm/fallback_parser.py'
s = open(p, encoding='utf-8').read()

# --- 1. Expand the time-range separator list ----------------------------------
old = '''    r"(?:until|to|through|til|-|\\u2013|\\u2014)\\s*"'''
new = '''    r"(?:until|to|through|til|and|from|before|after|-|\\u2013|\\u2014)\\s*"'''
assert old in s, 'separator marker not found'
s = s.replace(old, new)

# --- 2. Loosen the no_charge_window keyword check -----------------------------
old_block = '''    if (
        "no charge" in text_l
        or "cannot charge" in text_l
        or "won\'t charge" in text_l
        or "will not charge" in text_l
        or "charger isolated" in text_l
        or "charging circuit" in text_l and ("unavailable" in text_l or "disabled" in text_l)
        or "charging is disabled" in text_l
        or "charging outage" in text_l
    ):'''
new_block = '''    if (
        "no charge" in text_l
        or "cannot charge" in text_l
        or "won\'t charge" in text_l
        or "will not charge" in text_l
        or "charger isolated" in text_l
        or ("isolated" in text_l and ("charger" in text_l or "charging" in text_l))
        or "charging circuit" in text_l and ("unavailable" in text_l or "disabled" in text_l)
        or "charging is disabled" in text_l
        or "charging outage" in text_l
        or ("charging" in text_l and ("disabled" in text_l or "offline" in text_l or "unavailable" in text_l))
    ):'''
assert old_block in s, 'no_charge marker not found'
s = s.replace(old_block, new_block)

open(p, 'w', encoding='utf-8').write(s)
print('OK: range separators + no_charge keyword expanded.')
