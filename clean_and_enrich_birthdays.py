import os
import sys
import re
import json

sys.stdout.reconfigure(encoding='utf-8')

# Load the raw parsed birthdays
raw_json_path = os.path.join(os.path.dirname(__file__), 'data', 'cumpleanos.json')
with open(raw_json_path, 'r', encoding='utf-8') as f:
    raw_list = json.load(f)

# Load members DB
db_path = os.path.join(os.path.dirname(__file__), 'data', 'local_db.json')
with open(db_path, 'r', encoding='utf-8') as f:
    db = json.load(f)
members = db.get('miembros', [])

def norm(s):
    if not s: return ''
    s = s.lower()
    s = re.sub(r'[áàäâ]', 'a', s)
    s = re.sub(r'[éèëê]', 'e', s)
    s = re.sub(r'[íìïî]', 'i', s)
    s = re.sub(r'[óòöô]', 'o', s)
    s = re.sub(r'[úùüû]', 'u', s)
    s = re.sub(r'ñ', 'n', s)
    s = re.sub(r'[^a-z0-9]', '', s)
    return s

# Expand entries if there are multiple people listed in a single string (e.g. 'Dulce María y Miguel Ángel (María)')
refined_list = []
id_counter = 1

for item in raw_list:
    mes_num = item['mes_num']
    mes = item['mes']
    dia = item['dia']
    name = item['nombre'].strip()
    
    # Check specific multi-person strings or note patterns
    # 1. "Dulce María y Miguel Ángel ( María )"
    if 'dulce maría y miguel ángel' in name.lower():
        refined_list.append({
            'id': f"CUMP_{id_counter:03d}",
            'mes_num': mes_num,
            'mes': mes,
            'dia': dia,
            'nombre': 'Dulce María',
            'nota': 'Hija de María'
        })
        id_counter += 1
        refined_list.append({
            'id': f"CUMP_{id_counter:03d}",
            'mes_num': mes_num,
            'mes': mes,
            'dia': dia,
            'nombre': 'Miguel Ángel',
            'nota': 'Hijo de María'
        })
        id_counter += 1
        continue
        
    # 2. "Adara y Keren Miranda"
    if 'adara y keren' in name.lower():
        refined_list.append({
            'id': f"CUMP_{id_counter:03d}",
            'mes_num': mes_num,
            'mes': mes,
            'dia': dia,
            'nombre': 'Adara Miranda',
            'nota': 'Familia Miranda'
        })
        id_counter += 1
        refined_list.append({
            'id': f"CUMP_{id_counter:03d}",
            'mes_num': mes_num,
            'mes': mes,
            'dia': dia,
            'nombre': 'Keren Miranda',
            'nota': 'Familia Miranda'
        })
        id_counter += 1
        continue
    
    # 3. Fix names like "HolmanOtero" -> "Holman Otero"
    if name == 'HolmanOtero':
        name = 'Holman Otero'
        
    # 4. Extract parenthetical notes
    nota = ''
    m_note = re.search(r'\((.*?)\)', name)
    if m_note:
        nota = m_note.group(1).strip()
        name = re.sub(r'\(.*?\)', '', name).strip()
        
    # Clean up prefixes like "Pastor ", "Hermana ", "Esposa del pastor "
    cargo_o_parentesco = ''
    if name.lower().startswith('pastor '):
        cargo_o_parentesco = 'Pastor'
        name = name[7:].strip()
    elif name.lower().startswith('esposa del pastor '):
        cargo_o_parentesco = 'Esposa del Pastor'
        name = name[18:].strip()
    elif name.lower().startswith('hermana '):
        cargo_o_parentesco = 'Hermana'
        name = name[8:].strip()
    elif name.lower().startswith('hermano '):
        cargo_o_parentesco = 'Hermano'
        name = name[8:].strip()
        
    if cargo_o_parentesco:
        nota = f"{cargo_o_parentesco} - {nota}".strip(' -')

    refined_list.append({
        'id': f"CUMP_{id_counter:03d}",
        'mes_num': mes_num,
        'mes': mes,
        'dia': dia,
        'nombre': name,
        'nota': nota
    })
    id_counter += 1

# Now attempt fuzzy matching with members database to link member_id, phone, gender, category
matched_count = 0
for b in refined_list:
    b_name = b['nombre']
    b_norm = norm(b_name)
    best_match = None
    best_score = 0
    
    b_tokens = [norm(t) for t in b_name.split() if len(t) > 2]
    
    for m in members:
        m_full = f"{m.get('nombre', '')} {m.get('apellidos', '')}"
        m_norm = norm(m_full)
        m_first = norm(m.get('nombre', ''))
        
        # Exact full name match
        if b_norm == m_norm or b_norm == norm(f"{m.get('apellidos', '')} {m.get('nombre', '')}"):
            best_match = m
            best_score = 100
            break
            
        # All tokens in member name
        m_tokens = [norm(t) for t in m_full.split() if len(t) > 2]
        if b_tokens and all(tok in m_tokens for tok in b_tokens):
            if len(b_tokens) >= 2:
                best_match = m
                best_score = 90
                break
            elif len(b_tokens) == 1 and b_norm == m_first:
                # Single name match (e.g. 'Dalida' -> 'Dalida ...')
                if best_score < 70:
                    best_match = m
                    best_score = 70
                    
        # Token overlap
        overlap = len(set(b_tokens).intersection(set(m_tokens)))
        if overlap >= 2 and overlap > best_score:
            best_match = m
            best_score = overlap * 25
            
    if best_match and best_score >= 50:
        matched_count += 1
        b['member_id'] = best_match.get('id', '')
        b['member_nombre_completo'] = f"{best_match.get('nombre', '')} {best_match.get('apellidos', '')}".strip()
        b['categoria'] = best_match.get('categoria', 'Hermano')
        b['genero'] = best_match.get('genero', '')
        b['telefono'] = best_match.get('telefono', '')
    else:
        b['member_id'] = ''
        b['member_nombre_completo'] = ''
        b['categoria'] = 'Hermano/Feligrés'
        b['genero'] = ''
        b['telefono'] = ''

print(f"Total refined birthdays: {len(refined_list)}")
print(f"Matched with existing members DB: {matched_count}/{len(refined_list)}")

final_out = os.path.join(os.path.dirname(__file__), 'data', 'cumpleanos.json')
with open(final_out, 'w', encoding='utf-8') as f:
    json.dump(refined_list, f, ensure_ascii=False, indent=2)
print("Successfully written to:", final_out)
