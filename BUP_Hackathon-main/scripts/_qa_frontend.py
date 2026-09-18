import json, urllib.request, urllib.error, sys

DIRECTIVE_TYPES = {
    "solar_reduction", "minimum_battery_reserve",
    "no_charge_window", "no_discharge_window",
    "max_grid_window", "no_op",
}

def post(url, body, timeout=60):
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                 headers={"Content-Type":"application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.loads(r.read()), None
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read())
        except Exception:
            payload = None
        return e.code, payload, payload

def main():
    sm = json.loads(urllib.request.urlopen("http://127.0.0.1:5500/samples.json", timeout=5).read())
    failures = 0
    rows = []
    for case in sm["cases"]:
        sid = case["id"]
        raw = case["input"]
        body = {
            "scenario_id": sid,
            "operator_notes": raw.get("operator_notes", []),
            "battery": raw["battery"],
            "hours": raw["hours"],
        }
        status, resp, err = post("http://127.0.0.1:8000/optimize-energy", body)
        row = {"id": sid, "http": status, "errors": [], "display": {}}
        if err is not None and not isinstance(resp, dict):
            row["errors"].append("non-json error body")
            failures += 1; rows.append(row); continue
        if status != 200 or not isinstance(resp, dict):
            row["errors"].append("http " + str(status))
            failures += 1; rows.append(row); continue

        for k in ("scenario_id","directive_interpretation","hourly_plan",
                  "total_grid_kwh","total_cost_bdt","peak_grid_kwh","plan_summary"):
            if k not in resp:
                row["errors"].append("missing field " + k)
                failures += 1

        if resp.get("scenario_id") != sid:
            row["errors"].append("scenario_id mismatch " + repr(resp.get("scenario_id")))
            failures += 1

        plan = resp.get("hourly_plan") or []
        if len(plan) != 24:
            row["errors"].append("hourly_plan len " + str(len(plan)))
            failures += 1
        else:
            hours = [r["hour"] for r in plan]
            if hours != list(range(24)):
                row["errors"].append("hours not 0..23 in order")
                failures += 1
            else:
                tariffs = [h["tariff_bdt_per_kwh"] for h in raw["hours"]]
                rgrid = sum(r["grid_kwh"] for r in plan)
                rcost = sum(r["grid_kwh"] * tariffs[r["hour"]] for r in plan)
                rpeak = max((r["grid_kwh"] for r in plan), default=0)
                for k, exp, got in (
                    ("total_grid_kwh", rgrid, resp["total_grid_kwh"]),
                    ("total_cost_bdt", rcost, resp["total_cost_bdt"]),
                    ("peak_grid_kwh", rpeak, resp["peak_grid_kwh"]),
                ):
                    if abs(exp - got) > 0.01:
                        row["errors"].append(k + " mismatch recalc=%.3f api=%.3f" % (exp, got))
                        failures += 1

        di = resp.get("directive_interpretation") or []
        if len(di) != len(raw.get("operator_notes", [])):
            row["errors"].append("directive count " + str(len(di)))
            failures += 1
        for i, d in enumerate(di):
            if d.get("note_index") != i:
                row["errors"].append("di[%d].note_index wrong: %r" % (i, d.get("note_index")))
                failures += 1
            if d.get("directive_type") not in DIRECTIVE_TYPES:
                row["errors"].append("di[%d].directive_type invalid: %r" % (i, d.get("directive_type")))
                failures += 1
            if d.get("directive_type") == "no_op":
                if d.get("applies") is not False:
                    row["errors"].append("di[%d] no_op must have applies=false" % i)
                    failures += 1
                if d.get("structured_adjustment") is not None:
                    row["errors"].append("di[%d] no_op must have null adjustment" % i)
                    failures += 1
            else:
                if d.get("applies") is not True:
                    row["errors"].append("di[%d] applies!=true" % i)
                    failures += 1
                sa = d.get("structured_adjustment") or {}
                hrs = sa.get("hours")
                if not isinstance(hrs, list) or not all(isinstance(x, int) for x in hrs):
                    row["errors"].append("di[%d] hours not int list" % i)
                    failures += 1
                else:
                    if sorted(hrs) != hrs or len(set(hrs)) != len(hrs):
                        row["errors"].append("di[%d] hours not ascending+unique %s" % (i, hrs))
                        failures += 1
                    if any(h < 0 or h > 23 for h in hrs):
                        row["errors"].append("di[%d] hours out of 0..23" % i)
                        failures += 1
                if d.get("directive_type") == "solar_reduction":
                    f = sa.get("factor")
                    if not isinstance(f, (int, float)) or not (0.0 <= f <= 1.0):
                        row["errors"].append("di[%d] solar factor invalid %s" % (i, f))
                        failures += 1
                if d.get("directive_type") == "minimum_battery_reserve":
                    v = sa.get("minimum_energy_kwh")
                    cap = raw["battery"]["capacity_kwh"]
                    if not isinstance(v, (int, float)) or v < 0:
                        row["errors"].append("di[%d] reserve invalid %s" % (i, v))
                        failures += 1
                    elif v > cap:
                        row["errors"].append("di[%d] reserve > capacity %s>%s" % (i, v, cap))
                        failures += 1
                if d.get("directive_type") == "max_grid_window":
                    g = sa.get("max_grid_kwh")
                    if not isinstance(g, (int, float)) or g < 0:
                        row["errors"].append("di[%d] max_grid_kwh invalid %s" % (i, g))
                        failures += 1

        if len(plan) == 24:
            E0 = raw["battery"]["initial_energy_kwh"]
            cap = raw["battery"]["capacity_kwh"]
            mn = raw["battery"]["minimum_energy_kwh"]
            mch = raw["battery"]["max_charge_kwh_per_hour"]
            mdis = raw["battery"]["max_discharge_kwh_per_hour"]
            prev = E0
            last_after = None
            for r in plan:
                h = r["hour"]; action = r["battery_action"]; kwh = r["battery_kwh"]; after = r["battery_energy_after_kwh"]
                if action == "charge":
                    if kwh > mch + 1e-6:
                        row["errors"].append("h%d charge %.2f > %.2f" % (h, kwh, mch))
                        failures += 1
                    if abs((prev + kwh) - after) > 0.01:
                        row["errors"].append("h%d charge transition %.2f+%.2f != %.2f" % (h, prev, kwh, after))
                        failures += 1
                elif action == "discharge":
                    if kwh > mdis + 1e-6:
                        row["errors"].append("h%d discharge %.2f > %.2f" % (h, kwh, mdis))
                        failures += 1
                    if abs((prev - kwh) - after) > 0.01:
                        row["errors"].append("h%d discharge transition %.2f-%.2f != %.2f" % (h, prev, kwh, after))
                        failures += 1
                else:
                    if abs(prev - after) > 0.01 or kwh != 0:
                        row["errors"].append("h%d idle but kwh=%s after=%.2f prev=%.2f" % (h, kwh, after, prev))
                        failures += 1
                if after < mn - 1e-6:
                    row["errors"].append("h%d SOC %.2f below min %.2f" % (h, after, mn))
                    failures += 1
                if after > cap + 1e-6:
                    row["errors"].append("h%d SOC %.2f above cap %.2f" % (h, after, cap))
                    failures += 1
                orig = raw["hours"][h]
                lhs = r["grid_kwh"] + r["solar_used_kwh"] + (kwh if action == "discharge" else 0)
                rhs = orig["demand_kwh"] + (kwh if action == "charge" else 0)
                if abs(lhs - rhs) > 0.5:
                    row["errors"].append("h%d energy balance LHS=%.2f RHS=%.2f" % (h, lhs, rhs))
                    failures += 1
                prev = after
                last_after = after
            if last_after is not None and abs(last_after - E0) > 0.01:
                row["errors"].append("end-of-day SOC %.2f != initial %.2f" % (last_after, E0))
                failures += 1

        applies_count = sum(1 for d in di if d.get("applies"))
        row["display"] = {
            "kpi_grid": resp.get("total_grid_kwh"),
            "kpi_cost": resp.get("total_cost_bdt"),
            "kpi_peak": resp.get("peak_grid_kwh"),
            "kpi_directives": str(applies_count) + "/" + str(len(di)),
            "rows": len(plan),
            "summary_len": len(resp.get("plan_summary") or ""),
        }
        rows.append(row)
        print(json.dumps({"id": sid, "errors": row["errors"], "display": row["display"]}, ensure_ascii=False))
    print("---")
    print("total:", len(rows), "failures:", failures)
    sys.exit(0 if failures == 0 else 1)

main()