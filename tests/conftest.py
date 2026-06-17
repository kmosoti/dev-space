import ast
import inspect
import pytest
from _pytest.logging import LogCaptureFixture


@pytest.fixture(autouse=True)
def verify_observability_logging(caplog: LogCaptureFixture, request):
    """
    Enforces runtime system observability.
    Fails if the logic under review does not emit structured log telemetry.
    Can be bypassed by marking a test with @pytest.mark.no_observability.
    """
    yield
    
    # Allow explicit opt-out for utility functions that genuinely don't log
    if "no_observability" in request.node.keywords:
        return
        
    if not caplog.records:
        pytest.fail(
            "Observability Enforcement Breach: The active execution path "
            "completed without generating structural log telemetry."
        )


def pytest_collection_modifyitems(items):
    """
    Statically analyzes collected test objects via AST token validation
    to guarantee test quality parameters.
    """
    for item in items:
        try:
            source = inspect.getsource(item.obj)
        except (TypeError, OSError):
            continue

        tree = ast.parse(source)
        nodes = list(ast.walk(tree))

        has_assert = any(isinstance(node, ast.Assert) for node in nodes)
        has_property = any(
            isinstance(node, ast.Attribute) and getattr(node, "attr", "") == "given"
            for node in nodes
        )
        has_snapshot = any(
            isinstance(node, ast.Name) and getattr(node, "id", "") == "snapshot"
            for node in nodes
        )

        if not (has_assert or has_property or has_snapshot):
            pytest.fail(
                f"Agent Security Boundary Violation: Test '{item.name}' "
                f"lacks explicit logic verification targets."
            )

def pytest_configure(config):
    config.addinivalue_line(
        "markers", "no_observability: Mark a test to bypass the structured logging requirement"
    )
