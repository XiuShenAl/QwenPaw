# -*- coding: utf-8 -*-
"""Contract test: GovernanceAdapter interface exists and is mockable."""
import pytest

from qwenpaw.governance import (
    GovernanceAction,
    GovernanceAdapter,
    GovernanceDecision,
)


def test_governance_action_values():
    assert GovernanceAction.ALLOW == "allow"
    assert GovernanceAction.DENY == "deny"
    assert GovernanceAction.ASK == "ask"
    assert GovernanceAction.SANDBOX_FALLBACK == "sandbox_fallback"


def test_governance_decision_constructable():
    decision = GovernanceDecision(
        action=GovernanceAction.ALLOW,
        reason="test",
    )
    assert decision.action == GovernanceAction.ALLOW
    assert decision.reason == "test"
    assert decision.sandbox_config is None


def test_governance_decision_with_sandbox():
    decision = GovernanceDecision(
        action=GovernanceAction.SANDBOX_FALLBACK,
        reason="policy",
        sandbox_config={"mode": "strict"},
    )
    assert decision.sandbox_config == {"mode": "strict"}


@pytest.mark.asyncio
async def test_governance_adapter_not_implemented():
    adapter = GovernanceAdapter()
    with pytest.raises(NotImplementedError):
        await adapter.evaluate("tool", {}, None)


@pytest.mark.asyncio
async def test_governance_adapter_mockable():
    class MockAdapter(GovernanceAdapter):
        async def evaluate(self, tool_name, input_data, context):
            return GovernanceDecision(
                action=GovernanceAction.ALLOW,
                reason="mock says ok",
            )

    adapter = MockAdapter()
    result = await adapter.evaluate("shell", {"cmd": "ls"}, None)
    assert result.action == GovernanceAction.ALLOW
