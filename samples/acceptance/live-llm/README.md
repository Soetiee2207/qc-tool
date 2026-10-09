> **Đã retire ở V2 (2026-10-09).** Script chạy bộ này (`scripts/run_live_llm_acceptance.py`) và engine
> resolution/exploration nó dùng đã bị gỡ. Giữ thư mục làm lịch sử. Kiểm chứng agent hiện
> tại: `samples/customer_e2e_test_1/` và `docs/findings/agent-redesign.md`.

# Acceptance model thật (chạy thủ công)

Script dùng app hư cấu `tests/mock_server.py`, tự mở server trên port trống và
đóng khi xong. Không chạy trong CI offline. Không cần endpoint sản phẩm thật.

```bash
# Đặt credential qua môi trường hoặc .env gitignored, không ghi vào command history.
export QCTOOL_LLM_MODEL='<model>'
export QCTOOL_LLM_BASE_URL='https://api.openai.com/v1'
# QCTOOL_LLM_API_KEY phải có trong môi trường hoặc .env.
uv run python scripts/run_live_llm_acceptance.py --llm

# Tùy chọn: model phải đề xuất inspection trước khi có UI evidence.
uv run python scripts/run_live_llm_acceptance.py --llm --with-exploration \
  --out artifacts/live-llm-exploration
```

Fixture: `Given Open /; When Click Dự án; Then URL /ui/du-an`.
`Click Dự án` ban đầu là `perform.unmapped`; resolver deterministic không map
câu này. Model phải chọn link `nav-projects` từ evidence. Kỳ vọng URL đã cụ thể
và phải giữ nguyên. Không click nút ghi dữ liệu, không submit form.

Mặc định script kiểm tra plan cố định `/`, thu UI evidence bằng explorer rồi gọi
ResolutionLLM thật. Chế độ `--with-exploration` bắt đầu không có UI evidence,
cho phép loop hiện có gọi ExplorationLLM và chỉ thực thi request qua validator.
Giới hạn 1 cycle mặc định, 3 cycle khi bật exploration; không ép model tạo plan.

Exit code: `0` = validated repair, executable và runner thật Pass; `1` = thất bại
(gồm proposal bị reject/model abstain); `2` = chưa bật LLM hoặc thiếu config.
Thiếu config không gọi model hay browser. Không tự retry HTTP.

Artifact `artifacts/live-llm-acceptance/live-acceptance.json` chứa model/provider,
prompt + SHA256, completion, thời gian/call count, usage nếu provider trả token
counts, testcase/context trước-sau, proposal/validation/application, audit loop
và kết quả runner. Trace/screenshot ở `evidence/`. Khi lỗi, audit vẫn được ghi;
không biến rejected proposal thành testcase, không nới validator để đạt Pass.
API key được che ở lớp cuối trước khi ghi artifact; không log header/body lỗi.
Artifact có prompt/completion nên vẫn cần được xem như dữ liệu test nội bộ.

Test offline của script dùng adapter/observations ghi sẵn; không chứng minh model
thật đã chạy. Chỉ artifact của lệnh thủ công bật LLM mới là bằng chứng live.
