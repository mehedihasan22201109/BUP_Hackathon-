import json, urllib.request
cases = json.load(open("sample_cases/public_sample_cases.json"))["cases"]
sample = next(c for c in cases if c["id"]=="SAMPLE-01")
inp = sample["input"]
print("=== INPUT ===")
print(json.dumps(inp, indent=2))
print("\n=== EXPECTED OUTPUT ===")
print(json.dumps(sample["expected_output"], indent=2))
