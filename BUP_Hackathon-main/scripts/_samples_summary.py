import json
d = json.load(open("sample_cases/public_sample_cases.json", encoding="utf-8"))
for c in d["cases"]:
    eo = c["expected_output"]
    dis = eo.get("directive_interpretation", [])
    print(c["id"], "grid=", eo["total_grid_kwh"], "cost=", eo["total_cost_bdt"], "peak=", eo["peak_grid_kwh"])
    for di in dis:
        print("  ", di["note_index"], di["directive_type"], "applies=", di["applies"], "adj=", di.get("structured_adjustment"))
