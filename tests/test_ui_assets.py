import re
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class UIAssetTests(unittest.TestCase):
    def test_lucide_sprite_is_valid_and_contains_every_shell_icon(self):
        sprite = ROOT / "app/static/img/lucide-sprite.svg"
        templates = [ROOT / "app/templates/_shell.html", ROOT / "app/templates/org_dashboard.html", ROOT / "app/templates/fire_forms.html", ROOT / "app/templates/document_intelligence.html", ROOT / "app/templates/sites.html", ROOT / "app/templates/equipment.html", ROOT / "app/templates/tasks.html", ROOT / "app/templates/audits.html", ROOT / "app/templates/suppliers.html", ROOT / "app/templates/reports.html", ROOT / "app/templates/index.html", ROOT / "app/templates/login.html", ROOT / "app/templates/settings.html", ROOT / "app/templates/users.html", ROOT / "app/templates/audit_log.html", ROOT / "app/templates/admin_storage.html"]
        tree = ET.parse(sprite)
        ids = {
            node.attrib["id"]
            for node in tree.iter()
            if node.tag.rsplit("}", 1)[-1] == "symbol" and "id" in node.attrib
        }
        referenced = set()
        for template in templates:
            source = template.read_text(encoding="utf-8")
            referenced.update(re.findall(r"#(icon-[a-z0-9-]+)", source))
            referenced.update("icon-" + name for name in re.findall(r"(?:icon|ffIcon|dashboardIcon)\('([a-z0-9-]+)'\)", source))
        self.assertTrue(referenced, "The templates should use local Lucide symbols")
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
        self.assertIn("fields.every(hasMappedFireCoordinates)", fire_forms)

    def test_document_intelligence_has_search_and_clear_gemini_cost_notice(self):
        documents = (ROOT / "app/templates/document_intelligence.html").read_text(encoding="utf-8")
        self.assertIn("AI.filter(this.value)", documents)
        self.assertIn("filter,analyze", documents)
        self.assertIn("ניתוח Gemini עשוי לצרוך מכסת API או לגרור עלות", documents)
        self.assertIn("ai-overview-grid", documents)

    def test_operational_pages_share_the_module_header_system(self):
        pages = ["sites", "equipment", "tasks", "audits", "suppliers"]
        for page in pages:
            source = (ROOT / f"app/templates/{page}.html").read_text(encoding="utf-8")
            self.assertIn("ds-module-hero", source, f"{page} should use the shared module header")
        reports = (ROOT / "app/templates/reports.html").read_text(encoding="utf-8")
        self.assertIn("reports-hero", reports)
        design_system = (ROOT / "app/static/css/design-system.css").read_text(encoding="utf-8")
        self.assertIn(".ds-module-hero", design_system)

    def test_work_plan_page_follows_the_supplied_workbook_structure(self):
        tasks = (ROOT / "app/templates/tasks.html").read_text(encoding="utf-8")
        for column in [
            "שלב / שבוע", "משימה / נושא מרכזי", "נכס רלוונטי", "מס׳ תיק",
            "טופס להגשה", "גורם אחראי", "תאריך יעד", "סטטוס נוכחי",
            "הערות ודגשים", "ביצוע בפועל", "ימים ליעד", "התראת מועד", "תחום",
        ]:
            self.assertIn(column, tasks)
        self.assertIn("fireOverdueCount", tasks)
        self.assertIn("trackingDomainFilter", tasks)
        self.assertIn("trackingCaseFilter", tasks)
        self.assertIn("trackingPhaseFilter", tasks)
        self.assertIn("trackingOwnerFilter", tasks)
        self.assertIn("waiting_approval", tasks)
        dashboard = (ROOT / "app/templates/org_dashboard.html").read_text(encoding="utf-8")
        self.assertIn("waiting_approval: 'ממתין לאישור'", dashboard)
        self.assertIn('href="/tasks"', dashboard)
        self.assertIn("לתוכנית העבודה", dashboard)
        dashboard_service = (ROOT / "app/services/org_dashboard_service.py").read_text(encoding="utf-8")
        self.assertIn("גרסה: 2026-11-22-v2", dashboard_service)
        self.assertIn("ייבוא טבלת מעקב כבאות והצלה", dashboard_service)

    def test_all_pages_use_one_clear_hebrew_typography_system(self):
        shell = (ROOT / "app/templates/_shell.html").read_text(encoding="utf-8")
        login = (ROOT / "app/templates/login.html").read_text(encoding="utf-8")
        self.assertLess(shell.index("css/tailwind.generated.css"), shell.index("css/typography.css"))
        self.assertIn("css/typography.css", login)
        typography = (ROOT / "app/static/css/typography.css").read_text(encoding="utf-8")
        self.assertIn('--font-family-ui: Arial, "Segoe UI", sans-serif', typography)
        self.assertIn("body *::before, body *::after", typography)
        self.assertIn("--type-h1", typography)
        self.assertIn("--type-table", typography)
        self.assertIn("font-weight: 700 !important", typography)
        self.assertNotIn("fonts.googleapis.com", typography)
        self.assertNotIn("@import", typography)

    def test_sidebar_is_ordered_around_the_fire_safety_workflow(self):
        shell = (ROOT / "app/templates/_shell.html").read_text(encoding="utf-8")
        labels = [
            "תמונת מצב", "תוכנית עבודה", "נכסים ומבנים",
            "ליקויים וביקורות", "טפסים להגשה", "אישורים ורישיונות",
            "מסמכים וראיות", "ספקים ואנשי מקצוע", "ציוד כיבוי אש", "דוחות ובקרה",
        ]
        positions = [shell.index(label) for label in labels]
        self.assertEqual(positions, sorted(positions))
        self.assertIn("ds-nav-hint", shell)
        expected_titles = {
            "tasks.html": "תוכנית עבודה",
            "sites.html": "נכסים ומבנים",
            "fire_forms.html": "טפסים להגשה",
            "document_intelligence.html": "מסמכים וראיות",
            "suppliers.html": "ספקים ואנשי מקצוע",
            "reports.html": "דוחות ובקרה",
            "org_dashboard.html": "תמונת מצב",
        }
        for filename, title in expected_titles.items():
            page = (ROOT / "app/templates" / filename).read_text(encoding="utf-8")
            self.assertIn(title, page)
        styles = (ROOT / "app/static/css/design-system.css").read_text(encoding="utf-8")
        self.assertIn(".ds-nav-hint", styles)

    def test_home_dashboard_counts_unverified_documents_as_needing_review(self):
        index = (ROOT / "app/templates/index.html").read_text(encoding="utf-8")
        self.assertIn("פג תוקף / דורש בדיקה", index)
        self.assertIn("_data.alerts?.needs_review?.length", index)
        self.assertIn("totalRequirements?Math.round", index)
        self.assertIn("לא זמין", index)

    def test_admin_and_login_surfaces_keep_security_and_cost_disclosures(self):
        users = (ROOT / "app/templates/users.html").read_text(encoding="utf-8")
        self.assertIn("ההתחברות עדיין", users)
        for page in ["settings", "users", "audit_log", "admin_storage"]:
            source = (ROOT / f"app/templates/{page}.html").read_text(encoding="utf-8")
            self.assertIn("ds-module-hero", source, f"{page} should use the shared module header")
        storage = (ROOT / "app/templates/admin_storage.html").read_text(encoding="utf-8")
        self.assertIn("storage-cost-note", storage)
        self.assertIn("עשוי לצרוך מכסת API או לגרור עלות", storage)
        login = (ROOT / "app/templates/login.html").read_text(encoding="utf-8")
        self.assertIn("loginSplash", login)
        self.assertIn("loginThemeToggle", login)


if __name__ == "__main__":
    unittest.main()
