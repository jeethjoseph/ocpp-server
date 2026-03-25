# Backlog: WiFi Signal Quality Monitoring

**Created**: 2026-03-25
**Priority**: Medium
**Status**: Backlog

## Context

WiFi-connected chargers (e.g. `a623d346`) are already sending `WiFiRSSI` DataTransfer messages to the server, but the server currently responds with `UnknownMessageId` and discards the data.

The existing `SignalQuality` table and handler only support cellular (GSM) signal metrics (`rssi` 0-31, `ber` 0-7). WiFi RSSI uses a fundamentally different scale (dBm, typically -100 to 0) and includes additional fields like temperature and quality percentage.

## Incoming Payload

```json
{
    "rssi": -37,
    "quality": 126,
    "description": "Excellent",
    "unit": "dBm",
    "temperature": 29.03,
    "tempUnit": "C",
    "isWeak": false,
    "isCritical": false,
    "timestamp": "2026-03-25T09:53:44Z",
    "sequenceNumber": 42
}
```

| Field | Type | Description |
|-------|------|-------------|
| `rssi` | integer | WiFi signal strength in dBm (typically -100 to 0, higher is better) |
| `quality` | integer | Signal quality indicator |
| `description` | string | Human-readable quality label (e.g. "Excellent", "Good", "Poor") |
| `unit` | string | Always `"dBm"` |
| `temperature` | float | Device temperature in Celsius |
| `tempUnit` | string | Always `"C"` |
| `isWeak` | boolean | Whether signal is considered weak |
| `isCritical` | boolean | Whether signal is critically low |
| `timestamp` | string | ISO 8601 timestamp from charger |
| `sequenceNumber` | integer | Incrementing message counter |

OCPP wire format:
```json
[2, "<uniqueId>", "DataTransfer", {
    "vendorId": "VoltLync",
    "messageId": "WiFiRSSI",
    "data": "<JSON string>"
}]
```

## Why a Separate Table

The existing `signal_quality` table stores GSM metrics (RSSI 0-31, BER 0-7). WiFi data is incompatible:
- RSSI scales differ: GSM 0-31 vs WiFi dBm -100 to 0
- WiFi has no BER equivalent
- WiFi includes temperature, quality %, weak/critical flags
- Mixing both in one table makes data ambiguous and the API/frontend harder to build

## Implementation Tasks

### 1. New `WiFiSignalQuality` Model
**File**: `backend/models.py`

New table `wifi_signal_quality` with fields:
- `id` (PK)
- `created_at`, `updated_at` (auto timestamps)
- `charger` (FK to Charger, indexed)
- `rssi` (IntField) — dBm value
- `quality` (IntField)
- `description` (CharField) — "Excellent", "Good", etc.
- `temperature` (FloatField, nullable)
- `is_weak` (BooleanField)
- `is_critical` (BooleanField)
- `timestamp` (CharField) — raw timestamp from charger
- `sequence_number` (IntField, nullable)

### 2. DataTransfer Handler
**File**: `backend/main.py`

- Add `"WiFiRSSI"` route in `on_data_transfer()` alongside `"SignalQuality"` and `"GetLastMeterValue"`
- New `_handle_wifi_rssi(data)` method: parse JSON, validate required fields, store to DB, return `Accepted`

### 3. API Endpoints
**File**: `backend/routers/chargers.py`

Mirror the existing SignalQuality endpoints:
- `GET /{charger_id}/wifi-signal-quality` — paginated history with time filter
- `GET /{charger_id}/wifi-signal-quality/latest` — most recent reading

### 4. Database Migration
Generate via Aerich after model is added.

### 5. Frontend (Optional Follow-up)
- Display WiFi signal data on charger detail page (similar to existing cellular signal card)
- Show RSSI in dBm with color coding: > -50 Excellent, -50 to -60 Good, -60 to -70 Fair, < -70 Poor

## Acceptance Criteria

- [ ] Server accepts `WiFiRSSI` DataTransfer messages and responds with `Accepted`
- [ ] WiFi signal data is stored in `wifi_signal_quality` table
- [ ] Admin API returns WiFi signal history and latest reading per charger
- [ ] No impact on existing cellular `SignalQuality` handling
- [ ] No `UnknownMessageId` warnings in logs for WiFiRSSI messages
