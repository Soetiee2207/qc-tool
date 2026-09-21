---
type: srs
feature: demo
status: draft
---

# Demo SRS (fixture cho test, không phải tài liệu thật)

## 4. NON-FUNCTIONAL REQUIREMENTS

### 4.1 Security (NFR-SEC)

| ID | Requirement |
| --- | --- |
| NFR-SEC-01 | JWT validated via JWKS |

### 4.2 Performance (NFR-PERF)

| ID | Requirement |
| --- | --- |
| NFR-PERF-01 | `/auth/config` p95 < 100ms |

### 4.3 Availability (NFR-AVAIL)

| ID | Requirement |
| --- | --- |
| NFR-AVAIL-01 | IdP outage → login screen with clear error |

### 4.4 i18n (NFR-I18N)

| ID | Requirement |
| --- | --- |
| NFR-I18N-01 | Login screen EN/VI toggle |

### 4.5 Observability (NFR-OBS)

| ID | Requirement |
| --- | --- |
| NFR-OBS-01 | 401/403 rates monitorable |
