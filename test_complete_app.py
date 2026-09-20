import os
import sys
sys.path.append(os.path.join(os.path.dirname(__file__), 'api'))
sys.stdout.reconfigure(encoding='utf-8')

from index import app, load_cumpleanos_raw, get_birthday_alerts

print("--- 1. Testing Core Birthday Data ---")
birthdays = load_cumpleanos_raw()
print(f"Total birthdays loaded: {len(birthdays)}")
assert len(birthdays) >= 120, "Should have loaded 120+ birthdays"

print("--- 2. Testing Alert Calculations ---")
alerts_today = get_birthday_alerts('2026-09-19')
print(f"2026-09-19 (Hoy): {len(alerts_today['hoy'])} hoy, {len(alerts_today['proximos'])} próximos, {len(alerts_today['recientes'])} recientes")
assert 'hoy' in alerts_today and 'proximos' in alerts_today

alerts_oct = get_birthday_alerts('2026-10-15')
print(f"2026-10-15: {len(alerts_oct['hoy'])} hoy, {len(alerts_oct['proximos'])} próximos")
for h in alerts_oct['hoy']:
    print(f"  - Oct 15: {h['nombre']}")

client = app.test_client()

print("--- 3. Testing HTML Index Route ---")
res_html = client.get('/')
assert res_html.status_code == 200
html_text = res_html.data.decode('utf-8')
assert 'modalCumpleanos' in html_text, "HTML should contain modalCumpleanos"
assert 'birthdaySessionBanner' in html_text, "HTML should contain birthdaySessionBanner"
assert 'btn-cumpleanos' in html_text, "HTML should contain btn-cumpleanos"
assert 'modalWhatsappGreeting' in html_text, "HTML should contain modalWhatsappGreeting"
print("HTML markup validation passed! All birthday UI elements are present.")

print("--- 4. Testing Endpoints ---")
# GET /api/cumpleanos
res_c = client.get('/api/cumpleanos')
assert res_c.status_code == 200
assert res_c.json['total'] >= 120

# GET /api/cumpleanos with month filter
res_c_mes = client.get('/api/cumpleanos?mes=9')
assert res_c_mes.status_code == 200
assert res_c_mes.json['total'] >= 10
print(f"Septiembre birthdays: {res_c_mes.json['total']}")

# GET /api/cumpleanos/alertas
res_a = client.get('/api/cumpleanos/alertas?fecha=2026-09-19')
assert res_a.status_code == 200
assert res_a.json['status'] == 'ok'

# POST /api/cumpleanos/add
res_add = client.post('/api/cumpleanos/add', json={
    'nombre': 'Hermano Test Verificacion',
    'dia': 19,
    'mes_num': 9,
    'nota': 'Nota de prueba unitaria',
    'telefono': '+34611111111'
})
assert res_add.status_code == 200
new_id = res_add.json['record']['id']
print(f"Created test birthday with ID: {new_id}")

# POST /api/cumpleanos/update
res_up = client.post('/api/cumpleanos/update', json={
    'id': new_id,
    'nombre': 'Hermano Test Verificacion Modificado',
    'dia': 20,
    'mes_num': 9,
    'nota': 'Nota modificada'
})
assert res_up.status_code == 200
assert res_up.json['record']['nombre'] == 'Hermano Test Verificacion Modificado'
print("Updated test birthday successfully")

# POST /api/cumpleanos/delete
res_del = client.post('/api/cumpleanos/delete', json={'id': new_id})
assert res_del.status_code == 200
print("Deleted test birthday successfully")

# GET /api/cumpleanos/export-csv
res_csv = client.get('/api/cumpleanos/export-csv')
assert res_csv.status_code == 200
assert 'CALENDARIO OFICIAL' in res_csv.data.decode('utf-8')
print("CSV Export endpoint verified!")

print("--- 5. Testing Member Search with Birthday Enrichment ---")
res_s = client.get('/api/members/search?q=Berrio&fecha=2026-09-19')
assert res_s.status_code == 200
members = res_s.json
print(f"Search results for 'Berrio': {len(members)}")
for m in members:
    c_info = m.get('cumpleanos_info')
    if c_info:
        print(f"  * {m['nombre']} {m['apellidos']}: {c_info}")

print("========================================")
print("ALL COMPREHENSIVE TESTS PASSED 100% OK!")
print("========================================")
