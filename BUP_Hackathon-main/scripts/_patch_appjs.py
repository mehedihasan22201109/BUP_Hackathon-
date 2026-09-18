p = "frontend/app.js"
c = open(p, encoding="utf-8").read()
old = (
    'const API_BASE = (location.protocol === "file:" || location.port === "")\n'
    '  ? "http://127.0.0.1:8000"\n'
    '  : location.origin;'
)
new = 'const API_BASE = "http://127.0.0.1:8000";'
print("found:", old in c)
open(p, "w", encoding="utf-8").write(c.replace(old, new))
print("done")
