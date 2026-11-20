"""Canonical labels must be established before Orion captures result metadata."""
import json
import re

COHORTS = ('positive_auto', 'positive_manual', 'negative_auto')


def scene_labels(row):
    labels = row.get('labels', row.get('scenario_labels', []))
    if isinstance(labels, str):
        labels = json.loads(labels) if labels.startswith('[') else labels.split(',')
    return {str(v).strip() for v in labels}


def full_scene_label(period):
    release = period['release']
    if not re.fullmatch(r'gen4-release-\d{8}', release):
        raise ValueError('A dated gen4 release is required for Scenario labels')
    pattern = rf'ra_repro_full_\d{{8}}_{release[-8:]}'
    explicit = period.get('scenario_creation_label')
    if explicit:
        if not re.fullmatch(pattern, explicit):
            raise ValueError('Scenario namespace does not match release')
        return explicit
    labels = set(period.get('scenario_query_labels', []))
    for group in period.get('scenario_query_label_sets', []):
        labels.update(group)
    existing = {label for label in labels if re.fullmatch(pattern, label)}
    if len(existing) > 1:
        raise ValueError('Multiple full namespaces require an explicit canonical label')
    if existing:
        return existing.pop()
    end = period['cycle_end'].replace('-', '')
    if not re.fullmatch(r'\d{8}', end):
        raise ValueError('A closed cycle is required for Scenario labels')
    return f'ra_repro_full_{end}_{release[-8:]}'


def validate_scene_labels(row, label, release, cohort):
    labels = scene_labels(row)
    trigger = 'ManualTrigger' if cohort == 'positive_manual' else 'AutoTrigger'
    required = {label, f'{label}_{release}', f'{label}_{cohort}', f'{label}_{trigger}'}
    if cohort not in COHORTS or not required <= labels:
        raise ValueError('Scenario is missing canonical full/cohort/trigger labels')
    if any(v.startswith('ra_repro_cycle_') for v in labels):
        raise ValueError('Legacy cycle labels must be consolidated before submission')
    for value in labels:
        namespace = re.match(r'(ra_repro_full_\d{8}_\d{8})(?:_|$)', value)
        if namespace and namespace[1] != label:
            raise ValueError('Scenario has multiple full namespaces')
    if labels & {f'{label}_{c}' for c in COHORTS} != {f'{label}_{cohort}'}:
        raise ValueError('Scenario cohort labels disagree with frozen GT')
    if labels & {f'{label}_AutoTrigger', f'{label}_ManualTrigger'} != {f'{label}_{trigger}'}:
        raise ValueError('Scenario trigger group is ambiguous')


def cohort_label_update(row, label, release, cohort):
    """Reconcile GT-only drift before first submission, retaining other labels.

    Namespace, source identity and trigger changes require their own review.
    The caller must establish the current GT and prohibit changes to submitted jobs.
    """
    labels = scene_labels(row)
    present = [c for c in COHORTS if f'{label}_{c}' in labels]
    if len(present) != 1 or cohort not in COHORTS:
        raise ValueError('Scenario cohort labels are ambiguous')
    previous = present[0]
    validate_scene_labels(row, label, release, previous)
    if (previous == 'positive_manual') != (cohort == 'positive_manual'):
        raise ValueError('Scenario trigger change requires review')
    if previous == cohort:
        return None
    updated = labels - {f'{label}_{previous}'} | {f'{label}_{cohort}'}
    validate_scene_labels({'labels': sorted(updated)}, label, release, cohort)
    return sorted(updated)
