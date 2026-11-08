import re
import unittest
from pathlib import Path


MIGRATIONS_DIR = Path(__file__).resolve().parents[1] / "migrations" / "versions"


class AlembicRevisionIdTests(unittest.TestCase):
    def test_revision_ids_fit_alembic_version_column(self):
        revisions = {}
        for path in sorted(MIGRATIONS_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            revision_match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
            if not revision_match:
                continue
            revision = revision_match.group(1)
            self.assertLessEqual(
                len(revision),
                32,
                f"{path.name}: revision {revision!r} exceeds alembic_version.version_num VARCHAR(32)",
            )
            self.assertNotIn(revision, revisions, f"Duplicate Alembic revision {revision!r}")
            revisions[revision] = path.name

        self.assertTrue(revisions, "No Alembic revisions were discovered")

    def test_down_revision_references_exist(self):
        revisions = set()
        parents = {}
        for path in sorted(MIGRATIONS_DIR.glob("*.py")):
            source = path.read_text(encoding="utf-8")
            revision_match = re.search(r'^revision\s*=\s*["\']([^"\']+)["\']', source, re.MULTILINE)
            if not revision_match:
                continue
            revision = revision_match.group(1)
            revisions.add(revision)
            parent_match = re.search(r'^down_revision\s*=\s*(.+)$', source, re.MULTILINE)
            parents[revision] = parent_match.group(1).strip() if parent_match else "None"

        for revision, parent in parents.items():
            if parent == "None":
                continue
            parent_ids = re.findall(r'["\']([^"\']+)["\']', parent)
            for parent_id in parent_ids:
                self.assertIn(parent_id, revisions, f"{revision} references missing parent {parent_id}")


if __name__ == "__main__":
    unittest.main()
