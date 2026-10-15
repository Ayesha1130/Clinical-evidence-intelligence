"""
Shared helper for tests that call POST /api/research/{id}/start.

Since Phase 8, /start dispatches the pipeline as a background asyncio task
and returns immediately with status RUNNING (202) — tests need to poll
GET /api/research/{id} until the query reaches a terminal status before
asserting on the outcome, the same way a real frontend would poll (or
subscribe to the SSE stream) rather than expecting the result synchronously.
"""
import asyncio

TERMINAL_STATUSES = {"COMPLETED", "PARTIAL", "FAILED"}


async def wait_for_terminal_status(client, query_id, timeout: float = 60.0, poll_interval: float = 0.02) -> dict:
    """Polls GET /api/research/{id}/job until status is terminal, or raises
    TimeoutError. The polling itself yields control back to the event loop
    (asyncio.sleep), which is what actually lets the background pipeline
    task make progress when running under the ASGI-transport test client.
    Returns the full job dict (status, evidence_grade, failure_summary)."""
    elapsed = 0.0
    while elapsed < timeout:
        resp = await client.get(f"/api/research/{query_id}/job")
        data = resp.json()
        if data.get("status") in TERMINAL_STATUSES:
            return data
        await asyncio.sleep(poll_interval)
        elapsed += poll_interval
    raise TimeoutError(f"Research query {query_id} did not reach a terminal status within {timeout}s")
