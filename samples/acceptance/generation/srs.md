---
type: srs
feature: generation-acceptance
status: draft
---

# SRS hư cấu — acceptance generation

#### 3.2.1. F-01 Health của mock API

### B. API Specification

**Endpoint:** GET /api/v1/health

**Auth:** Không cần xác thực

**Response 200**

| No | Field | Type | Description |
| --- | --- | --- | --- |
| 1 | status | string | Trạng thái API |

Không suy ra business coverage từ việc endpoint trả HTTP 200.
