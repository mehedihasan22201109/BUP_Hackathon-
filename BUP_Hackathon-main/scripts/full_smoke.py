import json, urllib.request, sys
base = 'http://127.0.0.1:5500'
api  = 'http://127.0.0.1:8000'
errs = []

def check(label, url, expect_json=False):
    try:
        r = urllib.request.urlopen(url, timeout=5)
        body = r.read()
        tag = 'OK ' if r.status == 200 else 'FAIL'
        print(f'{tag} {label:20s} {r.status} {len(body):>7} B')
        if expect_json:
            json.loads(body)
    except Exception as e:
        errs.append((label, str(e)))
        print(f'FAIL {label:20s} -> {e}')

check('frontend /',        base + '/')
check('frontend index',    base + '/index.html')
check('frontend css',      base + '/styles.css')
check('frontend js',       base + '/app.js')
check('frontend samples',  base + '/samples.json', expect_json=True)
check('api /health',       api  + '/health',       expect_json=True)
check('api /openapi.json', api  + '/openapi.json', expect_json=True)

print()
print('=== POST /optimize-energy for all 10 samples ===')
sm = json.loads(urllib.request.urlopen(base + '/samples.json', timeout=5).read())
for c in sm['cases']:
    body = json.dumps(c['input']).encode()
    req = urllib.request.Request(api + '/optimize-energy', data=body, headers={'Content-Type':'application/json'})
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        rows = len(resp.get('hourly_plan', []))
        dirs = sum(1 for d in resp.get('directive_interpretation', []) if d.get('applies'))
        print(f'OK {c["id"]:10s} rows={rows} directives_applied={dirs}/{len(resp.get("directive_interpretation", []))}')
    except Exception as e:
        errs.append((c['id'], str(e)))
        print(f'FAIL {c["id"]} -> {e}')

print()
if errs:
    print('ERRORS:', errs); sys.exit(1)
print('all checks passed')
