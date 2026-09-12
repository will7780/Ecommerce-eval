"""Version-pinned API and seed compatibility, using only temporary SQLite data."""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from commerce_eval.api import create_app
from commerce_eval.business.bank import load_business_cases, load_business_templates
from commerce_eval.business.bootstrap import SURFACES, candidate_tool_contracts, seed_business_bank
from commerce_eval.contracts import TraceEnvelopeV1
from commerce_eval.providers.client import NativeCompatibleClient
from commerce_eval.providers.credentials import CredentialResolver
from commerce_eval.services.scenario_templates import load_templates
from commerce_eval.storage.models import Base
from commerce_eval.targets.business_candidate import BusinessCandidateTarget


VERSIONS = [('0.3.0', '1.0'), ('0.3.1', '1.1')]


@pytest.fixture(autouse=True)
def offline_only(tmp_path, monkeypatch):
    monkeypatch.setenv('COMMERCE_EVAL_DISABLE_CENTRAL_ENV', '1')
    monkeypatch.setenv('AGENT_API_ENV_FILE', str(tmp_path / 'disabled.env'))
    monkeypatch.delenv('COMMERCE_EVAL_API_TOKEN', raising=False)
    attempts = []

    def forbidden(*args, **kwargs):
        attempts.append('unexpected_external_execution')
        pytest.fail('Version compatibility tests must not resolve credentials, call models, or start experiments')

    async def forbidden_model(*args, **kwargs):
        forbidden()

    monkeypatch.setattr(CredentialResolver, 'resolve', forbidden)
    monkeypatch.setattr(NativeCompatibleClient, 'complete', forbidden_model)
    yield forbidden
    assert attempts == []


@pytest.fixture
def client(tmp_path, monkeypatch, offline_only):
    app = create_app(database_path=tmp_path / 'bank-revisions.db', static_dir=tmp_path / 'no-static')
    app.state.repository.create_project('p', 'Synthetic version compatibility')
    monkeypatch.setattr(app.state.experiment_manager, 'start', offline_only)
    try:
        with TestClient(app) as result:
            yield result
    finally:
        app.state.database.dispose()


def _snapshot(client):
    # Driver-level rows retain the original JSON text, checksums and timestamps.
    engine = client.app.state.database.engine
    quote = engine.dialect.identifier_preparer.quote
    with engine.connect() as connection:
        return {table.name: frozenset(tuple(row) for row in connection.exec_driver_sql(
                    f'SELECT * FROM {quote(table.name)}'))
                for table in Base.metadata.sorted_tables}


def _expected_cases(version, selected=None):
    return sorted((case.model_dump(mode='json') for case in load_business_cases(version=version)
                   if selected is None or case.scenario_id in selected), key=lambda case: case['case_id'])


def _assert_cases(cases, version, verifier_version, selected=None):
    assert sorted(cases, key=lambda case: case['case_id']) == _expected_cases(version, selected)
    assert {case['version'] for case in cases} == {version}
    assert {requirement['verifier_version'] for case in cases for requirement in case['business_requirements']} == {verifier_version}
    for case in cases:
        for requirement in case['business_requirements']:
            if requirement['verifier_id'] != 'failure_recovery':
                continue
            if version == '0.3.0':
                assert 'action' not in requirement['expected']
            else:
                expected_action = 'export' if requirement['expected']['mode'] == 'unknown_status' else 'inventory_query'
                assert requirement['expected']['action'] == expected_action


def _assert_seed(client, seeded, version, verifier_version, selected=None):
    repository = client.app.state.repository
    for key in ('dataset_version', 'target_version', 'tool_contract_version', 'evaluator_set_version'):
        assert seeded[key] == version
    assert seeded['executed'] is False
    assert seeded['requires_explicit_model_configuration'] is True
    dataset = repository.get_dataset('p', seeded['dataset_id'], version)
    _assert_cases(dataset['cases'], version, verifier_version, selected)
    assert seeded['case_count'] == dataset['case_count'] == len(_expected_cases(version, selected))
    assert {target['adapter_type'] for target in seeded['targets']} == set(SURFACES)
    assert len(seeded['candidate_experiment_specs']) == len(SURFACES)
    evaluator = repository.get_evaluator_set('p', seeded['evaluator_set_id'], version)
    assert evaluator['version'] == version and evaluator['metric_ids']
    for target in seeded['targets']:
        definition = repository.get_target('p', target['target_id'], version)
        assert definition.model_dump(mode='json') == target
        expected_config = {'project_id': 'p', 'execution_mode': 'sandbox', 'max_rounds': 24,
                           'environment_version': '1.0', 'tool_contract_set_id': target['target_id'],
                           'tool_contract_version': version}
        if version == '0.3.1':
            expected_config.update(model_timeout_seconds=120.0, max_completion_tokens=4096, max_model_calls=128)
        assert definition.config == expected_config
        expected_tools = {tool.tool_id: tool for tool in candidate_tool_contracts(target['adapter_type'], version)}
        assert repository.get_tool_contracts('p', target['target_id'], version) == expected_tools
        assert expected_tools and {tool.version for tool in expected_tools.values()} == {version}
        candidate = BusinessCandidateTarget(definition)
        assert candidate.definition.version == version
        assert candidate.complete is None and candidate._sessions == {}
    for spec in seeded['candidate_experiment_specs']:
        for key in ('dataset_version', 'target_version', 'tool_contract_version', 'evaluator_set_version'):
            assert spec[key] == version
        assert spec['dataset_id'] == seeded['dataset_id']
        assert spec['timeout_ms'] == 300000
        assert spec['execution_mode'] == 'sandbox' and spec['allow_paid'] is False
        expected_tags = {'environment_version': '1.0', 'rule_version': 'business-policy-1.0'}
        if version == '0.3.1':
            expected_tags.update(model_timeout_seconds='120.0', max_completion_tokens='4096',
                                 total_model_request_limit='128', whole_case_timeout_ms='300000')
        assert spec['tags'] == expected_tags


def _seed(client, version, selected=None, *, path='api'):
    if path == 'direct':
        return seed_business_bank(client.app.state.repository, 'p', selected, version=version)
    response = client.post('/api/v1/onboarding/demo', json={
        'project_id': 'p', 'bank_version': version, 'template_ids': selected})
    assert response.status_code == 200, response.text
    assert response.json()['readiness'] == {'ready': True, 'errors': []}
    return response.json()


@pytest.mark.parametrize('version,verifier_version', VERSIONS)
def test_template_api_returns_exact_selected_revision_without_writes(client, version, verifier_version):
    before = _snapshot(client)
    expected = [template.model_dump(mode='json') for template in load_business_templates(version=version)]
    assert [template.model_dump(mode='json') for template in load_templates(version)] == expected
    response = client.get('/api/v1/scenario-templates', params={'template_version': version})
    assert response.status_code == 200, response.text
    assert response.json() == {'items': expected}
    assert len(expected) == 32 and {template['scenario_version'] for template in expected} == {version}
    assert {requirement['verifier_version'] for template in expected
            for requirement in template['business_requirements']} == {verifier_version}
    assert _snapshot(client) == before


@pytest.mark.parametrize('version,verifier_version', VERSIONS)
@pytest.mark.parametrize('template_id,selected', [('bank', ['R03', 'M02', 'R01']), ('R03', ['R03'])])
def test_instantiate_compiles_the_selected_template_not_the_default(client, version, verifier_version, template_id, selected):
    before = _snapshot(client)
    body = {'project_id': 'p', 'dataset_id': 'chosen', 'version': 'import-1', 'template_version': version}
    if template_id == 'bank':
        body['template_ids'] = selected
    response = client.post(f'/api/v1/scenario-templates/{template_id}/instantiate', json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result['status'] == 'ready' and result['version'] == 'import-1'
    assert result['dataset'] == {'project_id': 'p', 'dataset_id': 'chosen', 'version': 'import-1'}
    _assert_cases(result['cases'], version, verifier_version, selected)
    stored = client.app.state.repository.get_dataset('p', 'chosen', 'import-1')
    assert stored['cases'] == result['cases']
    after = _snapshot(client)
    for table in before:
        if table not in ('dataset_versions', 'eval_cases'):
            assert after[table] == before[table], table
    repeated = client.post(f'/api/v1/scenario-templates/{template_id}/instantiate', json=body)
    assert repeated.status_code == 200 and repeated.json() == result
    assert _snapshot(client) == after


@pytest.mark.parametrize('version,verifier_version', VERSIONS)
@pytest.mark.parametrize('selected', [None, ['R03', 'M02', 'R01']])
def test_onboarding_demo_seeds_exact_revision_and_never_executes(client, version, verifier_version, selected):
    seeded = _seed(client, version, selected)
    _assert_seed(client, seeded, version, verifier_version, selected)
    snapshot = _snapshot(client)
    assert not snapshot['runs'] and not snapshot['experiments'] and not snapshot['evaluations']


@pytest.mark.parametrize('version,verifier_version', VERSIONS)
def test_direct_seed_is_idempotent_including_legacy_config_bytes(client, version, verifier_version):
    selected = ['R03', 'M02', 'R01']
    first = _seed(client, version, selected, path='direct')
    _assert_seed(client, first, version, verifier_version, selected)
    before = _snapshot(client)
    repeated = _seed(client, version, list(reversed(selected)), path='direct')
    assert repeated == first
    assert _snapshot(client) == before


@pytest.mark.parametrize('path', ['api', 'direct'])
def test_adding_new_revision_preserves_every_old_resource_and_evaluation_row(client, path):
    repository = client.app.state.repository
    old = _seed(client, '0.3.0', path=path)
    _assert_seed(client, old, '0.3.0', '1.0')
    repository.save_trace(TraceEnvelopeV1(contract_version='1.2', trace_id='synthetic-old-trace', project_id='p',
        target_id=old['target_id'], target_version='0.3.0', metadata={'synthetic_test': True}))
    response = client.post('/api/v1/evaluations', json={
        'trace_id': 'synthetic-old-trace', 'project_id': 'p', 'case_id': 'public-R03',
        **{key: old[key] for key in ('dataset_id', 'dataset_version', 'tool_contract_set_id',
                                    'tool_contract_version', 'evaluator_set_id', 'evaluator_set_version')}})
    assert response.status_code == 201, response.text
    evaluation = response.json()
    assert evaluation['overall_pass'] is False
    before = _snapshot(client)
    for table in ('eval_cases', 'target_versions', 'tool_contract_versions', 'evaluations', 'evaluation_metrics', 'runs'):
        assert before[table], table
    new = _seed(client, '0.3.1', path=path)
    assert new['dataset_id'] == old['dataset_id']
    _assert_seed(client, new, '0.3.1', '1.1')
    _assert_seed(client, old, '0.3.0', '1.0')
    after = _snapshot(client)
    additions = {'dataset_versions': 1, 'eval_cases': 32, 'target_versions': 2,
                 'tool_contract_versions': 2, 'evaluator_set_versions': 1}
    for table, rows in before.items():
        assert rows <= after[table], f'Historical rows changed in {table}'
        assert len(after[table] - rows) == additions.get(table, 0), table
    fetched = client.get('/api/v1/evaluations/' + evaluation['evaluation_id'])
    assert fetched.status_code == 200 and fetched.json() == evaluation
    assert len(repository.evaluation_history('synthetic-old-trace')) == 1
    assert _seed(client, '0.3.0', path=path) == old
    assert _seed(client, '0.3.1', path=path) == new
    assert _snapshot(client) == after


@pytest.mark.parametrize('surface', SURFACES)
def test_candidate_tool_contracts_pin_selected_version_without_changing_old_schemas(surface):
    old = candidate_tool_contracts(surface, '0.3.0')
    snapshot = [tool.model_dump(mode='json') for tool in old]
    new = candidate_tool_contracts(surface, '0.3.1')
    assert old and {tool.version for tool in old} == {'0.3.0'}
    assert new and {tool.version for tool in new} == {'0.3.1'}
    assert [tool.model_copy(update={'version': '0.3.1'}) for tool in old] == new
    assert [tool.model_dump(mode='json') for tool in old] == snapshot
    assert candidate_tool_contracts(surface, '0.3.0') == old


@pytest.mark.parametrize('version', ['0.3.2', 'latest', ''])
def test_unsupported_versions_are_rejected_without_partial_seed_or_instantiation(client, version):
    before = _snapshot(client)
    with pytest.raises(ValueError):
        load_templates(version)
    with pytest.raises(ValueError):
        seed_business_bank(client.app.state.repository, 'p', version=version)
    response = client.get('/api/v1/scenario-templates', params={'template_version': version})
    assert response.status_code == 400, response.text
    response = client.post('/api/v1/scenario-templates/R03/instantiate', json={
        'project_id': 'p', 'dataset_id': 'invalid', 'version': '1', 'template_version': version})
    assert response.status_code == 422, response.text
    response = client.post('/api/v1/onboarding/demo', json={'project_id': 'p', 'bank_version': version})
    assert response.status_code == 422, response.text
    assert _snapshot(client) == before


def test_new_template_cannot_overwrite_an_existing_old_dataset_revision(client):
    url = '/api/v1/scenario-templates/R03/instantiate'
    body = {'project_id': 'p', 'dataset_id': 'same-dataset', 'version': '1', 'template_version': '0.3.0'}
    first = client.post(url, json=body)
    assert first.status_code == 200, first.text
    before = _snapshot(client)
    changed = client.post(url, json={**body, 'template_version': '0.3.1'})
    assert changed.status_code == 409, changed.text
    assert _snapshot(client) == before
    new = client.post(url, json={**body, 'version': '2', 'template_version': '0.3.1'})
    assert new.status_code == 200, new.text
    _assert_cases(new.json()['cases'], '0.3.1', '1.1', ['R03'])
    stored_old = client.app.state.repository.get_dataset('p', 'same-dataset', '1')
    assert stored_old['cases'] == first.json()['cases']


def test_unqualified_business_seed_and_contracts_choose_new_revision(client):
    seeded = seed_business_bank(client.app.state.repository, 'p', ['R03'])
    _assert_seed(client, seeded, '0.3.1', '1.1', ['R03'])
    for surface in SURFACES:
        assert candidate_tool_contracts(surface) == candidate_tool_contracts(surface, '0.3.1')
