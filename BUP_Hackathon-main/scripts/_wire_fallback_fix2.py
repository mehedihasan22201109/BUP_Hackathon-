p = 'app/services/optimizer_service.py'
s = open(p, encoding='utf-8').read()

# Move fb_adj initialization above R1a early continue so R1b can use it.
old = '''        llm_applies = bool(llm.get("applies", False))
        fb_applies = bool(fb.get("applies", False))

        # R1a: LLM no_op but fallback found a directive.
        if not llm_applies and fb_applies:
            by_idx[idx] = fb
            continue

        if not fb_applies:
            continue

        llm_adj = llm.get("structured_adjustment") or {}
        fb_adj = fb.get("structured_adjustment") or {}'''
new = '''        llm_applies = bool(llm.get("applies", False))
        fb_applies = bool(fb.get("applies", False))
        llm_adj = llm.get("structured_adjustment") or {}
        fb_adj = fb.get("structured_adjustment") or {}

        # R1a: LLM no_op but fallback found a directive.
        if not llm_applies and fb_applies:
            by_idx[idx] = fb
            continue

        if not fb_applies:
            continue'''
assert old in s, 'fb_adj marker not found'
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
print('OK: fb_adj initialized before R1a.')
