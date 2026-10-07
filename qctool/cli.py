"""CLI của qc-tool.

    uv run qctool serve                       # giao diện web — bấm là chạy
    uv run qctool all --config qctool.yaml    # chạy cả pipeline từ file cấu hình

    uv run qctool ingest   <feature-dir>
    uv run qctool generate [--requirements <file>] [--openapi <file>]
    uv run qctool run      <testcases.yaml> --base-url <url>
    uv run qctool --version
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

from . import __version__, config, execute, generate, ingest, render, report
from .pipeline import PipelineConfig, run_pipeline
from .testcase import Step, StepKind, TestCase


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


def cmd_run(args: argparse.Namespace) -> int:
    """Primary project run, with compatible execution of existing testcase YAML."""
    from .cli_run import cmd_project
    if not args.testcases:
        return cmd_project(args)
    if any(getattr(args, key, None) is not None for key in
           ('docs', 'openapi', 'url', 'config', 'out', 'llm', 'allow_provisioning', 'test_environment')):
        print('LỖI  Không trộn testcase YAML với project flags; dùng một trong hai chế độ.', file=sys.stderr)
        return 2
    return cmd_run_testcases(args)


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
    from .execute.browser import BrowserSession

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
            trace=args.trace, axe=args.axe,
        )
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
                note=s.get("note", ""),
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
        ))
    return cases


def cmd_crawl(args: argparse.Namespace) -> int:
    from .ui import crawl as _crawl

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


def cmd_all(args: argparse.Namespace) -> int:
    """Chạy cả pipeline từ một file cấu hình."""
    if args.config:
        path = Path(args.config)
        if not path.is_file():
            print(f"LỖI  Không tìm thấy file cấu hình: {path}", file=sys.stderr)
            return 2
        cfg = PipelineConfig.from_file(path)
    else:
        env = config.load_config()
        cfg = PipelineConfig(
            docs_dir=Path(args.docs_dir) if args.docs_dir else None,
            openapi=Path(args.openapi) if args.openapi else None,
            feature=args.feature or "feature",
            module=args.module,
            base_url=(args.base_url or "").rstrip("/"),
            web_url=(args.web_url or "").rstrip("/"),
            auth_mode=args.auth_mode or _default_auth_mode(args, env),
            username=args.username or env.username,
            password=args.password or env.password,
            bearer_token=args.token or env.bearer_token,
            skip_run=args.skip_run,
            headless=not args.show_browser,
            llm_enabled=config._flag("QCTOOL_LLM_ENABLED", False),
        )
        _apply_ui_flags(cfg, args)
        if not cfg.docs_dir and not cfg.openapi:
            print("LỖI  Cần --config, hoặc --docs-dir / --openapi", file=sys.stderr)
            return 2

    if getattr(args, "llm", None) is not None:
        cfg.llm_enabled = args.llm

    def on_progress(stage: str, message: str) -> None:
        print(f"  [{stage:<9}] {message}")

    result = run_pipeline(cfg, on_progress=on_progress)
    print()
    if result.error:
        print(f"LỖI  {result.error}", file=sys.stderr)
        return 2
    for key, path in (("requirements", result.requirements_path),
                      ("testcase yaml", result.testcases_path),
                      ("testcase xlsx", result.xlsx_path),
                      ("báo cáo", result.report_path)):
        if path:
            print(f"  {key:<14}: {path}")
    if result.counts:
        return 1 if result.counts.get("Fail") else 0
    return 0


def _apply_ui_flags(cfg: PipelineConfig, args: argparse.Namespace) -> None:
    """Cờ UI từ CLI đè lên cấu hình. `None` = người dùng không nói gì → giữ nguyên."""
    if getattr(args, "ui_retry", None) is not None:
        cfg.ui_retry = max(0, min(int(args.ui_retry), 3))
    if getattr(args, "ui_evidence", None):
        cfg.ui_evidence = args.ui_evidence
    if getattr(args, "ui_trace", None) is not None:
        cfg.ui_trace = bool(args.ui_trace)
    if getattr(args, "ui_axe", None) is not None:
        cfg.ui_axe = bool(args.ui_axe)
    if getattr(args, "soft_assert", None) is not None:
        cfg.soft_assert = bool(args.soft_assert)


def _default_auth_mode(args: argparse.Namespace, env) -> str:
    """Chọn cách xác thực khi người dùng không nói rõ.

    Thứ tự ưu tiên: có web URL + tài khoản ⇒ đăng nhập bằng trình duyệt; có token
    ⇒ dùng token; còn lại ⇒ không xác thực.

    Bài học: trước đây chỉ cần `.env` có `QCTOOL_USERNAME` là chế độ tự đổi thành
    `browser`, và token bị xoá theo — khiến một lượt chạy API thuần báo 32 lỗi
    401 trong khi tài khoản hoàn toàn bình thường. Đoán ý người dùng ở đây nguy
    hiểm hơn là bắt họ nói rõ.
    """
    if args.web_url and env.username:
        return "browser"
    if args.token or env.bearer_token:
        return "token"
    return "manual"


def cmd_serve(args: argparse.Namespace) -> int:
    from .web import serve
    serve(port=args.port, host=args.host, open_browser=not args.no_browser)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="qctool", description="Tự động hoá QC: tài liệu → testcase → thực thi → báo cáo",
    )
    parser.add_argument("--version", action="version", version=f"qc-tool {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    p_ingest = sub.add_parser("ingest", help="Đọc tài liệu feature → requirements.yaml")
    p_ingest.add_argument("feature_dir", help="Thư mục chứa urd.md + srs.md")
    p_ingest.add_argument("--feature", help="Tên feature (mặc định: tên thư mục)")
    p_ingest.add_argument("--out", help="Đường dẫn file ra (mặc định: artifacts/<feature>/requirements.yaml)")
    p_ingest.add_argument("--strict", action="store_true", help="Có cảnh báo thì trả mã lỗi 1")
    p_ingest.set_defaults(func=cmd_ingest)

    p_gen = sub.add_parser("generate", help="Sinh testcase từ requirement và/hoặc OpenAPI")
    p_gen.add_argument("--requirements", help="File requirements.yaml (từ lệnh ingest)")
    p_gen.add_argument("--openapi", help="File OpenAPI spec")
    p_gen.add_argument("--module", help="Ghi đè tên module cho case sinh từ requirement")
    p_gen.add_argument("--out", help="Đường dẫn file testcases.yaml")
    p_gen.add_argument("--xlsx", help="Xuất thêm file Excel theo template team")
    p_gen.add_argument("--created-by", help="Ghi vào cột 'Created By / Date'")
    p_gen.add_argument("--strict", action="store_true",
                       help="Có gap/cảnh báo thì trả mã lỗi 1 (dùng cho CI)")
    p_gen.set_defaults(func=cmd_generate)

    p_run = sub.add_parser("run", help="Docs + OpenAPI + URL → testcase, thực thi và báo cáo",
                           description="Chạy toàn pipeline. Tương thích: run testcases.yaml --base-url URL.",
                           epilog="Advanced YAML-execution flags vẫn hỗ trợ; xem HUONG-DAN.md. UI/auth/fixtures cho project mode cấu hình trong YAML.")
    p_run.add_argument("testcases", nargs="?", help="Tùy chọn: chạy testcase YAML đã có (chế độ cũ)")
    _project_flags(p_run)
    p_run.add_argument("--base-url", help="Địa chỉ API cần test (mặc định: QCTOOL_BASE_URL)")
    p_run.add_argument("--web-url", help="Link webapp — cần khi có bước UI/UX")
    p_run.add_argument("--token", help="Bearer token (mặc định: lấy từ .env)")
    p_run.add_argument("--allow-anonymous", action="store_true",
                       help="Chạy không token — case cần xác thực sẽ báo 401")
    p_run.add_argument("--environment", help="Nhãn môi trường ghi vào báo cáo")
    p_run.add_argument("--xlsx", help="Ghi kết quả ngược vào file testcase này")
    p_run.add_argument("--executed-by", help="Ghi vào cột 'Executed By / Date'")
    p_run.add_argument("--out-dir", help="Thư mục chứa kết quả")
    p_run.add_argument("--show-browser", dest="headless", action="store_false",
                       help="Hiện cửa sổ trình duyệt thay vì chạy ẩn")
    p_run.add_argument("--login", action="store_true",
                       help="Đăng nhập bằng tài khoản trong .env trước khi chạy "
                            "(mặc định: chỉ dùng phiên đã lưu, không tự đăng nhập)")
    p_run.add_argument("--retry", type=int, default=0,
                       help="Số lần chạy lại case hỏng (0–3) — để tách chập chờn khỏi lỗi thật")
    p_run.add_argument("--evidence", choices=["off", "on-fail", "always"],
                       default="on-fail", help="Lưu ảnh bằng chứng (mặc định: khi hỏng)")
    p_run.add_argument("--trace", action="store_true",
                       help="Lưu trace Playwright mỗi case (xem lại từng bước)")
    p_run.add_argument("--axe", action="store_true", help="Bật quét accessibility")
    p_run.add_argument("--soft-assert", action="store_true",
                       help="Bước kiểm tra sai không dừng case — chạy hết để thấy mọi lỗi")
    p_run.add_argument("--timeout", type=int, help="Thời gian chờ mỗi bước (giây)")
    # Compatibility flags stay accepted; primary help exposes the simple project flow.
    compatibility_only = {'token','allow_anonymous','environment','xlsx','executed_by',
                          'out_dir','login','retry','evidence','trace','axe','soft_assert'}
    for action in p_run._actions:
        if action.dest in compatibility_only:
            action.help = argparse.SUPPRESS
    p_run.set_defaults(func=cmd_run)

    p_validate = sub.add_parser("validate", help="Preflight config/docs/OpenAPI, không gọi model/browser/API")
    _project_flags(p_validate)
    p_validate.set_defaults(func=cmd_preflight)

    p_all = sub.add_parser("all", help="Chạy cả pipeline: tài liệu + spec → testcase → chạy → báo cáo")
    p_all.add_argument("--config", help="File cấu hình qctool.yaml (thay cho các tham số dưới)")
    p_all.add_argument("--llm", action=argparse.BooleanOptionalAction, default=None,
                       help="Bật/tắt provider LLM; model/key/base URL/timeout lấy từ QCTOOL_LLM_*")
    p_all.add_argument("--docs-dir", help="Thư mục chứa urd.md + srs.md")
    p_all.add_argument("--openapi", help="File OpenAPI spec")
    p_all.add_argument("--feature", help="Tên feature")
    p_all.add_argument("--module", help="Tên module cho case sinh từ tài liệu")
    p_all.add_argument("--base-url", help="Địa chỉ hệ thống cần test")
    p_all.add_argument("--token", help="Bearer token")
    p_all.add_argument("--web-url", help="Link webapp cần test (dùng trình duyệt thật)")
    p_all.add_argument("--auth-mode", choices=["browser", "token", "manual"],
                       help="Cách xác thực (mặc định: browser nếu .env có tài khoản)")
    p_all.add_argument("--username", help="Tên đăng nhập (mặc định: QCTOOL_USERNAME)")
    p_all.add_argument("--password", help="Mật khẩu (mặc định: QCTOOL_PASSWORD)")
    p_all.add_argument("--skip-run", action="store_true", help="Chỉ sinh testcase, không chạy")
    p_all.add_argument("--show-browser", action="store_true",
                       help="Hiện cửa sổ trình duyệt thay vì chạy ẩn")
    p_all.add_argument("--ui-retry", type=int, default=None,
                       help="Số lần chạy lại case UI hỏng (0–3) — tách chập chờn khỏi lỗi thật")
    p_all.add_argument("--ui-evidence", choices=["off", "on-fail", "always"], default=None,
                       help="Lưu ảnh/trace/log làm bằng chứng (mặc định: khi hỏng)")
    p_all.add_argument("--ui-trace", action="store_true", default=None,
                       help="Lưu trace Playwright để xem lại từng bước")
    p_all.add_argument("--ui-axe", action="store_true", default=None,
                       help="Quét accessibility bằng axe-core")
    p_all.add_argument("--soft-assert", action="store_true", default=None,
                       help="Bước kiểm tra sai không dừng case")
    p_all.set_defaults(func=cmd_all)

    p_crawl = sub.add_parser("crawl", help="Dò element trên webapp → ui-map.yaml")
    p_crawl.add_argument("url", help="Địa chỉ webapp")
    p_crawl.add_argument("--paths", nargs="*", help="Các đường dẫn phụ cần dò thêm")
    p_crawl.add_argument("--wait", type=float, default=2.0, help="Giây chờ trang render (mặc định 2)")
    p_crawl.add_argument("--out", help="Đường dẫn file ra (mặc định artifacts/ui-map.yaml)")
    p_crawl.set_defaults(func=cmd_crawl)

    p_serve = sub.add_parser("serve", help="Mở giao diện web để chạy QC")
    p_serve.add_argument("--port", type=int, default=8080, help="Cổng (mặc định 8080)")
    p_serve.add_argument("--host", default="127.0.0.1", help="Địa chỉ lắng nghe")
    p_serve.add_argument("--no-browser", action="store_true", help="Không tự mở trình duyệt")
    p_serve.set_defaults(func=cmd_serve)

    return parser


def _project_flags(parser):
    parser.add_argument('--docs', '--docs-dir', dest='docs', help='Thư mục URD/SRS/flows')
    parser.add_argument('--openapi', help='File OpenAPI')
    parser.add_argument('--url', help='HTTP(S) URL ứng dụng')
    parser.add_argument('--config', help='YAML config; CLI flags ghi đè các giá trị đã chọn')
    parser.add_argument('--out', help='Thư mục artifacts')
    parser.add_argument('--feature', help='Tên feature/namespace requirement')
    parser.add_argument('--module', help='Module testcase')
    parser.add_argument('--llm', action=argparse.BooleanOptionalAction, default=None,
                        help='Bật/tắt LLM; provider/model/key lấy từ QCTOOL_LLM_*')
    parser.add_argument('--allow-provisioning', action=argparse.BooleanOptionalAction, default=None,
                        help='Opt-in tạo fixture qua reviewed policy; mặc định OFF')
    parser.add_argument('--test-environment', help='Environment cho reviewed provisioning policy')
    parser.add_argument('--skip-run', action='store_true', help='Chỉ generation; không báo Pass')


def cmd_preflight(args):
    from .cli_run import cmd_project
    return cmd_project(args, validate_only=True)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
