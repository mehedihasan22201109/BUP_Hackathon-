import json, urllib.request
with open("sample_cases/public_sample_cases.json", encoding="utf-8") as fh:
    cases = json.load(fh)["cases"]
url = "http://127.0.0.1:8000/optimize-energy"
tol = 0.01
passed = 0
for c in cases:
    body = json.dumps(c["input"]).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    exp = c["expected_output"]
    diffs = []
    for k in ("total_grid_kwh", "total_cost_bdt", "peak_grid_kwh"):
        if abs(resp[k] - exp[k]) > tol:
            diffs.append(f"{k}={resp[k]} (exp {exp[k]})")
    if not diffs:
        passed += 1
        verdict = "PASS"
    else:
        verdict = "FAIL " + ", ".join(diffs)
    print(f"{c['id']:12s} {verdict}")
print(f"-- {passed}/{len(cases)} within tolerance")
