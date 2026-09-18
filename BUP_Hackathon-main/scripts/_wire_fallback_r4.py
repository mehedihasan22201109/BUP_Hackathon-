p = 'app/services/optimizer_service.py'
s = open(p, encoding='utf-8').read()

# Add R4: same type but LLM numeric is missing/zero and fallback numeric is real.
old_anchor = '''        # R2: LLM hours empty, fallback hours populated.'''
new_block = '''        # R4: same directive type, but LLM numeric is zero/missing while
        # fallback has a real number. Use the fallback's numeric.
        if llm_type == fb_type and fb_applies and llm_type != "no_op":
            if llm_type == "max_grid_window":
                llm_cap = llm_adj.get("max_grid_kwh")
                fb_cap = fb_adj.get("max_grid_kwh")
                if llm_cap in (None, 0.0) and fb_cap not in (None, 0.0):
                    llm_adj = {**llm_adj, "max_grid_kwh": fb_cap}
                    llm["structured_adjustment"] = llm_adj
                    by_idx[idx] = llm
                    continue
            elif llm_type == "minimum_battery_reserve":
                llm_min = llm_adj.get("minimum_energy_kwh")
                fb_min = fb_adj.get("minimum_energy_kwh")
                if llm_min in (None, 0.0) and fb_min not in (None, 0.0):
                    llm_adj = {**llm_adj, "minimum_energy_kwh": fb_min}
                    llm["structured_adjustment"] = llm_adj
                    by_idx[idx] = llm
                    continue

        # R2: LLM hours empty, fallback hours populated.'''
assert old_anchor in s, 'R2 anchor not found'
s = s.replace(old_anchor, new_block)

open(p, 'w', encoding='utf-8').write(s)
print('OK: R4 installed.')
