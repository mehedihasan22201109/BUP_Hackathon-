import re, urllib.request as r
js  = r.urlopen("http://127.0.0.1:5500/app.js",   timeout=5).read().decode("utf-8-sig")
css = r.urlopen("http://127.0.0.1:5500/styles.css", timeout=5).read().decode("utf-8-sig")

print("--- app.js color values ---")
for c in ["ea580c","ca8a04","0ea5e9","7c3aed","e2e8f0","8c98b3","f6f8fc","ffffff","1f2c4a"]:
    n = js.count(c)
    print(f"  #{c}: {n} occurrences")

print("\n--- styles.css theme vars ---")
for v in ["--bg","--panel","--accent","--text","--muted","--card","--border"]:
    m = re.search(re.escape(v) + r"\s*:\s*([^;\n]+)", css)
    print(f"  {v} = {m.group(1).strip() if m else 'MISSING'}")

print("\n--- styles.css layout selector ---")
m = re.search(r"\.layout\s*\{[^}]*\}", css)
print(m.group(0) if m else "MISSING")