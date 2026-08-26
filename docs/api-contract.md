# GeoSentinel-NER — API Contract Required by Web Dashboard

Source of truth for what `apps/web-dashboard/src/services/api.ts` calls.
All paths are relative to the gateway origin (`http://localhost:8000`, proxied via `/api` in dev).

## Conventions

- **Auth**: `Authorization: Bearer <access_token>` — HS256 JWT, issuer `geosentinel-ner`,
  audience `geosentinel-api`, access TTL 30 min, refresh TTL 7 days, `jti` claim included.
- **Errors**: FastAPI envelope `{"detail": "<human readable>"}`.
  Expected codes: `401` bad/expired token · `403` missing permission · `409` duplicate ·
  `413` payload too large · `422` validation · `423` account locked · `429` rate limited.
- **Pagination** (`PageParams`): query `page` (≥1, default 1), `page_size` (1–100, default 20).
  Response wrapper:
  ```json
  { "items": [...], "total": 0, "page": 1, "page_size": 20, "total_pages": 0 }
  ```
- **CORS**: origins from `CORS_ALLOW_ORIGINS`; headers `Authorization`, `Content-Type`.

---

## 1. Auth

### POST `/api/v1/auth/login`
Public. Rate-limited per IP.

Request:
```json
{ "username": "admin", "password": "min-8-chars" }
```
(`username` may be an email — backend matches either column.)

Response `200` (`Token`):
```json
{ "access_token": "…", "refresh_token": "…", "token_type": "bearer" }
```
Errors: `401` generic "Incorrect username or password" (never reveal which part failed),
`423` locked ("Account temporarily locked"), `422` missing fields, `429` too many attempts.

### GET `/api/v1/auth/me` — Bearer
Used to restore sessions on page load.

Response `200` (`AppUserRead`):
```json
{
  "id": "uuid", "username": "admin", "email": null, "phone": null,
  "full_name": "System Administrator", "role": "district_officer",
  "state_id": null, "district_id": null, "block_id": null, "village_id": null,
  "preferred_language": "en", "is_active": true, "is_verified": true,
  "last_login_at": "2026-08-21T06:30:00Z", "created_at": "…", "updated_at": null
}
```

### POST `/api/v1/auth/refresh`
Request: `{ "refresh_token": "…" }` → `200` fresh `Token` pair. Rejects deactivated accounts.

### PATCH `/api/v1/auth/me` — Bearer
Only profile fields honoured: `full_name`, `email`, `phone`, `preferred_language`.
Role/jurisdiction fields are ignored server-side (admin-controlled).

---

## 2. Alerts

### GET `/api/v1/alerts?status=&severity=&zone_id=&page=&page_size=` — Bearer

Response items (`AlertRead`):
```json
{
  "id": "uuid",
  "rule_id": null,
  "zone_id": "uuid-or-null",
  "severity": "watch|warning|evacuation|advisory",
  "title": "Immediate evacuation advised — Zone Z-07",
  "message": "M2 dynamic risk model: …",
  "message_local": null,
  "language": "en",
  "issued_at": "2026-08-21T06:30:00Z",
  "expires_at": "2026-08-24T06:30:00Z",
  "status": "active|acknowledged|expired",
  "acknowledged_at": null,
  "acknowledged_by": null,
  "cap_identifier": null,
  "metadata": { "district": "Churachandpur", "probability": 0.87 }
}
```
> Dashboard reads `metadata.district` and `metadata.probability` for display — keep them populated.

### POST `/api/v1/alerts/{alert_id}/acknowledge` — Bearer
Requires RBAC `alerts.acknowledge` (state/district/block officers, admin).
Response `200`: `{ "status": "acknowledged", "alert_id": "<uuid>" }`. Forbidden roles get `403`.

---

## 3. Citizen Reports

### GET `/api/v1/reports?status=&report_type=&village_id=&page=&page_size=` — Bearer

Response items (`CitizenReportRead`) — dashboard displays at minimum:
```json
{
  "id": "uuid",
  "report_code": "GSN-2026-A41F",
  "report_type": "crack|bulge|subsidence|debris|rockfall|road_block|water_spring|other",
  "severity": "unknown|low|medium|high",
  "description": "New crack across village road…",
  "reporter_name": null,
  "status": "submitted|verified|assigned|resolved",
  "priority_score": 78.0,
  "cv_classification": null,
  "cv_confidence": null,
  "village_id": null,
  "geom": { "type": "Point", "coordinates": [91.88, 25.57] },
  "created_at": "…"
}
```

### POST `/api/v1/reports` — Bearer optional (anonymous allowed, rate-limited)

Request (`CitizenReportCreate`):
```json
{
  "report_type": "crack",
  "severity": "medium",
  "description": "What was observed",
  "reporter_name": "Anonymous",
  "geom": { "type": "Point", "coordinates": [91.88, 25.57] }
}
```
Response `200` = `CitizenReportRead` above (server assigns `report_code`, `priority_score`).

### POST `/api/v1/reports/{report_id}/media` — Bearer
Multipart form: `file` + `is_primary`.
Allowed types: jpg/jpeg/png/webp/heic/mp4/mov/webm/m4a/mp3/wav · max 25 MB → else `415`/`413`.
Response `200` (`CitizenReportMediaRead`): `{ "id", "report_id", "media_type", "file_path", "file_size_bytes", "mime_type", "is_primary", "created_at" }`.

---

## 4. Real-time (WebSocket)

### WS `/api/v1/ws/{client_uuid}?token=<access JWT>`
- Browsers cannot set headers on upgrade → token passed as query param.
- Invalid/missing token → server closes with code `4401`; malformed `client_uuid` → `4400`.
- Server pushes JSON messages shaped as:
```json
{ "type": "alert.new", "payload": { …AlertRead… }, "timestamp": "…" }
```
Dashboard consumes `alert.new` / `alert.update` / `report.update` event types when live.

---

## 5. Nice-to-have next (not yet consumed by UI)

| Endpoint | Purpose |
|---|---|
| `GET /api/v1/sensors/stations` | replace hardcoded sensor cards |
| `GET /api/v1/sensors/readings?station_id=&start_time=&end_time=` | sparklines per station |
| `GET /api/v1/risk/zones` | render susceptibility zones as map polygons |
| `POST /api/v1/auth/register` | citizen self-signup screen |
| `GET /api/v1/admin/states` | officer jurisdiction pickers |

*Generated from `packages/geosentinel-shared/geosentinel_shared/schemas.py` and
`services/api-gateway/app/main.py` on 21 Aug 2026.*
