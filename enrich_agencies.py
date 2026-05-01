import json, time, requests

AGENCIES_PATH = 'agencies.json'
HEADERS = {'User-Agent': 'ProlesHHC-Research/1.0'}


def search_nominatim(name, city):
    q = f"{name} {city} Maryland"
    try:
        r = requests.get(
            'https://nominatim.openstreetmap.org/search',
            params={'q': q, 'format': 'json', 'limit': 1, 'addressdetails': 1},
            headers=HEADERS,
            timeout=8
        )
        results = r.json()
        if results:
            return results[0]
    except Exception as e:
        print(f"  Nominatim error: {e}")
    return None


with open(AGENCIES_PATH, 'r', encoding='utf-8') as f:
    agencies = json.load(f)

enriched = 0
for a in agencies:
    if a.get('phone') and a.get('phone') != '—':
        continue
    name = a.get('name', '')
    city = a.get('city', '')
    print(f"Searching: {name} ({city})...")
    result = search_nominatim(name, city)
    if result and result.get('address'):
        addr = result['address']
        if addr.get('road'):
            full_addr = f"{addr.get('house_number', '')} {addr.get('road', '')}".strip()
            a['address'] = full_addr
            enriched += 1
            print(f"  Found address: {full_addr}")
    time.sleep(0.5)

with open(AGENCIES_PATH, 'w', encoding='utf-8') as f:
    json.dump(agencies, f, indent=2, ensure_ascii=False)

print(f"\nEnrichment complete. Updated {enriched} agencies.")
