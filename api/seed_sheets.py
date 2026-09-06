import os
import json
import traceback

def get_gc():
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

def init_church_sheet(sheet_id):
    """Inicializa las pestañas requeridas en la hoja de cálculo de Google."""
    gc = get_gc()
    if not gc:
        print('No se pudieron obtener credenciales de Google.')
        return False
        
    try:
        sh = gc.open_by_key(sheet_id)
        print(f'Conectado exitosamente a la hoja: {sh.title}')
        
        # 1. Pestaña Miembros
        try:
            ws_m = sh.worksheet('Miembros')
        except:
            ws_m = sh.add_worksheet('Miembros', 1000, 10)
            
        m_headers = ['ID', 'Categoria', 'Genero', 'Nombre', 'Apellidos', 'Telefono', 'Fecha_Registro', 'Estado']
        existing_m = ws_m.get_all_values()
        if not existing_m or len(existing_m) <= 1:
            ws_m.clear()
            ws_m.append_row(m_headers)
            
            # Cargar miembros iniciales
            init_json = os.path.join(os.path.dirname(__file__), '..', 'data', 'initial_members.json')
            if os.path.exists(init_json):
                with open(init_json, 'r', encoding='utf-8') as f:
                    m_list = json.load(f)
                rows_to_add = []
                for m in m_list:
                    rows_to_add.append([
                        m['id'], m['categoria'], m['genero'], m['nombre'],
                        m['apellidos'], m['telefono'], m['fecha_registro'], m['estado']
                    ])
                if rows_to_add:
                    ws_m.append_rows(rows_to_add)
                print(f'Se insertaron {len(rows_to_add)} miembros iniciales en la hoja Miembros.')
                
        # 2. Pestaña Asistencia
        try:
            ws_a = sh.worksheet('Asistencia')
        except:
            ws_a = sh.add_worksheet('Asistencia', 2000, 12)
            ws_a.append_row(['ID_Registro', 'Fecha', 'Culto', 'Hora', 'ID_Miembro', 'Nombre_Completo', 'Categoria', 'Genero', 'Ujier', 'Tipo_Asistencia'])
            
        # 3. Pestaña Cultos_Metricas
        try:
            ws_cm = sh.worksheet('Cultos_Metricas')
        except:
            ws_cm = sh.add_worksheet('Cultos_Metricas', 1000, 10)
            ws_cm.append_row(['Fecha', 'Culto', 'Ujier', 'Presenciales', 'Hermanos', 'Ninos', 'Amigos', 'Transmision_Online', 'Total_Alcance', 'Timestamp'])
            
        # 4. Pestaña Ujieres
        try:
            ws_u = sh.worksheet('Ujieres')
        except:
            ws_u = sh.add_worksheet('Ujieres', 500, 5)
            ws_u.append_row(['Nombre_Ujier', 'Fecha_Primer_Registro', 'Total_Servicios'])
            
        print('Estructura de pestañas verificada y lista en Google Sheets.')
        return True
    except Exception as e:
        print(f'Error inicializando hoja en Google Sheets: {e}')
        traceback.print_exc()
        return False

if __name__ == '__main__':
    import sys
    if len(sys.argv) > 1:
        s_id = sys.argv[1].strip()
        init_church_sheet(s_id)
    else:
        print('Uso: python seed_sheets.py <GOOGLE_SHEET_ID>')
