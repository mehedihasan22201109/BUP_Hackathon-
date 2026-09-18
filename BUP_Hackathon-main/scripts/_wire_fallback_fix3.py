p = 'app/services/optimizer_service.py'
s = open(p, encoding='utf-8').read()

old = '''        llm_applies = bool(llm.get("applies", False))
        fb_applies = bool(fb.get("applies", False))

        # R1a: LLM no_op but fallback found a directive.'''
new = '''        llm_applies = bool(llm.get("applies", False))
        fb_applies = bool(fb.get("applies", False))
        llm_adj = llm.get("structured_adjustment") or {}
        fb_adj = fb.get("structured_adjustment") or {}

        # R1a: LLM no_op but fallback found a directive.'''
assert old in s, 'marker not found'
s = s.replace(old, new)

# Now remove the duplicate definitions later.
old2 = '''        if not fb_applies:
            continue

        llm_adj = llm.get("structured_adjustment") or {}
        fb_adj = fb.get("structured_adjustment") or {}

        # R2: LLM hours empty, fallback hours populated.'''
new2 = '''        if not fb_applies:
            continue

        # R2: LLM hours empty, fallback hours populated.'''
assert old2 in s, 'duplicate marker not found'
s = s.replace(old2, new2)

open(p, 'w', encoding='utf-8').write(s)
print('OK: hoisted llm_adj/fb_adj, deduped.')
