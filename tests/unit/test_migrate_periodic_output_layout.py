"""
Unit tests for the periodic-output layout migration (flat -> per-community nested).

Verifies plan_moves and migrate against a temporary directory tree.
"""

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location("migrate_periodic_output_layout", ROOT / "scripts" / "migrate_periodic_output_layout.py")
_mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig)


def _make_flat_tree(base: Path, names: list[str]) -> None:
    base.mkdir(parents=True, exist_ok=True)
    for n in names:
        (base / n).mkdir()


class TestPlanMoves:
    def test_maps_flat_runs_to_community_subdirs(self, tmp_path):
        base = tmp_path / "generate_periodic_newsletter"
        _make_flat_tree(base, ["langtalks_2025-10-01_to_2025-10-26", "mcp_israel_2026-02-01_to_2026-02-28"])
        moves = _mig.plan_moves(base)
        dests = {src.name: dest for src, dest in moves}
        assert dests["langtalks_2025-10-01_to_2025-10-26"] == base / "langtalks" / "langtalks_2025-10-01_to_2025-10-26"
        assert dests["mcp_israel_2026-02-01_to_2026-02-28"] == base / "mcp_israel" / "mcp_israel_2026-02-01_to_2026-02-28"

    def test_handles_trailing_suffix_runs(self, tmp_path):
        base = tmp_path / "generate_periodic_newsletter"
        _make_flat_tree(base, ["ail_2026-04-17_to_2026-05-10_merged"])
        moves = _mig.plan_moves(base)
        assert len(moves) == 1
        src, dest = moves[0]
        assert dest == base / "ail" / "ail_2026-04-17_to_2026-05-10_merged"

    def test_skips_non_run_dirs(self, tmp_path):
        base = tmp_path / "generate_periodic_newsletter"
        _make_flat_tree(base, ["langtalks", "random_folder"])  # bare community + junk
        assert _mig.plan_moves(base) == []


class TestMigrate:
    def test_apply_moves_and_is_idempotent(self, tmp_path):
        base = tmp_path / "generate_periodic_newsletter"
        run = "langtalks_2025-10-01_to_2025-10-26"
        _make_flat_tree(base, [run])
        (base / run / "marker.txt").write_text("x")

        # Apply.
        assert _mig.migrate(base, apply=True) == 0
        moved = base / "langtalks" / run
        assert moved.is_dir()
        assert (moved / "marker.txt").read_text() == "x"
        assert not (base / run).exists()

        # Re-run: nothing left to migrate at the top level.
        assert _mig.plan_moves(base) == []
        assert _mig.migrate(base, apply=True) == 0

    def test_refuses_to_overwrite_existing_destination(self, tmp_path):
        base = tmp_path / "generate_periodic_newsletter"
        run = "langtalks_2025-10-01_to_2025-10-26"
        _make_flat_tree(base, [run])
        # Pre-create a colliding destination.
        (base / "langtalks" / run).mkdir(parents=True)
        assert _mig.migrate(base, apply=True) == 1
        # Source must remain untouched.
        assert (base / run).exists()
