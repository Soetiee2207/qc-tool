# qc-tool — hướng dẫn sử dụng

Công cụ tự động hoá QC: đưa **tài liệu** + **OAS** + **link web** + **tài khoản**, nhận lại
**danh sách testcase**, **kết quả chạy**, và **báo cáo**.

---

## Bốn đầu vào

```bash
./qc.sh --docs <thư-mục> --oas <file> --link <url> --acc <email> [mật-khẩu]
```

| Flag | Là gì | Bắt buộc? |
|---|---|---|
| `--docs` | Thư mục chứa `urd.md`, `srs.md` | Một trong hai |
| `--oas` | File OpenAPI spec (`.yaml`/`.json`) | Một trong hai |
| `--link` | Link webapp cần test | Nên có |
| `--acc` | Tài khoản đăng nhập | Nếu app cần đăng nhập |

Đưa được flag nào hay flag đó. Thiếu cái nào tool cũng nói rõ hệ quả.

---

## Chạy đầy đủ

```bash
cd /home/hendry/workspace/zcoding/qc-tool

./qc.sh \
  --docs /home/hendry/workspace/data-platform/data-management/vd-data-platform-portal/docs/authentication/login-sso \
  --oas ./openapi.json \
  --link https://dev-qc-portal.datafactory.fit \
  --acc v.binhhm1@vindynamics.net 'Abcd1234@'
```

Tên feature tự suy từ tên thư mục `--docs` (`login-sso`). Muốn đặt khác thì thêm `--feature <tên>`.

---

## Ba cách đưa mật khẩu

| Cách | Lệnh | Khi nào dùng |
|---|---|---|
| **Gõ thẳng** | `--acc user@x.com 'mật-khẩu'` | Tiện, nhưng mật khẩu nằm trong lịch sử shell |
| **Lấy từ `.env`** | `--acc user@x.com` | Chạy lặp lại nhiều lần |
| **Hỏi tại chỗ** | `--acc user@x.com -` | Máy dùng chung — không lưu vết |

Script đặt mật khẩu vào **biến môi trường** của tiến trình con, không truyền qua tham số
dòng lệnh — vì tham số dòng lệnh hiện trong `ps` cho mọi user trên máy đọc được.

---

## Thử ngay không cần hệ thống thật

```bash
./qc.sh --config qc-demo.yaml
```

Chạy trên API giả có 4 bug cài sẵn — thấy đủ cả Đạt lẫn Lỗi.

---

## Chạy lặp lại nhiều lần

Nếu ngày nào cũng chạy cùng một bộ đầu vào, ghi vào `qc.yaml` rồi gọi một lệnh:

```bash
./qc.sh --config qc.yaml
```

Flags và config dùng chung một đường đi — cái nào cũng được.

---

## Tuỳ chọn khác

| Flag | Việc |
|---|---|
| `--api <url>` | Địa chỉ API, nếu khác `--link` |
| `--feature <tên>` | Đặt tên feature (mặc định suy từ `--docs`) |
| `--module <tên>` | Module cho case sinh từ tài liệu |
| `--show-browser` | Hiện cửa sổ Chrome thay vì chạy ẩn |
| `--skip-run` | Chỉ sinh testcase, không chạy |
| `-h, --help` | Hướng dẫn đầy đủ |

---

## Test UI/UX bằng trình duyệt thật

Khi có `--link`, tool mở Chromium thật: dò element, chạy case UI, chụp bằng chứng.
Phần này không bật gì thêm cũng chạy, nhưng có mấy nút đáng biết — ghi trong `qc.yaml`:

```yaml
ui:
  retry: 1              # hỏng thì chạy lại 1 lần, để tách "chập chờn" khỏi "lỗi thật"
  evidence: on-fail     # ảnh chụp khi test hỏng (off | on-fail | always)
  trace: false          # ghi trace từng bước để xem lại
  axe: false            # quét accessibility
  soft_assert: false    # true = sai một bước vẫn chạy hết, thấy mọi lỗi trong 1 lượt
```

Hoặc dùng cờ dòng lệnh, ví dụ:

```bash
uv run qctool run artifacts/login-sso/testcases.yaml \
  --web-url https://dev-qc-portal.datafactory.fit \
  --retry 1 --evidence always --show-browser
```

**Nút "Chạy" bị khoá có đúng không, lỗi JS có hiện ra không, con trỏ có nằm đúng ô
không** — đó là những thứ test API không thấy được. Bộ verb UI/UX kiểm được:
`assert.disabled`, `assert.enabled`, `assert.console_clean`, `assert.no_broken_requests`,
`assert.focused`, `assert.text`, `assert.value`, `assert.attr`, `assert.count`,
`assert.checked`, `assert.axe`, `assert.screenshot`.

Xem lại một case hỏng:

```bash
uv run playwright show-trace artifacts/<feature>/evidence/TC_AUTH_001.trace.zip
```

---

## Đọc kết quả

Sau mỗi lần chạy, trong `artifacts/<feature>/`:

| File | Đọc để biết |
|---|---|
| `runs/<giờ>/report.md` | **Đọc cái này** — tóm tắt, chi tiết theo module, danh sách lỗi, chưa chạy được, bằng chứng |
| `testcases.xlsx` | File testcase 14 cột — **đã điền kết quả vào sẵn** |
| `runs/<giờ>/junit.xml` | Đưa vào CI |
| `runs/<giờ>/results.csv` | Mở Excel, tự làm pivot |
| `evidence/` | Ảnh chụp + trace của test UI, đặt tên theo mã test |
| `ui-map.yaml` | Webapp có những nút/element gì |

Script in sẵn đường dẫn báo cáo ở cuối mỗi lần chạy.

---

## Bốn trạng thái, đừng lẫn

| | Nghĩa | Việc cần làm |
|---|---|---|
| **Đạt** | Chạy xong, đúng | — |
| **Lỗi** | Chạy xong, **sai** → **sản phẩm có bug** | Báo dev |
| **Bị chặn** | **Chưa chạy được** — thiếu dữ liệu/tài khoản/case chưa map | Bổ sung môi trường. **Không phải bug** |
| **Chưa chạy** | Case thủ công, người phải làm theo các bước trong file | Đọc cột Test Steps rồi làm |

Thêm một thứ nữa không phải trạng thái mà là **cảnh báo**: test **chập chờn** (lần
đầu hỏng, chạy lại mới đạt). Nó nằm ở Mục 6 của báo cáo. Đừng bỏ qua — một test lúc
được lúc không là bug, chỉ khác là chưa biết bug của sản phẩm hay của test.

Nếu bạn thấy `Lỗi` mà nguyên nhân là "thiếu tài khoản" — đó là **bug của tool**, báo ngay.

---

## Vì sao OAS là đầu vào quan trọng nhất

Không có nó, case sinh từ tài liệu phải **map** sang hành động cụ thể mới chạy được.
Mà tài liệu viết *"sidebar chỉ hiện module tôi được phép"* — câu đó nói cần kiểm gì,
không nói element nào. Tool giữ nguyên và đánh dấu *chưa map*, rồi báo `Bị chặn`.

Có OAS thì tool sinh thẳng case chạy được: giá trị biên, mã lỗi, ma trận xác thực.

> Lấy spec từ FastAPI:
> ```bash
> python -c "import json,app.main; print(json.dumps(app.main.app.openapi()))" > openapi.json
> ```

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
| Nhiều `Lỗi` với `401` | Phiên hết hạn — xoá `artifacts/<feature>/.auth-state.json` rồi chạy lại |
| Nhiều `Lỗi` với `404` | Sai `--api` — thử thêm/bớt `/api/v1` |
| Crawl ra 0 element | Mạng chậm — thử lại; nếu vẫn vậy kiểm tra đăng nhập |
| Nhiều `Bị chặn` | Thiếu OAS — đây là lý do phổ biến nhất |
| Sai mật khẩu | Sửa `.env`, hoặc truyền lại qua `--acc` |
| Case UI báo `Lỗi` vì không tìm thấy element | Nhãn trên trang đã đổi. Chạy lại `uv run qctool crawl <url>` rồi sinh lại testcase |
| Case a11y báo `Bị chặn` với "axe-core" | Máy không ra được Internet — chép `axe.min.js` vào `qctool/execute/` hoặc đặt `QCTOOL_AXE_PATH` |
| Báo cáo có mục "Test chập chờn" | Đọc Mục 6 và 7: trace + ảnh nằm trong `evidence/`, mở bằng `playwright show-trace` |
| Tool tự đăng nhập dù không muốn | Đặt `auth.mode: manual` trong `qc.yaml` — chế độ này không bao giờ tự đăng nhập |
| Đăng nhập hỏng nhưng vẫn muốn chạy case UI khác | Cứ chạy: case cần xác thực báo `Bị chặn`, case còn lại vẫn chạy |

