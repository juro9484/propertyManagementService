# Peak Property — Lead Intelligence Dashboard

Boulder County property management lead generation system.

## Quick Start

### 1. Run the pipeline (Python)

```bash
python3 pipeline.py
```

This will:
- Score all owners in `data/boulder_records.csv`
- Detect new owners vs. previous snapshot
- Write `public/data/landlord_leads.json` (top 50 leads)
- Write `public/data/realtor_leads.json` (20 mocked realtors)
- Snapshot today's CSV → `data/previous_boulder_records.csv`

> **If you skip this step**, the dashboard still works — it falls back to built-in sample data automatically.

---

### 2. Start the dashboard (React)

```bash
npm install
npm run dev
```

Then open: http://localhost:5173

---

## Data Flow

```
data/boulder_records.csv
        │
        ▼
   pipeline.py
        │
        ├── public/data/landlord_leads.json  ←── React fetches this
        └── public/data/realtor_leads.json   ←── React fetches this
```

If the JSON files are missing (pipeline hasn't run), the React app falls back to `src/sampleData.js`.

---

## Adding Real Boulder County Data

Replace `data/boulder_records.csv` with a real export from Boulder County Assessor records. Required columns:

```
CreatedDate, strap, folio, status_cd, bld_num, str_num, str_pfx, str, str_sfx,
str_unit, city, sub_code, sub_dscr, section, township, range, block, lot,
owner_name, mail_to, mailingAddr1, mailingAddr2, mailingCity, mailingState,
mailingZip, mailingCountry, role_cd, pct_own, taxArea, nh, mill_levy,
legalDscr, waterFee, account_type
```

Then run `python3 pipeline.py` again.

---

## Scoring Logic

| Signal | Points |
|---|---|
| Owner name contains LLC, LP, Holdings, Trust, etc. | +4 |
| Mailing city ≠ property city (same state) | +3 |
| Mailing state ≠ CO | +5 |
| Owner appears 3–4 times in dataset | +3 |
| Owner appears 5+ times | +6 |
| Account type is multi-family / rental | +2 |
| New owner detected (vs. previous snapshot) | +5 |

---

## Project Structure

```
propertyManagementService/
├── pipeline.py              # Python scoring + realtor generator
├── data/
│   ├── boulder_records.csv          # Input: current property records
│   └── previous_boulder_records.csv # Auto-generated: yesterday's snapshot
├── public/
│   └── data/
│       ├── landlord_leads.json      # Output: top 50 landlord leads
│       └── realtor_leads.json       # Output: 20 realtor prospects
├── src/
│   ├── App.jsx
│   ├── sampleData.js                # Fallback data (no pipeline needed)
│   └── components/
│       ├── KPICards.jsx
│       ├── LandlordTable.jsx
│       ├── RealtorTable.jsx
│       └── OutreachModal.jsx
└── README.md
```
