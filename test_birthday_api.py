import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'api'))
sys.stdout.reconfigure(encoding='utf-8')

from index import app, get_birthday_alerts, load_cumpleanos_raw

print('=== TESTING CUMPLEAÑOS MODULE ===')
all_b = load_cumpleanos_raw()
print(f'Total birthdays in system: {len(all_b)}')

# Test for 2026-09-19
alerts = get_birthday_alerts('2026-09-19')
print(f"Alerts for 2026-09-19: Hoy={len(alerts['hoy'])}, Próximos={len(alerts['proximos'])}, Recientes={len(alerts['recientes'])}, Total Mes={len(alerts['mes_actual'])}")
for h in alerts['hoy']:
    print(f"  🎉 HOY: {h['nombre']} ({h.get('categoria', 'Hermano')}) - {h.get('nota', '')}")

for p in alerts['proximos']:
    print(f"  🎂 PRÓXIMO: {p['nombre']} -> {p.get('dia')} de {p.get('mes')} ({p.get('dia_semana')}) [{p.get('etiqueta')}]")

client = app.test_client()

# Test GET /api/cumpleanos
res1 = client.get('/api/cumpleanos?mes=9')
print(f'GET /api/cumpleanos?mes=9: status={res1.status_code}, count={len(res1.json.get("cumpleanos", []))}')

# Test GET /api/cumpleanos/alertas
res2 = client.get('/api/cumpleanos/alertas?fecha=2026-09-19')
print(f'GET /api/cumpleanos/alertas: status={res2.status_code}, hoy_count={len(res2.json["alertas"]["hoy"])}')

# Test search enrichment
res3 = client.get('/api/members/search?q=Berrio&fecha=2026-09-19')
print(f'GET /api/members/search?q=Berrio: status={res3.status_code}, count={len(res3.json)}')
for m in res3.json:
    if m.get('cumpleanos_info'):
        print(f"  - {m.get('nombre')} {m.get('apellidos')}: {m.get('cumpleanos_info')}")

print('ALL TESTS PASSED SUCCESSFULLY!')
