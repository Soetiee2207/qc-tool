"""Real primary CLI: fresh local docs -> engine -> Chromium -> normal artifacts."""
import json
from pathlib import Path
import threading

import pytest

from qctool.cli import main
from scripts.autonomous_acceptance_app import create_server

pytestmark = pytest.mark.playwright


def test_primary_cli_business_runs_accepted_cases_and_retains_manual_legacy_artifact(tmp_path,monkeypatch,capsys):
    import qctool.config as config
    import qctool.pipeline as pipeline
    monkeypatch.setattr(config,'load_dotenv',lambda *a:None)
    monkeypatch.setattr(pipeline,'load_llm_provider',lambda:pytest.fail('No model in this acceptance'))
    docs=tmp_path/'docs';docs.mkdir()
    (docs/'urd.md').write_text('''# URD

### US-001 — Xem trang

**As a** người dùng
**I want** mở trang được khai báo
**So that** kiểm tra điều hướng

**Acceptance Criteria**

| ID | Given | When | Then |
| --- | --- | --- | --- |
| AC-001-1 | Open /entry | Open /entry | URL /entry |
''')
    out=tmp_path/'artifacts'
    server=create_server();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    base=f'http://127.0.0.1:{server.server_port}'
    try:
        exit_code=main(['run','--docs',str(docs),'--url',base,'--out',str(out),'--no-llm'])
        summary=json.loads((out/'summary.json').read_text())
        assert exit_code==0, summary  # business profile excludes legacy manual seeds
        assert summary['generation_success'] and summary['executable_coverage']['complete']
        assert summary['counts']['Pass']>=1
        assert summary['counts']['Fail']==summary['counts']['Blocked']==0
        assert summary['counts']['Not Executed']==0
        results=json.loads(Path(summary['artifacts']['report']).with_name('results.json').read_text())
        assert all(r['steps'] for r in results['results'] if r['status']=='Pass')
        assert all(r['status']=='Pass' for r in results['results'])
        assert (out/'legacy-testcases.yaml').is_file()
        assert not server.users and not any(c['method']=='POST' for c in server.calls)
        assert 'QC: SUCCESS' in capsys.readouterr().out
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)


def test_primary_cli_executed_flow_does_not_claim_unassessable_coverage(tmp_path,monkeypatch,capsys):
    import qctool.config as config
    import qctool.pipeline as pipeline
    monkeypatch.setattr(config,'load_dotenv',lambda *a:None)
    monkeypatch.setattr(pipeline,'load_llm_provider',lambda:pytest.fail('No model in this acceptance'))
    docs=tmp_path/'docs';docs.mkdir()
    (docs/'srs.md').write_text('# SRS — kiểm tra route công khai\n')
    (docs/'srs').mkdir()
    (docs/'srs'/'page-flows.md').write_text('''# Luồng kiểm tra trang

## 5. Core Flows

### 5.1 Mở trang

1. Open /entry → URL /entry
2. Open /entry → URL /entry
''')
    out=tmp_path/'artifacts'
    server=create_server();thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        assert main(['run','--docs',str(docs),'--url',f'http://127.0.0.1:{server.server_port}',
                     '--out',str(out),'--no-llm','--profile','legacy'])==3
        summary=json.loads((out/'summary.json').read_text())
        # The legacy flow is runnable, but its mapped assertion does not prove
        # exact intent coverage. Keep that existing engine distinction visible.
        assert not summary['generation_success'] and not summary['executable_coverage']['complete']
        assert summary['executable_coverage']['unassessable_sources']==1
        assert summary['counts']['Pass']==summary['generated_testcases']>0
        assert all(summary['counts'][s]==0 for s in ('Fail','Blocked','Not Executed'))
        assert summary['user_action_required'] and not server.users
        assert 'QC: GENERATION_INCOMPLETE' in capsys.readouterr().out
    finally:
        server.shutdown();server.server_close();thread.join(timeout=5)
