"""CLI của qc-tool.

    qctool init <tên>              # tạo projects/<tên>/qctool.yaml
    qctool check <tên>             # kiểm tra cấu hình/tài liệu, không gọi model/browser/API
    qctool run <tên>               # tài liệu → testcase → chạy → báo cáo
    qctool trace <tên> <MÃ_TEST>   # xem lại từng bước của một case
    qctool ui                      # giao diện web
    qctool demo                    # chạy thử trên API giả, không cần hệ thống thật
    qctool step ingest|generate|exec|crawl …   # từng chặng, khi cần kiểm soát chi tiết

<tên> là tên thư mục trong projects/, một thư mục chứa qctool.yaml, hoặc đường dẫn file YAML.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from qctool import __version__, config, execute, generate, ingest, render, report
from qctool.pipeline import PipelineConfig, run_pipeline
from qctool.core.testcase import Step, StepKind, TestCase


def cmd_ingest(args: argparse.Namespace) -> int:
    feature_dir = Path(args.feature_dir).expanduser().resolve()
    if not feature_dir.is_dir():
        print(f"LỖI  Không phải thư mục: {feature_dir}", file=sys.stderr)
        return 2

    feature = args.feature or feature_dir.name
    data = ingest.ingest_feature(feature_dir, feature)

    out = Path(args.out) if args.out else Path("artifacts") / feature / "requirements.yaml"
    ingest.write_yaml(data, out)

    print(ingest.summary(data))
    print()
    print(f"→ {out}")
    return 1 if data["warnings"] and args.strict else 0


def cmd_generate(args: argparse.Namespace) -> int:
    req_path = Path(args.requirements) if args.requirements else None
    api_path = Path(args.openapi) if args.openapi else None

    if not req_path and not api_path:
        print("LỖI  Cần ít nhất một nguồn: --requirements hoặc --openapi", file=sys.stderr)
        return 2
    for label, path in (("--requirements", req_path), ("--openapi", api_path)):
        if path and not path.is_file():
            print(f"LỖI  {label}: không tìm thấy file {path}", file=sys.stderr)
            return 2

    cases, report, meta = generate.generate_all(req_path, api_path, args.module)

    if args.out:
        out = Path(args.out)
    else:
        # `requirements.yaml` → lấy tên thư mục cha (`login-sso`) chứ không lấy
        # stem (`requirements`) — nếu không mọi feature đều ghi vào một chỗ.
        source = req_path or api_path
        stem = source.parent.name if source.stem in {"requirements", "openapi"} else source.stem
        out = Path("artifacts") / stem / "testcases.yaml"
    generate.write_cases(cases, out, meta)

    print(report.text())
    print()
    print(f"→ {out}")

    if args.xlsx:
        xlsx_path = Path(args.xlsx)
        render.render(cases, xlsx_path, created_by=args.created_by or "qc-tool")
        print(f"→ {xlsx_path}   ({len(cases)} dòng, 14 cột)")

    if not report.ok:
        return 1
    return 1 if (report.warnings or report.gaps) and args.strict else 0


def cmd_run_testcases(args: argparse.Namespace) -> int:
    cases_path = Path(args.testcases)
    if not cases_path.is_file():
        print(f"LỖI  Không tìm thấy file testcase: {cases_path}", file=sys.stderr)
        return 2

    cfg = config.load_config()
    web_url = (args.web_url or "").rstrip("/")
    # Mặc định API lấy theo `--base-url`; nếu người dùng chỉ đưa `--web-url` thì
    # dùng chính địa chỉ web đó làm gốc (SPA và API thường cùng tên miền), chứ
    # KHÔNG lấy `QCTOOL_BASE_URL` trong `.env` — bài học từ lượt chạy thật: báo
    # cáo ghi môi trường là portal thật trong khi test đang trỏ vào mock.
    base_url = (args.base_url or web_url or cfg.base_url or "").rstrip("/")
    if not base_url and not web_url:
        print("LỖI  Cần --base-url (hoặc --web-url cho test UI), "
              "hoặc QCTOOL_BASE_URL trong .env", file=sys.stderr)
        return 2
    if args.base_url and web_url and _host(args.base_url) != _host(web_url):
        print(f"LƯU Ý  API và web khác tên miền: {_host(args.base_url)} "
              f"vs {_host(web_url)}")

    token = args.token
    if not token:
        try:
            cfg.validate()
            token = cfg.bearer_token
        except config.ConfigError as exc:
            # Không có credential thì vẫn chạy — case nào cần token sẽ Fail 401,
            # đó là thông tin thật, không phải lỗi của tool.
            print(f"LƯU Ý  {exc}")
            print("       Vẫn chạy tiếp; case cần token sẽ báo 401.")
    token = token or cfg.bearer_token or ("dummy-token-for-local-test" if args.allow_anonymous else None)

    cases = _load_cases(cases_path)
    if not cases:
        print(f"LỖI  Không đọc được testcase nào từ {cases_path}", file=sys.stderr)
        return 2

    session = execute.HttpSession(base_url or web_url, bearer_token=token,
                                  timeout=cfg.timeout_seconds, verify_ssl=cfg.verify_ssl)
    print(f"Chạy {len(cases)} testcase trên {base_url or web_url}")
    print(f"  xác thực: {'có token' if token else 'KHÔNG có token'}")

    browser = None
    if execute.needs_browser(cases):
        if not web_url:
            print("  ⚠ Có bước UI nhưng thiếu --web-url → các bước đó sẽ báo chưa chạy được")
        else:
            browser = _open_browser(web_url, args, cases_path)
            if browser is not None:
                print(f"  trình duyệt: {'ẩn' if args.headless else 'hiện'} · {web_url}")
    print()

    try:
        result = execute.run_cases(
            cases, session, environment=args.environment or web_url or base_url,
            browser=browser, retry=args.retry, soft_assert=args.soft_assert,
        )
    finally:
        if browser is not None:
            browser.close()

    out_dir = Path(args.out_dir) if args.out_dir else cases_path.parent / "runs" / _stamp(result)
    report.write_json(result, out_dir / "results.json")
    report.write_csv(result, out_dir / "results.csv")
    report.write_junit(result, out_dir / "junit.xml")
    report.render_markdown(result, out_dir / "report.md")

    counts = result.counts
    print(f"  Tổng      : {result.total}")
    print(f"  Đạt       : {counts[execute.STATUS_PASS]}")
    print(f"  Lỗi       : {counts[execute.STATUS_FAIL]}")
    print(f"  Bị chặn   : {counts[execute.STATUS_BLOCKED]}")
    print(f"  Chưa chạy : {counts[execute.STATUS_NOT_EXECUTED]}")
    if counts[execute.STATUS_PASS] + counts[execute.STATUS_FAIL]:
        print(f"  Tỉ lệ đạt : {result.pass_rate:.0f}%")
    if result.flaky_cases:
        print(f"  Chập chờn : {len(result.flaky_cases)} "
              f"({', '.join(c.case_id for c in result.flaky_cases[:5])})")
    print()
    print(f"→ {out_dir}/report.md")
    if browser is not None and args.evidence != "off":
        print(f"→ {cases_path.parent}/evidence/   (ảnh, trace, log console, request lỗi)")

    if args.xlsx:
        xlsx_path = Path(args.xlsx)
        updated = render.fill_results(xlsx_path, result,
                                      executed_by=args.executed_by or "qc-tool")
        print(f"→ {xlsx_path}   (đã điền kết quả vào {updated} dòng)")

    return 1 if counts[execute.STATUS_FAIL] else 0


def _open_browser(web_url: str, args: argparse.Namespace, cases_path: Path):
    """Mở BrowserSession cho `qctool run`.

    Chỉ đăng nhập khi người dùng **yêu cầu rõ** (`--login`), hoặc khi đã có phiên
    lưu từ trước. Bài học đã trả giá một lần trong `_default_auth_mode`: chỉ cần
    `.env` có tài khoản mà tự đi đăng nhập là đoán ý người dùng — và lần này nó
    làm hỏng cả lượt chạy UI trên một trang không có form đăng nhập.

    Đăng nhập hỏng **không** làm mất trình duyệt: case UI không cần xác thực vẫn
    chạy bình thường, còn case cần xác thực sẽ báo `Blocked` như đúng nghĩa của nó.
    """
    from qctool.execute.browser import BrowserSession

    state_path = cases_path.parent / ".auth-state.json"
    evidence_dir = None if args.evidence == "off" else cases_path.parent / "evidence"
    env = config.load_config()

    try:
        browser = BrowserSession(
            web_url, headless=args.headless,
            timeout_ms=cfg_timeout(args) * 1000,
            evidence_dir=evidence_dir,
            authenticated=bool(state_path.is_file()),
            storage_state=state_path if state_path.is_file() else None,
            trace=args.trace or args.trace_sensitive, axe=args.axe,
        )
        browser.trace_sensitive = args.trace_sensitive
        if args.trace_sensitive:
            print("  ⚠ --trace-sensitive: trace chứa MẬT KHẨU/TOKEN thật — không chia sẻ/commit")
        browser.start()
    except Exception as exc:                            # noqa: BLE001
        print(f"  ⚠ Không mở được trình duyệt: {type(exc).__name__}: {exc}")
        print("    Case UI sẽ báo «chưa chạy được» chứ không báo lỗi sản phẩm.")
        return None

    if state_path.is_file():
        print(f"  dùng lại phiên đăng nhập đã lưu: {state_path}")

    if args.login:
        if not (env.username and env.password):
            print("  ⚠ --login nhưng .env thiếu QCTOOL_USERNAME/QCTOOL_PASSWORD")
        else:
            try:
                print(f"  {browser.login(env.username, env.password)}")
                browser.save_state(state_path)
            except Exception as exc:                    # noqa: BLE001
                browser.authenticated = False
                print(f"  ⚠ Đăng nhập không thành công: {exc}")
                print("    Vẫn chạy tiếp; case cần xác thực sẽ báo «bị chặn».")
    return browser


def cfg_timeout(args: argparse.Namespace) -> int:
    return int(getattr(args, "timeout", 0) or config.load_config().timeout_seconds)


def _stamp(result) -> str:
    return result.started_at.replace("-", "").replace(":", "").replace(" ", "-")


def _host(url: str) -> str:
    from urllib.parse import urlparse

    return urlparse(url).netloc


def _load_cases(path: Path) -> list[TestCase]:
    """Đọc testcases.yaml → danh sách `TestCase` chạy được."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    cases: list[TestCase] = []
    for raw in data.get("testcases", []):
        steps = []
        for s in raw.get("steps", []):
            steps.append(Step(
                seq=s.get("seq", len(steps) + 1),
                kind=StepKind(s.get("kind", "when")),
                action=s["action"],
                args=s.get("args", {}),
                note=s.get("note", ""), source=s.get("source", {}),
            ))
        provenance = raw.get("provenance", {})
        cases.append(TestCase(
            id=raw["id"],
            module=raw.get("module", ""),
            title=raw.get("title", ""),
            objective=raw.get("objective", ""),
            steps=steps,
            preconditions=list(raw.get("preconditions", [])),
            test_data=dict(raw.get("test_data", {})),
            traces_to=list(raw.get("traces_to", [])),
            source_quote=provenance.get("source_quote", ""),
            source_ref=provenance.get("source_ref", ""),
            generated_by=raw.get("generated_by", "engine"),
            requires=raw.get("requires"),
            execution=raw.get("execution", "auto"),
            generation_status=raw.get("generation_status"), review_reasons=raw.get("review_reasons", []),
            obligation_ids=raw.get("obligation_ids", []), source_intent=raw.get("source_intent", {}),
        ))
    return cases


def cmd_crawl(args: argparse.Namespace) -> int:
    from qctool.ui import crawl as _crawl

    url = args.url.rstrip("/")
    print(f"Đang dò element trên {url} …")
    ui_map = _crawl(url, extra_paths=args.paths or ["/"],
                    wait_ms=args.wait * 1000,
                    on_progress=lambda m: print(f"  {m}"))
    out = Path(args.out) if args.out else Path("artifacts") / "ui-map.yaml"
    ui_map.save(out)
    print()
    print(f"  {len(ui_map.pages)} trang · {len(ui_map.elements)} element")
    for page in ui_map.pages:
        print(f"    {page.url}")
        for element in page.elements[:6]:
            print(f"      [{element.role:<8}] {element.name[:56]}")
        if len(page.elements) > 6:
            print(f"      … và {len(page.elements) - 6} element nữa")
    print()
    print(f"→ {out}")
    return 0


def cmd_serve(args: argparse.Namespace) -> int:
    from qctool.web import serve
    serve(port=args.port, host=args.host, open_browser=not args.no_browser)
    return 0


PROJECTS = Path("projects")

PROJECT_TEMPLATE = """\
# Project QC — đường dẫn tính từ thư mục này. Tài khoản/khoá API chỉ ở .env.
docs: ../../samples/{name}          # thư mục urd.md + srs.md (bỏ nếu chỉ có OpenAPI)
# openapi: ../../samples/{name}/openapi.yaml
web: https://app.example.com         # link webapp (bỏ nếu chỉ test API)
api: https://api.example.com         # địa chỉ API (mặc định = web)
llm: true                            # agent viết case UI từ tài liệu (cần QCTOOL_LLM_* trong .env)

# Bỏ comment nếu cần đăng nhập. Chỉ các AC liệt kê mới được dùng tài khoản
# QCTOOL_USERNAME/QCTOOL_PASSWORD — AC kiểu "sai mật khẩu" thì không liệt kê.
# account:
#   role: customer
#   login_for: [001-1, 001-3]

# Tuỳ chọn khác (đều có mặc định): run.timeout_seconds, ui.evidence (off|on-fail|always),
# ui.trace, ui.retry, ui.axe, generation.budget, auth.mode (browser|token|manual).
"""


def resolve_project(target: str) -> Path:
    """`customer` → projects/customer/qctool.yaml; thư mục → <dir>/qctool.yaml; file giữ nguyên."""
    path = Path(target).expanduser()
    for candidate in (path, path / "qctool.yaml", PROJECTS / target / "qctool.yaml"):
        if candidate.is_file():
            return candidate
    known = sorted(p.parent.name for p in PROJECTS.glob("*/qctool.yaml"))
    hint = f" Có sẵn: {', '.join(known)}." if known else " Tạo mới: qctool init <tên>."
    raise SystemExit(f"LỖI  Không tìm thấy project '{target}'.{hint}")


def _with_project(args: argparse.Namespace) -> argparse.Namespace:
    if getattr(args, "project", None):
        if args.config:
            raise SystemExit("LỖI  Chọn <tên project> hoặc --config, không dùng cả hai.")
        args.config = str(resolve_project(args.project))
    return args


def cmd_run(args: argparse.Namespace) -> int:
    from qctool.cli_run import cmd_project
    return cmd_project(_with_project(args))


def cmd_check(args: argparse.Namespace) -> int:
    from qctool.cli_run import cmd_project
    return cmd_project(_with_project(args), validate_only=True)


def cmd_init(args: argparse.Namespace) -> int:
    path = PROJECTS / args.name / "qctool.yaml"
    if path.exists():
        print(f"LỖI  {path} đã có — sửa trực tiếp file đó.", file=sys.stderr)
        return 2
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(PROJECT_TEMPLATE.format(name=args.name), encoding="utf-8")
    print(f"Đã tạo {path}\n  1. Sửa docs/web/api trong file\n  2. qctool check {args.name}\n  3. qctool run {args.name}")
    return 0


def cmd_trace(args: argparse.Namespace) -> int:
    import subprocess
    cfg = PipelineConfig.from_file(resolve_project(args.project))
    evidence = (cfg.out_dir or Path("artifacts") / cfg.feature) / "evidence"
    traces = sorted(evidence.glob(f"{args.case_id}*.trace.zip"))
    if not traces:
        print(f"LỖI  Không có trace cho {args.case_id} trong {evidence}. "
              "Bật `ui.trace: true` rồi chạy lại; case có mật khẩu cố ý không có trace.", file=sys.stderr)
        return 2
    return subprocess.call([sys.executable, "-m", "playwright", "show-trace", str(traces[-1])])


def cmd_demo(args: argparse.Namespace) -> int:
    import threading
    from tests.mock_server import create_server
    try:
        server = create_server(8099, "/api/v1")
    except OSError:
        print("LỖI  Cổng 8099 đang bận — tắt tiến trình đang dùng cổng đó rồi chạy lại.", file=sys.stderr)
        return 2
    threading.Thread(target=server.serve_forever, daemon=True).start()
    print("API giả chạy ở http://127.0.0.1:8099/api/v1 (4 bug cài sẵn — sẽ thấy cả Đạt lẫn Lỗi)")
    try:
        args.project, args.config = "demo", None
        return cmd_run(args)
    finally:
        server.shutdown()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qctool", description="Tự động hoá QC: tài liệu → testcase → thực thi → báo cáo",
    )
    parser.add_argument("--version", action="version", version=f"qc-tool {__version__}")
    sub = parser.add_subparsers(dest="command", required=True, metavar="<lệnh>")

    p = sub.add_parser("init", help="Tạo project mới: projects/<tên>/qctool.yaml")
    p.add_argument("name", help="Tên project (cũng là tên feature)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("check", help="Kiểm tra project, không gọi model/browser/API")
    _project_flags(p)
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("run", help="Chạy project: tài liệu → testcase → chạy → báo cáo")
    _project_flags(p)
    p.add_argument("--show-browser", dest="headless", action="store_false", help="Hiện cửa sổ trình duyệt")
    p.add_argument("--only", nargs="+", metavar="AC", help="Chỉ sinh case cho các AC này (vd: 001-1 001-3)")
    p.add_argument("--trace-sensitive", action="store_true", default=None,
                   help="Trace cả case có mật khẩu (file chứa bí mật — chỉ dùng cục bộ)")
    p.set_defaults(func=cmd_run)

    p = sub.add_parser("trace", help="Mở trace Playwright của một testcase")
    p.add_argument("project", help="Tên project")
    p.add_argument("case_id", help="Mã testcase, vd TC_CUSTOMER_001")
    p.set_defaults(func=cmd_trace)

    p = sub.add_parser("ui", help="Mở giao diện web")
    p.add_argument("--port", type=int, default=8080, help="Cổng (mặc định 8080)")
    p.add_argument("--host", default="127.0.0.1", help="Địa chỉ lắng nghe")
    p.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    p.set_defaults(func=cmd_serve)

    p = sub.add_parser("demo", help="Chạy thử trên API giả (projects/demo)")
    p.add_argument("--show-browser", dest="headless", action="store_false", help=argparse.SUPPRESS)
    p.set_defaults(func=cmd_demo, config=None, llm=None)

    _step_parsers(sub.add_parser("step", help="Chạy từng chặng (nâng cao)")
                  .add_subparsers(dest="step", required=True, metavar="<chặng>"))
    return parser


def _step_parsers(sub) -> None:
    p_ingest = sub.add_parser("ingest", help="Đọc tài liệu feature → requirements.yaml")
    p_ingest.add_argument("feature_dir", help="Thư mục chứa urd.md + srs.md")
    p_ingest.add_argument("--feature", help="Tên feature (mặc định: tên thư mục)")
    p_ingest.add_argument("--out", help="Đường dẫn file ra (mặc định: artifacts/<feature>/requirements.yaml)")
    p_ingest.add_argument("--strict", action="store_true", help="Có cảnh báo thì trả mã lỗi 1")
    p_ingest.set_defaults(func=cmd_ingest)

    p_gen = sub.add_parser("generate", help="Sinh testcase từ requirement và/hoặc OpenAPI (không gọi LLM)")
    p_gen.add_argument("--requirements", help="File requirements.yaml (từ chặng ingest)")
    p_gen.add_argument("--openapi", help="File OpenAPI spec")
    p_gen.add_argument("--module", help="Ghi đè tên module cho case sinh từ requirement")
    p_gen.add_argument("--out", help="Đường dẫn file testcases.yaml")
    p_gen.add_argument("--xlsx", help="Xuất thêm file Excel theo template team")
    p_gen.add_argument("--created-by", help="Ghi vào cột 'Created By / Date'")
    p_gen.add_argument("--strict", action="store_true",
                       help="Có gap/cảnh báo thì trả mã lỗi 1 (dùng cho CI)")
    p_gen.set_defaults(func=cmd_generate)

    p_exec = sub.add_parser("exec", help="Chạy testcases.yaml đã có")
    p_exec.add_argument("testcases", help="File testcases.yaml")
    p_exec.add_argument("--base-url", help="Địa chỉ API cần test (mặc định: QCTOOL_BASE_URL)")
    p_exec.add_argument("--web-url", help="Link webapp — cần khi có bước UI/UX")
    p_exec.add_argument("--token", help="Bearer token (mặc định: lấy từ .env)")
    p_exec.add_argument("--allow-anonymous", action="store_true",
                        help="Chạy không token — case cần xác thực sẽ báo 401")
    p_exec.add_argument("--environment", help="Nhãn môi trường ghi vào báo cáo")
    p_exec.add_argument("--xlsx", help="Ghi kết quả ngược vào file testcase này")
    p_exec.add_argument("--executed-by", help="Ghi vào cột 'Executed By / Date'")
    p_exec.add_argument("--out-dir", help="Thư mục chứa kết quả")
    p_exec.add_argument("--show-browser", dest="headless", action="store_false",
                        help="Hiện cửa sổ trình duyệt thay vì chạy ẩn")
    p_exec.add_argument("--login", action="store_true",
                        help="Đăng nhập bằng tài khoản trong .env trước khi chạy")
    p_exec.add_argument("--retry", type=int, default=0, help="Số lần chạy lại case hỏng (0–3)")
    p_exec.add_argument("--evidence", choices=["off", "on-fail", "always"], default="on-fail",
                        help="Lưu ảnh bằng chứng (mặc định: khi hỏng)")
    p_exec.add_argument("--trace", action="store_true", help="Lưu trace Playwright mỗi case")
    p_exec.add_argument("--trace-sensitive", action="store_true",
                        help="Trace cả case có mật khẩu (file chứa bí mật — chỉ dùng cục bộ)")
    p_exec.add_argument("--axe", action="store_true", help="Bật quét accessibility")
    p_exec.add_argument("--soft-assert", action="store_true", help="Bước kiểm tra sai không dừng case")
    p_exec.add_argument("--timeout", type=int, help="Thời gian chờ mỗi bước (giây)")
    p_exec.set_defaults(func=cmd_run_testcases)

    p_crawl = sub.add_parser("crawl", help="Dò element trên webapp → ui-map.yaml")
    p_crawl.add_argument("url", help="Địa chỉ webapp")
    p_crawl.add_argument("--paths", nargs="*", help="Các đường dẫn phụ cần dò thêm")
    p_crawl.add_argument("--wait", type=float, default=2.0, help="Giây chờ trang render (mặc định 2)")
    p_crawl.add_argument("--out", help="Đường dẫn file ra (mặc định artifacts/ui-map.yaml)")
    p_crawl.set_defaults(func=cmd_crawl)


def _project_flags(parser):
    parser.add_argument('project', nargs='?', help='Tên project trong projects/, thư mục, hoặc file YAML')
    parser.add_argument('--config', help=argparse.SUPPRESS)
    parser.add_argument('--docs', '--docs-dir', dest='docs', help='Ghi đè thư mục URD/SRS/flows')
    parser.add_argument('--openapi', help='Ghi đè file OpenAPI')
    parser.add_argument('--url', help='Ghi đè link webapp')
    parser.add_argument('--out', help='Thư mục artifacts')
    parser.add_argument('--profile', choices=('agent',), help=argparse.SUPPRESS)
    parser.add_argument('--feature', help=argparse.SUPPRESS)
    parser.add_argument('--module', help=argparse.SUPPRESS)
    parser.add_argument('--llm', action=argparse.BooleanOptionalAction, default=None,
                        help='Bật/tắt LLM (mặc định theo project); model/key lấy từ QCTOOL_LLM_*')
    parser.add_argument('--allow-provisioning', action=argparse.BooleanOptionalAction, default=None,
                        help=argparse.SUPPRESS)
    parser.add_argument('--test-environment', help=argparse.SUPPRESS)
    parser.add_argument('--skip-run', action='store_true', help='Chỉ sinh testcase, không chạy')


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
