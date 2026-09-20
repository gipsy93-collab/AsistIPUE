import os
import sys
import re
import json

sys.stdout.reconfigure(encoding='utf-8')

pdf_path = r'C:\Users\gipsy\Downloads\CUMPLEAÑOS IPUE GRANADA .pdf'
import pypdf
reader = pypdf.PdfReader(pdf_path)

months = [
    'Enero', 'Febrero', 'Marzo', 'Abril', 'Mayo', 'Junio',
    'Julio', 'Agosto', 'Septiembre', 'Octubre', 'Noviembre', 'Diciembre'
]

def unspace_token(token):
    token = token.strip()
    if not token:
        return ''
    # Some tokens have parentheses like '(  M a r í a  )' or '(  g u i n e a  e c u a t o r i a l )'
    words = re.split(r'\s{2,}', token)
    out_words = []
    for w in words:
        w_clean = re.sub(r'([A-Za-zÁÉÍÓÚáéíóúÑñ0-9])\s+(?=[A-Za-zÁÉÍÓÚáéíóúÑñ0-9])', r'\1', w)
        w_clean = re.sub(r'\(\s+', '(', w_clean)
        w_clean = re.sub(r'\s+\)', ')', w_clean)
        out_words.append(w_clean.strip())
    res = ' '.join(out_words).strip()
    res = re.sub(r'\s+', ' ', res)
    return res

parsed_birthdays = []

for m_idx, month_name in enumerate(months):
    page_idx = m_idx + 1
    if page_idx >= len(reader.pages):
        break
    page = reader.pages[page_idx]
    txt = page.extract_text()
    lines = [l.strip() for l in txt.split('\n') if l.strip()]
    
    for line in lines:
        m = re.match(r'^(\d(?:\s*\d)?)\s*[\.,]*\s*(.*)$', line)
        if m:
            day_str = m.group(1).replace(' ', '')
            day = int(day_str)
            rest = m.group(2).strip()
            rest = re.sub(r'^\.+', '', rest).strip()
            rest = re.sub(r'^/\s*', '', rest).strip()
            if not rest:
                continue
            
            parts = [p.strip() for p in rest.split('/') if p.strip()]
            for p in parts:
                clean_name = unspace_token(p)
                if clean_name and clean_name not in ('.', '..', '/'):
                    parsed_birthdays.append({
                        'mes_num': m_idx + 1,
                        'mes': month_name,
                        'dia': day,
                        'nombre': clean_name,
                        'raw': p
                    })

print(f"Total entries parsed: {len(parsed_birthdays)}")
for b in parsed_birthdays:
    print(f"{b['mes_num']:02d}-{b['dia']:02d} | {b['mes']:10s} | {b['nombre']}")

out_json = os.path.join(r'C:\Users\gipsy\Documents\CIENCIA TRANSMEDIA\CRECS\ASISIPUE\data', 'cumpleanos.json')
with open(out_json, 'w', encoding='utf-8') as f:
    json.dump(parsed_birthdays, f, ensure_ascii=False, indent=2)
print("Saved to:", out_json)
