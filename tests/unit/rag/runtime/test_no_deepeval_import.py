"""
Regression guard: the runtime evaluation package must not depend on DeepEval.

Walks every module file under src/rag/evaluation/runtime/ and parses its AST
to confirm no `import deepeval` or `from deepeval ...` statement appears.
"""

import ast
import pathlib

import pytest


def _runtime_dir() -> pathlib.Path:
    # tests/unit/rag/runtime/ -> repo root -> src/rag/evaluation/runtime/
    here = pathlib.Path(__file__).resolve()
    repo_root = here.parents[4]
    return repo_root / "src" / "rag" / "evaluation" / "runtime"


def _runtime_modules() -> list[pathlib.Path]:
    runtime_dir = _runtime_dir()
    if not runtime_dir.exists():
        # Returning empty list lets pytest collect a skipped placeholder;
        # the regression guard is enforced once the package is built.
        return []
    return sorted(p for p in runtime_dir.glob("*.py"))


def test_runtime_package_exists():
    """The runtime evaluation package must exist (production code)."""
    assert _runtime_dir().exists(), (
        f"Runtime evaluation package missing at {_runtime_dir()}"
    )


@pytest.mark.parametrize("module_path", _runtime_modules() or [pathlib.Path("__missing__")])
def test_runtime_module_has_no_deepeval_import(module_path: pathlib.Path):
    if module_path.name == "__missing__":
        pytest.skip("Runtime package not built yet; covered by test_runtime_package_exists")
    source = module_path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(module_path))

    offenders: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name == "deepeval" or alias.name.startswith("deepeval."):
                    offenders.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            if node.module and (node.module == "deepeval" or node.module.startswith("deepeval.")):
                offenders.append(f"from {node.module} import ...")

    assert not offenders, (
        f"{module_path.name} imports DeepEval, which is banned in runtime modules: {offenders}"
    )
