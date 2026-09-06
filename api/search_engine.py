import unicodedata
import re

# Diccionario expandido de apodos y diminutivos comunes
NICKNAMES = {
    'manu': ['manuel', 'manuela'],
    'rafa': ['rafael', 'rafaela'],
    'yois': ['joisse', 'joyce', 'joyse', 'yoisse', 'yoise'],
    'yoise': ['joisse', 'joyce'],
    'joyce': ['joisse', 'joyse'],
    'dani': ['daniel', 'daniela', 'danilo'],
    'alex': ['alejandro', 'alejandra', 'alexander', 'alexa'],
    'alejo': ['alejandro'],
    'aleja': ['alejandra'],
    'beto': ['alberto', 'roberto', 'heriberto'],
    'chepe': ['jose'],
    'pepe': ['jose'],
    'fer': ['fernando', 'fernanda'],
    'fercho': ['fernando'],
    'gabi': ['gabriel', 'gabriela'],
    'nacho': ['ignacio'],
    'pacho': ['francisco'],
    'pancho': ['francisco'],
    'vale': ['valentina', 'valeria'],
    'mati': ['mateo', 'matias'],
    'javi': ['javier'],
    'santi': ['santiago'],
    'nico': ['nicolas'],
    'pipe': ['felipe'],
    'tono': ['antonio'],
    'lina': ['carolina', 'paulina'],
    'pau': ['paula', 'paulina'],
    'guille': ['guillermo'],
    'leo': ['leonardo', 'leonor'],
    'sebas': ['sebastian'],
    'cata': ['catalina'],
    'charly': ['carlos'],
    'davi': ['david'],
    'conny': ['constanza'],
    'lucho': ['luis'],
    'migue': ['miguel'],
    'eli': ['eliana', 'elizabeth', 'elias'],
    'vane': ['vanessa'],
    'isa': ['isabel', 'isabela', 'isaias'],
    'dianis': ['diana'],
}

# Catálogo oficial de cultos y sus palabras clave / variantes para búsqueda
CULTOS_CATALOG = [
    {
        'nombre': 'Escuela Dominical',
        'dia_habitual': 'Domingo',
        'keywords': ['escuela', 'dominical', 'ninos', 'infantil', 'domingo', 'clase', 'biblica', 'escuelita']
    },
    {
        'nombre': 'Oración y Enseñanza',
        'dia_habitual': 'Martes / Jueves',
        'keywords': ['oracion', 'orasion', 'ensenanza', 'ensena', 'doctrina', 'estudio', 'clamor', 'martes', 'jueves']
    },
    {
        'nombre': 'Jóvenes Generación Vida',
        'dia_habitual': 'Sábado / Domingo',
        'keywords': ['jovenes', 'joven', 'generacion', 'vida', 'juvenil', 'chicos', 'juventud', 'gen']
    },
    {
        'nombre': 'Mujeres del Bien',
        'dia_habitual': 'Semanal',
        'keywords': ['mujeres', 'mujer', 'damas', 'femenil', 'bien', 'hermanas', 'dorcas']
    },
    {
        'nombre': 'Hombres de Verdad',
        'dia_habitual': 'Semanal',
        'keywords': ['hombres', 'hombre', 'caballeros', 'varones', 'verdad', 'hermanos']
    },
    {
        'nombre': 'Espigas de Vida',
        'dia_habitual': 'Semanal',
        'keywords': ['espigas', 'espiga', 'spig', 'spigas', 'espias', 'vida', 'cosecha']
    },
    {
        'nombre': 'Gavillas para Cristo',
        'dia_habitual': 'Semanal',
        'keywords': ['gavillas', 'gavilla', 'cristo', 'cosecha', 'gaviy']
    },
    {
        'nombre': 'Misionero',
        'dia_habitual': 'Mensual',
        'keywords': ['misionero', 'misiones', 'misionera', 'mision', 'ofrenda']
    },
    {
        'nombre': 'Evangelismo',
        'dia_habitual': 'Semanal',
        'keywords': ['evangelismo', 'evangelizacion', 'salidas', 'almas', 'evangelio']
    },
    {
        'nombre': 'Intercesión',
        'dia_habitual': 'Semanal',
        'keywords': ['intercesion', 'intersecion', 'intercesora', 'clamor', 'ruego', 'vigilia']
    },
    {
        'nombre': 'Obra social',
        'dia_habitual': 'Semanal',
        'keywords': ['obra', 'social', 'ayuda', 'comunidad', 'mercados', 'solidaridad']
    },
    {
        'nombre': 'Culto General / Especial',
        'dia_habitual': 'Especial',
        'keywords': ['general', 'especial', 'aniversario', 'confraternidad', 'convencion', 'campana']
    }
]

def normalize_str(s: str) -> str:
    """Limpia tildes, mayúsculas y caracteres no alfanuméricos."""
    if not s:
        return ''
    s = s.strip().lower()
    # Reemplazar ñ antes de normalizar para no perderla totalmente o estandarizarla
    s = s.replace('ñ', 'n')
    # Quitar acentos
    s = ''.join(c for c in unicodedata.normalize('NFD', s) if unicodedata.category(c) != 'Mn')
    return re.sub(r'[^a-z0-9\s]', '', s)

def phonetic_simplify(s: str) -> str:
    """Simplifica sonidos equivalentes comunes en español latino/español."""
    s = normalize_str(s)
    # b y v suenan igual
    s = s.replace('v', 'b')
    # z y c (ante e, i) suenan a s en latam o se confunden al escribir
    s = s.replace('z', 's')
    s = re.sub(r'c([ei])', r's\1', s)
    # y / ll / j / g (ante e, i)
    s = s.replace('ll', 'y')
    s = re.sub(r'g([ei])', r'j\1', s)
    s = s.replace('y', 'j')  # yois <-> jois
    # h es muda
    s = s.replace('h', '')
    # eliminar letras dobles repetidas
    s = re.sub(r'(.)\1+', r'\1', s)
    return s

def levenshtein_distance(s1: str, s2: str) -> int:
    """Calcula la distancia de Levenshtein para medir similitud tipográfica."""
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def search_culto(query: str):
    """Busca cultos tolerando abreviaciones, errores de tipeo y palabras clave."""
    q_norm = normalize_str(query)
    if not q_norm:
        return [c['nombre'] for c in CULTOS_CATALOG]
    
    q_phon = phonetic_simplify(query)
    matches = []
    
    for c in CULTOS_CATALOG:
        c_name = c['nombre']
        c_norm = normalize_str(c_name)
        c_phon = phonetic_simplify(c_name)
        score = 0
        
        # Coincidencia directa o prefijo
        if c_norm.startswith(q_norm):
            score += 100
        elif q_norm in c_norm:
            score += 80
            
        # Coincidencia fonética
        if q_phon in c_phon:
            score += 60
            
        # Coincidencia con palabras clave
        for kw in c['keywords']:
            kw_norm = normalize_str(kw)
            if q_norm == kw_norm:
                score += 90
            elif kw_norm.startswith(q_norm) or q_norm.startswith(kw_norm):
                score += 70
            elif q_norm in kw_norm:
                score += 50
            # Similitud Levenshtein con la palabra clave
            dist = levenshtein_distance(q_norm, kw_norm)
            if len(kw_norm) >= 4 and dist <= 2:
                score += 45 - (dist * 10)
                
        if score > 0:
            matches.append((score, c_name))
            
    matches.sort(key=lambda x: x[0], reverse=True)
    return [m[1] for m in matches]

def search_members_smart(query: str, members: list):
    """
    Busca miembros con alta tolerancia:
    - Búsqueda por nombre o apellido
    - Diccionario de diminutivos (Manu -> Manuel, Rafa -> Rafael, Yois -> Joisse)
    - Normalización fonética (c/s/z, b/v, y/ll/j)
    - Tolerancia a errores tipográficos (Levenshtein)
    """
    q_norm = normalize_str(query)
    if not q_norm or len(q_norm) < 2:
        return []
        
    q_phon = phonetic_simplify(query)
    
    # Buscar si la query es un diminutivo y expandir
    expanded_queries = [q_norm]
    for nick, real_names in NICKNAMES.items():
        if q_norm == nick or q_norm.startswith(nick) or nick.startswith(q_norm):
            expanded_queries.extend([normalize_str(rn) for rn in real_names])
            
    results = []
    
    for m in members:
        nombre = m.get('nombre', '')
        apellidos = m.get('apellidos', '')
        full_name = f"{nombre} {apellidos}".strip()
        full_rev = f"{apellidos} {nombre}".strip()
        
        nom_norm = normalize_str(nombre)
        ape_norm = normalize_str(apellidos)
        full_norm = normalize_str(full_name)
        full_phon = phonetic_simplify(full_name)
        
        score = 0
        
        # 1. Coincidencias directas
        if q_norm in full_norm:
            score += 100
            if nom_norm.startswith(q_norm) or ape_norm.startswith(q_norm):
                score += 40
        elif q_phon in full_phon:
            score += 80
            
        # 2. Coincidencias por apodo/diminutivo expandido
        for eq in expanded_queries:
            if eq in full_norm:
                score += 85
                break
            if phonetic_simplify(eq) in full_phon:
                score += 70
                break
                
        # 3. Coincidencias por palabras individuales (tolerancia a orden)
        q_words = q_norm.split()
        if len(q_words) > 1:
            all_matched = True
            for w in q_words:
                if w not in full_norm and phonetic_simplify(w) not in full_phon:
                    all_matched = False
                    break
            if all_matched:
                score += 90
                
        # 4. Fuzzy / Levenshtein con las palabras del nombre
        if score == 0:
            for word in full_norm.split():
                if len(word) >= 4 and len(q_norm) >= 3:
                    dist = levenshtein_distance(q_norm, word)
                    if dist <= 2:
                        score += (30 - dist * 10)
                        
        if score > 0:
            results.append((score, m))
            
    # Ordenar por relevancia
    results.sort(key=lambda x: x[0], reverse=True)
    return [r[1] for r in results[:40]]
