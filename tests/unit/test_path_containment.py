"""Unit tests for resolve_path_within_base (path-traversal containment).

These lock in the P0 security fix: the file-serving / run-deletion endpoints must
reject any client-supplied path that escapes the allowed base directory, using
real path containment (realpath + commonpath), NOT a bypassable startswith check.
"""

import os
import tempfile

import pytest

from custom_types.exceptions import PathContainmentError
from utils.validation import resolve_path_within_base


@pytest.fixture
def base_dir():
    with tempfile.TemporaryDirectory() as d:
        yield os.path.realpath(d)


def test_nested_relative_path_is_contained(base_dir):
    result = resolve_path_within_base(base_dir, "sub/file.html")
    assert result == os.path.join(base_dir, "sub", "file.html")


def test_absolute_path_inside_base_is_accepted(base_dir):
    inside = os.path.join(base_dir, "a", "b.json")
    assert resolve_path_within_base(base_dir, inside) == inside


def test_dotdot_traversal_is_blocked(base_dir):
    with pytest.raises(PathContainmentError):
        resolve_path_within_base(base_dir, "../../etc/passwd")


def test_absolute_escape_is_blocked(base_dir):
    with pytest.raises(PathContainmentError):
        resolve_path_within_base(base_dir, "/etc/passwd")


def test_sibling_prefix_bypass_is_blocked(base_dir):
    # A naive startswith(base) check would WRONGLY allow "<base>-evil/..."; commonpath does not.
    with pytest.raises(PathContainmentError):
        resolve_path_within_base(base_dir, f"{base_dir}-evil/secret")


def test_relative_base_is_realpathed(tmp_path, monkeypatch):
    # A relative base like "output" must be resolved against cwd before containment.
    monkeypatch.chdir(tmp_path)
    os.makedirs("output/sub", exist_ok=True)
    result = resolve_path_within_base("output", "sub/x.json")
    assert result == os.path.join(os.path.realpath(tmp_path), "output", "sub", "x.json")
