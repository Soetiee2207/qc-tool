# Template OpenAPI — hướng dẫn điền

File: `openapi-template.yaml`

## Vì sao dùng OpenAPI

Tool cần biết **chính xác** hệ thống có endpoint nào, nhận field gì, trả field gì.
Không có nó, tool phải đoán từ tài liệu — và đoán thì sinh ra testcase gọi endpoint không tồn tại.

OpenAPI là cách rẻ nhất để đưa thông tin đó cho tool: một file YAML, viết một lần, dùng mãi.

## Ba cách có file, chọn cách dễ nhất với anh

| Cách | Khi nào dùng | Việc phải làm |
|---|---|---|
| **1. Backend đã có sẵn** | FastAPI/NestJS/Spring thường tự sinh | Chạy lệnh export, xong. FastAPI: `python -c "import json,app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json` |
| **2. Viết tay từ template** | App không có spec (như portal hiện tại) | Copy `openapi-template.yaml`, điền dần. **Điền 1 endpoint cũng được** — không cần đủ |
| **3. Từ curl có sẵn** | Đã có sẵn lệnh curl chạy được | Dán curl vào [curlconverter.com](https://curlconverter.com), hoặc tự chuyển theo mục dưới |

> **Không cần điền hết.** Điền được endpoint nào thì tool ground được endpoint đó.
> Điền 3 endpoint vẫn tốt hơn không có gì.

## Tối thiểu cần gì cho một endpoint

Chỉ 5 thứ. Thiếu cái nào thì tool không sinh được testcase cho endpoint đó:

```yaml
paths:
  /api/v1/auth/config:
    get:                          # 1. method
      summary: Lấy cấu hình Keycloak   # 2. để tool đặt tên testcase
      security: []                # 3. rỗng = public, hoặc [{bearerAuth: []}] = cần token
      responses:
        '200':                    # 4. mã trả về
          content:
            application/json:
              schema:             # 5. các field trả ra
                type: object
                properties:
                  keycloak_enabled: {type: boolean}
```

Từ 5 thứ này tool sinh được: gọi đúng endpoint, assert đúng status, assert đủ field, assert đúng kiểu.

## Từ curl sang OpenAPI

```bash
curl -X POST https://api.example.com/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"a@b.com","password":"secret"}'
```

→

```yaml
/api/v1/auth/login:
  post:
    summary: Đăng nhập
    requestBody:
      required: true
      content:
        application/json:
          schema:
            type: object
            required: [email, password]
            properties:
              email: {type: string, format: email}
              password: {type: string}
    responses:
      '200': {description: OK}
      '401': {description: Sai thông tin đăng nhập}
```

## File template đã có gì

`openapi-template.yaml` được điền sẵn **3 operation thật** của pilot login-sso
(`GET /api/v1/auth/config`, `GET` + `PATCH /api/v1/auth/me`), kèm:

- `servers:` — khai báo môi trường dev/staging/prod, để đổi môi trường không phải sửa testcase
- `securitySchemes:` — khai báo cách xác thực (bearer token, API key, basic)
- Chú thích `x-qc-*` — vài field mở rộng để đánh dấu thứ QC cần mà OpenAPI không có

## Các field `x-qc-*` (mở rộng riêng của tool)

OpenAPI chuẩn không có chỗ khai báo vài thứ QC cần. Tool thêm tiền tố `x-qc-`:

| Field | Ý nghĩa | Ví dụ |
|---|---|---|
| `x-qc-id` | ID requirement liên quan, để trace | `F-01` |
| `x-qc-priority` | Mức ưu tiên test | `High` |
| `x-qc-test-data` | Dữ liệu mẫu để chạy | `{email: user@test.com}` |
| `x-qc-requires-auth` | Endpoint có bắt buộc đăng nhập không | `true` |
| `x-qc-latency-p95-ms` | Ngưỡng hiệu năng cần assert | `250` |

Không bắt buộc điền. Điền thì tool sinh được testcase sát hơn.

## Kiểm tra file trước khi đưa cho tool

```bash
uv run scripts/validate_openapi.py templates/api/openapi-template.yaml
```

Script kiểm tra: YAML hợp lệ, có `openapi`/`info`/`paths`, mỗi operation có `responses`,
và cảnh báo field nào còn để trống chưa điền.
