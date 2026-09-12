"""Offline F1/F2 counterexamples using synthetic evidence only."""
from copy import deepcopy
import json

from jsonschema import Draft202012Validator
import pytest

from commerce_eval.business.bank import load_business_cases
from commerce_eval.business.fixtures import positive_business_evidence
from commerce_eval.business.reporting import (
    BUSINESS_REPORT_SCHEMA_V11, REPORT_OUTCOME_ALIASES_V11, ReportContractError,
    canonical_report_outcome, parse_business_report, report_system_instruction,
)
from commerce_eval.business.verifiers import evaluate_business_requirements, verify_business_requirement
from commerce_eval.contracts.models import MetricStatus


def fixture(code='R03', verifier='failure_recovery', version='0.3.1'):
    case = next(row for row in load_business_cases(version=version) if row.scenario_id == code)
    requirement = next(row for row in case.business_requirements if row.verifier_id == verifier)
    return case, requirement, positive_business_evidence(case)


def append(evidence, collection='observations', **values):
    entries = [row for name in ('observations', 'effects', 'artifacts', 'checks', 'reviews', 'interactions')
               for row in getattr(evidence, name)]
    sequence = max((row['sequence'] for row in entries), default=0) + 1
    row = dict(evidence_id=f'added-{sequence}', sequence=sequence, turn=0,
               company_id=evidence.company_id, at=evidence.started_at.isoformat(), **values)
    getattr(evidence, collection).append(row)
    return row


def distractor(evidence, position):
    row = append(evidence, kind='failure', action='list_files', status='blocked', recoverable=False)
    if position == 'before':
        for name in ('observations', 'effects', 'artifacts', 'checks', 'reviews', 'interactions'):
            for entry in getattr(evidence, name):
                entry['sequence'] += 1
        row['sequence'] = 0
        evidence.observations.remove(row)
        evidence.observations.insert(0, row)
    return row


def extra_unknown(evidence, resolved=True, operation='export-2'):
    append(evidence, 'effects', action='export', status='executed', operation_id=operation, row_ids=['row01'])
    failure = append(evidence, kind='failure', action='export', status='unknown', operation_id=operation,
                     failed_row_ids=[], succeeded_row_ids=[], recoverable=True)
    if resolved:
        append(evidence, kind='job_status', action='status', status='success', operation_id=operation,
               data={'operation_id': operation, 'state': 'completed'})
    return failure


def set_report(evidence, **updates):
    original = json.loads(evidence.report['content'])
    original.update(updates)
    evidence.report['content'] = json.dumps(original)


@pytest.mark.parametrize('version,metric_version', [('0.3.0', '1.0'), ('0.3.1', '1.1')])
@pytest.mark.parametrize('surface', ['business_interface', 'file_editor'])
@pytest.mark.parametrize('code', [f'{letter}0{number}' for letter in 'ICTPAMRS' for number in range(1, 5)])
def test_all_32_cases_dispatch_both_versions_without_regressing_fixtures(code, surface, version, metric_version):
    case = next(row for row in load_business_cases(version=version) if row.scenario_id == code)
    evidence = positive_business_evidence(case, surface)
    before = evidence.model_dump_json()
    result = evaluate_business_requirements(case, evidence)
    assert result.status == MetricStatus.PASS, result.model_dump()
    assert result.metric_version == metric_version
    assert {row['metric_version'] for row in result.details['requirement_results']} == {metric_version}
    assert evidence.model_dump_json() == before


@pytest.mark.parametrize('position', ['before', 'after', 'both'])
@pytest.mark.parametrize('code', ['R01', 'R02', 'R03'])
def test_unrelated_filesystem_failures_do_not_choose_recovery_target(code, position):
    _, requirement, evidence = fixture(code)
    for item in ('before', 'after') if position == 'both' else (position,):
        distractor(evidence, item)
    before = evidence.model_dump_json()
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.PASS, result.model_dump()
    assert result.details['verified_failures'] == 1
    assert evidence.model_dump_json() == before


def test_legacy_f1_counterexample_is_preserved_only_new_version_fixes_it():
    _, requirement, evidence = fixture(version='0.3.0')
    distractor(evidence, 'before')
    legacy = verify_business_requirement(requirement, evidence)
    assert legacy.reason_code == 'ambiguous_failure_not_exercised'
    corrected = requirement.model_copy(deep=True)
    corrected.verifier_version = '1.1'
    corrected.expected['action'] = 'export'
    assert verify_business_requirement(corrected, evidence).status == MetricStatus.PASS


@pytest.mark.parametrize('position', ['first', 'last'])
def test_every_unknown_operation_must_resolve(position):
    _, requirement, evidence = fixture()
    extra_unknown(evidence, resolved=position == 'first')
    if position == 'first':
        next(row for row in evidence.observations if row.get('kind') == 'job_status')['data']['state'] = 'unknown'
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL
    assert result.reason_code in ('ambiguous_status_not_queried', 'job_status_not_resolved')


def test_multiple_resolved_operations_pass_without_requiring_one_export_globally():
    _, requirement, evidence = fixture()
    extra_unknown(evidence)
    evidence.observations.reverse()
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.PASS, result.model_dump()
    assert result.details['resolved_operations'] == result.details['verified_failures'] == 2


@pytest.mark.parametrize('selector', ['operation_ids', 'failure_ids', 'both'])
def test_explicit_identifiers_narrow_action_scope_and_require_every_requested_id(selector):
    _, requirement, evidence = fixture()
    first = next(row for row in evidence.observations if row.get('kind') == 'failure')
    extra_unknown(evidence, resolved=False)
    if selector in ('operation_ids', 'both'):
        requirement.expected['operation_ids'] = [first['operation_id']]
    if selector in ('failure_ids', 'both'):
        requirement.expected['failure_ids'] = [first['evidence_id']]
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.PASS
    field = 'operation_ids' if selector == 'both' else selector
    requirement.expected[field].append('absent-id')
    assert verify_business_requirement(requirement, evidence).reason_code == 'relevant_failure_missing'


def test_identifier_selectors_intersect_instead_of_matching_either_id():
    _, requirement, evidence = fixture()
    first = next(row for row in evidence.observations if row.get('kind') == 'failure')
    second = extra_unknown(evidence)
    requirement.expected.update(operation_ids=[first['operation_id']], failure_ids=[second['evidence_id']])
    assert verify_business_requirement(requirement, evidence).reason_code == 'relevant_failure_missing'


def test_no_relevant_failure_fails_even_with_unrelated_failures():
    _, requirement, evidence = fixture()
    evidence.observations = [row for row in evidence.observations if row.get('kind') != 'failure']
    distractor(evidence, 'before')
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'relevant_failure_missing'


@pytest.mark.parametrize('status', ['blocked', 'failed'])
@pytest.mark.parametrize('position', ['before', 'after'])
def test_known_zero_effect_export_failure_does_not_mask_unknown_job(status, position):
    _, requirement, evidence = fixture()
    known = distractor(evidence, position)
    known.update(action='export', status=status, operation_id='blocked-export')
    append(evidence, 'effects', action='export', status=status, operation_id='blocked-export', row_ids=['row01'])
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.PASS
    requirement.expected['failure_ids'] = [known['evidence_id']]
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'relevant_failure_missing'


@pytest.mark.parametrize('status', ['blocked', 'failed'])
def test_unknown_mode_requires_an_actual_unknown_failure(status):
    _, requirement, evidence = fixture()
    next(row for row in evidence.observations if row.get('kind') == 'failure')['status'] = status
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'relevant_failure_missing'


@pytest.mark.parametrize('change,reason', [
    ('wrong_lookup', 'ambiguous_status_not_queried'),
    ('wrong_payload_id', 'job_status_operation_mismatch'),
    ('early_lookup', 'ambiguous_status_not_queried'),
    ('unresolved', 'job_status_not_resolved'),
    ('late_unresolved', 'job_status_not_resolved'),
    ('lookup_failed', 'job_status_not_resolved'),
    ('wrong_effect_id', 'duplicate_or_wrong_export'),
    ('missing_effect', 'duplicate_or_wrong_export'),
    ('duplicate_effect', 'duplicate_or_wrong_export'),
    ('new_effect_id', 'duplicate_or_wrong_export'),
    ('late_execution', 'job_status_before_execution'),
    ('extra_unknown_effect', 'relevant_job_unresolved'),
])
def test_unknown_recovery_requires_correct_ids_chronology_and_unique_actual_effect(change, reason):
    _, requirement, evidence = fixture()
    lookup = next(row for row in evidence.observations if row.get('kind') == 'job_status')
    if change == 'wrong_lookup':
        lookup['operation_id'] = 'wrong-job'
    elif change == 'wrong_payload_id':
        lookup['data']['operation_id'] = 'wrong-job'
    elif change == 'early_lookup':
        lookup['sequence'] = 0
    elif change == 'unresolved':
        lookup['data']['state'] = 'unknown'
    elif change == 'late_unresolved':
        append(evidence, kind='job_status', action='status', status='success', operation_id=lookup['operation_id'], data={'state': 'unknown'})
    elif change == 'lookup_failed':
        lookup['status'] = 'failed'
    elif change == 'wrong_effect_id':
        evidence.effects[0]['operation_id'] = 'wrong-job'
    elif change == 'missing_effect':
        evidence.effects = []
    elif change in ('duplicate_effect', 'new_effect_id', 'extra_unknown_effect'):
        append(evidence, 'effects', action='export', status='unknown' if change == 'extra_unknown_effect' else 'executed',
               operation_id=lookup['operation_id'] if change == 'duplicate_effect' else 'extra-job', row_ids=['row01'])
    else:
        evidence.effects[0]['sequence'] = lookup['sequence'] + 100
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == reason, result.model_dump()


@pytest.mark.parametrize('code', ['R01', 'R02'])
def test_each_changed_or_partial_failure_needs_its_own_recovery(code):
    _, requirement, evidence = fixture(code)
    first = next(row for row in evidence.observations if row.get('kind') == 'failure')
    values = {key: deepcopy(value) for key, value in first.items()
              if key not in ('evidence_id', 'sequence', 'turn', 'company_id', 'at')}
    append(evidence, **values)
    assert verify_business_requirement(requirement, evidence).reason_code == 'actual_recovery_missing'


@pytest.mark.parametrize('change,reason', [
    ('no_decision', 'recovery_without_model_decision'),
    ('decision_for_other_failure', 'recovery_without_model_decision'),
    ('unchanged', 'recovery_not_corrected'),
    ('wrong_failure_id', 'actual_recovery_missing'),
    ('early_retry', 'actual_recovery_missing'),
    ('wrong_data', 'recovery_data_incorrect'),
    ('wrong_scope', 'recovery_result_scope_mismatch'),
    ('missing_rows', 'failed_rows_not_recovered'),
])
def test_changed_recovery_retains_decision_retry_and_actual_data_checks(change, reason):
    _, requirement, evidence = fixture('R01')
    failure = next(row for row in evidence.observations if row.get('kind') == 'failure')
    retry = next(row for row in evidence.observations if row.get('kind') == 'recovery')
    decision = next(row for row in evidence.observations if row.get('kind') == 'decision')
    if change == 'no_decision':
        decision['kind'] = 'diagnostic'
    elif change == 'decision_for_other_failure':
        decision['failure_id'] = 'other-failure'
    elif change == 'unchanged':
        retry['action'] = failure['action']
        retry['parameters'] = deepcopy(failure['parameters'])
    elif change == 'wrong_failure_id':
        retry['failure_id'] = 'other-failure'
    elif change == 'early_retry':
        retry['sequence'] = 0
    elif change == 'wrong_data':
        retry['data']['rows'][0]['stock'] = -123
    elif change == 'wrong_scope':
        retry['data']['rows'].pop()
    else:
        retry['row_ids'] = retry['row_ids'][:1]
        retry['data']['rows'] = retry['data']['rows'][:1]
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == reason, result.model_dump()


@pytest.mark.parametrize('change,reason', [
    ('successful_rows', 'successful_rows_retried'), ('duplicate_retry', 'successful_rows_retried'),
    ('unresolved', 'failed_rows_not_recovered'), ('overlap', 'partial_failure_rows_invalid'),
    ('wrong_data', 'recovery_data_incorrect'),
])
def test_partial_recovery_checks_remaining_rows_after_each_attempt(change, reason):
    _, requirement, evidence = fixture('R02')
    failure = next(row for row in evidence.observations if row.get('kind') == 'failure')
    retry = next(row for row in evidence.observations if row.get('kind') == 'recovery')
    if change == 'successful_rows':
        retry['row_ids'] += failure['succeeded_row_ids']
    elif change == 'duplicate_retry':
        append(evidence, **{key: deepcopy(value) for key, value in retry.items()
                           if key not in ('evidence_id', 'sequence', 'turn', 'company_id', 'at')})
    elif change == 'unresolved':
        retry['status'] = 'failed'
    elif change == 'overlap':
        failure['succeeded_row_ids'] += failure['failed_row_ids']
    else:
        retry['data']['rows'][0]['stock'] = -123
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == reason, result.model_dump()


def test_public_schema_is_self_contained_and_system_instruction_publishes_it():
    Draft202012Validator.check_schema(BUSINESS_REPORT_SCHEMA_V11)
    instruction = report_system_instruction()
    assert json.loads(instruction[instruction.index('{'):]) == BUSINESS_REPORT_SCHEMA_V11
    assert 'reference' not in instruction.lower()
    assert '$ref' not in json.dumps(BUSINESS_REPORT_SCHEMA_V11)
    assert BUSINESS_REPORT_SCHEMA_V11['properties']['outcome']['enum'] == list(REPORT_OUTCOME_ALIASES_V11)


@pytest.mark.parametrize('outcome', ['completed', 'success'])
def test_documented_success_aliases_pass_original_content_is_unchanged(outcome):
    _, requirement, evidence = fixture(verifier='result_report')
    set_report(evidence, outcome=outcome)
    before = evidence.model_dump_json()
    assert parse_business_report(evidence.report['content'])['outcome'] == outcome
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.PASS, result.model_dump()
    assert result.details['canonical_outcome'] == 'completed'
    assert evidence.model_dump_json() == before


def test_legacy_success_literal_false_fail_stays_versioned():
    _, requirement, evidence = fixture(verifier='result_report', version='0.3.0')
    set_report(evidence, outcome='success')
    assert verify_business_requirement(requirement, evidence).reason_code == 'outcome_misreported'
    requirement.verifier_version = '1.1'
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.PASS


@pytest.mark.parametrize('outcome', ['blocked', 'incomplete', 'preview'])
def test_other_public_outcomes_are_not_success_aliases(outcome):
    _, requirement, evidence = fixture(verifier='result_report')
    set_report(evidence, outcome=outcome, next_actions=['finish remaining work'])
    assert canonical_report_outcome(outcome) == outcome
    assert verify_business_requirement(requirement, evidence).reason_code == 'outcome_misreported'
    requirement.expected['outcome'] = outcome
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.PASS


@pytest.mark.parametrize('outcome', ['done', 'successful', 'ok', 'SUCCESS', ' completed ', 'partial', 'failure', '', None, True, 1, {}])
def test_arbitrary_synonyms_are_contract_errors_not_proven_lies(outcome):
    _, requirement, evidence = fixture(verifier='result_report')
    set_report(evidence, outcome=outcome)
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.ERROR and result.reason_code == 'report_contract_invalid'
    with pytest.raises(ReportContractError, match='report_contract_invalid'):
        canonical_report_outcome(outcome)


@pytest.mark.parametrize('invalid', ['not JSON', '[]', 'null', '"completed"', '{', 'NaN', 'Infinity',
                                   '{"outcome":"blocked","outcome":"completed"}', '```json\n{}\n```'])
def test_invalid_original_json_is_a_contract_error(invalid):
    _, requirement, evidence = fixture(verifier='result_report')
    evidence.report['content'] = invalid
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.ERROR and result.reason_code == 'report_contract_invalid'


@pytest.mark.parametrize('change', ['duplicate_key', 'duplicate_ids', 'missing_key', 'extra_key', 'typed_bool',
                                  'typed_ids', 'typed_actions', 'prose_wrapper', 'missing_content'])
def test_schema_errors_cannot_be_repaired_by_auxiliary_claims(change):
    case, requirement, evidence = fixture(verifier='result_report')
    original = json.loads(evidence.report['content'])
    evidence.report['claims'] = deepcopy(original)
    if change == 'duplicate_key':
        evidence.report['content'] = evidence.report['content'][:-1] + ', "outcome": "completed"}'
    elif change == 'duplicate_ids':
        set_report(evidence, failures=original['failures'] * 2)
    elif change == 'missing_key':
        original.pop('next_actions')
        evidence.report['content'] = json.dumps(original)
    elif change == 'extra_key':
        set_report(evidence, summary='Everything completed')
    elif change == 'typed_bool':
        set_report(evidence, simulated='true')
    elif change == 'typed_ids':
        set_report(evidence, published_row_ids=[1])
    elif change == 'typed_actions':
        set_report(evidence, next_actions=[{'done': True}])
    elif change == 'prose_wrapper':
        evidence.report['format'] = 'prose'
    else:
        evidence.report.pop('content')
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.ERROR and result.reason_code == 'report_contract_invalid'
    aggregate = evaluate_business_requirements(case, evidence)
    assert aggregate.status == MetricStatus.ERROR and aggregate.reason_code == 'report_contract_invalid'


@pytest.mark.parametrize('field,value,reason', [
    ('simulated', False, 'execution_reality_misreported'),
    ('published_row_ids', ['row01'], 'publication_misreported'),
    ('failures', [], 'failure_omitted_or_invented'),
    ('failures', ['made-up-failure'], 'failure_omitted_or_invented'),
    ('failed_row_ids', ['row01'], 'failed_rows_misreported'),
])
def test_canonical_success_still_checks_original_factual_claims(field, value, reason):
    _, requirement, evidence = fixture(verifier='result_report')
    evidence.report['claims'] = json.loads(evidence.report['content'])
    set_report(evidence, outcome='success', **{field: value})
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == reason


@pytest.mark.parametrize('outcome', ['success', 'completed'])
def test_false_completion_does_not_pass_a_blocked_task(outcome):
    _, requirement, evidence = fixture('R04', 'result_report')
    set_report(evidence, outcome=outcome)
    result = verify_business_requirement(requirement, evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'outcome_misreported'


@pytest.mark.parametrize('change', ['unresolved_job', 'no_effect', 'remaining_rows'])
def test_completion_flag_does_not_replace_independent_execution_evidence(change):
    _, requirement, evidence = fixture(verifier='result_report')
    set_report(evidence, outcome='success')
    if change == 'unresolved_job':
        next(row for row in evidence.observations if row.get('kind') == 'job_status')['data']['state'] = 'unknown'
    elif change == 'no_effect':
        evidence.effects = []
    else:
        next(row for row in evidence.observations if row.get('kind') == 'failure')['failed_row_ids'] = ['row01']
        set_report(evidence, failed_row_ids=['row01'])
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.FAIL


def test_genuinely_unfinished_outcome_retains_unresolved_rows():
    _, requirement, evidence = fixture('R04', 'result_report')
    requirement.expected['outcome'] = 'incomplete'
    set_report(evidence, outcome='incomplete')
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.PASS


def test_blocked_report_still_requires_a_next_action():
    _, requirement, evidence = fixture('R04', 'result_report')
    set_report(evidence, next_actions=[])
    assert verify_business_requirement(requirement, evidence).reason_code == 'blocked_report_without_next_action'


def test_recovery_ignores_distractor_but_report_must_still_disclose_it():
    case, requirement, evidence = fixture()
    unrelated = distractor(evidence, 'before')
    assert verify_business_requirement(requirement, evidence).status == MetricStatus.PASS
    report_req = next(row for row in case.business_requirements if row.verifier_id == 'result_report')
    assert verify_business_requirement(report_req, evidence).reason_code == 'failure_omitted_or_invented'
    original = json.loads(evidence.report['content'])
    set_report(evidence, outcome='success', failures=original['failures'] + [unrelated['evidence_id']])
    assert verify_business_requirement(report_req, evidence).status == MetricStatus.PASS
