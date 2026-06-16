"""Generated MARAG pytest harness fixtures and hooks."""

from __future__ import annotations

import logging

import pytest


def pytest_addoption(parser):
    parser.addoption(
        "--marag-env",
        action="store",
        default="placeholder",
        help="Generated MARAG automation target environment.",
    )


def pytest_configure(config):
    config.addinivalue_line("markers", "generated: generated MARAG automation testcase")
    config.addinivalue_line("markers", "evidence_bound: generated test linked to evidence")
    config.addinivalue_line("markers", "requirement(id): BRD requirement trace marker")
    config.addinivalue_line("markers", "mock: explicit generated mock execution")


@pytest.fixture(scope="session")
def automation_context(pytestconfig):
    return {
        "environment": pytestconfig.getoption("--marag-env"),
        "mode": "dependency_aware_generation",
    }


@pytest.fixture(autouse=True)
def precise_test_logging(request):
    log = logging.getLogger(request.node.name)
    log.info("starting generated testcase: %s", request.node.nodeid)
    yield
    log.info("finished generated testcase: %s", request.node.nodeid)
