import os
import sys
import json
import csv
import io
from datetime import datetime, date
from flask import Flask, render_template, request, jsonify, Response
import traceback

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from search_engine import search_culto, search_members_smart, CULTOS_CATALOG

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'static')
app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)
app.config['TEMPLATES_AUTO_RELOAD'] = True

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'data')
os.makedirs(DATA_DIR, exist_ok=True)
LOCAL_DB_FILE = os.path.join(DATA_DIR, 'local_db.json')
INITIAL_MEMBERS_FILE = os.path.join(DATA_DIR, 'initial_members.json')

SHEET_ID = os.environ.get('SHEET_ID', '').strip()

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
        id_file = os.path.join(DATA_DIR, 'sheet_id.txt')
        if os.path.exists(id_file):
            with open(id_file, 'r', encoding='utf-8') as f:
                SHEET_ID = f.read().strip()
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
def load_db():
    if os.path.exists(LOCAL_DB_FILE):
        try:
            with open(LOCAL_DB_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            print(f'Error leyendo local_db.json: {e}')

    members = []
    if os.path.exists(INITIAL_MEMBERS_FILE):
        with open(INITIAL_MEMBERS_FILE, 'r', encoding='utf-8') as f:
            members = json.load(f)

    db = {
        'miembros': members,
        'asistencias': [],
        'metricas_cultos': {},
        'ujieres': [] # Lista vacía para agregar manualmente
    }
    save_db(db)
    return db

def save_db(db):
    try:
        with open(LOCAL_DB_FILE, 'w', encoding='utf-8') as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f'Error guardando local_db.json: {e}')

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
            datetime.now().isoformat()
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
    now = datetime.now()
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
        'sheet_configured': bool(SHEET_ID)
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
    fecha = data.get('fecha', date.today().strftime('%Y-%m-%d')).strip()
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
        
    now = datetime.now()
    rec_id = f"A{len(db['asistencias']) + 1:04d}"
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
    
    db['asistencias'] = [a for a in db['asistencias'] if not (a.get('fecha') == fecha and a.get('culto') == culto and a.get('member_id') == member_id)]
    
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
    save_db(db)
    return jsonify({'status': 'ok'})

@app.route('/api/attendance/stream', methods=['POST'])
def api_attendance_stream():
    global db
    data = request.json or {}
    fecha = data.get('fecha', date.today().strftime('%Y-%m-%d')).strip()
    culto = data.get('culto', '').strip()
    espectadores = int(data.get('espectadores', 0))
    ujier = data.get('ujier', '').strip()
    
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
    fecha_reg = data.get('fecha', date.today().strftime('%Y-%m-%d')).strip()
    culto = data.get('culto', '').strip()
    ujier = data.get('ujier', '').strip()
    marcar_asistencia = data.get('marcar_asistencia', True)
    
    if not nombre:
        return jsonify({'error': 'El nombre es obligatorio'}), 400
        
    prefix = 'V' if categoria == 'Visita' else ('A' if categoria == 'Amigo' else ('N' if categoria == 'Niño' else 'M'))
    count = sum(1 for m in db['miembros'] if m.get('id', '').startswith(prefix)) + 1
    new_id = f"{prefix}{count:03d}"
    
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
    sync_sheets_write_member(new_m)
    
    if marcar_asistencia and culto:
        now = datetime.now()
        rec_id = f"A{len(db['asistencias']) + 1:04d}"
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
    now = datetime.now()
    
    asistencias = db.get('asistencias', [])
    filtered = []
    
    for a in asistencias:
        f_str = a.get('fecha', '')
        if not f_str: continue
        try:
            f_dt = datetime.strptime(f_str, '%Y-%m-%d')
        except:
            continue
            
        if periodo == 'semana':
            if (now - f_dt).days <= 7:
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
        'meses_counts': meses_counts
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
    return Response(output.getvalue(), mimetype='text/csv',
                    headers={'Content-Disposition': 'attachment; filename=asistencia_ipue_granada.csv'})

@app.route('/static/<path:filename>')
def serve_static(filename):
    from flask import send_file
    for base in [
        STATIC_DIR,
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'public', 'static'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'static'),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), 'static'),
        os.path.dirname(os.path.abspath(__file__))
    ]:
        p = os.path.join(base, filename)
        if os.path.exists(p) and os.path.isfile(p):
            mimetype = 'text/css' if filename.endswith('.css') else ('image/jpeg' if filename.endswith(('.jpg', '.jpeg')) else None)
            return send_file(p, mimetype=mimetype)
    return "Not found", 404

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

