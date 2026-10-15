from app.integrations.clinical_trials import ClinicalTrialsClient

SAMPLE_STUDY = {
    "protocolSection": {
        "identificationModule": {
            "nctId": "NCT01234567",
            "officialTitle": "A Randomized Trial of Metformin for Cardiovascular Risk Reduction in T2D",
            "briefTitle": "Metformin CV Risk Trial",
        },
        "statusModule": {
            "overallStatus": "COMPLETED",
            "startDateStruct": {"date": "2018-03"},
            "completionDateStruct": {"date": "2022-11"},
        },
        "conditionsModule": {"conditions": ["Type 2 Diabetes Mellitus"]},
        "designModule": {
            "studyType": "INTERVENTIONAL",
            "phases": ["PHASE3"],
            "enrollmentInfo": {"count": 4200},
        },
        "armsInterventionsModule": {
            "interventions": [{"name": "Metformin"}, {"name": "Placebo"}]
        },
        "sponsorCollaboratorsModule": {"leadSponsor": {"name": "Example University"}},
        "outcomesModule": {
            "primaryOutcomes": [{"measure": "Major adverse cardiovascular events"}]
        },
        "contactsLocationsModule": {
            "locations": [{"city": "Boston", "country": "United States"}]
        },
        "descriptionModule": {"briefSummary": "This trial evaluates metformin's effect on CV outcomes."},
    }
}


def test_parses_all_core_fields():
    trial = ClinicalTrialsClient._parse_study(SAMPLE_STUDY)
    assert trial.nct_id == "NCT01234567"
    assert "Metformin" in trial.title
    assert trial.status == "COMPLETED"
    assert trial.conditions == ["Type 2 Diabetes Mellitus"]
    assert trial.interventions == ["Metformin", "Placebo"]
    assert trial.study_type == "INTERVENTIONAL"
    assert trial.phase == ["PHASE3"]
    assert trial.enrollment == 4200
    assert trial.sponsor == "Example University"
    assert trial.start_date == "2018-03"
    assert trial.completion_date == "2022-11"
    assert trial.outcomes == ["Major adverse cardiovascular events"]
    assert trial.locations == ["Boston, United States"]
    assert trial.brief_summary and "metformin" in trial.brief_summary.lower()


def test_falls_back_to_brief_title_and_handles_missing_sections():
    minimal = {
        "protocolSection": {
            "identificationModule": {"nctId": "NCT09999999", "briefTitle": "Minimal Trial"},
        }
    }
    trial = ClinicalTrialsClient._parse_study(minimal)
    assert trial.nct_id == "NCT09999999"
    assert trial.title == "Minimal Trial"
    assert trial.status is None
    assert trial.conditions == []
    assert trial.enrollment is None
