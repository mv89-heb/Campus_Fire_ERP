import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UIAssetTests(unittest.TestCase):
    def test_lucide_sprite_is_valid_and_contains_every_shell_icon(self):
        sprite = ROOT / "app/static/img/lucide-sprite.svg"
        templates = [ROOT / "app/templates/_shell.html", ROOT / "app/templates/org_dashboard.html", ROOT / "app/templates/fire_forms.html"]
        tree = ET.parse(sprite)
        ids = {
            node.attrib["id"]
            for node in tree.iter()
            if node.tag.rsplit("}", 1)[-1] == "symbol" and "id" in node.attrib
        }
        referenced = set().union(*(set(re.findall(r"#(icon-[a-z0-9-]+)", template.read_text(encoding="utf-8"))) for template in templates))
        self.assertTrue(referenced, "The shared shell should use local Lucide symbols")
        self.assertFalse(referenced - ids, f"Missing local icon symbols: {sorted(referenced - ids)}")

    def test_shell_uses_local_rtl_stylesheets_and_prefixed_utilities(self):
        shell = (ROOT / "app/templates/_shell.html").read_text(encoding="utf-8")
        generated = ROOT / "app/static/css/tailwind.generated.css"
        self.assertIn('lang="he" dir="rtl"', shell)
        self.assertIn("css/design-system.css", shell)
        self.assertIn("css/tailwind.generated.css", shell)
        dashboard = (ROOT / "app/templates/org_dashboard.html").read_text(encoding="utf-8")
        self.assertIn("מדד מסמכים וציוד", dashboard)
        self.assertNotIn("מוכנות כללית", dashboard)
        self.assertIn("dashboard-insight-grid", dashboard)
        self.assertTrue(generated.is_file(), "Compiled Tailwind CSS must be committed for Render")
        css = generated.read_text(encoding="utf-8")
        self.assertIn(".tw-flex", css)
        self.assertIn(".tw-items-center", css)
        self.assertNotIn("*,::before,::after", css, "Tailwind preflight must remain disabled")

    def test_fire_forms_only_enable_print_when_mapping_coordinates_exist(self):
        fire_forms = (ROOT / "app/templates/fire_forms.html").read_text(encoding="utf-8")
        self.assertIn("hasMappedFireCoordinates", fire_forms)
        self.assertIn('disabled title="יש להגדיר מיקומים לפני מילוי"', fire_forms)
        self.assertIn("mapped?'ready':'needs'", fire_forms)


if __name__ == "__main__":
    unittest.main()
