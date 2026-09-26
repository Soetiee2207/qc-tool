## Wireframe (ASCII)

```
┌────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│  Review  ›  QC Checklists                                    [ EN / VI ]  [ Publish ]                  │
│  Quản lý phiên bản checklist QC                                                                        │
├──────────────────┬─────────────────────────────────────────────────────────────────────────────────────┤
│ VERSION          │  v2.3  · QC Checklist                                                                 │
│                  │                                                                                       │
│ ┌──────────────┐ │  ┌───┬──────────────┬──────────────┬────┬──────────┬────────┬───┐                    │
│ │ v2.3         │ │  │ ≡ │ Tên (EN)     │ Tên (VI)     │ Op │ Expected │ Std    │ × │                    │
│ │ ● Published  │ │  ├───┼──────────────┼──────────────┼────┼──────────┼────────┼───┤                    │
│ │ binhhm       │ │  │ ≡ │ Frame stable │ Khung ổn định│ ≥  │ 95%      │ Manual │ × │                    │
│ │ 12 tiêu chí  │ │  │ ≡ │ Face visible │ Mặt nhìn thấy│ =  │ yes      │ Auto   │ × │                    │
│ └──────────────┘ │  └───┴──────────────┴──────────────┴────┴──────────┴────────┴───┘                    │
│ ┌──────────────┐ │                                                                                       │
│ │ v2.2         │ │  ┌ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┐        │
│ │ ○ Archived   │ │    +  Thêm tiêu chí                                                          │        │
│ │ 10 tiêu chí  │ │  └ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ┘        │
│ └──────────────┘ │                                                                                       │
│ ┌ ─ ─ ─ ─ ─ ─ ┐ │                                                                                       │
│   + Lưu version  │                                                                                       │
│ └ ─ ─ ─ ─ ─ ─ ┘ │                                                                                       │
└──────────────────┴─────────────────────────────────────────────────────────────────────────────────────┘
```

## Screen description

| # | Items | Control type | Data type | Description |
|---|-------|---------------|-----------|-------------|
| 1 | Page title | Heading | string | • `nav_qc_checklists`; subtitle `checklists_subtitle` |
| 2 | Language toggle | Button | — | • Hiển thị EN/VI toggle (UI shell; portal i18n global) |
| 3 | Publish | Button primary | — | • `handlePublish` → PATCH status=published<br>• Disabled khi không có `selectedId` |
| 4 | Version sidebar | List buttons | version[] | • Width ~208px (`w-52`)<br>• Active: `border-primary bg-accent`<br>• Mỗi card: version mono, StatusChip, created_by, criteria_count |
| 5 | Save version | Dashed button | — | • `qc_save_version` + Plus icon<br>• <!-- TBD: wire POST create --> |
| 6 | Version header | Text | string | • `detail.version` + label `qc_checklist` |
| 7 | Criteria header row | Grid labels | — | • Columns: grip, EN, VI, operator, expected, standard, delete |
| 8 | Criterion row | Grid inputs | ChecklistCriterion | • `nameEn`, `nameVi`, `expected` bound<br>• `section` select: auto/manual (`qc_auto_tool` / `qc_manual`)<br>• Operator select: ≥ ≤ = > < between contains — **chưa bind value**<br>• Trash remove row |
| 9 | Add criterion | Dashed full-width | — | • `addCriterion()` new UUID client-side |
| 10 | Grip handle | Icon | — | • `GripVertical` — reorder P1 (not persisted) |
| 11 | Loading | Text | — | • Sidebar `loading` khi `isLoading && versions.length===0` |
