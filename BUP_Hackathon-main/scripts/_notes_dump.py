import json
d = json.load(open("sample_cases/public_sample_cases.json", encoding="utf-8"))
for c in d["cases"]:
    print(c["id"], "|", c["label"])
    for i, n in enumerate(c["input"]["operator_notes"]):
        print(" ", i, ":", n)
    print()
