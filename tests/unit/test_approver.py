import pytest

from patchthecode.security.approver import AutoApprover, LoggingApprover


@pytest.mark.asyncio
async def test_auto_approver_approves():
    assert await AutoApprover().approve("open_pull_request", {"repository": "x"}) is True


@pytest.mark.asyncio
async def test_logging_approver_blocks_by_default():
    assert await LoggingApprover().approve("open_pull_request", {"repository": "x"}) is False