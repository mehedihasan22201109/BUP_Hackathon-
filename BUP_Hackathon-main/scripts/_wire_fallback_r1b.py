p = 'app/services/optimizer_service.py'
s = open(p, encoding='utf-8').read()

# Strengthen R1: when LLM and fallback types differ AND the fallback has
# non-default evidence (a non-empty numeric value), the LLM misclassified
# and we should prefer the fallback's interpretation.
old_r1 = '''        # R1: LLM no_op but fallback found a directive.
        if not llm_applies and fb_applies:
            by_idx[idx] = fb
            continue'''
new_r1 = '''        # R1a: LLM no_op but fallback found a directive.
        if not llm_applies and fb_applies:
            by_idx[idx] = fb
            continue

        # R1b: LLM and fallback disagree on type, AND fallback has a
        # non-default numeric (factor, cap, minimum) -- the LLM misclassified
        # the note. Trust the fallback.
        if (
            llm_applies
            and fb_applies
            and llm_type != fb_type
            and fb_type != "no_op"
        ):
            fb_adj_check = fb_adj
            has_evidence = (
                fb_adj_check.get("factor") not in (None, 0.5)
                or fb_adj_check.get("minimum_energy_kwh") not in (None, 0)
                or fb_adj_check.get("max_grid_kwh") not in (None, 0)
            )
            if has_evidence:
                by_idx[idx] = fb
                continue'''

assert old_r1 in s, 'r1 marker not found'
s = s.replace(old_r1, new_r1)

open(p, 'w', encoding='utf-8').write(s)
print('OK: R1b installed.')
