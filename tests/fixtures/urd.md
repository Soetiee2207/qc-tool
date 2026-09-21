---
type: urd
feature: demo
status: draft
---

# Demo URD (fixture cho test, không phải tài liệu thật)

### US-001 — Đăng nhập

**As a** nhân viên  
**I want** đăng nhập một lần  
**So that** tôi vào được portal

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Chưa đăng nhập | Mở `/projects` | Redirect `/login` |
| AC-001-2 | Ở `/login` | Bấm nút SSO | Sang IdP |

### US-002 — Xem menu

**As a** user  
**I want** thấy menu đúng quyền  
**So that** không thấy chức năng cấm

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-002-1 | Có `project:view` | Load trang | Menu Projects hiện |
