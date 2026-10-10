"""LLM authoring entry point; native runner remains the runtime authority."""
from copy import deepcopy
from dataclasses import dataclass, fields, is_dataclass
from enum import Enum
from pathlib import Path

from qctool.core.coverage import CoverageStatus, analyze_coverage
from qctool.core.executability import analyze_executability
from qctool.core.model import Requirement
from qctool.core.testcase import TestCase
from qctool.core.validate import validate_batch
from qctool.agent.llm_provider import LLMProviderError, capture_provider_attempts
from qctool.agent.gate import source_routes
from qctool.agent.loop import AgentBudget, AuthoringResult, author_intent, manual_case, design_intents
from qctool.agent.tools import AgentTools, public
from qctool.agent.safety import SafetyPolicy
from qctool.agent.knowledge import AppKnowledge


class GenerationStatus(str, Enum):
    SUCCESS = 'SUCCESS'
    NEEDS_REVIEW = 'NEEDS_REVIEW'
    INVALID_TESTCASES = 'INVALID_TESTCASES'
    UNASSESSABLE_COVERAGE = 'UNASSESSABLE_COVERAGE'
    INCOMPLETE_COVERAGE = 'INCOMPLETE_COVERAGE'
    FAILED = 'FAILED'


@dataclass(frozen=True)
class GenerationIssue:
    stage: str
    code: str
    message: str
    testcase_id: str | None = None


@dataclass(frozen=True)
class GenerationResult:
    cases: tuple
    executable_cases: tuple
    unresolved_cases: tuple
    generated_cases: tuple
    coverage: object
    intent_coverage: object
    validation: object
    issues: tuple
    status: GenerationStatus
    agent_history: tuple = ()
    design_audit: tuple = ()
    test_data_preparations: tuple = ()

    @property
    def success(self):
        return self.status == GenerationStatus.SUCCESS

    @property
    def history(self):
        return self.agent_history

    @property
    def accepted_generated_cases(self):
        ids = {c.id for c in self.executable_cases}
        return tuple(c for c in self.generated_cases if c.id in ids)

    @property
    def executable_coverage_complete(self):
        return bool(self.coverage.requirements) and all(r.status == CoverageStatus.COVERED for r in self.coverage.requirements)

    def to_dict(self):
        return {**{f.name: _serializable(getattr(self, f.name)) for f in fields(self)},
                'success': self.success, 'executable_coverage_complete': self.executable_coverage_complete}


def _serializable(value):
    if isinstance(value, Enum): return value.value
    if isinstance(value, Path): return str(value)
    if hasattr(value, 'to_dict'): return _serializable(value.to_dict())
    if is_dataclass(value): return {f.name: _serializable(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, dict): return {k: _serializable(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)): return [_serializable(v) for v in value]
    return value


def run_generation(requirements, existing_cases=(), *, flows=None, endpoints=None,
                   resolution_llm=None, exploration_llm=None, base_url=None, storage_state=None,
                   fixture_store=None, allow_provisioning=False, environment=None,
                   module='GEN', mutation_policy=None, mutation_budget=None,
                   knowledge_path=None, agent_budget=None, intent_ids=None, max_intents=None,
                   headless=True, on_progress=None, auth_operations=(), critic=False, **unused_legacy_options):
    """Enumerate explicit source obligations, author complete cases with tools.

    No legacy patch/resolution/coverage loop is invoked. Existing cases are
    detached and retained. A citation certifies source location, not semantic
    equivalence; weak oracles run as needs_review without claiming success.
    Provisioning is still reviewed and OFF by default. Knowledge is public hints.
    """
    from qctool.generate.from_openapi import IdAllocator
    from qctool.data.preparation import prepare_test_data
    from qctool.data.cache import PreparationCache
    if isinstance(requirements, dict):
        flows = flows if flows is not None else requirements.get('flows')
        requirements = requirements.get('requirements', [])
    rows = deepcopy([r.to_dict() if isinstance(r, Requirement) else r for r in requirements])
    original = tuple(deepcopy(tuple(existing_cases)))
    input_validation = validate_batch(list(original))
    if not input_validation.ok:
        report = analyze_coverage(rows, (), flows=deepcopy(flows))
        return GenerationResult(original, (), original, (), report, report, input_validation,
            (GenerationIssue('input', 'INVALID_TESTCASE', 'Input testcase batch is invalid'),),
            GenerationStatus.INVALID_TESTCASES)
    coverage = analyze_coverage(rows, original, flows=deepcopy(flows))
    obligations = list({o.id: o for r in coverage.requirements for o in r.obligations if o.status != CoverageStatus.COVERED}.values())
    if intent_ids is not None:
        # `AC-x-001-4` chọn mọi obligation của AC đó; `AC-x-001-4:then` chọn đúng một.
        def picked(o, wanted):
            return o.id == wanted or (':' not in wanted and o.id.split(':')[0] == wanted)
        if any(not any(picked(o, w) for o in obligations) for w in intent_ids):
            raise ValueError('Unknown source obligation selection')
        obligations = [o for o in obligations if any(picked(o, w) for w in intent_ids)]
    if max_intents is not None:
        if type(max_intents) is not int or max_intents < 1:
            raise ValueError('max_intents must be a positive integer')
        obligations = obligations[:max_intents]
    llm = (resolution_llm or exploration_llm) if base_url else None
    budget = agent_budget if isinstance(agent_budget, AgentBudget) else AgentBudget(**(agent_budget or {}))
    allocator = IdAllocator()
    existing_ids = {c.id for c in original}
    issues, authored, preparations, generated = [], [], [], []
    cache = PreparationCache()  # run-owned verifier freshness, never persisted KB
    knowledge = AppKnowledge(knowledge_path, base_url.rstrip('/'), store=fixture_store) if knowledge_path and base_url else None
    intents = [{'id': o.id, 'req_id': o.source.source_id, 'given': o.condition,
                'when': o.action, 'expected': o.expected, 'title': o.expected[:100],
                'source_ref': o.source.file} for o in obligations]
    design_audit = []
    if llm and intents:
        try:
            with capture_provider_attempts() as captured_design:
                try:
                    intents, _ = design_intents(public(intents, fixture_store), llm)
                finally:
                    design_audit = deepcopy(captured_design)
        except Exception as exc:
            issues.append(GenerationIssue('design', 'DESIGN_FAILED', getattr(exc, 'safe_message', type(exc).__name__)))
            # Design only titles/orders source obligations. A malformed design
            # falls back to the original intents unchanged; only a provider
            # failure stops authoring calls.
            if isinstance(exc, LLMProviderError):
                llm = None
    for intent in intents:
        case_id = allocator.next(module)
        while case_id in existing_ids:
            case_id = allocator.next(module)
        existing_ids.add(case_id)
        initial = manual_case(intent, case_id, module, 'Explicit LLM configuration required')
        if fixture_store:
            initial = fixture_store.bind(initial)
        preparation = prepare_test_data(initial, fixture_store=fixture_store, endpoints=endpoints or (),
            base_url=base_url, preparation_cache=cache, allow_provisioning=allow_provisioning, environment=environment)
        if preparation.initial is not None:
            preparations.append(preparation)
        if not preparation.available:
            initial.generation_status = 'blocked_env'
            initial.review_reasons = [b['code'] for b in preparation.blockers]
            generated.append(initial)
            issues.extend(GenerationIssue('test_data', b['code'], b['message'], case_id) for b in preparation.blockers)
            continue
        if llm is None or not base_url:
            issues.append(GenerationIssue('agent', 'AUTHORING_UNAVAILABLE', 'Configure an LLM and application URL to author this source intent', case_id))
            generated.append(initial)
            continue
        policy = SafetyPolicy(base_url, endpoints=endpoints or (), fixture_store=fixture_store,
            mutation=mutation_policy, req_ids=[intent['req_id']], budget=mutation_budget, auth_operations=auth_operations,
            source_routes=source_routes(intent))
        tools = AgentTools(intent, case_id, module, policy, storage_state=storage_state,
            knowledge=knowledge, headless=headless, on_progress=on_progress)
        record = author_intent(intent, tools, llm, budget=budget, critic=critic)
        authored.append(record)
        generated.append(record.case)
        issues.extend(GenerationIssue('agent', record.stop_reason, msg, case_id) for msg in record.issues)
    if knowledge:
        knowledge.save()
    inventory = original + tuple(generated)
    executable = tuple(c for c in inventory if analyze_executability(c).executable)
    unresolved = tuple(c for c in inventory if not analyze_executability(c).executable)
    report = analyze_coverage(rows, executable, flows=deepcopy(flows))
    intent_report = analyze_coverage(rows, inventory, flows=deepcopy(flows))
    validation = validate_batch(list(inventory))
    complete = bool(report.requirements) and all(r.status == CoverageStatus.COVERED for r in report.requirements)
    if not validation.ok: status = GenerationStatus.INVALID_TESTCASES
    elif any(c.generation_status == 'needs_review' for c in executable): status = GenerationStatus.NEEDS_REVIEW
    elif complete: status = GenerationStatus.SUCCESS
    elif not report.requirements or report.unassessable_obligations or any(not r.obligations for r in report.requirements): status = GenerationStatus.UNASSESSABLE_COVERAGE
    else: status = GenerationStatus.INCOMPLETE_COVERAGE
    return GenerationResult(deepcopy(inventory), deepcopy(executable), deepcopy(unresolved), deepcopy(tuple(generated)),
        report, intent_report, validation, tuple(issues), status, tuple(authored), tuple(design_audit), tuple(preparations))
