from __future__ import annotations

import ast
import inspect

from dcs_copilot_cloud.aircraft import raw
from dcs_copilot_cloud.database import (
    FlightRuleStatistic,
    FlightSessionRecord,
    FlightSummaryRecord,
)


def test_raw_telemetry_store_has_no_persistence_dependency() -> None:
    tree = ast.parse(inspect.getsource(raw))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported.update(
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    )

    assert not {
        module
        for module in imported
        if "sqlalchemy" in module
        or module.endswith("accounts")
        or module.endswith("database")
    }


def test_flight_persistence_contains_only_bounded_semantic_records() -> None:
    persisted_columns = {
        column.name
        for model in (FlightSessionRecord, FlightSummaryRecord, FlightRuleStatistic)
        for column in model.__table__.columns
    }

    assert persisted_columns.isdisjoint(
        {
            "raw_telemetry",
            "telemetry",
            "catalog",
            "snapshot",
            "deltas",
            "controls",
            "values_json",
        }
    )
