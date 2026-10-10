"""Product CLI facade: safe live progress, preflight and factual summary.

No mapping/resolution/exploration/execution logic lives here. Legacy commands keep
existing exit behavior. Resolution blockers never become runner Fail/Blocked.
"""
from contextlib import redirect_stdout, redirect_stderr
from dataclasses import dataclass, field
from io import StringIO
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlsplit

import yaml

from qctool import config, ingest, pipeline
from qctool.core.coverage import CoverageStatus
from qctool.core.executability import analyze_executability
from qctool.generate.loader import load_endpoints


class PreflightError(ValueError):
    pass


@dataclass
class Preflight:
    config: pipeline.PipelineConfig = field(repr=False)
    requirements: int = 0
    operations: int = 0
    warnings: int = 0
    adapter: object = field(default=None, repr=False)


def _mapping_file(path):
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8'))
    except (OSError, UnicodeError, yaml.YAMLError):
        raise PreflightError('Không đọc được YAML đầu vào; kiểm tra đường dẫn và cú pháp.') from None
    if not isinstance(data, dict):
        raise PreflightError('File cấu hình phải là YAML mapping.')
    return data


def preflight(args, *, require_target=True):
    """Read trusted sources/config with existing loaders; no HTTP/browser/model call."""
    data = {}
    if args.config:
        path = Path(args.config).expanduser()
        data = _mapping_file(path)
        for key in ('run','auth','out','ui','llm','provisioning','generation'):
            if key in data and not isinstance(data[key], dict):
                raise PreflightError('Các section cấu hình phải là YAML mappings.')
        for section, keys in {'llm':['enabled'], 'provisioning':['enabled'],
                              'run':['verify_ssl'], 'out':['skip_run','headless'],
                              'ui':['trace','trace_sensitive','axe','soft_assert']}.items():
            if any(k in data.get(section,{}) and type(data[section][k]) is not bool for k in keys):
                raise PreflightError('Cờ bật/tắt cấu hình phải là boolean true/false.')
        try:
            cfg = pipeline.PipelineConfig.from_file(path)
        except Exception:
            raise PreflightError('Cấu hình không hợp lệ; kiểm tra schema, fixture aliases và env.') from None
        # New facade defaults anonymous/manual; env credentials do not authorize login.
        if 'mode' not in data.get('auth', {}):
            cfg.auth_mode = 'manual'
    else:
        env = config.load_config()
        cfg = pipeline.PipelineConfig(llm_enabled=config._flag('QCTOOL_LLM_ENABLED', False),
            username=env.username, password=env.password, bearer_token=env.bearer_token)
    cfg.generation_profile = getattr(args, 'profile', None) or data.get('generation', {}).get('profile', 'agent')
    if cfg.generation_profile not in {'agent', 'business', 'legacy'}:
        raise PreflightError('generation.profile cần agent; business/legacy là alias đã deprecated.')
    for arg, attr in [('docs','docs_dir'),('openapi','openapi'),('out','out_dir')]:
        if value := getattr(args,arg,None):
            setattr(cfg,attr,Path(value).expanduser().resolve())
    if getattr(args,'url',None):
        cfg.web_url = args.url.rstrip('/')
        if not cfg.base_url:
            cfg.base_url = cfg.web_url
    for arg,attr in [('base_url','base_url'),('web_url','web_url'),('feature','feature'),
                     ('module','module'),('test_environment','data_environment')]:
        if value := getattr(args,arg,None):
            setattr(cfg,attr,value)
    for arg,attr in [('llm','llm_enabled'),('allow_provisioning','allow_provisioning'),('timeout','timeout_seconds')]:
        value = getattr(args,arg,None)
        if value is not None:
            setattr(cfg,attr,value)
    if getattr(args,'skip_run',False):
        cfg.skip_run = True
    if getattr(args,'headless',True) is False:
        cfg.headless = False
    if not cfg.docs_dir and not cfg.openapi:
        raise PreflightError('Cần --docs, --openapi hoặc --config có nguồn đầu vào.')
    for value in (cfg.web_url,cfg.base_url):
        if not value:
            continue
        try:
            url = urlsplit(value)
            valid = url.scheme in ('http','https') and bool(url.hostname) and not (
                url.username or url.password or url.query or url.fragment)
            _ = url.port
        except ValueError:
            valid = False
        if not valid:
            raise PreflightError('URL cần http(s), không chứa credentials, query hoặc fragment.')
    if require_target and not cfg.skip_run and not (cfg.base_url or cfg.web_url):
        raise PreflightError('Cần --url hoặc run.base_url/web_url; dùng out.skip_run để chỉ sinh.')
    if cfg.auth_mode not in {'manual','browser','token','password'}:
        raise PreflightError('auth.mode không được hỗ trợ.')
    if cfg.timeout_seconds <= 0:
        raise PreflightError('Timeout phải lớn hơn 0.')
    if cfg.allow_provisioning and (not isinstance(cfg.data_environment,str) or not cfg.data_environment.strip()):
        raise PreflightError('Provisioning cần environment tường minh và reviewed fixture policy.')
    checked = Preflight(cfg)
    if cfg.docs_dir:
        try:
            document = ingest.ingest_feature(cfg.docs_dir,cfg.feature)
        except Exception:
            raise PreflightError('Không đọc được docs; cần urd.md/srs.md trong thư mục đã chọn.') from None
        checked.requirements = len(document.get('requirements', []))
        checked.warnings += len(document.get('warnings', []))
        if not checked.requirements and not any(document.get('flows',{}).values()):
            raise PreflightError('Docs không có requirement/flow được hỗ trợ; kiểm tra định dạng tài liệu.')
    if cfg.openapi:
        try:
            operations,warnings,_ = load_endpoints(cfg.openapi)
        except Exception:
            raise PreflightError('OpenAPI không đọc được; kiểm tra paths, responses và $ref được hỗ trợ.') from None
        checked.operations = len(operations)
        checked.warnings += len(warnings)
    if cfg.llm_enabled:
        try:
            checked.adapter = pipeline.load_llm_provider()
        except Exception:
            raise PreflightError('LLM bật nhưng cấu hình không hợp lệ; cần QCTOOL_LLM_MODEL/API_KEY và provider URL.') from None
    return checked


_ACTIONS = {
    'MISSING_FIXTURE':'Điền env cho fixture aliases đã khai báo trong test_fixtures.',
    'MISSING_TEST_DATA':'Cung cấp fixture phù hợp và bằng chứng cho required facts.',
    'UNVERIFIED_TEST_DATA':'Thêm reviewed verification rule hoặc bằng chứng trạng thái hợp lệ.',
    'INVALID_TEST_DATA':'Kiểm tra tài khoản/dữ liệu hiện có; không thay đổi expected outcome.',
    'UNSAFE_TO_VERIFY':'Cung cấp phương thức verification được policy cho phép.',
    'UNSAFE_TO_PROVISION':'Cung cấp dữ liệu sẵn có hoặc reviewed provisioning rule trong test environment.',
    'PROVISIONABLE':'Cung cấp fixture sẵn có hoặc bật provisioning với reviewed test-environment policy.',
    'NEEDS_EXTERNAL_INTERACTION':'Cần người dùng xử lý OTP/mailbox hoặc tương tác ngoài phạm vi tool.',
    'MISSING_PRECONDITION':'Cung cấp dữ liệu/phiên xác thực và bằng chứng cho precondition.',
    'MISSING_LOCATOR':'Cung cấp UI evidence hoặc cho phép controlled exploration qua LLM.',
    'UNMAPPED_ACTION':'Bổ sung source/evidence rõ ràng hoặc bật LLM với evidence phù hợp.',
}


def _data_blockers(generation):
    """Read existing ordered audit receipts; latest preparation per case wins."""
    latest = {}
    def visit(value):
        if isinstance(value,dict):
            if {'testcase_id','initial','final','blockers','status'} <= value.keys():
                latest[value['testcase_id']] = value
            for item in value.values():
                visit(item)
        elif isinstance(value,(list,tuple)):
            for item in value:
                visit(item)
    visit(generation.to_dict())
    result = []
    for case_id, receipt in latest.items():
        if receipt['status'] in ('AVAILABLE','NO_DATA_REQUIRED'):
            continue
        needs = []
        for finding in (receipt.get('final') or {}).get('findings', []):
            req = finding.get('requirement',{})
            needs.append({'fixture':req.get('fixture'),'aliases':req.get('aliases',[]),
                          'facts':req.get('facts',{})})
        codes = list(dict.fromkeys(b['code'] for b in receipt['blockers']))
        code = receipt['status']
        if code == 'UNVERIFIED_TEST_DATA' and 'MISSING_TEST_DATA' in codes:
            code = 'MISSING_TEST_DATA'
        result.append({'testcase_id':case_id,'code':code,'preparation_status':receipt['status'],
                       'issue_codes':codes,'needs':needs,
                       'user_action':_ACTIONS.get(code,'Kiểm tra test-data policy và generation.json.')})
    return result


def build_summary(result):
    gen = result.generation_result
    counts = {key:result.counts.get(key,0) for key in ('Pass','Fail','Blocked','Not Executed')}
    if result.run_result is None:
        counts['Not Executed'] = result.total_cases
    sources = len(gen.coverage.requirements) if gen else 0
    requirements = sources
    if result.requirements_path and result.requirements_path.is_file():
        document = yaml.safe_load(result.requirements_path.read_text()) or {}
        requirements = len(document.get('requirements',[]))
    obligations = {o.id:o for r in gen.coverage.requirements for o in r.obligations} if gen else {}
    covered = sum(o.status == CoverageStatus.COVERED for o in obligations.values())
    unknown = sum(o.status == CoverageStatus.UNASSESSABLE for o in obligations.values())
    unknown_sources = sum(r.status == CoverageStatus.UNASSESSABLE for r in gen.coverage.requirements) if gen else 0
    blockers = _data_blockers(gen) if gen else []
    rows = []
    data_by_id = {b['testcase_id']:b for b in blockers}
    reports = {}
    runtime = {r.case_id:r.status for r in result.run_result.cases} if result.run_result else {}
    execution_blockers = [{'testcase_id':r.case_id,'reason':r.blocked_reason or 'Thiếu điều kiện thực thi.',
                           'user_action':'Bổ sung điều kiện môi trường được báo trong report.md.'}
                          for r in result.run_result.cases if r.status == 'Blocked'] if result.run_result else []
    for case in gen.unresolved_cases if gen else ():
        if case.id in data_by_id:
            row = dict(data_by_id[case.id])
        else:
            gaps = (reports[case.id] if case.id in reports else analyze_executability(case)).gaps
            code = next((g.code for g in gaps if g.code != 'MANUAL_EXECUTION'),'MANUAL_EXECUTION')
            row = {'testcase_id':case.id,'code':code,
                   'user_action':_ACTIONS.get(code,'Kiểm tra source/evidence và generation.json; không đoán expected outcome.')}
        rows.append({**row,'runtime_status':runtime.get(case.id,'Not Executed')})
    scope_counts = {scope: {key:0 for key in counts} for scope in ('BUSINESS_COVERAGE','LEGACY_DIAGNOSTIC')}
    for case in gen.cases if gen else ():
        scope = result.case_scopes.get(case.id, 'BUSINESS_COVERAGE')
        scope_counts[scope][runtime.get(case.id, 'Not Executed')] += 1
    if result.error or not result.ok:
        code,status = 2,'PIPELINE_ERROR'
    elif counts['Fail']:
        code,status = 1,('EXECUTION_FAILED' if scope_counts['BUSINESS_COVERAGE']['Fail'] else 'DIAGNOSTIC_EXECUTION_FAILED')
    elif not result.generation_success:
        code,status = 3,'GENERATION_INCOMPLETE'
    elif counts['Blocked'] or counts['Not Executed'] or result.run_result is None:
        code,status = 4,'EXECUTION_INCOMPLETE'
    else:
        code,status = 0,'SUCCESS'
    return {'generation_profile':result.generation_profile,'case_scopes':result.case_scopes,
            'business_counts':scope_counts['BUSINESS_COVERAGE'],
            'diagnostic_counts':scope_counts['LEGACY_DIAGNOSTIC'],
            'status':status,'exit_code':code,'pipeline_ok':result.ok,
            'generation_success':result.generation_success,'generation_status':result.generation_status,
            'requirements':requirements,'coverage_sources':sources,'obligations':len(obligations),
            'generated_testcases':result.total_cases,'new_coverage_testcases':len(gen.generated_cases) if gen else 0,
            'executable_testcases':len(gen.executable_cases) if gen else 0,
            'execution_performed':result.run_result is not None,'counts':counts,
            'flaky_cases':len(result.run_result.flaky_cases) if result.run_result else 0,
            'executable_coverage':{'covered':covered,'total':len(obligations),'unassessable':unknown,
                'unassessable_sources':unknown_sources,
                'complete':bool(gen and gen.executable_coverage_complete)},
            'unresolved_test_data':blockers,'unresolved_cases':rows,'execution_blockers':execution_blockers,
            'user_action_required':status != 'SUCCESS',
            'artifacts':{'legacy_testcases':str(result.legacy_testcases_path) if result.legacy_testcases_path else None,
                         'generation':str(result.generation_path) if result.generation_path else None,
                         'testcases':str(result.testcases_path) if result.testcases_path else None,
                         'xlsx':str(result.xlsx_path) if result.xlsx_path else None,
                         'report':str(result.report_path) if result.report_path else None}}


def redact(value,cfg):
    if cfg.fixture_store:
        value = cfg.fixture_store.redact(value)
    secrets = {cfg.username,cfg.password,cfg.bearer_token}
    secrets.update(v for k,v in os.environ.items() if k.startswith('QCTOOL_') and any(
        part in k for part in ('KEY','TOKEN','PASSWORD','SECRET')))
    if isinstance(value,str):
        from urllib.parse import quote
        for secret in sorted((s for s in secrets if isinstance(s,str) and s),key=len,reverse=True):
            for spelling in (secret,quote(secret,safe=''),json.dumps(secret)[1:-1]):
                value = value.replace(spelling,'[REDACTED]')
        return value
    if isinstance(value,dict):
        return {k:redact(v,cfg) for k,v in value.items()}
    if isinstance(value,list):
        return [redact(v,cfg) for v in value]
    return value


def print_summary(summary,out):
    print(f"QC: {summary['status']}")
    print(f"Requirements: {summary['requirements']} | Obligations: {summary['obligations']}")
    print(f"Generated: {summary['generated_testcases']} | Executable: {summary['executable_testcases']}")
    c=summary['counts']
    print(f"Pass: {c['Pass']} | Fail: {c['Fail']} | Blocked: {c['Blocked']} | Not Executed: {c['Not Executed']}")
    if summary['generation_profile']=='legacy':
        for scope,key in (('Business','business_counts'),('Legacy diagnostic','diagnostic_counts')):
            values=summary[key]
            print(scope+': '+ ' | '.join(f'{status}: {count}' for status,count in values.items()))
    if not summary['execution_performed']:
        print('Execution: chưa chạy')
    coverage=summary['executable_coverage']
    print(f"Executable coverage: {coverage['covered']}/{coverage['total']} | Unassessable sources: {coverage['unassessable_sources']}")
    print(f"Generation: {summary['generation_status'] or 'chưa hoàn tất'} | Unresolved test data: {len(summary['unresolved_test_data'])}")
    if summary['flaky_cases']:
        print(f"Flaky: {summary['flaky_cases']} (đạt sau khi chạy lại)")
    for row in summary['unresolved_cases'][:5]:
        print(f"  {row['testcase_id']} — {row['runtime_status']}; resolution blocker: {row['code']}")
        if row.get('needs'):
            for need in row['needs']:
                parts = [f"fixture {need['fixture']}" if need['fixture'] else 'test data']
                parts.extend(f'{key}={value}' for key,value in need['facts'].items())
                if need['aliases']:
                    parts.append('aliases: '+', '.join(need['aliases']))
                print('    Need: '+'; '.join(parts))
        print('    Action: '+row['user_action'])
    if len(summary['unresolved_cases']) > 5:
        print('  Các blockers còn lại: xem summary.json.')
    for row in summary['execution_blockers'][:5]:
        print(f"  {row['testcase_id']} — Blocked: {row['reason']}")
        print('    Action: '+row['user_action'])
    if summary['status']=='PIPELINE_ERROR':
        print('Action: kiểm tra cấu hình/đầu vào và pipeline.log.')
    elif summary['counts']['Fail']:
        print('Action: xem report.md và execution evidence cho assertion thất bại.')
    elif summary['user_action_required'] and not summary['unresolved_cases'] and not summary['execution_blockers']:
        print('Action: xem generation.json/report.md; bổ sung source rõ ràng hoặc điều kiện thực thi.')
    elif not summary['user_action_required']:
        print('User action required: không')
    print(f'Artifacts: {out}')


def cmd_project(args, *, validate_only=False):
    try:
        checked = preflight(args, require_target=not validate_only)
    except PreflightError as exc:
        print(f'LỖI PREFLIGHT: {exc}')
        return 2
    except Exception:
        print('LỖI PREFLIGHT: cấu hình/đầu vào không hợp lệ; nội dung lỗi được giữ kín.')
        return 2
    cfg = checked.config
    if validate_only:
        print(f'PREFLIGHT OK | Requirements: {checked.requirements} | API operations: {checked.operations} | Warnings: {checked.warnings}')
        print('Không gọi model/browser/API; không chứng minh tài khoản hay website hoạt động.')
        return 0
    buffer = StringIO()
    terminal = sys.stdout
    progress = []
    try:
        out = cfg.out_dir or Path('artifacts')/cfg.feature
        out.mkdir(parents=True,exist_ok=True)
        # Use the original terminal while raw dependency output stays buffered.
        # Flush each phase to terminal AND disk before browser/model work proceeds.
        with (out/'pipeline.log').open('w',encoding='utf-8') as live_log:
            def on_progress(stage, message):
                line = redact(f'  [{stage}] {message}',cfg)
                progress.append(line)
                print(line,file=terminal,flush=True)
                live_log.write(line+'\n')
                live_log.flush()

            with redirect_stdout(buffer), redirect_stderr(buffer):
                result = pipeline.run_pipeline(cfg,on_progress=on_progress,
                    resolution_llm=checked.adapter,exploration_llm=checked.adapter)
        summary = redact(build_summary(result),cfg)
        out = result.out_dir or cfg.out_dir or Path('artifacts')/cfg.feature
        out.mkdir(parents=True,exist_ok=True)
        (out/'pipeline.log').write_text(redact('\n'.join(progress+result.log)+'\n'+buffer.getvalue(),cfg),encoding='utf-8')
        (out/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
        print_summary(summary,redact(str(out),cfg))
        return summary['exit_code']
    except Exception:
        print('LỖI PIPELINE: không hoàn tất run/artifacts; kiểm tra quyền ghi và cấu hình.')
        return 2
