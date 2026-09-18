import json, urllib.request, urllib.error
url = 'http://127.0.0.1:8000/optimize-energy'

base_body = {
    'scenario_id': 'T', 'operator_notes': ['note one'], 'battery': {
        'capacity_kwh': 100, 'initial_energy_kwh': 50, 'minimum_energy_kwh': 10,
        'max_charge_kwh_per_hour': 20, 'max_discharge_kwh_per_hour': 20,
    },
    'hours': [{'hour': h, 'demand_kwh': 50, 'solar_kwh': 0, 'tariff_bdt_per_kwh': 6} for h in range(24)],
}

def post(notes):
    body = dict(base_body, operator_notes=notes)
    req = urllib.request.Request(url, data=json.dumps(body).encode(),
        headers={'Content-Type': 'application/json'})
    try:
        r = urllib.request.urlopen(req, timeout=5)
        return r.status, r.read()[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read()[:200]

print('empty:', post([]))
print('one:  ', post(['only note']))
print('three:', post(['a','b','c']))
print('four: ', post(['a','b','c','d']))
