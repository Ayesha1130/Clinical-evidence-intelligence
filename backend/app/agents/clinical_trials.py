from app.agents.base import BaseAgent
from app.integrations.clinical_trials import ClinicalTrialsClient
from app.schemas.source_agents import ClinicalTrialSchema, ClinicalTrialsAgentOutput, SourceAgentInput


class ClinicalTrialsAgent(BaseAgent[SourceAgentInput, ClinicalTrialsAgentOutput]):
    name = "clinical_trials_research"
    timeout_seconds = 30.0
    max_attempts = 3

    def __init__(self, client: ClinicalTrialsClient) -> None:
        self._client = client

    async def _execute(self, payload: SourceAgentInput) -> ClinicalTrialsAgentOutput:
        seen_nct_ids: set[str] = set()
        trials: list[ClinicalTrialSchema] = []

        for query in payload.queries:
            results = await self._client.search(query, max_results=payload.max_results_per_query)
            for trial in results:
                if not trial.nct_id or trial.nct_id in seen_nct_ids:
                    continue
                seen_nct_ids.add(trial.nct_id)
                trials.append(
                    ClinicalTrialSchema(
                        nct_id=trial.nct_id,
                        title=trial.title,
                        status=trial.status,
                        conditions=trial.conditions,
                        interventions=trial.interventions,
                        study_type=trial.study_type,
                        phase=trial.phase,
                        enrollment=trial.enrollment,
                        sponsor=trial.sponsor,
                        start_date=trial.start_date,
                        completion_date=trial.completion_date,
                        outcomes=trial.outcomes,
                        locations=trial.locations,
                        brief_summary=trial.brief_summary,
                    )
                )

        return ClinicalTrialsAgentOutput(trials=trials)
