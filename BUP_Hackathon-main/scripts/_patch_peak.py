p = 'app/optimization/model.py'
src = open(p, encoding='utf-8').read()
old = '''    # ---- Objective ----
    prob += pulp.lpSum(artifacts.grid[h] * tariff[h] for h in range(24))
'''
new = '''    # ---- Objective ----
    # Primary: minimize total grid electricity cost (spec §5.2).
    # Secondary: minimize peak grid kWh as a tie-breaker so that the solver
    # picks the lowest-peak schedule among cost-equivalent optima. The
    # tie-breaker weight (PEAK_WEIGHT) is intentionally tiny: any cost
    # difference of 1e-3 BDT dominates it, so cost ordering is preserved.
    # This makes the chosen schedule deterministic and reproducible across
    # cases where multiple schedules achieve the same minimum cost.
    PEAK_WEIGHT = 1e-3
    peak = pulp.LpVariable("peak_grid_kwh", lowBound=0)
    for h in range(24):
        prob += peak >= artifacts.grid[h]
    prob += (
        pulp.lpSum(artifacts.grid[h] * tariff[h] for h in range(24))
        + PEAK_WEIGHT * peak
    )
'''
assert old in src, 'old block not found'
src = src.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(src)
print('patched model.py with peak tie-breaker')
