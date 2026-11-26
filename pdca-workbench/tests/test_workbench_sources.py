from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException

from app.workbench_sources import SalesQuery, VemoryQuery, _sales, _vemory


def test_personal_sales_token_must_belong_to_verified_vps_user(monkeypatch):
    monkeypatch.delenv("PDCA_WORKBENCH_AISALES_VPS_TOKEN", raising=False)
    query = SalesQuery(kind="ainative-sales", report="reach", start="2026-11-20", end="2026-11-26")
    target = {"rows": [{"subject_type": "employee", "exact_match": True, "employee_id": 23}]}
    with patch("app.workbench_sources.get_settings", return_value=SimpleNamespace(aisales_mcp_token="fixture")), \
         patch("app.duzhan_ledger.mcp_call", side_effect=[target, {"rows": [], "permission_scope": {"mapped_local_user_id": 24}}]) as call:
        with pytest.raises(HTTPException) as denied:
            _sales(query, 123)
        assert denied.value.status_code == 403
        assert [item.args[0] for item in call.call_args_list] == ["business.resolve_subject", "business.catalog"]
        assert all("vps_user_id" not in item.args[1] for item in call.call_args_list)


def test_meeting_lookup_uses_only_unique_vps_binding(monkeypatch):
    monkeypatch.setenv("VEMORY_OPENAPI_KEY", "fixture")
    query = VemoryQuery(kind="vemory-todos", start="2026-11-20", end="2026-11-26")
    roster = [{"vpsUserId": 123, "vemoryUserId": 10}, {"vpsUserId": 124, "vemoryUserId": 11}]
    with patch("app.workbench_sources.load_vemory_users", return_value=roster), \
         patch("app.workbench_sources.fetch_vemory_todos", return_value=[]) as fetch:
        with pytest.raises(HTTPException) as denied:
            _vemory(query, 999)
        assert denied.value.status_code == 403
        fetch.assert_not_called()
        assert _vemory(query, 123)["total"] == 0
        assert fetch.call_args.args[0] == roster[0]
