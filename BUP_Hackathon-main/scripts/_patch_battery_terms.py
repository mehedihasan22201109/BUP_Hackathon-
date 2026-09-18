import re
p = 'app/llm/fallback_parser.py'
src = open(p, encoding='utf-8').read()
old = '_BATTERY_TERMS = ("battery", "soc", "reserve", "charger", "inverter",\n                  "storage", "discharge")'
new = '_BATTERY_TERMS = ("battery", "soc", "reserve", "charger", "charging",\n                  "charge", "inverter",\n                  "storage", "discharge")'
assert old in src, 'old pattern not found'
src = src.replace(old, new, 1)
open(p, 'w', encoding='utf-8').write(src)
print('patched _BATTERY_TERMS')
