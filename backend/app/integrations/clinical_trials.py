"""
Real ClinicalTrials.gov API (v2) integration.

Docs: https://clinicaltrials.gov/data-api/api
No API key required. This is a straightforward JSON REST API, so unlike
PubMed there's no XML parsing — just careful, defensive field extraction
since not every trial record populates every field.
"""
from dataclasses import dataclass, field

import httpx

CTGOV_BASE = "https://clinicaltrials.gov/api/v2/studies"


@dataclass
class ClinicalTrial:
    nct_id: str
    title: str
    status: str | None = None
    conditions: list[str] = field(default_factory=list)
    interventions: list[str] = field(default_factory=list)
    study_type: str | None = None
    phase: list[str] = field(default_factory=list)
    enrollment: int | None = None
    sponsor: str | None = None
    start_date: str | None = None
    completion_date: str | None = None
    outcomes: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    brief_summary: str | None = None


class ClinicalTrialsIntegrationError(Exception):
    pass


class ClinicalTrialsClient:
    def __init__(self) -> None:
        pass  # no credentials required for this API

    async def search(self, query: str, max_results: int = 20) -> list[ClinicalTrial]:
        params = {
            "query.term": query,
            "pageSize": min(max_results, 100),
            "format": "json",
        }
        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(CTGOV_BASE, params=params)
        if resp.status_code != 200:
            raise ClinicalTrialsIntegrationError(
                f"ClinicalTrials.gov search failed with status {resp.status_code}"
            )
        data = resp.json()
        studies = data.get("studies", [])
        return [self._parse_study(s) for s in studies[:max_results]]

    @staticmethod
    def _parse_study(raw: dict) -> ClinicalTrial:
        protocol = raw.get("protocolSection", {})

        identification = protocol.get("identificationModule", {})
        nct_id = identification.get("nctId", "")
        title = (
            identification.get("officialTitle")
            or identification.get("briefTitle")
            or "Untitled trial"
        )

        status_module = protocol.get("statusModule", {})
        status = status_module.get("overallStatus")
        start_date = (status_module.get("startDateStruct") or {}).get("date")
        completion_date = (status_module.get("completionDateStruct") or {}).get("date")

        conditions_module = protocol.get("conditionsModule", {})
        conditions = conditions_module.get("conditions", []) or []

        design_module = protocol.get("designModule", {})
        study_type = design_module.get("studyType")
        phases = design_module.get("phases", []) or []
        enrollment_info = design_module.get("enrollmentInfo", {})
        enrollment = enrollment_info.get("count")

        arms_module = protocol.get("armsInterventionsModule", {})
        interventions = [
            i.get("name") for i in (arms_module.get("interventions") or []) if i.get("name")
        ]

        sponsor_module = protocol.get("sponsorCollaboratorsModule", {})
        sponsor = (sponsor_module.get("leadSponsor") or {}).get("name")

        outcomes_module = protocol.get("outcomesModule", {})
        outcomes = [
            o.get("measure")
            for o in (outcomes_module.get("primaryOutcomes") or [])
            if o.get("measure")
        ]

        contacts_module = protocol.get("contactsLocationsModule", {})
        locations = []
        for loc in contacts_module.get("locations", []) or []:
            city = loc.get("city")
            country = loc.get("country")
            if city or country:
                locations.append(", ".join(p for p in [city, country] if p))

        description_module = protocol.get("descriptionModule", {})
        brief_summary = description_module.get("briefSummary")

        return ClinicalTrial(
            nct_id=nct_id,
            title=title,
            status=status,
            conditions=conditions,
            interventions=interventions,
            study_type=study_type,
            phase=phases,
            enrollment=enrollment,
            sponsor=sponsor,
            start_date=start_date,
            completion_date=completion_date,
            outcomes=outcomes,
            locations=locations,
            brief_summary=brief_summary,
        )
