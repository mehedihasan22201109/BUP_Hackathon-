import json
from app.llm.fallback_parser import fallback_parse

d = json.load(open('sample_cases/public_sample_cases.json', encoding='utf-8'))
for c in d['cases']:
    print(c['id'])
    for i, n in enumerate(c['input']['operator_notes']):
        r = fallback_parse(n, i, capacity_kwh=c['input']['battery']['capacity_kwh'])
        print('  ', i, '->', r['directive_type'], r.get('structured_adjustment'))
