---
type: srs-flows
feature: qc-checklists
updated: 2026-09-05
---

# QC Checklists — Flows

## Flow: Publish Checklist Version (Sequence)

**Trigger:** QC Lead bấm Publish

**Related FR:** F-04

```mermaid
sequenceDiagram
    participant L as QC Lead
    participant FE as Portal FE
    participant API as FastAPI /qc/checklists
    participant DB as PostgreSQL
    participant Cache as Redis

    L->>FE: Click Publish
    FE->>API: PATCH /api/v1/qc/checklists/{version_id}
    Note over FE,API: { status: "published" }
    API->>API: require_permission(qc:checklist:manage)
    API->>DB: SELECT other published versions
    loop each old published
        API->>DB: UPDATE status = archived
    end
    API->>DB: UPDATE target status = published
    API->>DB: COMMIT
    API->>Cache: invalidate_published_criteria_cache()
    API-->>FE: 200 ChecklistVersionOut
    FE-->>L: UI refresh status chip
```

## Flow: Load Published Criteria for Review (Sequence)

**Trigger:** Review detail mount

**Related FR:** F-06

```mermaid
sequenceDiagram
    participant R as Reviewer
    participant FE as Review FE
    participant API as FastAPI
    participant Cache as Redis
    participant DB as PostgreSQL

    R->>FE: Open review detail
    FE->>API: GET /api/v1/qc/checklists/published/criteria
    API->>API: require_permission(qc:review:perform)
    alt cache hit
        API->>Cache: get criteria list
        Cache-->>API: ChecklistCriterionOut[]
    else cache miss
        API->>DB: SELECT latest published version + criteria
        DB-->>API: rows
        API->>Cache: set with TTL
    end
    API-->>FE: 200 { data: criteria[] }
    FE-->>R: Render checklist panel
```

## Flow: Create Version with Criteria (Activity)

**Trigger:** POST create (API ready; FE save button TBD)

**Related FR:** F-03

```mermaid
flowchart TB
    Start((POST /checklists)) --> D1{status = published?}
    D1 -->|Yes| A1[Archive all published]
    D1 -->|No| A2[Skip archive]
    A1 --> A3[INSERT ChecklistVersion]
    A2 --> A3
    A3 --> A4[INSERT ChecklistCriterion rows]
    A4 --> D2{published?}
    D2 -->|Yes| A5[invalidate cache]
    D2 -->|No| End((201 DetailOut))
    A5 --> End
```
