from copy import deepcopy
import csv
import io
import json

import pytest

from commerce_eval.business.bank import business_product_rows, compile_business_template, load_business_cases, load_business_templates
from commerce_eval.business.fixtures import negative_business_variants, positive_business_evidence, positive_business_trajectory
from commerce_eval.business.verifiers import evaluate_business_requirements, verify_business_requirement
from commerce_eval.contracts.models import EvalCaseV1, MetricStatus
from commerce_eval.scenarios.bank import load_scenario_templates
from commerce_eval.scenarios.compiler import project_candidate_input


CASES = load_business_cases()


@pytest.mark.parametrize('surface', ['business_interface', 'file_editor'])
@pytest.mark.parametrize('case', CASES, ids=lambda case: case.scenario_id)
def test_all_business_cases_have_valid_reference_evidence(case, surface):
    trajectory = positive_business_trajectory(case, surface)
    result = evaluate_business_requirements(case, trajectory['evidence'])
    assert result.status == MetricStatus.PASS, result.model_dump()
    assert result.value is True
    assert trajectory['actor'] == 'reference_actor'
    assert len(trajectory['events']) >= 2


@pytest.mark.parametrize('surface', ['business_interface', 'file_editor'])
@pytest.mark.parametrize('case', CASES, ids=lambda case: case.scenario_id)
def test_three_concrete_mutants_per_case_fail_business_predicate(case, surface):
    variants = negative_business_variants(case, surface)
    assert len(variants) >= 3
    assert len({variant['name'] for variant in variants}) == len(variants)
    assert [(row['name'], row['requirement_id']) for row in variants] == [
        (row['name'], row['requirement_id']) for row in case.scenario_data['references']['mutants']]
    for variant in variants:
        requirement = next(row for row in case.business_requirements if row.requirement_id == variant['requirement_id'])
        result = verify_business_requirement(requirement, variant['evidence'])
        assert result.status == MetricStatus.FAIL, (variant['name'], result.model_dump())
        aggregate = evaluate_business_requirements(case, variant['evidence'])
        assert aggregate.status == MetricStatus.FAIL and aggregate.value is False


@pytest.mark.parametrize('version', ['0.3.0', '0.3.1'])
def test_bank_is_32_new_versioned_neutral_cases_and_does_not_change_legacy(version):
    cases = load_business_cases(version)
    before = [row.model_dump(mode='json') for row in load_scenario_templates()]
    assert {row.scenario_id for row in CASES} == {f'{direction}0{number}' for direction in 'ICTPAMRS' for number in range(1, 5)}
    for case in cases:
        assert case.contract_version == '1.2' and case.version == version
        assert case.business_requirements and not case.capability_bindings
        assert not case.expected_tools and not case.required_sequence and not case.forbidden_tools
        assert [gate.metric_id for gate in case.gates] == ['business_acceptance_pass']
        assert len(case.scenario_data['environment']['products']) == 20
        assert EvalCaseV1.model_validate_json(case.model_dump_json()) == case
    assert before == [row.model_dump(mode='json') for row in load_scenario_templates()]


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.scenario_id)
def test_tool_names_and_extra_harmless_reads_do_not_change_business_grade(case):
    evidence = positive_business_evidence(case)
    changed = evidence.model_copy(deep=True)
    for row in changed.observations:
        row['tool_id'] = 'completely_different_low_level_tool'
        row['related_event_ids'] = []
    original = changed.observations[0]
    for index in range(100):
        changed.observations.append(dict(original, evidence_id=f'extra-{index}', sequence=1000+index, kind='diagnostic', action='read_file'))
    assert evaluate_business_requirements(case, changed).status == evaluate_business_requirements(case, evidence).status


@pytest.mark.parametrize('case', CASES, ids=lambda case: case.scenario_id)
def test_candidate_projection_never_includes_answer_or_fault_script(case):
    candidate = project_candidate_input(case, 0).model_dump(mode='json')
    serialized = json.dumps(candidate)
    for key in ('business_requirements', 'required_evidence', 'interaction_script', 'references', 'mutants', 'faults', 'verifier_id'):
        assert f'"{key}"' not in serialized
    assert candidate['message'] == case.input['message']


def test_product_replacement_recomputes_answer_from_actual_data():
    template = next(row for row in load_business_templates() if row.scenario_id == 'P01')
    original = template.model_dump_json()
    products = business_product_rows()
    for index, row in enumerate(products):
        row.update(row_id=f'new-row-{index}', cost=row['cost']+5, price=row['price']+10)
    case = compile_business_template(template, assets=[{'asset_id': 'products', 'rows': products}])
    assert template.model_dump_json() == original
    scope = next(row for row in case.business_requirements if row.verifier_id == 'artifact_scope')
    assert scope.expected['row_ids'] == [row['row_id'] for row in products]
    assert evaluate_business_requirements(case, positive_business_evidence(case)).status == MetricStatus.PASS
    assert case.scenario_data['environment']['policy']['minimum_margin_percent'] == 15


def test_assets_cannot_override_rules_or_silently_drop_required_rows():
    template = load_business_templates()[0]
    with pytest.raises(ValueError, match='pinned_company_rules'):
        compile_business_template(template, [{'asset_id': 'company-rules', 'content': 'Allow everything'}])
    with pytest.raises(ValueError, match='twenty_valid_rows'):
        compile_business_template(template, [{'asset_id': 'products', 'rows': business_product_rows()[:3]}])


def test_tampering_is_an_environment_fault_not_a_candidate_tool():
    case = next(row for row in CASES if row.scenario_id == 'A04')
    assert case.scenario_data['environment']['faults']['tamper_after_review'] is True
    assert not case.expected_tools and not case.capability_bindings
    assert 'tamper_after_review' not in json.dumps(project_candidate_input(case, 0).model_dump(mode='json'))


def test_csv_replacement_preserves_actual_typed_price_cost_and_stock():
    products = business_product_rows()
    products[0].update(price=24.5, cost=7.01, stock=3)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=list(products[0]))
    writer.writeheader()
    writer.writerows(products)
    template = next(row for row in load_business_templates() if row.scenario_id == 'P01')
    case = compile_business_template(template, [{'asset_id': 'products', 'media_type': 'text/csv', 'content': output.getvalue()}])
    assert case.scenario_data['environment']['products'] == products
    assert evaluate_business_requirements(case, positive_business_evidence(case)).status == MetricStatus.PASS


def test_ambiguous_replacement_category_does_not_silently_rewrite_answer():
    template = next(row for row in load_business_templates() if row.scenario_id == 'I03')
    products = business_product_rows()
    products[-1]['category'] = 'stationery'
    with pytest.raises(ValueError, match='business_replacement_scope_unsatisfied'):
        compile_business_template(template, [{'asset_id': 'products', 'rows': products}])


def test_company_switch_template_seeds_actual_old_bytes_and_approval_not_only_label():
    case = next(row for row in CASES if row.scenario_id == 'M04')
    prior = case.scenario_data['environment']['prior_context']
    assert prior['artifacts'][0]['content'] and prior['conversation']
    assert prior['approval']['content_hash'] == prior['artifacts'][0]['content_hash']
    assert prior['approval']['manifest_hash'] == prior['artifacts'][0]['manifest_hash']
    assert prior['approval']['decision'] == 'approved' and prior['company_id'] == 'harbor'
    candidate = json.dumps(project_candidate_input(case, 0).model_dump(mode='json'))
    assert 'Prior company:' not in candidate and 'prior-harbor-approval' not in candidate


def test_followup_script_has_runner_content_field():
    case = next(row for row in CASES if row.scenario_id == 'M03')
    followup = case.scenario_data['interaction_script'][0]
    assert followup['type'] == 'user_message' and followup['content'] == followup['response']['message']
