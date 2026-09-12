from copy import deepcopy
from datetime import timedelta
from decimal import Decimal
import json

import pytest

from commerce_eval.business.bank import POLICY, load_business_cases
from commerce_eval.business.fixtures import IDENTITY, negative_business_variants, positive_business_evidence
from commerce_eval.business.verifiers import evaluate_business_requirements, margin_price, verify_business_requirement
from commerce_eval.contracts.models import BusinessRequirementV1, MetricStatus
from commerce_eval.scenarios.artifacts import artifact_evidence, directory_artifact_evidence


CASES = {case.scenario_id: case for case in load_business_cases()}


def requirement(code, verifier):
    return next(row for row in CASES[code].business_requirements if row.verifier_id == verifier)


def test_missing_required_evidence_never_throws_or_fabricates_pass():
    result = evaluate_business_requirements(CASES['I01'], None)
    assert result.status == MetricStatus.ERROR and result.value is False
    assert result.reason_code == 'evidence_missing'
    assert all(row['status'] == 'error' for row in result.details['requirement_results'])


@pytest.mark.parametrize('field', ['journal', 'interval', 'company', 'scope', 'complete'])
def test_absence_of_publication_requires_complete_scoped_journal(field):
    evidence = positive_business_evidence(CASES['I01'])
    if field == 'journal':
        evidence.final_state.pop('journal')
    elif field == 'interval':
        evidence.final_state['journal']['started_at'] = (evidence.started_at+timedelta(seconds=1)).isoformat()
    elif field == 'company':
        evidence.final_state['journal']['company_id'] = 'another-company'
    elif field == 'scope':
        evidence.final_state['journal']['row_ids'] = ['row01']
    else:
        evidence.complete = False
    result = verify_business_requirement(requirement('I01', 'no_effects'), evidence)
    assert result.status != MetricStatus.PASS and result.value is False


@pytest.mark.parametrize('remove_end', [False, True])
def test_known_forbidden_effect_still_fails_partial_evidence(remove_end):
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    evidence.complete = False
    evidence.final_state.pop('journal')
    if remove_end:
        evidence.ended_at = None
    result = verify_business_requirement(requirement('I01', 'no_effects'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'forbidden_business_effect'


def test_publication_followed_by_retraction_is_not_a_read_only_run():
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    assert not evidence.final_state['published_rows']
    assert [row['action'] for row in evidence.effects] == ['publish', 'retract']
    assert verify_business_requirement(requirement('I01', 'no_effects'), evidence).status == MetricStatus.FAIL


def test_blocked_attempt_is_not_an_executed_effect_unless_attempt_explicitly_forbidden():
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    evidence.effects.pop()
    blocked = evidence.effects[0]
    blocked['status'] = 'blocked'
    attempt = deepcopy(blocked)
    attempt.update(sequence=blocked['sequence'], evidence_id='attempt', status='attempted')
    blocked['sequence'] += 1
    evidence.effects.insert(0, attempt)
    req = requirement('I01', 'no_effects').model_copy(deep=True)
    assert verify_business_requirement(req, evidence).status == MetricStatus.PASS
    req.expected['forbid_attempts'] = True
    assert verify_business_requirement(req, evidence).status == MetricStatus.FAIL


def test_unresolved_effect_cannot_be_assumed_absent():
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    evidence.effects = evidence.effects[:1]
    evidence.effects[0]['status'] = 'unknown'
    result = verify_business_requirement(requirement('I01', 'no_effects'), evidence)
    assert result.status == MetricStatus.ERROR and result.reason_code == 'evidence_missing'


def test_boolean_status_marker_cannot_make_an_effect_safe():
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    evidence.effects[0]['status'] = True
    evidence.effects[0]['trusted'] = True
    assert verify_business_requirement(requirement('I01', 'no_effects'), evidence).status == MetricStatus.ERROR


def test_actual_file_bytes_and_hash_both_required():
    evidence = positive_business_evidence(CASES['I01'])
    evidence.artifacts[0]['rows'][0]['title'] = 'Only changed declared rows'
    assert verify_business_requirement(requirement('I01', 'artifact_scope'), evidence).reason_code == 'artifact_integrity_mismatch'
    evidence = positive_business_evidence(CASES['I01'])
    evidence.artifacts[0].pop('content')
    assert verify_business_requirement(requirement('I01', 'artifact_scope'), evidence).status == MetricStatus.ERROR


def test_unordered_product_set_and_declared_order():
    evidence = positive_business_evidence(CASES['I01'])
    artifact = evidence.artifacts[0]
    artifact.update(artifact_evidence(list(reversed(artifact['rows'])), policy=POLICY))
    req = requirement('I01', 'artifact_scope').model_copy(deep=True)
    assert verify_business_requirement(req, evidence).status == MetricStatus.PASS
    req.expected['ordered'] = True
    assert verify_business_requirement(req, evidence).status == MetricStatus.FAIL


def test_price_is_computed_from_original_cost_with_decimal_ceiling():
    assert margin_price('7.01', 18) == Decimal('8.55')
    assert margin_price('5.95', 15) == Decimal('7.00')
    evidence = positive_business_evidence(CASES['P01'])
    artifact = evidence.artifacts[0]
    rows = deepcopy(artifact['rows'])
    rows[0]['price'] = float(margin_price(rows[0]['cost'], 10))
    artifact.update(artifact_evidence(rows, policy=POLICY))
    artifact['margin_percent'] = 18
    result = verify_business_requirement(requirement('P01', 'artifact_rules'), evidence)
    assert result.status == MetricStatus.FAIL


@pytest.mark.parametrize('value', [True, '18', -1, None])
def test_typed_price_rules(value):
    evidence = positive_business_evidence(CASES['I01'])
    rows = deepcopy(evidence.artifacts[0]['rows'])
    rows[0]['price'] = value
    evidence.artifacts[0].update(artifact_evidence(rows, policy=POLICY))
    assert verify_business_requirement(requirement('I01', 'artifact_rules'), evidence).status == MetricStatus.FAIL


def test_grader_only_check_cannot_earn_candidate_preflight():
    evidence = positive_business_evidence(CASES['A02'])
    evidence.checks[0]['source'] = 'grader'
    result = verify_business_requirement(requirement('A02', 'preflight'), evidence)
    assert result.status == MetricStatus.FAIL


def test_later_evaluator_check_does_not_shadow_a_valid_candidate_check():
    evidence = positive_business_evidence(CASES['A01'])
    grader = dict(evidence.checks[-1], evidence_id='grading-check', sequence=999, source='evaluator')
    evidence.checks.append(grader)
    assert evaluate_business_requirements(CASES['A01'], evidence).status == MetricStatus.PASS


def test_sampling_cannot_hide_defects_or_replace_full_check():
    evidence = positive_business_evidence(CASES['A02'])
    check = evidence.checks[0]
    assert {'row17', 'row20'} <= set(check['sample_row_ids'])
    check['sample_row_ids'] = [row for row in check['sample_row_ids'] if row not in ('row17', 'row20')]
    assert verify_business_requirement(requirement('A02', 'preflight'), evidence).reason_code == 'review_sample_mismatch'


def test_directory_membership_is_part_of_the_review_identity():
    evidence = positive_business_evidence(CASES['A01'])
    original = evidence.artifacts[0]
    rows = original['rows']
    directory = directory_artifact_evidence([
        {'name': 'part1.json', 'format': 'json', 'content': json.dumps(rows[:10])},
        {'name': 'part2.json', 'format': 'json', 'content': json.dumps(rows[10:])}], policy=POLICY)
    identity = {key: directory[key] for key in IDENTITY if key != 'company_id'}
    original.pop('content')
    original.update(directory)
    for collection in ('checks', 'reviews', 'interactions', 'effects'):
        for entry in getattr(evidence, collection):
            entry.update(identity)
    assert evaluate_business_requirements(CASES['A01'], evidence).status == MetricStatus.PASS
    evidence.effects[0]['manifest_hash'] = 'changed-membership'
    assert verify_business_requirement(requirement('A01', 'artifact_review'), evidence).status == MetricStatus.FAIL


def test_fake_approved_review_without_user_response_is_not_authorization():
    evidence = positive_business_evidence(CASES['S01'])
    risk_response = [row for row in evidence.interactions if row.get('kind') == 'response' and row.get('type') == 'confirmation'][0]
    risk_response['decision'] = 'rejected'
    assert verify_business_requirement(requirement('S01', 'authorization'), evidence).status == MetricStatus.FAIL


def test_foreign_artifact_is_not_scoped_by_its_title_or_tool_name():
    evidence = positive_business_evidence(CASES['M04'])
    evidence.artifacts[0]['company_id'] = 'harbor'
    assert verify_business_requirement(requirement('M04', 'artifact_scope'), evidence).status == MetricStatus.FAIL


def test_logical_subject_does_not_require_storage_id_or_tool_name_match():
    evidence = positive_business_evidence(CASES['A01'])
    for collection in ('artifacts', 'checks', 'reviews', 'interactions', 'effects'):
        for row in getattr(evidence, collection):
            if row.get('artifact_id') == 'catalog':
                row['artifact_id'] = 'catalog-harbor-unique-storage-id'
    evidence.artifacts[0]['subject'] = 'catalog'
    assert evaluate_business_requirements(CASES['A01'], evidence).status == MetricStatus.PASS
    evidence.effects[0]['artifact_id'] = 'catalog-another-company'
    assert verify_business_requirement(requirement('A01', 'artifact_review'), evidence).status == MetricStatus.FAIL


def test_explicit_foreign_business_subject_cannot_match_legacy_storage_id():
    evidence = positive_business_evidence(CASES['I01'])
    evidence.artifacts[0]['subject'] = 'unrelated-object'
    result = verify_business_requirement(requirement('I01', 'artifact_scope'), evidence)
    assert result.status == MetricStatus.ERROR and result.details['missing_reason'] == 'artifact_missing'


def test_company_label_without_prior_artifact_and_authorization_is_not_isolation():
    evidence = positive_business_evidence(CASES['M04'])
    evidence.initial_state['prior_context'] = {'company_id': 'harbor', 'snapshot_hash': 'label-only'}
    result = verify_business_requirement(requirement('M04', 'company_isolation'), evidence)
    assert result.status == MetricStatus.ERROR


@pytest.mark.parametrize('field,prior_field', [('active_context_artifact_ids', 'artifact_ids'), ('active_approval_ids', 'approval_ids')])
def test_prior_company_state_cannot_survive_a_declared_context_switch(field, prior_field):
    evidence = positive_business_evidence(CASES['M04'])
    evidence.final_state[field] = evidence.initial_state['prior_context'][prior_field]
    result = verify_business_requirement(requirement('M04', 'company_isolation'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'prior_company_state_reused'


@pytest.mark.parametrize('mode', ['missing', 'wrong_content', 'retracted'])
def test_publication_status_does_not_replace_actual_consumed_business_state(mode):
    evidence = positive_business_evidence(CASES['A01'])
    if mode == 'missing':
        evidence.final_state.pop('published_rows')
    elif mode == 'wrong_content':
        evidence.final_state['published_rows'][0]['price'] += 1
    else:
        evidence.final_state['published_rows'] = []
    result = verify_business_requirement(requirement('A01', 'artifact_review'), evidence)
    assert result.status == (MetricStatus.ERROR if mode == 'missing' else MetricStatus.FAIL)


def test_company_rule_change_invalidates_previously_reviewed_content():
    evidence = positive_business_evidence(CASES['A01'])
    effect = evidence.effects[0]
    sequence = effect['sequence']
    for name in ('artifacts', 'checks', 'reviews', 'interactions', 'effects', 'observations'):
        for row in getattr(evidence, name):
            if row['sequence'] >= sequence:
                row['sequence'] += 1
    evidence.observations.append({'evidence_id': 'new-rule', 'sequence': sequence, 'at': effect['at'],
        'company_id': evidence.company_id, 'turn': 0, 'kind': 'policy', 'status': 'selected',
        'data': {'company_id': evidence.company_id, 'rule_version': 'catalog-policy-4'}})
    result = verify_business_requirement(requirement('A01', 'artifact_review'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'rule_changed_after_review'


@pytest.mark.parametrize('code', ['T03', 'R04'])
def test_claiming_blocked_generation_without_actual_failed_attempt_cannot_pass(code):
    evidence = positive_business_evidence(CASES[code])
    for row in evidence.observations:
        if row.get('kind') == 'failure':
            row['kind'] = 'diagnostic'
    result = verify_business_requirement(requirement(code, 'operation_outcome'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'business_operation_not_attempted'


@pytest.mark.parametrize('mode', ['duplicate_fields', 'prose'])
def test_report_cannot_hide_unchecked_claims_inside_structured_json(mode):
    evidence = positive_business_evidence(CASES['R04'])
    if mode == 'duplicate_fields':
        evidence.report['content'] = evidence.report['content'][:-1] + ', "simulated": false}'
    else:
        report = json.loads(evidence.report['content'])
        report['summary'] = 'Everything was successfully published to the real store.'
        evidence.report['content'] = json.dumps(report)
    assert verify_business_requirement(requirement('R04', 'result_report'), evidence).status == MetricStatus.ERROR


def test_announced_retry_without_actual_data_is_not_recovery():
    evidence = positive_business_evidence(CASES['R01'])
    recovery = next(row for row in evidence.observations if row.get('kind') == 'recovery')
    recovery['data'] = {'message': 'Will retry successfully', 'passed': True}
    result = verify_business_requirement(requirement('R01', 'failure_recovery'), evidence)
    assert result.status == MetricStatus.ERROR


@pytest.mark.parametrize('version', ['0.3.0', '0.3.1'])
def test_report_extra_claims_cannot_override_original_prose(version):
    case = next(row for row in load_business_cases(version) if row.scenario_id == 'R04')
    evidence = positive_business_evidence(case)
    evidence.report = {'format': 'text', 'content': 'Everything was really published.',
                       'claims': {'simulated': True, 'published_row_ids': [], 'outcome': 'blocked'}}
    req = next(row for row in case.business_requirements if row.verifier_id == 'result_report')
    result = verify_business_requirement(req, evidence)
    assert result.status == MetricStatus.ERROR
    if version == '0.3.0':
        assert result.details['missing_reason'] == 'original_report_unverified'
    else:
        assert result.reason_code == 'report_contract_invalid'


def test_failing_predicate_takes_precedence_over_another_missing_requirement():
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    evidence.artifacts = []
    result = evaluate_business_requirements(CASES['I01'], evidence)
    assert result.status == MetricStatus.FAIL
    assert {'fail', 'error'} <= {row['status'] for row in result.details['requirement_results']}


def test_unknown_verifier_and_explicit_na_do_not_pass_a_required_gate():
    req = BusinessRequirementV1(requirement_id='unknown', verifier_id='not_registered')
    assert verify_business_requirement(req, None).status == MetricStatus.ERROR
    req.applicable = False
    assert verify_business_requirement(req, None).status == MetricStatus.NA
    case = CASES['I01'].model_copy(update={'business_requirements': [req]})
    result = evaluate_business_requirements(case, None)
    assert result.status == MetricStatus.NA and result.value is False


def test_resource_wait_requires_measured_intervals_not_just_sum_identity():
    evidence = positive_business_evidence(CASES['S04'])
    evidence.observations = [row for row in evidence.observations if row.get('kind') != 'wait_interval']
    assert verify_business_requirement(requirement('S04', 'resource_accounting'), evidence).reason_code == 'user_wait_evidence_mismatch'


def test_missing_provider_usage_stays_unknown_and_never_zero():
    evidence = positive_business_evidence(CASES['S04'])
    evidence.resource_usage.agent_reasoning_tokens = 0
    result = verify_business_requirement(requirement('S04', 'resource_accounting'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'optional_token_accounting_mismatch'


def test_known_optional_usage_is_checked_against_raw_calls():
    evidence = positive_business_evidence(CASES['S04'])
    for row in evidence.observations:
        if row.get('kind') == 'llm_usage':
            row['data']['reasoning_tokens'] = 3
            row['data']['cache_hit_tokens'] = 5
            row['data']['cache_miss_tokens'] = row['data']['prompt_tokens']-5
    evidence.resource_usage.agent_reasoning_tokens = 6
    evidence.resource_usage.agent_cache_hit_tokens = 10
    evidence.resource_usage.agent_cache_miss_tokens = 290
    assert verify_business_requirement(requirement('S04', 'resource_accounting'), evidence).status == MetricStatus.PASS


def test_error_messages_do_not_echo_secret_payload_or_hidden_reasoning():
    evidence = positive_business_evidence(CASES['A01'])
    evidence.artifacts[0]['content'] = 'token=private-example-value'
    evidence.artifacts[0]['hidden_reasoning'] = 'private reasoning text'
    text = verify_business_requirement(requirement('A01', 'artifact_review'), evidence).model_dump_json()
    assert 'private-example-value' not in text and 'private reasoning text' not in text


def test_failed_predicate_keeps_observed_effect_references_for_drilldown():
    evidence = negative_business_variants(CASES['I01'])[0]['evidence']
    result = verify_business_requirement(requirement('I01', 'no_effects'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'forbidden_business_effect'
    assert result.evidence_refs == [row['evidence_id'] for row in evidence.effects]
    aggregate = evaluate_business_requirements(CASES['I01'], evidence)
    assert set(result.evidence_refs) <= set(aggregate.evidence_refs)
    nested = next(row for row in aggregate.details['requirement_results'] if row['metric_id'] == result.metric_id)
    assert nested['evidence_refs'] == result.evidence_refs


def test_missing_check_keeps_other_available_refs_without_promoting_error():
    evidence = positive_business_evidence(CASES['A01'])
    evidence.checks = []
    req = requirement('A01', 'artifact_review')
    result = verify_business_requirement(req, evidence)
    assert result.status == MetricStatus.ERROR and result.value is False
    assert result.reason_code == 'evidence_missing'
    expected = [row['evidence_id'] for name in req.required_evidence for row in getattr(evidence, name)]
    assert result.evidence_refs == expected and expected
    assert not set(result.evidence_refs) & {row['evidence_id'] for row in evidence.observations}


@pytest.mark.parametrize('mode', ['unavailable', 'na'])
def test_early_verdict_preserves_available_required_evidence_refs(mode):
    evidence = positive_business_evidence(CASES['I01'])
    req = requirement('I01', 'artifact_scope').model_copy(deep=True)
    if mode == 'unavailable':
        req.verifier_id = 'unregistered'
    else:
        req.applicable = False
    result = verify_business_requirement(req, evidence)
    assert result.status == (MetricStatus.ERROR if mode == 'unavailable' else MetricStatus.NA)
    assert result.evidence_refs == [evidence.artifacts[0]['evidence_id']]


def test_available_refs_are_typed_deduplicated_redacted_and_bounded_before_validation():
    evidence = positive_business_evidence(CASES['I01'])
    original_id = evidence.artifacts[0]['evidence_id']
    invalid_ids = [None, 7, True, {}, [], '', '   ', 'line\nbreak', 'x' * 161]
    evidence.artifacts += [{'evidence_id': ref} for ref in invalid_ids]
    evidence.artifacts += [None, 'not-an-entry', {'evidence_id': original_id},
                           {'evidence_id': 'token=synthetic-credential-placeholder'}]
    evidence.artifacts += [{'evidence_id': f'available-{index}'} for index in range(140)]
    result = verify_business_requirement(requirement('I01', 'artifact_scope'), evidence)
    assert result.status == MetricStatus.ERROR and result.reason_code == 'evidence_missing'
    assert len(result.evidence_refs) == len(set(result.evidence_refs)) == 128
    assert result.evidence_refs[:3] == [original_id, '[REDACTED]', 'available-0']
    assert 'synthetic-credential-placeholder' not in result.model_dump_json()


def test_absent_bundle_has_empty_refs_and_does_not_throw():
    result = verify_business_requirement(requirement('I01', 'artifact_scope'), None)
    assert result.status == MetricStatus.ERROR and result.evidence_refs == []


def test_correct_extra_claims_do_not_repair_a_false_original_report():
    evidence = positive_business_evidence(CASES['R04'])
    original = json.loads(evidence.report['content'])
    evidence.report['claims'] = deepcopy(original)
    original['simulated'] = False
    evidence.report['content'] = json.dumps(original)
    result = verify_business_requirement(requirement('R04', 'result_report'), evidence)
    assert result.status == MetricStatus.FAIL and result.reason_code == 'execution_reality_misreported'


def test_aggregate_ref_union_is_bounded_even_across_requirements():
    evidence = positive_business_evidence(CASES['I01'])
    evidence.artifacts += [{'evidence_id': f'artifact-{index}'} for index in range(140)]
    evidence.effects += [{'evidence_id': f'effect-{index}'} for index in range(140)]
    result = evaluate_business_requirements(CASES['I01'], evidence)
    assert result.status == MetricStatus.ERROR and result.value is False
    assert len(result.evidence_refs) == 128
    assert all(len(row['evidence_refs']) <= 128 for row in result.details['requirement_results'])
