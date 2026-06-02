"""
共享测试 fixtures
"""

from unittest.mock import MagicMock, patch

import pytest

from src.output.redliner import Redliner
from src.output.report import ReportGenerator
from src.output.security import SecurityPreprocessor


@pytest.fixture
def redliner():
    return Redliner(llm_client=None)


@pytest.fixture
def generator():
    return ReportGenerator()


@pytest.fixture
def security_processor():
    return SecurityPreprocessor()


@pytest.fixture
def mock_freshness():
    """Mock freshness checker for report tests."""
    with patch("src.output.report.get_freshness_checker") as mock:
        checker = MagicMock()
        checker.check_all.return_value = MagicMock(overall_status="healthy", warnings=[])
        checker.get_freshness_disclaimer.return_value = ""
        mock.return_value = checker
        yield mock
