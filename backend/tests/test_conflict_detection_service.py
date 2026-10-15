"""
Pure unit tests for conflict detection — no DB required since
detect_conflicts() operates on plain objects with the attributes it needs.
"""
import uuid
from types import SimpleNamespace

from app.services.conflict_detection_service import (
    NOT_ESTABLISHED,
    detect_conflicts,
    directions_conflict,
    explain_difference,
)


def _study(**overrides):
    defaults = dict(
        id=uuid.uuid4(),
        population=None,
        study_type=None,
        follow_up=None,
        intervention=None,
        sample_size=None,
        study_findings=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _finding(outcome: str, direction: str, effect_size: str | None = None):
    return SimpleNamespace(outcome=outcome, effect_direction=direction, effect_size=effect_size)


# ---------- direction rule table ----------


def test_benefit_vs_no_effect_is_a_conflict():
    assert directions_conflict("BENEFIT", "NO_EFFECT") is not None


def test_benefit_vs_harm_is_a_strong_conflict_with_higher_confidence():
    benefit_harm = directions_conflict("BENEFIT", "HARM")
    benefit_no_effect = directions_conflict("BENEFIT", "NO_EFFECT")
    assert benefit_harm is not None
    assert benefit_harm > benefit_no_effect


def test_no_effect_vs_no_effect_is_not_a_conflict():
    assert directions_conflict("NO_EFFECT", "NO_EFFECT") is None


def test_unclear_is_never_a_confirmed_conflict():
    assert directions_conflict("UNCLEAR", "BENEFIT") is None
    assert directions_conflict("UNCLEAR", "HARM") is None
    assert directions_conflict("UNCLEAR", "UNCLEAR") is None


def test_same_direction_is_not_a_conflict():
    assert directions_conflict("BENEFIT", "BENEFIT") is None
    assert directions_conflict("HARM", "HARM") is None


# ---------- detect_conflicts over a study set ----------


def test_two_studies_disagreeing_on_same_outcome_produce_one_conflict():
    study_a = _study()
    study_a.study_findings = [_finding("cardiovascular events", "BENEFIT")]
    study_b = _study()
    study_b.study_findings = [_finding("cardiovascular events", "NO_EFFECT")]

    conflicts = detect_conflicts([study_a, study_b])
    assert len(conflicts) == 1
    assert conflicts[0].study_a_id == study_a.id
    assert conflicts[0].study_b_id == study_b.id


def test_same_study_cannot_conflict_with_itself():
    study = _study()
    study.study_findings = [_finding("cardiovascular events", "BENEFIT")]
    conflicts = detect_conflicts([study, study])
    assert conflicts == []


def test_no_conflict_when_outcomes_differ():
    study_a = _study()
    study_a.study_findings = [_finding("cardiovascular events", "BENEFIT")]
    study_b = _study()
    study_b.study_findings = [_finding("weight loss", "NO_EFFECT")]

    assert detect_conflicts([study_a, study_b]) == []


def test_unclear_finding_does_not_produce_a_conflict():
    study_a = _study()
    study_a.study_findings = [_finding("cardiovascular events", "BENEFIT")]
    study_b = _study()
    study_b.study_findings = [_finding("cardiovascular events", "UNCLEAR")]

    assert detect_conflicts([study_a, study_b]) == []


def test_duplicate_conflict_prevention_across_multiple_matching_findings():
    """Even if a study reports the same outcome twice (shouldn't normally
    happen, but robustness matters), the same study pair + outcome must
    only produce one conflict record."""
    study_a = _study()
    study_a.study_findings = [
        _finding("cardiovascular events", "BENEFIT"),
        _finding("Cardiovascular Events", "BENEFIT"),  # same outcome, different casing
    ]
    study_b = _study()
    study_b.study_findings = [_finding("cardiovascular events", "HARM")]

    conflicts = detect_conflicts([study_a, study_b])
    assert len(conflicts) == 1


def test_three_studies_only_compares_distinct_pairs():
    study_a = _study()
    study_a.study_findings = [_finding("cardiovascular events", "BENEFIT")]
    study_b = _study()
    study_b.study_findings = [_finding("cardiovascular events", "HARM")]
    study_c = _study()
    study_c.study_findings = [_finding("cardiovascular events", "NO_EFFECT")]

    conflicts = detect_conflicts([study_a, study_b, study_c])
    assert len(conflicts) == 3
    pairs = {frozenset({c.study_a_id, c.study_b_id}) for c in conflicts}
    assert len(pairs) == 3


# ---------- explanation heuristics ----------


def test_explanation_cites_population_difference_when_present():
    study_a = _study(population="adults with type 2 diabetes")
    study_b = _study(population="elderly patients with heart failure")
    assert explain_difference(study_a, study_b) == "population differences"


def test_explanation_falls_back_to_not_established_when_nothing_differs():
    study_a = _study()
    study_b = _study()
    assert explain_difference(study_a, study_b) == NOT_ESTABLISHED


def test_explanation_cites_sample_size_when_ratio_is_large():
    study_a = _study(sample_size=100)
    study_b = _study(sample_size=5000)
    assert "sample size" in explain_difference(study_a, study_b)


def test_explanation_never_invents_a_clinical_mechanism():
    """Explanation must only ever be one of the metadata-grounded strings
    or the literal fallback — never free text describing a biological
    mechanism, which would be fabricated."""
    study_a = _study(population="group A")
    study_b = _study(population="group B")
    explanation = explain_difference(study_a, study_b)
    allowed = {
        "population differences",
        "study design differences",
        "follow-up duration differences",
        "intervention differences",
        "sample size differences (statistical uncertainty)",
        NOT_ESTABLISHED,
    }
    assert explanation in allowed
