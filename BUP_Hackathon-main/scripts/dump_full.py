import json, urllib.request
with open("sample_cases/public_sample_cases.json", encoding="utf-8") as fh:
    cases = json.load(fh)["cases"]
url = "http://127.0.0.1:8000/optimize-energy"
for c in cases:
    body = json.dumps(c["input"]).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type":"application/json"})
    resp = json.loads(urllib.request.urlopen(req, timeout=60).read())
    print(c["id"], "keys:", sorted(resp.keys()))
    print("  grid=", resp["total_grid_kwh"], "cost=", resp["total_cost_bdt"], "peak=", resp["peak_grid_kwh"])
    print("  directives:", [(d["directive_type"], d["applies"]) for d in resp["directive_interpretation"]])
