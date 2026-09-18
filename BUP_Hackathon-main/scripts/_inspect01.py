import json, urllib.request
cases = json.load(open("sample_cases/public_sample_cases.json"))["cases"]
sample = next(c for c in cases if c["id"]=="SAMPLE-01")
inp = sample["input"]
body = {"scenario_id": inp["scenario_id"], "operator_notes": inp["operator_notes"], "hours": inp["hours"]}
req = urllib.request.Request("http://127.0.0.1:8000/optimize-energy", data=json.dumps(body).encode(), headers={"Content-Type":"application/json"})
r = json.loads(urllib.request.urlopen(req).read())
m = r["metrics"]
print("peak:", m["peak_grid_kwh"], "total_grid:", m["total_grid_kwh"], "cost:", m["total_cost_bdt"])
print("expected: peak=", sample["expected_output"]["metrics"]["peak_grid_kwh"], "total_grid=", sample["expected_output"]["metrics"]["total_grid_kwh"], "cost=", sample["expected_output"]["metrics"]["total_cost_bdt"])
print("hourly grid (kWh):")
for h in r["hourly_schedule"]:
    print(f"  h={h['hour']:>2}  grid={h['grid_kwh']:.2f}")
