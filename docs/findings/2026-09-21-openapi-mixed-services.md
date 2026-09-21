---
type: finding
status: open
created: 2026-09-21
updated: 2026-09-21
lang: vi
owner: "@binhhm"
source: docs/OAS/authentication/openapi.yaml (repo vd-data-platform-portal)
links: [docs/tracking/todo.md]
tags: [openapi, login-sso, spec-quality, tool-behaviour]
changelog:
  - 2026-09-21 | manual | spec trộn endpoint portal + Keycloak; tool bỏ qua `x-external` thay vì sinh case 404
---

# OpenAPI `authentication` trộn hai service trong một file

Phát hiện khi chạy tool với spec thật (`--oas .../docs/OAS/authentication/openapi.yaml`).

## Hiện trạng

Spec khai 8 operation, nhưng chỉ 3 là của portal:

| Operation | Service thật | Ghi chú |
|---|---|---|
| `GET /auth/config` | portal | |
| `GET /auth/me` | portal | |
| `PATCH /auth/me` | portal | |
| `GET /realms/{realm}/protocol/openid-connect/auth` | Keycloak | `x-external: true` |
| `POST /realms/{realm}/protocol/openid-connect/token` | Keycloak | `x-external: true` |
| `GET /realms/{realm}/protocol/openid-connect/logout` | Keycloak | `x-external: true` |
| `GET /realms/{realm}/protocol/openid-connect/userinfo` | Keycloak | `x-external: true` |
| `GET /realms/{realm}/protocol/openid-connect/certs` | Keycloak | `x-external: true` |

Năm operation Keycloak khai `servers` riêng ở cấp operation (`https://auth.datafactory.fit`,
`http://127.0.0.1:8180/auth`) — đây là cơ chế OpenAPI chuẩn và spec đang dùng **đúng**.

## Vấn đề

`servers` gốc của file chỉ có portal (`…/api/v1`). Không tôn trọng `servers` cấp
operation thì 5 operation Keycloak bị gọi vào host portal → **404 hàng loạt**, và
báo cáo ghi `Fail` trong khi sản phẩm không có lỗi nào.

Đã xác minh trên hệ thống thật (2026-09-21):

| Gọi đúng host | Kết quả |
|---|---|
| `POST https://auth.datafactory.fit/realms/vd-dev/protocol/openid-connect/token` (không body) | `400` |
| `GET  …/userinfo` (không token) | `401` |
| `GET  …/certs` | `200` |
| `POST` với `grant_type=authorization_code` + code giả | `400 invalid_grant` |

→ Keycloak **đúng**; 404 trước đây là lỗi gọi sai host.

## Tool đã sửa (2026-09-21)

1. **Tôn trọng `servers` cấp operation/cấp path.** Endpoint khai server riêng thì
   case sinh ra mang theo `base`; runner gọi đúng host đó.
2. **Bỏ qua operation `x-external: true`.** Đây là quy ước của dự án (không thuộc
   chuẩn OpenAPI) để đánh dấu "không phải service đang test". Sinh case cho nó là
   sinh case luôn sai. Tool ghi cảnh báo rõ thay vì im lặng bỏ.
3. In cảnh báo từ lúc đọc spec ra màn hình, để số testcase tụt không bị hiểu là
   tool bỏ sót.

Sau khi sửa: **8 case API, 8 đạt, 0 lỗi** (trước đó 9 lỗi, trong đó 8 là hệ quả
của việc gọi sai host).

## Đề xuất cho repo portal

Không bắt buộc, spec hiện tại **hợp lệ**. Hai lựa chọn nếu muốn rõ ràng hơn:

1. **Tách file** — `openapi/authentication/portal.yaml` (3 operation portal) và
   `openapi/authentication/keycloak.yaml` (5 operation IdP). Mỗi file khai đúng
   `servers` gốc của mình; không cần `x-external`.
2. **Giữ nguyên** — đã hoạt động đúng với tool, vì tool tôn trọng `servers` cấp
   operation và bỏ qua `x-external`.

Thêm một ghi chú nhỏ: `GET /auth/config` không khai `security`, mà `spec.security`
cũng không có → tool suy ra `requires_auth = false`. Đã kiểm chứng đúng: endpoint
này trả `200` khi không có token, đúng như thiết kế (SPA cần đọc trước khi login).

## Chưa kiểm

- `/realms/...` trên môi trường local (`http://127.0.0.1:8180/auth`, realm
  `vd-platform`) — chưa dựng local nên chưa xác minh.
- `x-external` là quy ước riêng của repo này. Tool đọc nó, nhưng spec của hệ thống
  khác không có khoá này vẫn chạy bình thường.
