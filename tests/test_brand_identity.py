"""Regression checks for the Campus Fire ERP brand layer and pre-login experience."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET


ROOT = Path(__file__).resolve().parents[1]


class BrandIdentityTests(unittest.TestCase):
    def test_original_brand_mark_is_valid_svg(self):
        logo = ROOT / "app" / "static" / "img" / "campus-fire-mark.svg"
        root = ET.parse(logo).getroot()
        self.assertTrue(root.tag.endswith("svg"))
        self.assertIn("viewBox", root.attrib)
        self.assertIn("Campus Fire ERP", logo.read_text(encoding="utf-8"))

    def test_pre_login_intro_is_separate_from_authenticated_shell(self):
        login = (ROOT / "app" / "templates" / "login.html").read_text(encoding="utf-8")
        shell = (ROOT / "app" / "templates" / "_shell.html").read_text(encoding="utf-8")
        self.assertIn('id="loginSplash"', login)
        self.assertIn("sessionStorage.getItem('campus-fire-intro-seen')", login)
        self.assertIn("window.location.replace('/')", login)
        self.assertNotIn('id="loginSplash"', shell)

    def test_login_intro_has_accessible_skip_and_reduced_motion(self):
        login = (ROOT / "app" / "templates" / "login.html").read_text(encoding="utf-8")
        self.assertIn("דילוג לפתיחת המערכת", login)
        self.assertIn("prefers-reduced-motion:reduce", login)
        self.assertIn("4700", login)

    def test_adaptive_brand_tokens_exist_for_both_themes(self):
        css = (ROOT / "app" / "static" / "css" / "design-system.css").read_text(encoding="utf-8")
        self.assertIn('--color-bg:            #101c2c', css)
        self.assertIn('--color-bg:            #f4f6f8', css)
        self.assertIn('--color-primary:       #22b8b0', css)
        self.assertIn('--color-primary:       #087f82', css)
        self.assertIn('--color-accent-gold:', css)


    def test_global_ui_finish_includes_accessibility_and_mobile_workspaces(self):
        css = (ROOT / "app" / "static" / "css" / "design-system.css").read_text(encoding="utf-8")
        self.assertIn(":focus-visible", css)
        self.assertIn("prefers-reduced-motion: reduce", css)
        self.assertIn(".ai-grid", css)
        self.assertIn(".doc-list-card", css)
        self.assertIn(".ff-grid", css)

    def test_dashboard_uses_campus_fire_identity_and_refined_kpis(self):
        dashboard = (ROOT / "app" / "templates" / "org_dashboard.html").read_text(encoding="utf-8")
        self.assertIn("לוח בקרה ארגוני | Campus Fire ERP", dashboard)
        self.assertIn("Dashboard presentation refinement", dashboard)
        self.assertIn("grid-template-columns: repeat(6, minmax(0, 1fr))", dashboard)


if __name__ == "__main__":
    unittest.main()
