---
type: srs-flows
feature: qc-dashboard
updated: 2026-09-05
---

# QC Dashboard — Flows

## Flow: Load Dashboard (Sequence)

**Trigger:** Navigate `/qc/dashboard`

**Related FR:** F-01, F-02

```mermaid
sequenceDiagram
    participant U as QC User
    participant FE as QCDashboard.tsx
    participant API as FastAPI /qc
    participant Cache as Redis
    participant DB as PostgreSQL

    U->>FE: Open /qc/dashboard
    FE->>API: GET /api/v1/qc/dashboard?include_analytics=true
    API->>API: require_permission(dashboard:qc:view)
    alt cache TTL > 0
        API->>Cache: get_or_compute_dashboard_stats(scope_key)
    else
        API->>DB: aggregate status hours
    end
    API->>DB: fetch_my_queue_candidates (top for user)
    opt include_analytics
        API->>Cache: get_or_compute_dashboard_analytics
    end
    API-->>FE: 200 QcDashboardOut
    FE-->>U: Tiles + pie + my queue + QCDashboardAnalytics
```

## Flow: Auto-assign Run Now (Sequence)

**Trigger:** Lead clicks Run now

**Related FR:** F-06

```mermaid
sequenceDiagram
    participant L as QC Lead
    participant FE as AutoAssignRulesPanel
    participant API as FastAPI
    participant DB as PostgreSQL

    L->>FE: Click Run now
    FE->>API: POST /api/v1/qc/auto-assign/run
    API->>API: require_permission(qc:assign)
    API->>DB: load config + eligible reviewers
    API->>DB: select unassigned pending items (scope)
    loop each item
        API->>API: pick reviewer by strategy
        API->>DB: UPDATE assignee, pending→in_review
    end
    API->>DB: COMMIT
    API-->>FE: 200 { assigned, skipped }
    FE->>FE: invalidate qcKeys + autoAssignKeys
    FE-->>L: Toast success
```

## Flow: Save Auto-assign Rules (Sequence)

**Trigger:** Toggle/checkbox/select change

**Related FR:** F-04

```mermaid
sequenceDiagram
    participant L as QC Lead
    participant FE as AutoAssignRulesPanel
    participant API as FastAPI
    participant DB as PostgreSQL

    L->>FE: Change enabled/strategy/reviewers
    FE->>FE: merge rules + toApi()
    FE->>API: PUT /api/v1/qc/auto-assign/rules
    API->>DB: UPDATE qc_auto_assign_config
    API-->>FE: 200 QcAutoAssignRulesOut
    FE->>FE: setQueryData rules cache
```

## Flow: Dashboard vs Annotation Mode (Activity)

```mermaid
flowchart LR
    Route["/qc/dashboard"] --> D1{mode}
    RouteA["/qc/annotation-dashboard"] --> Ann[manual_annotation_only=true]
    D1 --> QC[product_line default]
    QC --> Panel[AutoAssignRulesPanel visible if qc:assign]
    Ann --> Hide[Hide AutoAssign panel]
    Ann --> Link[CTA view_annotation_queue → /qc/annotation]
```
