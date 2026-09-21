# qc-tool

Công cụ tự động hoá QC: đưa **tài liệu yêu cầu** + **OpenAPI spec** + **link webapp**,
nhận lại **testcase**, **kết quả chạy**, và **báo cáo**.

Tool dùng chung, không gắn với một webapp cụ thể. Đầu vào thiếu cái nào thì chặng dùng
cái đó bị bỏ qua và tool nói rõ hệ quả.

```bash
uv sync && uv run playwright install chromium
uv run qctool serve            # giao diện web — bấm là chạy
```

## Bốn chặng

```
tài liệu ─┐
OpenAPI  ─┼─► requirements.yaml ─► testcases.yaml ─► runner ─► results.json
          │         (ingest)          (generate)      (execute)   results.csv
          │                              │                        junit.xml
          ▼                              ▼                        report.md
       webapp ◄──── ui-map.yaml      testcases.xlsx ◄─────────────────┘
      (crawl)                        (14 cột)         ghi kết quả ngược
```

| Chặng | Làm gì | Module |
|---|---|---|
| **Ingest** | Tài liệu markdown → requirement có ID ổn định + trích dẫn nguồn | `qctool/ingest/` |
| **Generate** | Requirement và/hoặc OpenAPI → testcase IR, qua validator | `qctool/generate/` |
| **Execute** | Chạy testcase: HTTP thật, hoặc Chromium thật cho case UI/UX | `qctool/execute/` |
| **Report** | `report.md` + `junit.xml` + `results.csv`, ghi kết quả ngược vào `.xlsx` | `qctool/report/`, `qctool/render/` |

Điểm quan trọng nhất của luồng dữ liệu: file `.xlsx` 14 cột là **bản ghi hai pha** — sinh
ra một lần, rồi chạy điền kết quả vào chính file đó (4 cột runtime). QC không phải đối
chiếu hai file.

**LLM không bao giờ sinh ra thứ không chạy được.** LLM chỉ làm hai việc — prose → mô hình
test, và prose → step theo vocabulary đóng. Hiện chưa có track LLM; mọi case đều
`generated_by: engine`.

## Cài đặt

Cần **Python ≥ 3.12** và [uv](https://docs.astral.sh/uv/). Playwright + Chromium chỉ cần
khi chạy test UI/UX.

```bash
uv sync
uv run playwright install chromium    # chỉ cần cho test UI/UX
cp .env.example .env                  # rồi điền tài khoản, token (không commit .env)
```

## Dùng

### 1. Cả pipeline bằng một lệnh

```bash
uv run qctool all --config qctool.yaml
```

`qctool.example.yaml` là mẫu đầy đủ, chú thích từng khoá. Không cần file cấu hình thì
truyền thẳng tham số:

```bash
uv run qctool all --openapi ./openapi.yaml --feature login-sso --module AUTH \
                  --base-url https://dev.example.com --token "$TOKEN"
```

Bốn thứ cần đưa, đưa được cái nào hay cái đó:

| Đầu vào | Flag | Có thì được gì |
|---|---|---|
| Tài liệu (`urd.md`, `srs.md`) | `--docs-dir` | Case từ acceptance criteria + NFR |
| OpenAPI spec | `--openapi` | Case kỹ thuật: biên, mã lỗi, ma trận xác thực |
| Link webapp | `--web-url` | Mở Chromium thật: dò element, chạy case UI, chụp bằng chứng |
| Tài khoản / token | `--username` `--password` `--token` | Case cần xác thực chạy được |

### 2. Giao diện web

```bash
uv run qctool serve            # http://127.0.0.1:8080
```

Bí mật nhập trên giao diện **không được lưu lại**. CLI, web UI và CI dùng chung một hàm
`qctool/pipeline.py::run_pipeline()` — không có logic nào chỉ tồn tại trong giao diện.

### 3. Từng chặng, khi cần kiểm soát chi tiết

```bash
uv run qctool ingest   <thư-mục-tài-liệu> --feature login-sso
uv run qctool generate --requirements artifacts/login-sso/requirements.yaml \
                       --openapi ./openapi.yaml \
                       --xlsx artifacts/login-sso/testcases.xlsx
uv run qctool run      artifacts/login-sso/testcases.yaml \
                       --base-url https://dev.example.com --token "$TOKEN" \
                       --xlsx artifacts/login-sso/testcases.xlsx
uv run qctool crawl    https://dev.example.com --out artifacts/login-sso/ui-map.yaml
```

### 4. Thử toàn bộ, không cần hệ thống thật

API giả trong `tests/mock_server.py` có **4 bug API + 4 bug giao diện cài sẵn**, nên một
lượt chạy thấy đủ cả Đạt lẫn Lỗi:

```bash
uv run python -m tests.mock_server --port 8099 &
uv run qctool all --openapi samples/openapi/task-manager-sample.yaml \
                  --feature sample --module SAMPLE \
                  --base-url http://127.0.0.1:8099/api/v1 --token fake
```

Kết quả mong đợi: `54 test · 29 đạt · 15 lỗi · 10 bị chặn`. Hoặc gọn hơn bằng script:

```bash
./qc.sh --config qc-demo.yaml
```

`./qc.sh` là lớp bọc quanh CLI cho người dùng cuối (`--docs --oas --link --acc`), có sẵn
ba cách đưa mật khẩu (gõ thẳng / lấy từ `.env` / hỏi tại chỗ). Chi tiết: `HUONG-DAN.md`.

## Kết quả

Mỗi lượt chạy tạo `artifacts/<feature>/`:

| File | Đọc để biết |
|---|---|
| `runs/<giờ>/report.md` | **Đọc cái này** — tóm tắt, theo module, danh sách lỗi, chưa chạy được, bằng chứng |
| `testcases.xlsx` | Testcase 14 cột, **đã điền kết quả vào sẵn** |
| `runs/<giờ>/junit.xml` | Đưa vào CI |
| `runs/<giờ>/results.csv` | Mở Excel, tự làm pivot |
| `evidence/` | Ảnh chụp + trace của test UI, đặt tên theo mã test |
| `ui-map.yaml` | Webapp có những nút/element gì |

`artifacts/` là output sinh lại được — không sửa tay, không commit.

## Bốn trạng thái, đừng lẫn

| Trạng thái | Nghĩa | Tuyệt đối không dùng khi |
|---|---|---|
| `Pass` | Đã chạy, đúng như mong đợi | Case chưa chạy, còn bước chưa map, hoặc chỉ đạt nhờ chạy lại |
| `Fail` | Đã chạy, **sai** → **sản phẩm có lỗi** | Thiếu môi trường, case chưa map, hoặc lỗi do tool |
| `Blocked` | **Chưa chạy được**: cần tài khoản/dữ liệu/cách map/axe-core | Sản phẩm thật sự trả sai |
| `Not Executed` | Chưa tới lượt (gồm case thủ công) | — |

Trạng thái thứ năm không phải kết quả mà là **dấu vết**: case đạt ở lần chạy lại mang cờ
`flaky`. Nó vẫn tính `Pass` về số liệu nhưng báo cáo nêu riêng ở Mục 6 — một test lúc được
lúc không là vấn đề, không phải bằng chứng chất lượng.

Báo cáo QC chỉ có giá trị khi mỗi con số đều đúng, nên:

- Case cần "tài khoản không có quyền" để kiểm 403 mà chỉ có một tài khoản → `Blocked` kèm
  lý do, **không** `Fail`. Ghi `Fail` là gửi dev đi tìm bug không tồn tại.
- Không nạp được axe-core vì mạng chập → ném `NeedsEnvironment` → `Blocked`. Lỗi của tool
  không phải câu trả lời của sản phẩm.
- Tỉ lệ đạt luôn ghi kèm mẫu số + số test chưa chạy: `Tỉ lệ đạt 66% (29/44) · 10 chưa chạy`.

## Testcase — template 14 cột

`templates/testcase/testcase-template.xlsx` sinh tự động từ
`scripts/build_testcase_template.py`. **Không sửa tay file `.xlsx`** — lần sinh sau sẽ ghi
đè; sửa script rồi chạy lại:

```bash
uv run scripts/build_testcase_template.py
```

- Một dòng = một testcase, không phải một bước. Các bước nằm chung ô `Test Steps`, đánh số.
- ID: `TC_{MODULE}_{NNN}`.
- 10 cột tool sinh (xanh) · 4 cột điền khi chạy (cam): `Actual Result`, `Status`,
  `Environment`, `Executed By / Date`.
- Có dropdown `Pass / Fail / Blocked / Not Executed`, tô màu theo Status, lọc tự động.
- Đổi cấu trúc template là phá vỡ file người dùng đang dùng — phải ghi changelog và báo trước.

## UI/UX test bằng trình duyệt thật

Case UI chạy trên Chromium thật: mỗi testcase một browser context riêng, assert dùng
`expect()` tự chờ thay vì đọc DOM một lần, ưu tiên selector `data-testid`.

Bộ verb UI/UX: `assert.disabled` `assert.enabled` `assert.console_clean`
`assert.no_broken_requests` `assert.focused` `assert.text` `assert.value` `assert.attr`
`assert.count` `assert.checked` `assert.axe` `assert.screenshot`.

```yaml
ui:
  retry: 1              # hỏng thì chạy lại 1 lần, để tách "chập chờn" khỏi "lỗi thật"
  evidence: on-fail     # ảnh chụp khi test hỏng (off | on-fail | always)
  trace: false          # ghi trace từng bước để xem lại
  axe: false            # quét accessibility
  soft_assert: false    # true = sai một bước vẫn chạy hết, thấy mọi lỗi trong 1 lượt
```

Xem lại một case hỏng:

```bash
uv run playwright show-trace artifacts/<feature>/evidence/TC_AUTH_001.trace.zip
```

`auth.mode: manual` nghĩa là **không tự đăng nhập**, kể cả khi `.env` có tài khoản. Chỉ
`browser` mới đăng nhập qua form của IdP.

## Cấu trúc repo

| Đường dẫn | Là gì |
|---|---|
| `qctool/` | Mã nguồn — `ingest/` `generate/` `execute/` `ui/` `report/` `render/` `web/` `pipeline.py` |
| `templates/testcase/` | Template 14 cột — tool ghi ra, sinh từ script |
| `templates/api/` | Template OpenAPI — người điền, tool đọc vào để ground |
| `templates/report/` | Template báo cáo |
| `samples/` | Dữ liệu **hư cấu** để dev/test — không phải hệ thống thật |
| `tests/mock_server.py` | API + trang HTML giả, có bug cài sẵn |
| `docs/` | Brainstorm, findings, tracking |
| `scripts/` | Sinh template, validate OpenAPI |
| `artifacts/` | Output mỗi lần chạy — gitignored |
| `docs/tracking/milestones.md` | Trạng thái M01–M07 |
| `HUONG-DAN.md` | Hướng dẫn cho người dùng cuối |

Nguyên tắc: **OpenAPI là nguồn ground cho API.** Endpoint/field không có trong OpenAPI hoặc
tài liệu thì tool không được bịa — thà bỏ sót còn hơn sinh case gọi endpoint không tồn tại.
Requirement không nêu endpoint thì case sinh ra ở dạng `perform.unmapped` và bị đánh dấu
*chưa map*, không được đoán ra selector hay URL.

## Phát triển

```bash
uv run python -m pytest tests/ -q -m "not playwright"   # nhanh, không cần trình duyệt
uv run python -m pytest tests/ -q                       # đầy đủ, mở Chromium thật
uv run scripts/validate_openapi.py <file.yaml>          # kiểm spec trước khi dùng
```

Góp ý cho coding agent: đọc `AGENTS.md` trước khi sửa — có danh sách lỗi đã gặp thật và
luật sinh ra để chặn chúng tái diễn.

## Giới hạn hiện tại

| Chưa có | Ảnh hưởng |
|---|---|
| Bảng traceability đầy đủ | Mới có cảnh báo requirement thiếu test |
| `.docx` / `.pdf` | Tài liệu phải là markdown |
| Tài khoản thiếu quyền | Case 403/forbidden sẽ `Blocked` |
| UI map nhiều trang | Dò được nhiều trang, chưa bấm sâu vào menu |
| Chạy song song | Chạy lần lượt, bộ test lớn sẽ chậm |
| Upload file / iframe / dialog hệ thống | Chưa có verb cho nhóm này |
| Track LLM | Mọi case hiện đều `generated_by: engine` |

Xem `docs/tracking/todo.md` và `docs/tracking/milestones.md` để biết đang làm gì tiếp.
