# Prior Art API - Usage Guide

REST API servis za dohvaćanje USPTO patentnih dokumenata iz TAR/ZIP arhiva.

**Port**: 8095
**Jezik**: Go
**Lokacija**: `/home/mark/projects/uspto_patent_extractor/prior_art_api/`

---

## Pokretanje servisa

### Opcija 1: Korištenje run.sh (preporučeno)

```bash
cd /home/mark/projects/uspto_patent_extractor/prior_art_api
./run.sh
```

Skripta automatski:
1. Zaustavlja postojeći proces (ako postoji)
2. Ponovno kompajlira ako su source fajlovi promijenjeni
3. Pokreće server na portu 8095

### Opcija 2: Ručno pokretanje

```bash
cd /home/mark/projects/uspto_patent_extractor/prior_art_api

# Kompajliranje (samo ako je potrebno)
go build -o prior_art_api .

# Pokretanje
./prior_art_api
```

### Opcija 3: Pokretanje u pozadini

```bash
cd /home/mark/projects/uspto_patent_extractor/prior_art_api
nohup ./prior_art_api > api.log 2>&1 &
```

---

## Zaustavljanje servisa

### Opcija 1: Korištenje pkill

```bash
pkill -f prior_art_api
```

### Opcija 2: Pronađi PID i zaustavi

```bash
# Pronađi PID
ps aux | grep prior_art_api

# Zaustavi proces
kill <PID>
```

### Opcija 3: Zaustavi sve na portu 8095

```bash
fuser -k 8095/tcp
```

---

## Provjera statusa

### Health check

```bash
curl http://localhost:8095/health

curl http://100.76.27.122:8095/health
```

Očekivani odgovor:
```json
{"status": "ok"}
```

### Info endpoint

```bash
curl http://localhost:8095/

curl http://100.76.27.122:8095/
```

---

## API Endpoints

| Endpoint | Metoda | Opis |
|----------|--------|------|
| `/` | GET | Informacije o servisu |
| `/health` | GET | Health check |
| `/api/patent/{pub_number}` | GET | Dohvati patent kao JSON |

---

## Dohvaćanje patenta

### Osnovni primjer

```bash
curl http://localhost:8095/api/patent/20160148332

curl http://100.76.27.122:8095/api/patent/US20160148332A1
```

### Podržani formati pub_number

Svi ovi formati rade:

```bash
# Samo broj
curl http://localhost:8095/api/patent/20160148332

# S prefiksom US
curl http://localhost:8095/api/patent/US20160148332

# Puni format s kind kodom
curl http://localhost:8095/api/patent/US20160148332A1
```

API automatski normalizira ulaz.

### Primjer odgovora

```json
{
  "success": true,
  "patent": {
    "pub_number": "20160148332",
    "kind": "A1",
    "title": "Identity Protection",
    "publication": {
      "date": "2016-05-26",
      "date_formatted": "05/26/2016"
    },
    "application": {
      "number": "14947996",
      "date": "2015-11-20",
      "date_formatted": "11/20/2015"
    },
    "applicant": {
      "name": "BLUE SUN TECHNOLOGIES, INC.",
      "location": "Malibu, CA (US)"
    },
    "inventors": [
      {
        "name": "Jeffrey M. Stibel",
        "location": "Malibu, CA (US)"
      }
    ],
    "classifications": {
      "ipc": ["G06Q 20/40"],
      "cpc": ["G06Q 20/401", "G06Q 20/4014"]
    },
    "abstract": "Some embodiments provide systems and methods...",
    "drawings": [
      {
        "num": 1,
        "id": "Fig-EMI-D00001",
        "file": "US20160148332A1-20160526-D00001.TIF",
        "path": "/mnt/patents/data/historical/2016/..."
      }
    ],
    "description": [
      {"type": "heading", "text": "BACKGROUND"},
      {"type": "paragraph", "num": 1, "text": "..."}
    ],
    "claims": [
      {"num": 1, "text": "A method of identity protection..."},
      {"num": 2, "text": "The method of claim 1..."}
    ],
    "source": {
      "archive": "I20160526.tar",
      "xml_path": "I20160526.tar/US20160148332A1-20160526/US20160148332A1-20160526.XML"
    }
  }
}
```

### Greške

Ako patent nije pronađen:

```json
{
  "success": false,
  "error": "Patent not found: US99999999A1"
}
```

---

## Konfiguracija

Environment varijable (s defaultima):

| Varijabla | Default | Opis |
|-----------|---------|------|
| `DB_HOST` | localhost | PostgreSQL host |
| `DB_PORT` | 5432 | PostgreSQL port |
| `DB_NAME` | companies_db | Naziv baze |
| `DB_USER` | mark | Korisnik |
| `DB_PASSWORD` | mark123 | Lozinka |
| `SERVER_PORT` | 8095 | API port |
| `ARCHIVE_BASE` | /mnt/patents/data/historical | Bazni direktorij arhiva |

Primjer s custom konfiguracijom:

```bash
DB_HOST=192.168.1.100 SERVER_PORT=9000 ./prior_art_api
```

---

## Integracija s drugim servisima

### Python primjer

```python
import requests

def get_patent(pub_number):
    url = f"http://localhost:8095/api/patent/{pub_number}"
    response = requests.get(url)
    data = response.json()

    if data["success"]:
        return data["patent"]
    else:
        raise Exception(data["error"])

# Korištenje
patent = get_patent("20160148332")
print(f"Title: {patent['title']}")
print(f"Abstract: {patent['abstract']}")
```

### cURL s jq za formatiranje

```bash
# Samo naslov i abstract
curl -s http://localhost:8095/api/patent/20160148332 | jq '{title: .patent.title, abstract: .patent.abstract}'

# Lista izumitelja
curl -s http://localhost:8095/api/patent/20160148332 | jq '.patent.inventors[].name'

# Svi claimovi
curl -s http://localhost:8095/api/patent/20160148332 | jq '.patent.claims'
```

---

## Troubleshooting

### Problem: Connection refused

```bash
# Provjeri je li servis pokrenut
ps aux | grep prior_art_api

# Provjeri sluša li na portu
netstat -tlnp | grep 8095
```

### Problem: Database connection error

```bash
# Provjeri PostgreSQL
pg_isready -h localhost -p 5432

# Testiraj konekciju
psql -h localhost -U mark -d companies_db -c "SELECT 1"
```

### Problem: TAR file not found

Provjeri postoji li arhiv:

```bash
ls -la /mnt/patents/data/historical/2016/I20160526.tar
```

### Logovi

Ako je servis pokrenut s run.sh, logovi se ispisuju na stdout. Za pozadinsko pokretanje:

```bash
nohup ./prior_art_api > /home/mark/projects/uspto_patent_extractor/logs/prior_art_api.log 2>&1 &
tail -f /home/mark/projects/uspto_patent_extractor/logs/prior_art_api.log
```

---

## Arhitektura

```
Request: GET /api/patent/{pub_number}
              │
              ▼
    ┌─────────────────────┐
    │  1. NORMALIZE       │  Očisti pub_number (ukloni US, kind)
    └─────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │  2. DB LOOKUP       │  Pronađi u patent_data_unified
    └─────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │  3. EXTRACT TAR     │  Otvori /mnt/patents/.../I{date}.tar
    └─────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │  4. EXTRACT ZIP     │  Pronađi i dekomprimiraj ZIP iz TAR-a
    └─────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │  5. PARSE XML       │  Parsiraj XML, identificiraj TIF fajlove
    └─────────────────────┘
              │
              ▼
    ┌─────────────────────┐
    │  6. BUILD JSON      │  Strukturiraj sve u JSON odgovor
    └─────────────────────┘
              │
              ▼
         JSON Response
```

---

Last Updated: January 2026
