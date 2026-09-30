from __future__ import annotations

import ast
import unittest
from pathlib import Path

def test_clash_profile_does_not_require_geosite_ru() -> None:
    source = Path(__file__).parents[1] / "app" / "main.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    assignment = next(
        node for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "CLASH_RULES_RU_SPLIT" for target in node.targets)
    )
    rules = ast.literal_eval(assignment.value)

    assert "GEOSITE,ru,DIRECT" not in rules
    assert "GEOIP,ru,DIRECT,no-resolve" in rules


def test_clash_subscription_does_not_advertise_a_fake_traffic_limit() -> None:
    source = Path(__file__).parents[1] / "app" / "main.py"
    module = ast.parse(source.read_text(encoding="utf-8"))
    response_builder = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "clash_profile_response"
    )

    assert "Subscription-Userinfo" not in ast.unparse(response_builder)


def load_tests(
    loader: unittest.TestLoader,
    tests: unittest.TestSuite,
    pattern: str | None,
) -> unittest.TestSuite:
    return unittest.TestSuite(
        unittest.FunctionTestCase(test)
        for test in (
            test_clash_profile_does_not_require_geosite_ru,
            test_clash_subscription_does_not_advertise_a_fake_traffic_limit,
        )
    )
