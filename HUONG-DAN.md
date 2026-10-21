# qc-tool — hướng dẫn sử dụng

Công cụ tự động hoá QC: đưa **tài liệu** + **OAS** + **link web** + **tài khoản**, nhận lại
**danh sách testcase**, **kết quả chạy**, và **báo cáo**.

---

## Lệnh cần nhớ

```bash
qctool init  salonhub/loyalty         # tạo feature mới (projects/salonhub/loyalty/)
qctool check salonhub                 # kiểm tra mọi feature, không gọi model/browser/API
qctool run   salonhub                 # chạy MỌI feature của project
qctool run   salonhub --auth          # chỉ chạy feature auth (lặp được: --auth --profile)
qctool trace salonhub TC_AUTH_001     # xem lại từng bước của một case
qctool ui                             # trợ lý chat: tải tài liệu + tài khoản, nói muốn test gì → duyệt kế hoạch → chạy
                                      # bảng điều khiển chi tiết (log, agent, kết quả): /console
```

Chạy trong venv của repo (`uv sync` một lần, `source .venv/bin/activate`), hoặc thêm
`uv run` phía trước mỗi lệnh.

---

## Project = một sản phẩm · feature = một phần của nó

```
projects/
  salonhub/                     ← một sản phẩm / một webapp
    project.yaml                ← cấu hình CHUNG: web, api, llm, vai trò tài khoản, timeout…
    auth/                       ← một feature
      urd.md  srs.md  openapi.yaml               ← tài liệu đầu vào
      qctool.yaml               ← cấu hình RIÊNG feature (ghi đè project.yaml)
      artifacts/                ← kết quả lượt chạy gần nhất (xem "Đọc kết quả")
    profile/  services/  …       ← 11 feature phía khách hàng
  demo/task-manager/            ← API giả để thử tool
```

`project.yaml` (dùng chung):

```yaml
web: https://salonhub-soe.vercel.app
api: https://salonhub-3cg8.onrender.com   # bỏ thì dùng `web`
llm: true                                 # agent viết case UI từ tài liệu
account:
  role: customer                          # tài khoản lấy từ .env
```

`<feature>/qctool.yaml` (riêng feature, thường chỉ vài dòng):

```yaml
account:
  login_for: [001-1, 001-3]               # AC cần đăng nhập ĐÚNG tài khoản
```

| Khoá | Mặc định khi bỏ trống |
|---|---|
| Tài liệu / OpenAPI | `urd.md`/`srs.md` và `openapi.yaml` nằm cạnh `qctool.yaml` |
| `feature` / `module` | Tên thư mục feature (`customer` / `CUSTOMER`) |
| Thư mục kết quả | `<feature>/artifacts/` |
| `auth.mode` | `browser` nếu có `account`, ngược lại `manual` |
| `generation.budget` | 14 lượt · 90k token · 480 giây mỗi AC |
| `run.timeout_seconds` | 30 |
| `ui.evidence` / `ui.trace` | `on-fail` / tắt |

**Không cần mở file:** `qctool ui` → **📎 Dữ liệu đầu vào** chỉnh được ảnh bằng chứng/trace/timeout
(mục 1), tick AC *dùng tài khoản thật* + giá trị giả cho từng AC (mục 2, sau khi chọn chức năng), vai trò
tài khoản (mục 3). Khoá nâng cao (`exploration.safe_controls`, `write.deny`…) sửa ở ô *Nâng cao* — YAML
được nạp thử bằng loader của pipeline trước khi lưu, sai thì giữ file cũ.

**Tài khoản** luôn lấy từ `.env` (`QCTOOL_USERNAME`, `QCTOOL_PASSWORD`), không bao giờ ghi
vào YAML. Chỉ AC nằm trong `login_for` mới được dùng tài khoản. AC kiểu *"sai mật khẩu
thì báo lỗi"* thì **không** liệt kê, để tool không điền mật khẩu đúng vào case đó.

Mọi khoá nâng cao (`auth`, `run`, `ui`, `generation`, `provisioning`, `exploration`,
`test_fixtures`) đặt được ở cả hai file; feature thắng project. Muốn cho agent thực hiện
một thao tác ghi cụ thể, khai `exploration.mutation` (rule theo từng nút/API) trong `qctool.yaml` của feature.

Chạy cả project thì mỗi feature chạy lần lượt, kết quả ghi vào **đúng** thư mục feature
đó; cuối cùng in bảng tổng hợp. Mã thoát là mã xấu nhất trong các feature.

---

## Thử ngay không cần hệ thống thật

```bash
qctool demo
```

Tự bật API giả (cổng 8099, có 4 bug cài sẵn) rồi chạy `projects/demo` (feature `task-manager`), nên sẽ thấy cả Đạt lẫn Lỗi.

---

## Cờ hay dùng với `run`

| Cờ | Việc |
|---|---|
| `--no-llm` / `--llm` | Tắt/bật agent, đè cấu hình |
| `--only 001-1 001-3` | Chỉ sinh case cho các AC này (tiết kiệm chi phí khi thử) |
| `--skip-run` | Chỉ sinh testcase, không chạy |
| `--show-browser` | Hiện cửa sổ Chrome thay vì chạy ẩn |
| `--trace-sensitive` | Trace cả case có mật khẩu (⚠ file chứa bí mật) |
| `--write` / `--safe` / `--yes` | Bật/tắt chế độ ghi dữ liệu thật cho lượt này (xem dưới) |
| `--docs` `--openapi` `--url` `--out` | Đè đường dẫn trong cấu hình |

---

## Từng chặng (nâng cao)

```bash
qctool step ingest   <thư-mục-docs> --feature <tên>
qctool step generate --requirements <a>/1-ingest/requirements.yaml \
                     --openapi <spec.yaml> --xlsx <a>/4-render/testcases.xlsx
qctool step exec     <a>/3-generate/testcases.yaml --base-url <url> --xlsx <a>/4-render/testcases.xlsx
# <a> = projects/<project>/<feature>/artifacts
qctool step crawl    <url>     # dò element → ui-map.yaml
```

`step generate` không gọi LLM: OpenAPI → case API; tài liệu → case thủ công. Case UI tự
động từ tài liệu chỉ có qua `qctool run` khi bật LLM.

---

## Test UI/UX bằng trình duyệt thật

Khi có `web`, tool mở Chromium thật: dò element, chạy case UI, chụp bằng chứng. Các nút
chỉnh trong `qctool.yaml`:

```yaml
ui:
  retry: 1              # hỏng thì chạy lại 1 lần, để tách "chập chờn" khỏi "lỗi thật"
  evidence: on-fail     # ảnh chụp: off | on-fail | always
  trace: true           # ghi trace từng bước để xem lại
  axe: false            # quét accessibility
  soft_assert: false    # true = sai một bước vẫn chạy hết, thấy mọi lỗi trong 1 lượt
```

**Nút "Chạy" bị khoá có đúng không, lỗi JS có hiện ra không, con trỏ có nằm đúng ô
không**: test API không thấy được những thứ này. Bộ verb UI/UX kiểm được:
`assert.disabled`, `assert.enabled`, `assert.console_clean`, `assert.no_broken_requests`,
`assert.focused`, `assert.text`, `assert.value`, `assert.attr`, `assert.count`,
`assert.checked`, `assert.axe`, `assert.screenshot`.

Xem lại một case: `qctool trace salonhub TC_AUTH_001`.

---

## Đọc kết quả

Mỗi lượt chạy ghi vào `projects/<project>/<feature>/artifacts/`, chia theo bước. Bước nào
sinh ra gì thì nằm trong thư mục của bước đó:

```
artifacts/
  run.json          ← ĐỌC ĐẦU TIÊN: bước nào xong/đang chạy/bị bỏ qua/LỖI, file nào sinh ra
  events.jsonl      ← dòng thời gian: mỗi dòng {t, stage, level, message}
  pipeline.log      ← log đầy đủ (đã che mật khẩu/token)
  summary.json      ← số liệu + đường dẫn file chính
  1-ingest/    requirements.yaml               (requirement đọc được từ tài liệu)
  2-crawl/     app-model.yaml                  (trang/element agent đã thấy, macro đăng nhập)
  3-generate/  generation.json  testcases.yaml (agent gọi tool nào, lỗi gate/dry-run, token)
  4-render/    testcases.xlsx                  (14 cột, đã điền kết quả sau khi chạy)
  5-execute/   results.json  results.csv  junit.xml  evidence/   (từng bước, ảnh, trace)
  6-report/    report.md                       (báo cáo cho người đọc)
```

Mỗi thư mục bước có `stage.log` — log riêng của bước đó. **Bước bị lỗi có thêm `error.log`**
(thông báo + traceback), và `run.json` trỏ thẳng tới nó:

```json
"status": "failed",
"error": {"stage": "generate", "message": "…", "log": "3-generate/error.log"}
```

| Muốn biết | Mở |
|---|---|
| Tool đang ở bước nào / dừng ở đâu | `run.json` → `current_stage`, `stages.<bước>.status` |
| Vì sao hỏng | `run.json` → `error.log` → `<bước>/stage.log` |
| Kết quả cho người đọc | `6-report/report.md` |
| Một case UI chạy ra sao | `5-execute/results.json`, `5-execute/evidence/<MÃ>-*.png`, `qctool trace` |
| Agent đã làm gì | `3-generate/generation.json` → `agent_history` |

Lượt chạy mới **ghi đè** lượt trước, trừ `2-crawl/app-model.yaml` và phiên đăng nhập đã lưu
(giữ lại để agent không phải dò và đăng nhập lại từ đầu). Muốn giữ một lượt chạy thì
chép thư mục `artifacts/` ra chỗ khác trước khi chạy lại.

---

## Chế độ ghi dữ liệu (`--write`)

Mặc định tool chạy **safe**: chỉ đọc. Các AC tạo/sửa/xoá dữ liệu (đặt hàng, đặt lịch, thêm địa
chỉ, đăng ký, xoá giỏ…) thành case thủ công. Muốn chạy tự động cả những AC đó:

```bash
qctool run salonhub --cart_checkout --write        # bật cho một lượt, hỏi xác nhận
qctool run salonhub --write --yes                  # CI: bỏ qua câu hỏi
qctool run salonhub --safe                         # ép chỉ đọc dù config đặt mode: write
```

hoặc đặt trong `project.yaml` / `<feature>/qctool.yaml`:

```yaml
mode: write              # safe (mặc định) | write
write:
  deny:                  # vẫn chặn kể cả khi mode: write
    - PUT /api/auth/change-password
```

Khi chế độ ghi bật:
- Agent được bấm nút tạo/sửa/xoá và gọi POST/PUT/PATCH/DELETE tới **chính** web/api đã khai.
  Request tới domain khác và mục trong `write.deny` vẫn bị chặn.
- Dry-run của agent **dừng ngay trước request ghi đầu tiên** (không gửi đi), nên runner ghi **đúng
  một lần**. Case đó mang nhãn `needs_review` (`WRITE_NOT_DRY_RUN`) vì các bước sau chưa được thử trước.
- `ui.retry` bị ép về 0 (chạy lại = ghi thêm lần nữa).
- `run.json`, `report.md`, `summary/<ngày_giờ>/summary.md` ghi rõ **Chế độ GHI**.
- Không có TTY mà thiếu `--yes` → tool từ chối chạy (mã 2).

⚠ Dữ liệu tạo ra **không tự dọn**. AC cần dữ liệu duy nhất (đăng ký email mới) sẽ báo 409 ở lần chạy sau.

Các tuỳ chọn liên quan trong `exploration`:
- `safe_paths: [/register]`: trang có tên trông rủi ro nhưng chỉ đọc, mở được ở chế độ safe.
- `safe_controls: [<data-testid>]`: control có nhãn trông rủi ro (Đăng ký, Đăng xuất) nhưng đã
  review là chỉ điều hướng/validate. Chế độ safe vẫn chặn request ghi mà chúng gây ra.
- `background_paths` (mặc định `["/socket.io/"]`): request nền của framework, bị chặn lặng lẽ thay
  vì làm hỏng cú click đang thử.

Ô mật khẩu chỉ nhận fixture alias. Giá trị giả cho case âm tính (sai mật khẩu, mật khẩu ngắn) khai ở
`account.test_values: {"001-3": {password: "SaiMatKhau123"}}` → fixture `ac_001_3.password`.

---

## Báo cáo tổng hợp các lần chạy

Mỗi lượt `qctool run <project>` (cả project hoặc `--<feature>`) ghi thêm một báo cáo tổng hợp,
đặt tên theo ngày giờ bắt đầu chạy (GMT+7):

```
projects/salonhub/summary/
  README.md                       ← lịch sử: mọi lượt chạy, mới nhất lên đầu
  2026-10-10_14-30-05/
    summary.md                    ← số liệu · theo feature · Fail · Bị chặn · TOÀN BỘ testcase
    testcases.csv  summary.json   ← cùng dữ liệu, cho Excel / máy đọc
    auth/  profile/  …            ← bản sao report, results, testcases.xlsx, log, evidence của lượt đó
```

Artifacts trong feature bị ghi đè mỗi lượt; `summary/<ngày_giờ>/` thì giữ nguyên, nên đây là
chỗ xem lại các lần chạy cũ. Feature không chạy được (lỗi cấu hình) được ghi rõ là không
chạy — kết quả cũ còn sót trong `artifacts/` của nó không bị tính vào lượt mới.
`summary/` chứa evidence/log nên đã được gitignore — không commit, không chia sẻ công khai.
`qctool check` không tạo báo cáo.

---

## Bốn trạng thái, đừng lẫn

| | Nghĩa | Việc cần làm |
|---|---|---|
| **Đạt** | Chạy xong, đúng | — |
| **Lỗi** | Chạy xong, **sai** → **sản phẩm có bug** | Báo dev |
| **Bị chặn** | **Chưa chạy được**: thiếu dữ liệu/tài khoản/case chưa map | Bổ sung môi trường. **Không phải bug** |
| **Chưa chạy** | Case thủ công, người phải làm theo các bước trong file | Đọc cột Test Steps rồi làm |

Thêm một thứ không phải trạng thái mà là **cảnh báo**: test **chập chờn** (lần đầu hỏng,
chạy lại mới đạt). Nó nằm ở Mục 6 của báo cáo. Đừng bỏ qua: một test lúc được lúc không
là bug, chỉ là chưa biết bug của sản phẩm hay của test.

Nếu bạn thấy `Lỗi` mà nguyên nhân là "thiếu tài khoản" thì đó là **bug của tool**, báo ngay.

---

## Tài liệu và OAS — mỗi thứ dùng để làm gì

**Tài liệu (URD/SRS markdown)** là nguồn chính cho test giao diện. Agent đọc từng
acceptance criterion (Given/When/Then), tự mở website, tìm nút/ô bằng `data-testid`
hoặc role + tên, viết testcase rồi chạy thử. Kết quả mong đợi **phải trích nguyên văn**
tài liệu; agent không được lấy theo những gì website đang hiển thị. Câu mơ hồ
(*"sidebar chỉ hiện module tôi được phép"*) không có giá trị cụ thể để trích, nên case
thành `needs_review` hoặc thủ công, không bao giờ tự thành Đạt.

**OAS** cho phép: (1) sinh thẳng case API (giá trị biên, mã lỗi, ma trận xác thực) không
cần LLM; (2) agent kiểm response API sau một thao tác UI (ví dụ POST login trả 200).

> Lấy spec từ FastAPI:
> ```bash
> python -c "import json,app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json
> ```

---

## LLM (agent) cho generation

Agent dùng Chat Completions tương thích OpenAI có **tool calling**
(`<base URL>/chat/completions`), đã kiểm với DeepSeek. Cấu hình một lần trong `.env`:

```bash
QCTOOL_LLM_BASE_URL=https://api.deepseek.com/v1
QCTOOL_LLM_MODEL=deepseek-chat
QCTOOL_LLM_API_KEY=…
QCTOOL_LLM_TIMEOUT_SECONDS=90
QCTOOL_LLM_THINKING=disabled      # DeepSeek: tool calling không reasoning
```

Bật bằng `llm: true` trong project hoặc `--llm`; `--no-llm` tắt kể cả khi config đã bật.
Chỉ có API key thì **không** tự bật LLM.

Mỗi call thử lại **đúng một lần** khi timeout/429/5xx. Lỗi được báo có kiểm soát, không
ghi API key/nội dung phản hồi. Model không sửa testcase trực tiếp: mọi bản nháp phải qua
gate (schema, an toàn, trích dẫn, thứ tự bước) và dry-run trên trình duyệt. Không có LLM
thì case từ tài liệu ở dạng thủ công; case OpenAPI vẫn sinh bình thường.

Agent quan sát ARIA → viết case có source quote → thử action/locator trên context riêng →
nhận lỗi để sửa trong cùng hội thoại. Dry-run **chưa** là Pass: runner mới kiểm expected.

- `ready`: gate + dry-run đủ, expected literal có nguồn.
- `needs_review`: oracle yếu/nonliteral/critic nghi ngờ; vẫn chạy, có nhãn trong report
  và Description. QC ghi quyết định tại sheet Review; 14 cột Test Cases không đổi.
- `manual` / `blocked_env`: chưa chấp nhận chạy tự động; xem `generation.json`.

Budget áp dụng **mỗi AC**, cộng thêm một call thiết kế intent. Timeout/call lỗi vẫn tốn
chi phí nếu provider đã xử lý. Dùng `--only` hoặc `generation.max_intents: 1` khi thử.
Coverage vẫn hiển thị toàn bộ nguồn: chạy một phần không có nghĩa toàn bộ tài liệu đã covered.

### Xem lại agent và Playwright đã làm gì

| Muốn xem | Mở |
|---|---|
| Agent gọi tool nào, lỗi gì, tốn bao nhiêu token | `3-generate/generation.json` → `agent_history[i].history`, `provider_attempts` |
| Các bước của testcase | `3-generate/testcases.yaml` hoặc `4-render/testcases.xlsx` |
| Playwright chạy từng bước ra sao | `5-execute/results.json`, `6-report/report.md` |
| Xem lại trực quan (DOM, mạng, console) | `qctool trace <tên> <MÃ>` |

Case có điền mật khẩu hoặc bắt request đăng nhập **không** có trace/ảnh. Tool tắt có chủ ý
để file không chứa mật khẩu/token; kết quả từng bước vẫn có trong `results.json`. Muốn
xem cả bước đăng nhập: `qctool run <tên> --trace-sensitive` (hoặc `ui.trace_sensitive: true`).
⚠ Khi đó `.trace.zip` chứa mật khẩu/token thật: chỉ dùng tài khoản test, xem trên máy
mình, xoá `5-execute/evidence/` sau khi xem, không chia sẻ/commit.

---

## Giới hạn hiện tại

| Chưa có | Ảnh hưởng |
|---|---|
| **Bảng traceability** | Có cảnh báo requirement thiếu test, chưa có bảng đầy đủ |
| **Hỗ trợ `.docx`/`.pdf`** | Tài liệu phải là markdown |
| **Tài khoản thiếu quyền** | Case kiểm 403/forbidden sẽ `Bị chặn` |
| **UI map nhiều trang** | Dò được nhiều trang, nhưng chưa bấm sâu vào menu để dò hết |
| **Chạy song song** | Chạy lần lượt, bộ test lớn sẽ chậm |
| **Upload file / iframe / dialog hệ thống** | Chưa có verb cho nhóm này |

---

## Khi có trục trặc

| Hiện tượng | Xử lý |
|---|---|
| Nhiều `Lỗi` với `401` | Phiên hết hạn: xoá `<feature>/artifacts/2-crawl/.auth-state.json` rồi chạy lại |
| Nhiều `Lỗi` với `404` | Sai `api`: thử thêm/bớt `/api/v1` |
| Crawl ra 0 element | Mạng chậm: thử lại; nếu vẫn vậy kiểm tra đăng nhập |
| Nhiều `Bị chặn` | Thiếu OAS: đây là lý do phổ biến nhất |
| Sai mật khẩu | Sửa `.env` |
| Case UI báo `Lỗi` vì không tìm thấy element | Nhãn trên trang đã đổi. Chạy `qctool step crawl <url>` rồi sinh lại testcase |
| Case a11y báo `Bị chặn` với "axe-core" | Máy không ra được Internet: chép `axe.min.js` vào `qctool/execute/` hoặc đặt `QCTOOL_AXE_PATH` |
| Báo cáo có mục "Test chập chờn" | Đọc Mục 6 và 7: trace + ảnh nằm trong `evidence/`, mở bằng `qctool trace` |
| Tool tự đăng nhập dù không muốn | Đặt `auth: {mode: manual}` trong `qctool.yaml`. Chế độ này không bao giờ tự đăng nhập |
| Đăng nhập hỏng nhưng vẫn muốn chạy case UI khác | Cứ chạy: case cần xác thực báo `Bị chặn`, case còn lại vẫn chạy |
| `Cổng 8099 đang bận` khi `qctool demo` | Tắt mock server cũ đang chạy |

Ví dụ đầy đủ: `projects/salonhub/` — 11 feature phía khách hàng viết từ source SalonHub; AC ghi dữ liệu
thật được đánh dấu **⚠ GHI DỮ LIỆU THẬT** và để thủ công.
