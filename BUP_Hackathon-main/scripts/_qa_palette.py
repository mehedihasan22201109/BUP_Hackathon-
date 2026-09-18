import re, urllib.request as r
js  = r.urlopen("http://127.0.0.1:5500/app.js", timeout=5).read().decode("utf-8-sig")
# Print all chart color literals and the dataset palette block
print("--- color: '...' lines ---")
for m in re.finditer(r"color\s*:\s*['\"]#[0-9a-fA-F]{3,8}['\"]", js):
    print(" ", m.group(0))
print("\n--- backgroundColor: '...' lines ---")
for m in re.finditer(r"backgroundColor\s*:\s*['\"]#?[0-9a-fA-F]{3,8}['\"]", js):
    print(" ", m.group(0))
print("\n--- borderColor: '...' lines ---")
for m in re.finditer(r"borderColor\s*:\s*['\"]#?[0-9a-fA-F]{3,8}['\"]", js):
    print(" ", m.group(0))
print("\n--- rgba(...) lines ---")
for m in re.finditer(r"rgba\([^)]+\)", js):
    print(" ", m.group(0))