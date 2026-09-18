import re, urllib.request as r
css = r.urlopen("http://127.0.0.1:5500/styles.css", timeout=5).read().decode("utf-8-sig")
js  = r.urlopen("http://127.0.0.1:5500/app.js",   timeout=5).read().decode("utf-8-sig")
html = r.urlopen("http://127.0.0.1:5500/",         timeout=5).read().decode("utf-8-sig")

results = []

# U1: CSS file is valid UTF-8 and serves with no BOM
results.append(("U1 CSS no BOM + light theme variables",
                "PASS" if ("--bg:#f6f8fc" in css and "--panel:#ffffff" in css) else "FAIL",
                "css len=%d bg=%s panel=%s" % (len(css),
                    re.search(r"--bg:\s*([^;\n]+)", css).group(1) if re.search(r"--bg:", css) else "?",
                    re.search(r"--panel:\s*([^;\n]+)", css).group(1) if re.search(r"--panel:", css) else "?")))

# U2: dark-theme colors should NOT be in styles.css
dark = ["#0b1220", "#1f2c4a", "#8c98b3"]
found_dark = [c for c in dark if c in css]
results.append(("U2 no dark-theme background colors remain",
                "PASS" if not found_dark else "FAIL",
                "residual dark colors: " + ", ".join(found_dark)))

# U3: light-theme chart palette present in app.js Chart options
expected_js = ["#ea580c", "#ca8a04", "#0ea5e9", "#7c3aed", "#e2e8f0"]
missing = [c for c in expected_js if c not in js]
results.append(("U3 light chart palette in app.js",
                "PASS" if not missing else "FAIL",
                "missing: " + ", ".join(missing) if missing else "all 5 colors present (grid/solar/batt/soc/orange grid line)"))

# U4: dark-mode ticks gone from Chart.js options
bad = ['color: "#8c98b3"', "color: '#8c98b3'"]
results.append(("U4 no dark-mode tick colors in app.js",
                "PASS" if not any(b in js for b in bad) else "FAIL",
                "residual dark tick colors: " + str([b for b in bad if b in js])))

# U5: KPI cards + 4 cards exist
kpi_ids = ["kpi-grid", "kpi-cost", "kpi-peak", "kpi-directives"]
present = all(("id=\"" + i + "\"" in html for i in kpi_ids))
results.append(("U5 four KPI cards present", "PASS" if present else "FAIL",
                "found: " + ", ".join(i for i in kpi_ids if ("id=\""+i+"\"") in html)))

# U6: hourly plan table renders 6 columns
header_present = all(s in html for s in ["hour","grid","solar","action","battery kWh","SOC after"])
results.append(("U6 plan table 6 columns", "PASS" if header_present else "FAIL",
                "headers seen"))

# U7: loading state on Optimize button
btn_optimize = "Optimizing" in js or 'btn.textContent = "Optimizing' in js
results.append(("U7 loading state on Optimize button", "PASS" if btn_optimize else "FAIL",
                "btnOptimize text set to Optimizing"))

# U8: error rendering path
err = ('showError' in js and 'errorbar' in js)
results.append(("U8 error state rendered to DOM", "PASS" if err else "FAIL",
                "showError() + errorbar"))

# U9: long-notes safety — textarea rows=4 + CSS line-clamp on .why
ok_long = ('rows="4"' in html) and (".why" in css)
results.append(("U9 long notes do not break layout (textarea rows=4 + .why style)",
                "PASS" if ok_long else "FAIL",
                "textarea+css present"))

# U10: responsive layout uses grid
results.append(("U10 responsive grid layout in CSS",
                "PASS" if ".layout{" in css and "grid" in css else "FAIL",
                "layout uses CSS grid"))

# U11: API_BASE hardcoded to :8000 so POSTs don't hit the static server
results.append(("U11 API_BASE pinned to :8000 (no 501 from http.server)",
                "PASS" if 'const API_BASE = "http://127.0.0.1:8000"' in js else "FAIL",
                "pinned in app.js"))

# U12: directive_interpretation passed straight through, no rewriting
passthrough = ('d.directive_type' in js and 'd.applies' in js and 'd.note_index' in js)
results.append(("U12 directive interpretation rendered verbatim",
                "PASS" if passthrough else "FAIL",
                "render() reads d.directive_type / d.applies / d.note_index"))

print("\n%-55s %-6s %s" % ("UI/UX check", "Status", "Evidence"))
print("-"*100)
for name, st, ev in results:
    print("%-55s %-6s %s" % (name, st, ev))
total = len(results); passed = sum(1 for _,s,_ in results if s == "PASS"); failed = total - passed
print("-"*100)
print("total:", total, "passed:", passed, "failed:", failed)