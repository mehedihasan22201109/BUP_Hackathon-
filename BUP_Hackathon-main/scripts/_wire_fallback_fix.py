p = 'app/services/optimizer_service.py'
s = open(p, encoding='utf-8').read()

# Remove the early continue after R2 so R3 can also fire.
old = '''            if not llm_hours and fb_hours:
                llm_adj = {**llm_adj, "hours": fb_hours}
                llm["structured_adjustment"] = llm_adj
                by_idx[idx] = llm
                continue'''
new = '''            if not llm_hours and fb_hours:
                llm_adj = {**llm_adj, "hours": fb_hours}
                llm["structured_adjustment"] = llm_adj
                by_idx[idx] = llm'''

assert old in s, 'r2-early-continue marker not found'
s = s.replace(old, new)

open(p, 'w', encoding='utf-8').write(s)
print('OK: removed early continue so R3 can also fire.')
