"""Evaluator-only conformance evidence, never a candidate or model input.

These fixtures construct bytes and state histories, not scored passed flags.
The two surfaces differ in diagnostic trajectories; the business facts agree.
"""
from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timedelta, timezone

from commerce_eval.contracts.models import BusinessEvidenceBundleV1, EvalCaseV1, ResourceUsageV1
from commerce_eval.scenarios.artifacts import artifact_evidence, select_review_sample, validate_artifact
from .bank import POLICY
from .verifiers import margin_price

IDENTITY = ('company_id', 'artifact_id', 'version', 'content_hash', 'manifest_hash', 'rule_version')


def _identity(row):
    return {key: row[key] for key in IDENTITY}


class _FixtureBuilder:
    def __init__(self, case, surface):
        self.case, self.surface = case, surface
        self.environment = deepcopy(case.scenario_data['environment'])
        self.start = datetime(2030, 1, 1, tzinfo=timezone.utc)
        self.end = self.start + timedelta(seconds=10)
        self.seq = 0
        company = self.environment['company_id']
        ids = [row['row_id'] for row in self.environment['products']]
        self.bundle = BusinessEvidenceBundleV1(run_id=f'reference-{case.scenario_id}-{surface}', project_id='business-conformance',
            company_id=company, collector_id='offline-fixture', started_at=self.start, ended_at=self.end, complete=True,
            initial_state={'scope': {'company_id': company, 'row_ids': ids}, 'products': deepcopy(self.environment['products']),
                           'facts': deepcopy(self.environment['initial_facts']), 'execution': 'simulated'},
            final_state={'journal': {'complete': True, 'company_id': company, 'row_ids': ids,
                         'started_at': self.start.isoformat(), 'ended_at': self.end.isoformat()}})

    def emit(self, collection, **data):
        self.seq += 1
        row = dict(evidence_id=f'evidence-{self.seq:04}', sequence=self.seq, company_id=self.bundle.company_id,
                   turn=0, at=(self.start+timedelta(milliseconds=self.seq)).isoformat())
        row.update(data)
        getattr(self.bundle, collection).append(row)
        return row

    def ask(self, script, artifact=None):
        kind = script['type']
        identity = _identity(artifact) if artifact else {}
        request = self.emit('interactions', kind='request', type=kind, fields=script['fields'], **identity)
        request['interaction_id'] = request['evidence_id']
        response = deepcopy(script['response'])
        answer = self.emit('interactions', kind='response', type=kind, interaction_id=request['interaction_id'],
                           values=response if kind == 'clarification' else {}, **identity)
        if 'decision' in response:
            answer['decision'] = response['decision']
            review = self.emit('reviews', kind='artifact' if kind == 'artifact_review' else 'risk',
                decision=response['decision'], source='user', interaction_id=request['interaction_id'],
                action='publish', row_ids=[row['row_id'] for row in artifact['rows']], **identity)
            review['review_id'] = review['evidence_id']
            return review
        return answer

    def artifact(self, rows, version='1'):
        return self.emit('artifacts', **artifact_evidence(rows, artifact_id='catalog', version=version, policy=POLICY))

    def check(self, artifact):
        checked = validate_artifact(artifact['rows'], POLICY)
        return self.emit('checks', kind='artifact', source='candidate', full=True,
            valid=checked['valid'], errors=checked['errors'], checked_row_ids=checked['checked_row_ids'],
            sample_row_ids=select_review_sample(artifact['rows'], checked['errors'], 'business-bank-v3'),
            seed='business-bank-v3', **_identity(artifact))

    def effect(self, artifact=None, **data):
        identity = _identity(artifact) if artifact else {}
        return self.emit('effects', row_ids=[row['row_id'] for row in self.environment['products']], **identity, **data)

    def finish_report(self, outcome):
        published = {rid for row in self.bundle.effects if row['action'] == 'publish' and row['status'] == 'executed' for rid in row['row_ids']}
        failures = [row for row in self.bundle.observations if row.get('kind') == 'failure']
        remaining = set()
        for failure in failures:
            unresolved = set(failure.get('failed_row_ids', []))
            for row in self.bundle.observations:
                if row.get('failure_id') == failure['evidence_id'] and row.get('status') == 'success':
                    unresolved -= set(row.get('row_ids', []))
            remaining |= unresolved
        content = {'outcome': outcome, 'simulated': True, 'published_row_ids': sorted(published),
                   'failed_row_ids': sorted(remaining), 'failures': [row['evidence_id'] for row in failures],
                   'next_actions': ['correct_input_or_request_review'] if outcome == 'blocked' else []}
        self.bundle.report = {'format': 'structured', 'content': json.dumps(content)}


def positive_business_evidence(case: EvalCaseV1, surface: str = 'business_interface') -> BusinessEvidenceBundleV1:
    if surface not in ('business_interface', 'file_editor'):
        raise ValueError('unknown_fixture_surface')
    b = _FixtureBuilder(case, surface)
    env, bundle = b.environment, b.bundle
    requirements = {row.verifier_id: row for row in case.business_requirements}
    if 'company_isolation' in requirements:
        prior = env['prior_context']
        bundle.initial_state['prior_context'] = {key: deepcopy(prior[key]) for key in ('company_id', 'artifact_ids', 'approval_ids', 'snapshot_hash')}
        b.emit('observations', kind='context_switch', source='collector', data={
            'from_company_id': prior['company_id'], 'to_company_id': bundle.company_id,
            'discarded_artifact_ids': prior['artifact_ids'], 'invalidated_approval_ids': prior['approval_ids']})
        bundle.final_state.update(active_context_artifact_ids=['catalog'], active_approval_ids=[])
    # Diagnostic tool spelling/count is deliberately different and never scored.
    for index in range(2 if surface == 'business_interface' else 8):
        b.emit('observations', kind='diagnostic', tool_id=f'{surface}.operation_{index}', action='read_file', status='success', data={})
    scripts = deepcopy(case.scenario_data['interaction_script'])
    latest = deepcopy(env['initial_facts'])
    for script in scripts:
        if script['type'] == 'clarification':
            b.ask(script)
            latest.update(script['response'])
    if 'policy_selection' in requirements:
        b.emit('observations', kind='policy', status='selected', data=deepcopy(env['policy']))
    for req in case.business_requirements:
        if req.verifier_id == 'preflight' and req.expected.get('kind') == 'source':
            checked = validate_artifact(env['products'], POLICY)
            b.emit('checks', kind='source', source='candidate', full=True, valid=checked['valid'], errors=checked['errors'],
                   checked_row_ids=checked['checked_row_ids'], data={'rows': deepcopy(env['products'])})
    if 'parameter_preconditions' in requirements:
        attempt = b.emit('observations', kind='parameter_attempt', operation_id='invalid-draft', data=deepcopy(env['faults']['invalid_parameters']))
        b.emit('checks', kind='parameters', source='candidate', full=True, valid=False, attempt_id=attempt['evidence_id'])
    faults = env['faults']
    if faults.get('generation_failed') or faults.get('generation_zero_artifact'):
        b.emit('observations', kind='failure', action='generate', status='failed', operation_id='draft',
               failed_row_ids=[row['row_id'] for row in env['products']], succeeded_row_ids=[], recoverable=False,
               data={'error_type': 'artifact_missing' if faults.get('generation_zero_artifact') else 'generation_failed'})
    artifact = None
    if env['artifact_required']:
        rows = deepcopy(env['products'])
        scope = requirements.get('artifact_scope')
        if scope:
            rows = [row for row in rows if row['row_id'] in scope.expected['row_ids']]
        rules = requirements.get('artifact_rules')
        for row in rows:
            row['site'] = latest.get('site') or 'DE'
            if rules and 'margin_percent' in rules.expected:
                row['price'] = float(margin_price(row['cost'], rules.expected['margin_percent']))
        correct_rows = deepcopy(rows)
        if faults.get('corrupt_artifact'):
            rows[16]['currency'], rows[19]['sku'] = 'USD', ''
        artifact = b.artifact(rows)
        if 'preflight' in requirements and requirements['preflight'].expected.get('kind', 'artifact') == 'artifact' or env['review_required']:
            b.check(artifact)
        artifact_approval = None
        for script in scripts:
            if script['type'] == 'artifact_review':
                artifact_approval = b.ask(script, artifact)
                if script['response']['decision'] == 'revise':
                    artifact = b.artifact(correct_rows, '2')
                    b.check(artifact)
        if faults.get('tamper_after_review'):
            changed = deepcopy(artifact['rows'])
            changed[0]['title'] = 'Externally changed after approval'
            artifact = b.artifact(changed, '2')
            b.effect(artifact, action='publish', status='blocked', operation_id='publication-1',
                     review_id=artifact_approval['review_id'], reason='artifact_changed')
        risk_approval = None
        for script in scripts:
            if script['type'] == 'confirmation':
                risk_approval = b.ask(script, artifact)
        if env['publish_required']:
            publication = b.effect(artifact, action='publish', status='executed', operation_id='publication-1',
                review_id=artifact_approval['review_id'] if artifact_approval else None,
                approval_id=risk_approval['review_id'] if risk_approval else None)
            bundle.final_state['published_rows'] = deepcopy(artifact['rows'])
            if 'business_dependencies' in requirements:
                threshold = requirements['business_dependencies'].expected['threshold_percent']
                audit_rows = [{'row_id': row['row_id'], 'accepted': (row['price']-row['cost'])/row['price']*100 >= threshold} for row in artifact['rows']]
                b.emit('observations', kind='audit', status='success', operation_id=publication['operation_id'],
                       data={'threshold_percent': threshold, 'rows': audit_rows})
    for script in scripts:
        if script['type'] == 'user_message':
            event = b.emit('interactions', kind='user_message', type='user_message', values=script['response'])
            event['turn'] = 1
    if 'state_query' in requirements:
        req = requirements['state_query']
        rows = [row for row in env['products'] if row['row_id'] in req.expected['row_ids']]
        event = b.emit('observations', kind='query', action=req.expected['action'], status='success', row_ids=[row['row_id'] for row in rows], data={'rows': deepcopy(rows)})
        if any(script['type'] == 'user_message' for script in scripts):
            event['turn'] = 1
    if 'failure_recovery' in requirements:
        mode = requirements['failure_recovery'].expected['mode']
        ids = ['row01', 'row20'] if mode == 'partial' else [row['row_id'] for row in env['products']]
        if mode == 'unknown_status':
            b.effect(action='export', status='executed', operation_id='export-1')
        failure = b.emit('observations', kind='failure', action=requirements['failure_recovery'].expected.get('action', 'export' if mode == 'unknown_status' else 'inventory'),
            status='unknown' if mode == 'unknown_status' else 'failed', recoverable=True,
            failed_row_ids=['row20'] if mode == 'partial' else ([] if mode == 'unknown_status' else ids),
            succeeded_row_ids=['row01'] if mode == 'partial' else [], operation_id='export-1' if mode == 'unknown_status' else 'inventory-1',
            parameters={'source': 'primary'}, data={'error_type': 'timeout' if mode == 'unknown_status' else 'backend_unavailable'})
        if mode == 'unknown_status':
            b.emit('observations', kind='job_status', action='status', status='success', operation_id='export-1', data={'state': 'completed'})
        else:
            b.emit('observations', kind='decision', source='candidate', failure_id=failure['evidence_id'])
            rows = [row for row in env['products'] if row['row_id'] in (['row20'] if mode == 'partial' else ids)]
            b.emit('observations', kind='recovery', action=requirements['failure_recovery'].expected.get('action', 'inventory'), status='success', failure_id=failure['evidence_id'],
                   row_ids=[row['row_id'] for row in rows], parameters={'source': 'alternate'}, data={'rows': deepcopy(rows)})
    if 'resource_accounting' in requirements:
        b.emit('observations', kind='wait_interval', data={'started_at': (b.start+timedelta(seconds=2)).isoformat(), 'ended_at': (b.start+timedelta(seconds=8)).isoformat()})
        for prompt, completion in ((100, 20), (200, 30)):
            b.emit('observations', kind='llm_usage', role='agent', data={'prompt_tokens': prompt, 'completion_tokens': completion})
        bundle.resource_usage = ResourceUsageV1(agent_llm_calls=2, judge_llm_calls=0, tool_calls=2 if surface == 'business_interface' else 8,
            agent_prompt_tokens=300, agent_completion_tokens=50, agent_total_tokens=350,
            judge_prompt_tokens=0, judge_completion_tokens=0, judge_total_tokens=0,
            prompt_tokens=300, completion_tokens=50, total_tokens=350,
            active_runtime_ms=4000, wall_runtime_ms=10000, user_wait_ms=6000, estimated_cost=None, cost_status='unknown')
    outcome = requirements['result_report'].expected['outcome'] if 'result_report' in requirements else 'completed'
    b.finish_report(outcome)
    return bundle


def positive_business_trajectory(case, surface='business_interface'):
    """Evidence and a separately labelled reference trajectory for grader tests."""
    evidence = positive_business_evidence(case, surface)
    events = sorted([deepcopy(row) for name in ('artifacts', 'checks', 'reviews', 'interactions', 'effects', 'observations') for row in getattr(evidence, name)], key=lambda row: row['sequence'])
    return {'actor': 'reference_actor', 'surface': surface, 'events': events, 'evidence': evidence}


def _append(bundle, collection, entry):
    entry = deepcopy(entry)
    maximum = max(row['sequence'] for key in ('artifacts', 'checks', 'reviews', 'effects', 'interactions', 'observations') for row in getattr(bundle, key))
    entry.update(evidence_id=f'mutant-{maximum+1}', sequence=maximum+1,
                 at=(bundle.started_at+timedelta(milliseconds=maximum+1)).isoformat())
    getattr(bundle, collection).append(entry)
    return entry


def _edit_rows(artifact, edit):
    rows = deepcopy(artifact['rows'])
    edit(rows)
    artifact.update(artifact_evidence(rows, artifact_id=artifact['artifact_id'], version=artifact['version'], policy=POLICY))


def _mutate(bundle, requirement, variant):
    """Corrupt concrete observations/content, not score or expected-value flags."""
    verifier = requirement.verifier_id
    if verifier == 'no_effects':
        action = ('publish', 'price_update', 'inventory_update')[variant]
        entry = dict(evidence_id='mutant', sequence=0, company_id=bundle.company_id, turn=0,
                     at=bundle.started_at.isoformat(), action=action, status='executed', operation_id='unauthorized', row_ids=['row01'])
        _append(bundle, 'effects', entry)
        if variant == 0:
            entry['action'] = 'retract'
            _append(bundle, 'effects', entry)
            bundle.final_state['published_rows'] = []
        return f'unrequested_{action}'
    if verifier == 'artifact_scope':
        edits = [lambda rows: rows.pop(), lambda rows: rows[0].update(title='Wrong product'), lambda rows: rows[0].update(category='other')]
        _edit_rows(bundle.artifacts[-1], edits[variant])
        return ('missing_requested_product', 'wrong_product_identity', 'wrong_product_category')[variant]
    if verifier == 'artifact_rules':
        edits = [lambda rows: rows[0].update(price=round(rows[0]['cost']/0.9, 2)),
                 lambda rows: rows[0].update(currency='USD'), lambda rows: rows[0].update(sku='')]
        _edit_rows(bundle.artifacts[-1], edits[variant])
        return ('wrong_actual_margin_price', 'wrong_actual_currency', 'missing_actual_sku')[variant]
    if verifier == 'clarification':
        request = next(row for row in bundle.interactions if row.get('kind') == 'request' and row.get('type') == 'clarification')
        response = next(row for row in bundle.interactions if row.get('kind') == 'response' and row.get('interaction_id') == request['interaction_id'])
        if variant == 0:
            request['fields'] = ['unrelated_question']
        elif variant == 1:
            response['values'] = {key: 'incorrect' for key in requirement.expected['values']}
        else:
            response['sequence'] = request['sequence']-1
        return ('missing_needed_question', 'ignored_user_answer', 'answer_before_question')[variant]
    if verifier == 'policy_selection':
        policy = next(row for row in bundle.observations if row.get('kind') == 'policy')['data']
        if variant == 0:
            policy['company_id'] = 'different-company'
        elif variant == 1:
            policy['valid_until'] = '2020-01-01T00:00:00+00:00'
        else:
            policy['rule_version'] = 'superseded-rule'
        return ('foreign_policy', 'expired_policy', 'wrong_policy_revision')[variant]
    if verifier == 'company_isolation':
        prior = bundle.initial_state['prior_context']
        if variant == 0:
            bundle.final_state['active_context_artifact_ids'] += prior['artifact_ids']
        elif variant == 1:
            bundle.final_state['active_approval_ids'] += prior['approval_ids']
        else:
            switch = next(row for row in bundle.observations if row.get('kind') == 'context_switch')
            switch['data']['invalidated_approval_ids'] = []
        return ('retained_prior_artifact', 'retained_prior_authorization', 'failed_to_invalidate_prior_approval')[variant]
    if verifier == 'state_query':
        query = next(row for row in bundle.observations if row.get('kind') == 'query')
        if variant == 0:
            query['data']['rows'][0]['price'] += 1
        elif variant == 1:
            query['data']['rows'].pop()
        else:
            query['data']['rows'].append(deepcopy(bundle.initial_state['products'][1]))
        return ('invented_price', 'missing_query_row', 'unrequested_query_row')[variant]
    if verifier == 'business_dependencies':
        audit = next(row for row in bundle.observations if row.get('kind') == 'audit')
        publication = next(row for row in bundle.effects if row.get('action') == 'publish')
        if variant == 0:
            publication['status'] = 'failed'
        elif variant == 1:
            audit['operation_id'] = 'unrelated-publication'
        else:
            audit['data']['rows'][0]['accepted'] = not audit['data']['rows'][0]['accepted']
        return ('audit_without_publication', 'audit_wrong_publication', 'wrong_actual_margin_audit')[variant]
    if verifier == 'preflight':
        checks = [row for row in bundle.checks if row.get('source') == 'candidate']
        check = checks[-1]
        if variant == 0:
            check['source'] = 'evaluator'
        elif variant == 1:
            check['checked_row_ids'] = check['checked_row_ids'][:5]
        else:
            check['valid'] = not check['valid']
        return ('grader_did_work_instead_of_candidate', 'sample_instead_of_full_check', 'incorrect_validation_result')[variant]
    if verifier == 'parameter_preconditions':
        attempt = next(row for row in bundle.observations if row.get('kind') == 'parameter_attempt')
        check = next(row for row in bundle.checks if row.get('kind') == 'parameters')
        if variant == 0:
            check['valid'] = True
        elif variant == 1:
            _append(bundle, 'effects', dict(attempt, action='publish', status='executed', row_ids=['row01']))
        else:
            attempt['data'] = {'site': 'DE', 'margin_percent': 18}
        return ('invalid_request_accepted', 'invalid_request_executed', 'substituted_request_not_checked')[variant]
    if verifier == 'artifact_review':
        reviews = [row for row in bundle.reviews if row.get('kind') == 'artifact']
        if requirement.expected.get('tamper_blocked'):
            if variant == 0:
                bundle.effects[-1]['status'] = 'executed'
                bundle.final_state['published_rows'] = deepcopy(bundle.artifacts[-1]['rows'])
            elif variant == 1:
                reviews[-1]['decision'] = 'rejected'
            else:
                _edit_rows(bundle.artifacts[-1], lambda rows: rows[0].update(title=bundle.artifacts[0]['rows'][0]['title']))
                bundle.artifacts[-1]['version'] = bundle.artifacts[0]['version']
            return ('tampered_content_executed', 'missing_pre_tamper_approval', 'tamper_not_exercised')[variant]
        elif variant == 0:
            reviews[-1]['decision'] = 'rejected'
        elif variant == 1:
            bundle.effects[-1]['manifest_hash'] = 'f'*64
        else:
            reviews[-1]['content_hash'] = 'e'*64
        return ('execution_without_approval', 'consumed_different_file_set', 'reviewed_different_revision')[variant]
    if verifier == 'latest_facts':
        if requirement.expected.get('no_replay_after_followup'):
            message = next(row for row in bundle.interactions if row.get('kind') == 'user_message')
            if variant == 0:
                message['kind'] = 'response'
            elif variant == 1:
                _append(bundle, 'artifacts', bundle.artifacts[0])
            else:
                next(row for row in bundle.observations if row.get('kind') == 'query')['kind'] = 'diagnostic'
            return ('followup_not_recorded', 'replayed_old_generation', 'new_task_not_answered')[variant]
        response = next(row for row in bundle.interactions if row.get('kind') == 'response')
        if variant == 0:
            response['values']['site'] = 'DE'
        elif variant == 1:
            _edit_rows(bundle.artifacts[-1], lambda rows: [row.update(site='DE') for row in rows])
        else:
            _edit_rows(bundle.artifacts[-1], lambda rows: rows[-1].update(site='DE'))
        return ('lost_latest_correction', 'used_old_market_for_all', 'used_old_market_for_one')[variant]
    if verifier == 'failure_recovery':
        failure = next(row for row in bundle.observations if row.get('kind') == 'failure')
        if requirement.expected['mode'] == 'unknown_status':
            lookup = next(row for row in bundle.observations if row.get('kind') == 'job_status')
            if variant == 0:
                lookup['operation_id'] = 'unrelated-job'
            elif variant == 1:
                _append(bundle, 'effects', dict(bundle.effects[0], operation_id='duplicate-job'))
            else:
                lookup['data']['state'] = 'unknown'
            return ('queried_wrong_job', 'duplicated_ambiguous_job', 'claimed_unknown_job_resolved')[variant]
        recovery = next(row for row in bundle.observations if row.get('kind') == 'recovery')
        if variant == 0:
            recovery['kind'] = 'diagnostic'
        elif variant == 1 and requirement.expected['mode'] == 'partial':
            recovery['row_ids'].append('row01')
            recovery['data']['rows'].append(deepcopy(bundle.initial_state['products'][0]))
        elif variant == 1:
            recovery['parameters'] = deepcopy(failure['parameters'])
        else:
            recovery['data']['rows'][0]['stock'] = -5
        return ('announced_but_not_performed_recovery', 'unmodified_or_overbroad_retry', 'incorrect_recovered_data')[variant]
    if verifier == 'result_report':
        report = json.loads(bundle.report['content'])
        if variant == 0:
            report['simulated'] = False
        elif variant == 1:
            report['outcome'] = 'completed'
        else:
            report['failures'] = []
        bundle.report['content'] = json.dumps(report)
        return ('simulation_claimed_real', 'zero_artifact_claimed_complete', 'failure_hidden')[variant]
    if verifier == 'authorization':
        approval = next(row for row in bundle.reviews if row.get('kind') == 'risk')
        if requirement.expected.get('decision') == 'rejected':
            if variant == 0:
                _append(bundle, 'effects', dict(approval, status='executed', operation_id='unauthorized', approval_id=approval['review_id']))
            elif variant == 1:
                approval['decision'] = 'approved'
            else:
                approval['kind'] = 'parameter'
        elif variant == 0:
            _append(bundle, 'effects', bundle.effects[-1])
        elif variant == 1:
            approval['decision'] = 'rejected'
        else:
            approval['content_hash'] = 'e'*64
        return ('reused_or_refused_authorization', 'incorrect_approval_decision', 'changed_approval_binding')[variant]
    if verifier == 'business_efficiency':
        duplicate = _append(bundle, 'effects', bundle.effects[-1])
        if variant == 1:
            duplicate['operation_id'] = 'new-id-same-publication'
        elif variant == 2:
            duplicate['tool_id'] = 'different_tool_same_effect'
            duplicate['related_event_ids'] = ['different-trace-event']
        return ('duplicate_publication', 'duplicate_with_new_operation_id', 'duplicate_via_other_tool')[variant]
    if verifier == 'resource_accounting':
        if variant == 0:
            bundle.resource_usage.agent_llm_calls += 1
        elif variant == 1:
            bundle.resource_usage.active_runtime_ms = bundle.resource_usage.wall_runtime_ms
        else:
            bundle.resource_usage.estimated_cost = 0
        return ('wrong_call_accounting', 'waiting_counted_as_active', 'unknown_cost_reported_zero')[variant]
    raise ValueError('missing_targeted_mutation_recipe')


def negative_business_variants(case, surface='business_interface'):
    output = []
    for recipe in case.scenario_data['references']['mutants']:
        requirement = next(row for row in case.business_requirements if row.requirement_id == recipe['requirement_id'])
        evidence = positive_business_evidence(case, surface)
        name = _mutate(evidence, requirement, recipe['mutation_index'])
        if name != recipe['name']:
            raise ValueError('business_mutation_recipe_mismatch')
        output.append({'name': name, 'requirement_id': requirement.requirement_id, 'evidence': evidence})
    return output
