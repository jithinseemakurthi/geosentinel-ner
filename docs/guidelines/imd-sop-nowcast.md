---
id: imd-sop
collection: imd_nowcast
title: "IMD Nowcast — NER colour codes"
source: IMD
year: 2024
---

IMD nowcast colours: Green (no action), Yellow (watch), Orange (prepare), Red (take action). NER districts Aizawl, Imphal, Shillong, Gangtok are covered at 3-hourly refresh. State_District and category mapping is available via /imd/nowcast which proxies api.imd.gov.in. Colour 2 = Yellow, 3 = Orange, 4 = Red. Frontend fetches this live; the assistant should prefer live IMD data over this guideline when available.
