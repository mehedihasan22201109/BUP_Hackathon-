import json, urllib.request
cases = json.load(open("sample_cases/public_sample_cases.json"))["cases"]
sample = next(c for c in cases if c["id"]=="SAMPLE-01")
inp = sample["input"]
req = urllib.request.Request("http://127.0.0.1:8000/optimize-energy", data=json.dumps(inp).encode(), headers={"Content-Type":"application/json"})
r = json.loads(urllib.request.urlopen(req).read())
print("SCENARIO:", r["scenario_id"])
print("TOTAL:", r["total_grid_kwh"], "COST:", r["total_cost_bdt"], "PEAK:", r["peak_grid_kwh"])
print("DIRECTIVES:")
for d in r["directive_interpretation"]:
    print(" ", d)
print("\nHOURLY PLAN:")
for h in r["hourly_plan"]:
    flag = ""
    if h["grid_kwh"] >= 175:
        flag = "  <-- high!"
    print(f"  h={h['hour']:>2}  grid={h['grid_kwh']:.2f}  solar_used={h['solar_used_kwh']:.2f}  act={h['battery_action']:<8}  bat={h['battery_kwh']:.2f}  E_after={h['battery_energy_after_kwh']:.2f}{flag}")
