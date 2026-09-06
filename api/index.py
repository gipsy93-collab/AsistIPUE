import os
import sys
import json
import csv
import io
import uuid
from datetime import datetime, date, timedelta
from flask import Flask, render_template, request, jsonify, Response, send_from_directory
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from search_engine import search_culto, search_members_smart, CULTOS_CATALOG, normalize_str

def now_local():
    """Hora del reloj local del servidor (sin zona horaria forzada)."""
    return datetime.now()

def to_int(value, default=0):
    """Convierte a entero de forma tolerante (evita 500 con entrada no numérica)."""
    try:
        return int(float(str(value).strip()))
    except (ValueError, TypeError):
        return default

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True

class VercelPathFix:
    def __init__(self, wsgi_app):
        self.wsgi_app = wsgi_app
    def __call__(self, environ, start_response):
        matched = environ.get('HTTP_X_MATCHED_PATH') or environ.get('HTTP_X_FORWARDED_URI')
        if matched and not matched.startswith('/api/index'):
            environ['PATH_INFO'] = matched
        else:
            path = environ.get('PATH_INFO', '')
            for prefix in ['/api/index.py', '/api/index']:
                if path.startswith(prefix):
                    new_path = path[len(prefix):]
                    environ['PATH_INFO'] = new_path if new_path.startswith('/') else ('/' + new_path)
                    break
        return self.wsgi_app(environ, start_response)

app.wsgi_app = VercelPathFix(app.wsgi_app)

PROJECT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# En serverless (Vercel) el directorio del proyecto es de solo lectura:
# la base local debe vivir en /tmp; en desarrollo se usa data/ del proyecto.
if os.environ.get('DATA_DIR'):
    DATA_DIR = os.environ['DATA_DIR']
elif os.environ.get('VERCEL') or not os.access(PROJECT_DIR, os.W_OK):
    DATA_DIR = os.path.join('/tmp', 'asisipue_data')
else:
    DATA_DIR = os.path.join(PROJECT_DIR, 'data')
os.makedirs(DATA_DIR, exist_ok=True)
LOCAL_DB_FILE = os.path.join(DATA_DIR, 'local_db.json')
INITIAL_MEMBERS_FILE = os.path.join(PROJECT_DIR, 'data', 'initial_members.json')

SHEET_ID = os.environ.get('SHEET_ID', '').strip()

def resolve_sheet_id():
    """Devuelve el ID de hoja activo: variable de entorno > data/sheet_id.txt del proyecto."""
    if SHEET_ID:
        return SHEET_ID
    id_file = os.path.join(PROJECT_DIR, 'data', 'sheet_id.txt')
    if os.path.exists(id_file):
        try:
            with open(id_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        except Exception:
            pass
    return ''

def get_gc():
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        scopes = ['https://www.googleapis.com/auth/spreadsheets']
        creds_json = os.environ.get('GOOGLE_CREDENTIALS')
        if creds_json:
            creds_dict = json.loads(creds_json)
            creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        else:
            local_creds = os.path.join(os.path.dirname(__file__), '..', '..', 'tinkuy-ciencia-transmedia-4938ed06a087.json')
            if not os.path.exists(local_creds):
                local_creds = os.path.join(os.path.dirname(__file__), '..', 'credentials.json')
            if os.path.exists(local_creds):
                creds = Credentials.from_service_account_file(local_creds, scopes=scopes)
            else:
                return None
        return gspread.authorize(creds)
    except Exception as e:
        print(f'Error obteniendo credenciales Google: {e}')
        return None

def get_sheet():
    global SHEET_ID
    if not SHEET_ID:
        SHEET_ID = resolve_sheet_id()
    if not SHEET_ID:
        return None
    gc = get_gc()
    if not gc:
        return None
    try:
        return gc.open_by_key(SHEET_ID)
    except Exception as e:
        print(f'Error abriendo hoja con ID {SHEET_ID}: {e}')
        return None

# =========================================================
# GESTIÓN DE BASE DE DATOS LOCAL Y SINCRONIZACIÓN
# =========================================================
def _empty_db():
    return {
        'miembros': [],
        'asistencias': [],
        'metricas_cultos': {},
        'ujieres': []
    }

def _normalize_db(db):
    """Garantiza que la estructura exista completa aunque el JSON sea de una versión antigua."""
    if not isinstance(db, dict):
        return _empty_db()
    for key in ('miembros', 'asistencias', 'ujieres'):
        if not isinstance(db.get(key), list):
            db[key] = []
    if not isinstance(db.get('metricas_cultos'), dict):
        db['metricas_cultos'] = {}
    return db

def load_db():
    if os.path.exists(LOCAL_DB_FILE):
        try:
            with open(LOCAL_DB_FILE, 'r', encoding='utf-8') as f:
                return _normalize_db(json.load(f))
        except Exception as e:
            print(f'Error leyendo local_db.json: {e}')

    db = _empty_db()
    if os.path.exists(INITIAL_MEMBERS_FILE):
        try:
            with open(INITIAL_MEMBERS_FILE, 'r', encoding='utf-8') as f:
                members = json.load(f)
            if isinstance(members, list):
                db['miembros'] = members
        except Exception as e:
            print(f'Error leyendo initial_members.json: {e}')

    # Arranque frío en serverless: si no hay datos locales, recuperar desde Sheets
    if not db['miembros'] and not db['asistencias']:
        try:
            restore_db_from_sheets(db)
        except Exception as e:
            print(f'No se pudo restaurar desde Sheets: {e}')

    save_db(db)
    return db

def save_db(db):
    try:
        tmp_file = LOCAL_DB_FILE + '.tmp'
        with open(tmp_file, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
        os.replace(tmp_file, LOCAL_DB_FILE)
    except Exception as e:
        print(f'Error guardando local_db.json: {e}')

def restore_db_from_sheets(db):
    """Reconstruye la base local desde Google Sheets tras un arranque frío."""
    sh = get_sheet()
    if not sh:
        return False
    try:
        ws_m = sh.worksheet('Miembros')
        for r in ws_m.get_all_records():
            db['miembros'].append({
                'id': str(r.get('ID', '')),
                'categoria': r.get('Categoria', ''),
                'genero': r.get('Genero', ''),
                'nombre': str(r.get('Nombre', '')),
                'apellidos': str(r.get('Apellidos', '')),
                'telefono': str(r.get('Telefono', '')),
                'fecha_registro': str(r.get('Fecha_Registro', '')),
                'estado': r.get('Estado', 'Activo') or 'Activo'
            })
    except Exception as e:
        print(f'Restore Miembros: {e}')
    try:
        ws_a = sh.worksheet('Asistencia')
        for r in ws_a.get_all_records():
            db['asistencias'].append({
                'id': str(r.get('ID_Registro', '')),
                'fecha': str(r.get('Fecha', '')),
                'culto': str(r.get('Culto', '')),
                'hora': str(r.get('Hora', '')),
                'member_id': str(r.get('ID_Miembro', '')),
                'nombre_completo': str(r.get('Nombre_Completo', '')),
                'categoria': r.get('Categoria', ''),
                'genero': r.get('Genero', ''),
                'ujier': str(r.get('Ujier', '')),
                'tipo_asistencia': r.get('Tipo_Asistencia', 'Presencial') or 'Presencial'
            })
    except Exception as e:
        print(f'Restore Asistencia: {e}')
    try:
        ws_c = sh.worksheet('Cultos_Metricas')
        for r in ws_c.get_all_records():
            key = f"{r.get('Fecha', '')}_{r.get('Culto', '')}"
            if key != '_':
                db['metricas_cultos'][key] = {
                    'fecha': str(r.get('Fecha', '')),
                    'culto': str(r.get('Culto', '')),
                    'ujier': str(r.get('Ujier', '')),
                    'transmision_online': to_int(r.get('Transmision_Online', 0))
                }
    except Exception as e:
        print(f'Restore Metricas: {e}')
    try:
        ws_u = sh.worksheet('Ujieres')
        for r in ws_u.get_all_records():
            nom = str(r.get('Nombre_Ujier', '')).strip()
            if nom and nom not in db['ujieres']:
                db['ujieres'].append(nom)
        db['ujieres'].sort()
    except Exception as e:
        print(f'Restore Ujieres: {e}')
    print(f'Restored desde Sheets: {len(db["miembros"])} miembros, {len(db["asistencias"])} asistencias')
    return bool(db['miembros'] or db['asistencias'])

db = load_db()

def sync_sheets_write_asistencia(rec):
    sh = get_sheet()
    if not sh: return
    try:
        ws = sh.worksheet('Asistencia')
        ws.append_row([
            rec.get('id', ''),
            rec.get('fecha', ''),
            rec.get('culto', ''),
            rec.get('hora', ''),
            rec.get('member_id', ''),
            rec.get('nombre_completo', ''),
            rec.get('categoria', ''),
            rec.get('genero', ''),
            rec.get('ujier', ''),
            rec.get('tipo_asistencia', 'Presencial')
        ])
    except Exception as e:
        print(f'Error sync asistencia a Sheets: {e}')

def sync_sheets_delete_asistencia(rec):
    """Elimina de Sheets la fila de asistencia anulada localmente (matching por ID_Registro)."""
    sh = get_sheet()
    if not sh: return
    rec_id = rec.get('id', '')
    if not rec_id: return
    try:
        ws = sh.worksheet('Asistencia')
        all_v = ws.get_all_values()
        for i in range(len(all_v) - 1, 0, -1):  # de abajo hacia arriba para no desplazar índices
            if all_v[i] and all_v[i][0] == rec_id:
                ws.delete_rows(i + 1)
    except Exception as e:
        print(f'Error borrando asistencia en Sheets: {e}')

def sync_sheets_write_member(m):
    sh = get_sheet()
    if not sh: return
    try:
        ws = sh.worksheet('Miembros')
        ws.append_row([
            m.get('id', ''),
            m.get('categoria', ''),
            m.get('genero', ''),
            m.get('nombre', ''),
            m.get('apellidos', ''),
            m.get('telefono', ''),
            m.get('fecha_registro', ''),
            m.get('estado', 'Activo')
        ])
    except Exception as e:
        print(f'Error sync miembro a Sheets: {e}')

def sync_sheets_update_member(m):
    sh = get_sheet()
    if not sh: return
    try:
        ws = sh.worksheet('Miembros')
        all_v = ws.get_all_values()
        target_row = None
        for i, r in enumerate(all_v):
            if i == 0: continue
            if r and r[0] == m.get('id'):
                target_row = i + 1
                break
        row_vals = [
            m.get('id', ''),
            m.get('categoria', ''),
            m.get('genero', ''),
            m.get('nombre', ''),
            m.get('apellidos', ''),
            m.get('telefono', ''),
            m.get('fecha_registro', ''),
            m.get('estado', 'Activo')
        ]
        if target_row:
            ws.update(f'A{target_row}:H{target_row}', [row_vals])
        else:
            ws.append_row(row_vals)
    except Exception as e:
        print(f'Error sync update miembro a Sheets: {e}')

def sync_sheets_write_metrics(key, data):
    sh = get_sheet()
    if not sh: return
    try:
        ws = sh.worksheet('Cultos_Metricas')
        all_v = ws.get_all_values()
        target_row = None
        for i, r in enumerate(all_v):
            if i == 0: continue
            if len(r) >= 2 and f"{r[0]}_{r[1]}" == key:
                target_row = i + 1
                break
        row_vals = [
            data.get('fecha', ''),
            data.get('culto', ''),
            data.get('ujier', ''),
            data.get('presenciales', 0),
            data.get('hermanos', 0),
            data.get('ninos', 0),
            data.get('amigos', 0),
            data.get('transmision_online', 0),
            data.get('total_alcance', 0),
            now_local().isoformat()
        ]
        if target_row:
            ws.update(f'A{target_row}:J{target_row}', [row_vals])
        else:
            ws.append_row(row_vals)
    except Exception as e:
        print(f'Error sync metricas a Sheets: {e}')

# =========================================================
# UTILIDADES DE FECHAS EN ESPAÑOL
# =========================================================
DIAS_ES = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo']
MESES_ES = ['Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio', 'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre']

def get_current_date_info():
    now = now_local()
    dia_sem = DIAS_ES[now.weekday()]
    mes_str = MESES_ES[now.month - 1]
    
    if now.weekday() == 6: # Domingo
        culto_sugerido = 'Escuela Dominical'
    elif now.weekday() in [1, 3]: # Martes o Jueves
        culto_sugerido = 'Oración y Enseñanza'
    elif now.weekday() == 5: # Sábado
        culto_sugerido = 'Jóvenes Generación Vida'
    else:
        culto_sugerido = 'Culto General / Especial'
        
    return {
        'fecha': now.strftime('%Y-%m-%d'),
        'ano': now.year,
        'mes': now.month,
        'dia': now.day,
        'dia_semana': dia_sem,
        'mes_nombre': mes_str,
        'fecha_larga': f"{dia_sem}, {now.day} de {mes_str} de {now.year}",
        'culto_sugerido': culto_sugerido
    }

# =========================================================
# RUTAS DE PÁGINAS PRINCIPALES
# =========================================================
@app.route('/')
@app.route('/api/index.py')
@app.route('/api/index')
def index_page():
    return render_template('index.html')

@app.route('/report')
def report_page():
    return render_template('report.html')

# =========================================================
# API ENDPOINTS
# =========================================================
@app.route('/api/info')
def api_info():
    return jsonify({
        'date_info': get_current_date_info(),
        'cultos': [c['nombre'] for c in CULTOS_CATALOG],
        'ujieres': db.get('ujieres', []),
        'sheet_configured': bool(resolve_sheet_id())
    })

@app.route('/api/cultos/search')
def api_cultos_search():
    q = request.args.get('q', '').strip()
    return jsonify(search_culto(q))

@app.route('/api/ujieres')
def api_get_ujieres():
    return jsonify(db.get('ujieres', []))

@app.route('/api/ujieres/add', methods=['POST'])
def api_add_ujier():
    global db
    data = request.json or {}
    nombre = data.get('nombre', '').strip()
    if not nombre:
        return jsonify({'error': 'Nombre requerido'}), 400
    if nombre not in db['ujieres']:
        db['ujieres'].append(nombre)
        db['ujieres'].sort()
        save_db(db)
    return jsonify({'status': 'ok', 'ujieres': db['ujieres']})

@app.route('/api/members/search')
def api_members_search():
    q = request.args.get('q', '').strip()
    fecha = request.args.get('fecha', date.today().strftime('%Y-%m-%d')).strip()
    culto = request.args.get('culto', '').strip()
    include_inactive = request.args.get('include_inactive', 'false').lower() == 'true'
    
    # Filtrar inactivos a menos que se solicite
    members_pool = db.get('miembros', [])
    if not include_inactive:
        members_pool = [m for m in members_pool if m.get('estado', 'Activo') != 'Inactivo']
        
    matched = search_members_smart(q, members_pool)
    
    # Marcas para el culto y fecha activos
    marked_ids = {}
    for a in db.get('asistencias', []):
        if a.get('fecha') == fecha and a.get('culto') == culto:
            marked_ids[a.get('member_id')] = a.get('hora')
            
    # Conteo histórico de asistencias por persona
    history_counts = {}
    for a in db.get('asistencias', []):
        mid = a.get('member_id')
        history_counts[mid] = history_counts.get(mid, 0) + 1
            
    results = []
    for m in matched:
        m_copy = dict(m)
        m_id = m.get('id')
        m_copy['asistio'] = m_id in marked_ids
        m_copy['hora_asistencia'] = marked_ids.get(m_id, '')
        
        tot_asist = history_counts.get(m_id, 0)
        m_copy['total_asistencias'] = tot_asist
        
        # Alerta de regularidad de visita (> 10 asistencias)
        sugerir_promo = False
        if m.get('categoria') == 'Visita' and tot_asist >= 10:
            recordar_en = m.get('recordar_en', 10)
            if tot_asist >= recordar_en:
                sugerir_promo = True
        m_copy['sugerir_promocion'] = sugerir_promo
        
        results.append(m_copy)
        
    return jsonify(results)

@app.route('/api/members/update', methods=['POST'])
def api_members_update():
    """Modificación de datos, categoría o desagregación (inactivo) de un asistente."""
    global db
    data = request.json or {}
    mid = data.get('id', '').strip()
    if not mid:
        return jsonify({'error': 'ID de miembro obligatorio'}), 400
        
    member = next((m for m in db['miembros'] if m.get('id') == mid), None)
    if not member:
        return jsonify({'error': 'Miembro no encontrado'}), 404
        
    # Actualizar campos permitidos
    if 'nombre' in data and data['nombre'].strip():
        member['nombre'] = data['nombre'].strip().upper()
    if 'apellidos' in data:
        member['apellidos'] = data['apellidos'].strip().upper()
    if 'categoria' in data and data['categoria']:
        member['categoria'] = data['categoria'].strip()
    if 'genero' in data and data['genero']:
        member['genero'] = data['genero'].strip()
    if 'telefono' in data:
        member['telefono'] = data['telefono'].strip()
    if 'estado' in data and data['estado']:
        member['estado'] = data['estado'].strip() # 'Activo' o 'Inactivo'
        
    save_db(db)
    sync_sheets_update_member(member)
    return jsonify({'status': 'ok', 'member': member})

@app.route('/api/members/promote-visita', methods=['POST'])
def api_members_promote_visita():
    """Gestiona la respuesta a la alerta de visita con más de 10 asistencias."""
    global db
    data = request.json or {}
    mid = data.get('id', '').strip()
    action = data.get('action', '').strip() # 'promote', 'no', 'remind_10'
    
    member = next((m for m in db['miembros'] if m.get('id') == mid), None)
    if not member:
        return jsonify({'error': 'Miembro no encontrado'}), 404
        
    tot_asist = sum(1 for a in db.get('asistencias', []) if a.get('member_id') == mid)
    
    if action == 'promote':
        member['categoria'] = 'Amigo'
        member['recordar_en'] = None
    elif action == 'remind_10':
        member['recordar_en'] = tot_asist + 10
    elif action == 'no':
        member['recordar_en'] = tot_asist + 9999 # No volver a sugerir
        
    save_db(db)
    sync_sheets_update_member(member)
    return jsonify({'status': 'ok', 'member': member})

@app.route('/api/attendance/summary')
def api_attendance_summary():
    fecha = request.args.get('fecha', date.today().strftime('%Y-%m-%d')).strip()
    culto = request.args.get('culto', '').strip()
    key = f"{fecha}_{culto}"
    
    culto_asist = [a for a in db.get('asistencias', []) if a.get('fecha') == fecha and a.get('culto') == culto]
    
    hermanos = sum(1 for a in culto_asist if a.get('categoria') == 'Hermano')
    ninos = sum(1 for a in culto_asist if a.get('categoria') == 'Niño')
    amigos = sum(1 for a in culto_asist if a.get('categoria') == 'Amigo')
    visitas = sum(1 for a in culto_asist if a.get('categoria') == 'Visita')
    
    metric = db.get('metricas_cultos', {}).get(key, {})
    transmision = metric.get('transmision_online', 0)
    presenciales = len(culto_asist)
    
    return jsonify({
        'fecha': fecha,
        'culto': culto,
        'presenciales': presenciales,
        'hermanos': hermanos,
        'ninos': ninos,
        'amigos': amigos,
        'visitas': visitas,
        'transmision_online': transmision,
        'total_alcance': presenciales + transmision
    })

@app.route('/api/attendance/mark', methods=['POST'])
def api_attendance_mark():
    global db
    data = request.json or {}
    member_id = data.get('member_id', '').strip()
    fecha = data.get('fecha', now_local().strftime('%Y-%m-%d')).strip()
    culto = data.get('culto', '').strip()
    ujier = data.get('ujier', '').strip()
    observacion = data.get('observacion', '').strip()
    
    if not member_id or not culto:
        return jsonify({'error': 'Miembro y Culto son obligatorios'}), 400
        
    if ujier and ujier not in db['ujieres']:
        db['ujieres'].append(ujier)
        db['ujieres'].sort()
        
    member = next((m for m in db.get('miembros', []) if m.get('id') == member_id), None)
    if not member:
        return jsonify({'error': 'Miembro no encontrado'}), 404
        
    existing = next((a for a in db.get('asistencias', []) if a.get('fecha') == fecha and a.get('culto') == culto and a.get('member_id') == member_id), None)
    if existing:
        return jsonify({'status': 'already', 'hora': existing.get('hora'), 'message': 'Ya registrado'})
        
    now = now_local()
    rec_id = f"A{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
    rec = {
        'id': rec_id,
        'fecha': fecha,
        'culto': culto,
        'hora': now.strftime('%H:%M:%S'),
        'member_id': member_id,
        'nombre_completo': f"{member.get('nombre', '')} {member.get('apellidos', '')}".strip(),
        'categoria': member.get('categoria', 'Hermano'),
        'genero': member.get('genero', 'Hombre'),
        'ujier': ujier,
        'tipo_asistencia': 'Presencial',
        'observacion': observacion
    }
    db['asistencias'].append(rec)
    
    key = f"{fecha}_{culto}"
    if key not in db['metricas_cultos']:
        db['metricas_cultos'][key] = {'fecha': fecha, 'culto': culto, 'ujier': ujier, 'transmision_online': 0}
    culto_asist = [a for a in db['asistencias'] if a.get('fecha') == fecha and a.get('culto') == culto]
    h = sum(1 for a in culto_asist if a.get('categoria') == 'Hermano')
    n = sum(1 for a in culto_asist if a.get('categoria') == 'Niño')
    am = sum(1 for a in culto_asist if a.get('categoria') == 'Amigo')
    vi = sum(1 for a in culto_asist if a.get('categoria') == 'Visita')
    tr = db['metricas_cultos'][key].get('transmision_online', 0)
    db['metricas_cultos'][key].update({
        'presenciales': len(culto_asist),
        'hermanos': h,
        'ninos': n,
        'amigos': am,
        'visitas': vi,
        'total_alcance': len(culto_asist) + tr
    })
    
    save_db(db)
    sync_sheets_write_asistencia(rec)
    sync_sheets_write_metrics(key, db['metricas_cultos'][key])
    
    # Chequear si amerita alerta de regularidad de visita
    tot_asist = sum(1 for a in db['asistencias'] if a.get('member_id') == member_id)
    sugerir_promo = False
    if member.get('categoria') == 'Visita' and tot_asist >= 10:
        recordar_en = member.get('recordar_en', 10)
        if tot_asist >= recordar_en:
            sugerir_promo = True
            
    return jsonify({'status': 'ok', 'record': rec, 'sugerir_promocion': sugerir_promo, 'total_asistencias': tot_asist})

@app.route('/api/attendance/unmark', methods=['POST'])
def api_attendance_unmark():
    global db
    data = request.json or {}
    member_id = data.get('member_id', '').strip()
    fecha = data.get('fecha', '').strip()
    culto = data.get('culto', '').strip()
    
    if not member_id or not fecha or not culto:
        return jsonify({'error': 'Miembro, fecha y culto son obligatorios'}), 400

    removed = [a for a in db['asistencias'] if a.get('fecha') == fecha and a.get('culto') == culto and a.get('member_id') == member_id]
    db['asistencias'] = [a for a in db['asistencias'] if a not in removed]
    
    key = f"{fecha}_{culto}"
    if key in db['metricas_cultos']:
        culto_asist = [a for a in db['asistencias'] if a.get('fecha') == fecha and a.get('culto') == culto]
        h = sum(1 for a in culto_asist if a.get('categoria') == 'Hermano')
        n = sum(1 for a in culto_asist if a.get('categoria') == 'Niño')
        am = sum(1 for a in culto_asist if a.get('categoria') == 'Amigo')
        vi = sum(1 for a in culto_asist if a.get('categoria') == 'Visita')
        tr = db['metricas_cultos'][key].get('transmision_online', 0)
        db['metricas_cultos'][key].update({
            'presenciales': len(culto_asist),
            'hermanos': h,
            'ninos': n,
            'amigos': am,
            'visitas': vi,
            'total_alcance': len(culto_asist) + tr
        })
        sync_sheets_write_metrics(key, db['metricas_cultos'][key])
    for rec in removed:
        sync_sheets_delete_asistencia(rec)
    save_db(db)
    return jsonify({'status': 'ok'})

@app.route('/api/attendance/stream', methods=['POST'])
def api_attendance_stream():
    global db
    data = request.json or {}
    fecha = data.get('fecha', now_local().strftime('%Y-%m-%d')).strip()
    culto = data.get('culto', '').strip()
    espectadores = max(0, to_int(data.get('espectadores', 0)))
    ujier = data.get('ujier', '').strip()
    
    if not culto:
        return jsonify({'error': 'Culto obligatorio'}), 400
    
    key = f"{fecha}_{culto}"
    if key not in db['metricas_cultos']:
        db['metricas_cultos'][key] = {'fecha': fecha, 'culto': culto, 'ujier': ujier}
        
    culto_asist = [a for a in db['asistencias'] if a.get('fecha') == fecha and a.get('culto') == culto]
    h = sum(1 for a in culto_asist if a.get('categoria') == 'Hermano')
    n = sum(1 for a in culto_asist if a.get('categoria') == 'Niño')
    am = sum(1 for a in culto_asist if a.get('categoria') == 'Amigo')
    vi = sum(1 for a in culto_asist if a.get('categoria') == 'Visita')
    
    db['metricas_cultos'][key].update({
        'fecha': fecha,
        'culto': culto,
        'ujier': ujier or db['metricas_cultos'][key].get('ujier', ''),
        'transmision_online': espectadores,
        'presenciales': len(culto_asist),
        'hermanos': h,
        'ninos': n,
        'amigos': am,
        'visitas': vi,
        'total_alcance': len(culto_asist) + espectadores
    })
    save_db(db)
    sync_sheets_write_metrics(key, db['metricas_cultos'][key])
    return jsonify({'status': 'ok', 'metric': db['metricas_cultos'][key]})

@app.route('/api/members/new', methods=['POST'])
def api_members_new():
    global db
    data = request.json or {}
    nombre = data.get('nombre', '').strip().upper()
    apellidos = data.get('apellidos', '').strip().upper()
    categoria = data.get('categoria', 'Visita').strip() # Visita, Amigo, Hermano, Niño
    genero = data.get('genero', 'Hombre').strip() # Hombre, Mujer, Niño
    telefono = data.get('telefono', '').strip()
    fecha_reg = data.get('fecha', now_local().strftime('%Y-%m-%d')).strip()
    culto = data.get('culto', '').strip()
    ujier = data.get('ujier', '').strip()
    marcar_asistencia = data.get('marcar_asistencia', True)
    
    if not nombre:
        return jsonify({'error': 'El nombre es obligatorio'}), 400
        
    # Evitar duplicados: mismo nombre normalizado ya registrado y activo
    full_norm = normalize_str(f"{nombre} {apellidos}")
    if full_norm:
        dup = next((m for m in db['miembros']
                    if m.get('estado', 'Activo') != 'Inactivo'
                    and normalize_str(f"{m.get('nombre', '')} {m.get('apellidos', '')}") == full_norm), None)
        if dup:
            dup_nombre = f'{dup.get("nombre", "")} {dup.get("apellidos", "")}'.strip()
            return jsonify({'error': f'Ya existe "{dup_nombre}" como {dup.get("categoria")} (ID {dup.get("id")}). Use el apartado de Modificaciones si desea cambiar sus datos.', 'duplicate': True}), 409

    prefix = 'V' if categoria == 'Visita' else ('A' if categoria == 'Amigo' else ('N' if categoria == 'Niño' else 'M'))
    # ID monótono: máximo número existente + 1 (evita colisiones)
    max_n = 0
    for m in db['miembros']:
        mid = str(m.get('id', ''))
        if mid.startswith(prefix) and len(mid) > len(prefix):
            try:
                max_n = max(max_n, int(mid[len(prefix):]))
            except ValueError:
                pass
    new_id = f"{prefix}{max_n + 1:03d}"
    
    new_m = {
        'id': new_id,
        'nombre': nombre,
        'apellidos': apellidos,
        'categoria': categoria,
        'genero': genero,
        'telefono': telefono,
        'fecha_registro': fecha_reg,
        'estado': 'Activo'
    }
    db['miembros'].append(new_m)
    save_db(db)
    sync_sheets_write_member(new_m)
    
    if marcar_asistencia and culto:
        now = now_local()
        rec_id = f"A{now.strftime('%Y%m%d%H%M%S')}{uuid.uuid4().hex[:4].upper()}"
        rec = {
            'id': rec_id,
            'fecha': fecha_reg,
            'culto': culto,
            'hora': now.strftime('%H:%M:%S'),
            'member_id': new_id,
            'nombre_completo': f"{nombre} {apellidos}".strip(),
            'categoria': categoria,
            'genero': genero,
            'ujier': ujier,
            'tipo_asistencia': 'Presencial',
            'observacion': f'Nuevo registro ({categoria})'
        }
        db['asistencias'].append(rec)
        sync_sheets_write_asistencia(rec)
        
        key = f"{fecha_reg}_{culto}"
        if key not in db['metricas_cultos']:
            db['metricas_cultos'][key] = {'fecha': fecha_reg, 'culto': culto, 'ujier': ujier, 'transmision_online': 0}
        culto_asist = [a for a in db['asistencias'] if a.get('fecha') == fecha_reg and a.get('culto') == culto]
        h = sum(1 for a in culto_asist if a.get('categoria') == 'Hermano')
        n = sum(1 for a in culto_asist if a.get('categoria') == 'Niño')
        am = sum(1 for a in culto_asist if a.get('categoria') == 'Amigo')
        vi = sum(1 for a in culto_asist if a.get('categoria') == 'Visita')
        tr = db['metricas_cultos'][key].get('transmision_online', 0)
        db['metricas_cultos'][key].update({
            'presenciales': len(culto_asist),
            'hermanos': h,
            'ninos': n,
            'amigos': am,
            'visitas': vi,
            'total_alcance': len(culto_asist) + tr
        })
        sync_sheets_write_metrics(key, db['metricas_cultos'][key])

    save_db(db)
    return jsonify({'status': 'ok', 'member': new_m})

# =========================================================
# REPORTES Y ANALÍTICA AVANZADA
# =========================================================
@app.route('/api/reports/analytics')
def api_reports_analytics():
    periodo = request.args.get('periodo', 'ano')
    now = now_local()
    
    asistencias = db.get('asistencias', [])
    filtered = []
    
    for a in asistencias:
        f_str = a.get('fecha', '')
        if not f_str: continue
        try:
            f_dt = datetime.strptime(f_str, '%Y-%m-%d')
        except ValueError:
            continue
            
        if periodo == 'semana':
            if timedelta(0) <= (now - f_dt) <= timedelta(days=7):
                filtered.append((f_dt, a))
        elif periodo == 'mes':
            if f_dt.year == now.year and f_dt.month == now.month:
                filtered.append((f_dt, a))
        elif periodo == 'ano':
            if f_dt.year == now.year:
                filtered.append((f_dt, a))
        else:
            filtered.append((f_dt, a))
            
    total_asistencias = len(filtered)
    cultos_unicos = len(set(f"{a['fecha']}_{a['culto']}" for _, a in filtered))
    promedio_por_culto = round(total_asistencias / cultos_unicos, 1) if cultos_unicos > 0 else 0
    
    # Desglose por género y categoría
    hombres = sum(1 for _, a in filtered if a.get('categoria') == 'Hermano' and a.get('genero') == 'Hombre')
    mujeres = sum(1 for _, a in filtered if a.get('categoria') == 'Hermano' and a.get('genero') == 'Mujer')
    ninos = sum(1 for _, a in filtered if a.get('categoria') == 'Niño' or a.get('genero') == 'Niño')
    amigos = sum(1 for _, a in filtered if a.get('categoria') == 'Amigo')
    visitas = sum(1 for _, a in filtered if a.get('categoria') == 'Visita')
    
    culto_counts = {}
    for _, a in filtered:
        c = a.get('culto', 'Otro')
        culto_counts[c] = culto_counts.get(c, 0) + 1
    cultos_ranking = sorted([{'culto': k, 'total': v} for k, v in culto_counts.items()], key=lambda x: x['total'], reverse=True)
    
    dias_counts = {d: 0 for d in DIAS_ES}
    for f_dt, _ in filtered:
        dia_nom = DIAS_ES[f_dt.weekday()]
        dias_counts[dia_nom] += 1
    dias_ranking = sorted([{'dia': k, 'total': v} for k, v in dias_counts.items()], key=lambda x: x['total'], reverse=True)
    
    meses_counts = {m: 0 for m in MESES_ES}
    for f_dt, _ in filtered:
        mes_nom = MESES_ES[f_dt.month - 1]
        meses_counts[mes_nom] += 1
        
    total_transmision = sum(m.get('transmision_online', 0) for m in db.get('metricas_cultos', {}).values())
    
    return jsonify({
        'periodo': periodo,
        'total_asistencias': total_asistencias,
        'cultos_realizados': cultos_unicos,
        'promedio_por_culto': promedio_por_culto,
        'total_transmision_online': total_transmision,
        'genero': {
            'hombres': hombres,
            'mujeres': mujeres,
            'ninos': ninos,
            'amigos': amigos,
            'visitas': visitas,
            'total': total_asistencias
        },
        'cultos_ranking': cultos_ranking,
        'dias_ranking': dias_ranking,
        'meses_counts': meses_counts,
        'meses_ranking': sorted([{'mes': k, 'total': v} for k, v in meses_counts.items()], key=lambda x: x['total'], reverse=True)
    })

@app.route('/api/reports/friends')
def api_reports_friends():
    """Listado de amigos y visitas con datos de contacto para seguimiento pastoral."""
    personas = [m for m in db.get('miembros', []) if m.get('categoria') in ['Amigo', 'Visita']]
    
    result = []
    for p in personas:
        m_id = p.get('id')
        asistencias_p = [a for a in db.get('asistencias', []) if a.get('member_id') == m_id]
        fechas = [a.get('fecha') for a in asistencias_p]
        
        tel = p.get('telefono', '').strip()
        wa_tel = ''.join(c for c in tel if c.isdigit())
        
        result.append({
            'id': m_id,
            'nombre': p.get('nombre', ''),
            'apellidos': p.get('apellidos', ''),
            'categoria': p.get('categoria', 'Visita'),
            'telefono': tel,
            'whatsapp_link': f"https://wa.me/{wa_tel}" if wa_tel else None,
            'fecha_registro': p.get('fecha_registro', ''),
            'total_asistencias': len(asistencias_p),
            'ultimo_culto': asistencias_p[-1].get('culto', '') if asistencias_p else '',
            'ultima_fecha': fechas[-1] if fechas else '',
            'ultima_asistencia': fechas[-1] if fechas else '',
            'estado': p.get('estado', 'Activo')
        })
        
    result.sort(key=lambda x: x['total_asistencias'], reverse=True)
    return jsonify(result)

@app.route('/api/reports/export-csv')
def api_reports_export_csv():
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['ID_Registro', 'Fecha', 'Culto', 'Hora', 'ID_Miembro', 'Nombre_Completo', 'Categoria', 'Genero', 'Ujier', 'Tipo'])
    for a in db.get('asistencias', []):
        writer.writerow([
            a.get('id', ''),
            a.get('fecha', ''),
            a.get('culto', ''),
            a.get('hora', ''),
            a.get('member_id', ''),
            a.get('nombre_completo', ''),
            a.get('categoria', ''),
            a.get('genero', ''),
            a.get('ujier', ''),
            a.get('tipo_asistencia', 'Presencial')
        ])
    return Response('\ufeff' + output.getvalue(), mimetype='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename=asistencia_ipue_granada.csv'})

@app.route('/static/<path:filename>')
def serve_static(filename):
    # send_from_directory previene path traversal fuera del directorio estático
    return send_from_directory(STATIC_DIR, filename)

@app.route('/api/logo')
def serve_logo():
    from flask import send_file
    for p in [
        os.path.join(STATIC_DIR, 'logo_ipue.jpeg'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'logo_ipue.jpeg'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'public', 'static', 'logo_ipue.jpeg'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static', 'logo_ipue.jpeg')
    ]:
        if os.path.exists(p) and os.path.isfile(p):
            return send_file(p, mimetype='image/jpeg')
    return "Logo not found", 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    print(f'Servidor IPUE ASISIPUE iniciado en http://localhost:{port}')
    app.run(debug=True, host='0.0.0.0', port=port)

