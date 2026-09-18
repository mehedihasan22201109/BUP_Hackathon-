import json, urllib.request
cases = json.load(open('sample_cases/public_sample_cases.json'))['cases']
url = 'http://127.0.0.1:8000/optimize-energy'
for c in cases:
    body = json.dumps(c['input']).encode()
    req = urllib.request.Request(url, data=body, headers={'Content-Type':'application/json'})
    r = json.loads(urllib.request.urlopen(req).read())
    e = c['expected_output']
    diffs = []
    if abs(r['total_grid_kwh']-e['total_grid_kwh'])>0.01: diffs.append(f"grid={r['total_grid_kwh']}({e['total_grid_kwh']})")
    if abs(r['total_cost_bdt']-e['total_cost_bdt'])>0.01: diffs.append(f"cost={r['total_cost_bdt']}({e['total_cost_bdt']})")
    if abs(r['peak_grid_kwh']-e['peak_grid_kwh'])>0.01: diffs.append(f"peak={r['peak_grid_kwh']}({e['peak_grid_kwh']})")
    flag = 'OK' if not diffs else 'DIFF '+', '.join(diffs)
    print(c['id'], 'cost=', r['total_cost_bdt'], 'peak=', r['peak_grid_kwh'], flag)
