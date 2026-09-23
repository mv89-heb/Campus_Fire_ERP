import json
import unittest
from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Document, Site, Supplier, Audit
from app.services.document_link_service import resolve_document
from app.services.gemini_document_service import findings, actions

class TestDocumentAI(unittest.TestCase):
    def setUp(self):
        class TestConfig(Config):
            TESTING=True
            SECRET_KEY="test-secret"
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:"
            AUTO_CREATE_DB=True
            GEMINI_API_KEY=None
        self.app=create_app(TestConfig)
        self.ctx=self.app.app_context(); self.ctx.push(); db.create_all()
    def tearDown(self):
        db.session.remove(); self.ctx.pop()
    def test_empty(self):
        d=Document(file_name="x.pdf",file_path="x.pdf",file_hash="a"*64)
        self.assertEqual(findings(d),[]); self.assertEqual(actions(d),{})

    def test_unique_relationships_are_auto_linked(self):
        site=Site(name="קמפוס מרכז",address="רחוב ראשי 1")
        supplier=Supplier(company_name="ספק מערכות אש",supplier_number="SUP-10")
        db.session.add_all([site,supplier]); db.session.flush()
        audit=Audit(audit_number="AUD-2026-10",site_id=site.id)
        db.session.add(audit); db.session.flush()
        d=Document(file_name="audit.pdf",file_path="audit.pdf",file_hash="c"*64,
                   ai_actions_json=json.dumps({"audit_number":"AUD-2026-10","site_name":"קמפוס מרכז","supplier_name":"ספק מערכות אש","supplier_number":"SUP-10"},ensure_ascii=False))
        db.session.add(d); db.session.flush()
        links=resolve_document(d,persist=True)
        self.assertEqual(d.audit_id,audit.id)
        self.assertEqual(d.site_id,site.id)
        self.assertEqual(d.supplier_id,supplier.id)
        self.assertEqual(links["audit"]["status"],"linked")

    def test_ambiguous_site_is_not_auto_linked(self):
        db.session.add_all([Site(name="קמפוס צפון"),Site(name="קמפוס צפון")]); db.session.flush()
        d=Document(file_name="x.pdf",file_path="x.pdf",file_hash="d"*64,
                   ai_actions_json=json.dumps({"site_name":"קמפוס צפון"},ensure_ascii=False))
        db.session.add(d); db.session.flush()
        links=resolve_document(d,persist=False)
        self.assertIsNone(d.site_id)
        self.assertEqual(links["site"]["status"],"candidate")

    def test_json(self):
        d=Document(file_name="x.pdf",file_path="x.pdf",file_hash="b"*64,
                   ai_findings_json=json.dumps([{"title":"ליקוי"}],ensure_ascii=False),
                   ai_actions_json=json.dumps({"missing_items":["אישור"]},ensure_ascii=False))
        self.assertEqual(findings(d)[0]["title"],"ליקוי")
        self.assertEqual(actions(d)["missing_items"],["אישור"])
if __name__=="__main__": unittest.main()
