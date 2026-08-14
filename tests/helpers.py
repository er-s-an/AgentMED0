from __future__ import annotations

from fastapi.testclient import TestClient

from agentmed.kernel import ROLE_PRINCIPALS


def authorize_local_shadow(client: TestClient, case_id: str) -> dict:
    plan = client.post(
        f"/v1/cases/{case_id}/release-plans",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
        json={},
    )
    assert plan.status_code == 200, plan.text
    auth = client.post(
        f"/v1/cases/{case_id}/gates/release-authorization",
        headers={"X-AgentMED-Principal": ROLE_PRINCIPALS["lead"]},
        json={},
    )
    assert auth.status_code == 200, auth.text
    work_order_id = auth.json()["work_order"]["id"]
    approved = client.post(
        f"/v1/cases/{case_id}/approvals",
        headers={"X-AgentMED-Principal": "human:cli"},
        json={"work_order_id": work_order_id},
    )
    assert approved.status_code == 200, approved.text
    return {
        "plan": plan.json(),
        "authorization": auth.json(),
        "approval": approved.json(),
        "work_order_id": work_order_id,
    }
