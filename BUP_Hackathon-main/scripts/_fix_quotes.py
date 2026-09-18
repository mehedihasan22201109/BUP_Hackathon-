import io
p = 'app/schemas.py'
s = open(p, encoding='utf-8').read()
bad = "description=''1 to 3 operator notes per official spec \u00a77.1''"
good = 'description="1 to 3 operator notes per official spec section 7.1"'
assert bad in s, 'marker not found'
s = s.replace(bad, good)
open(p, 'w', encoding='utf-8').write(s)
print('OK')
