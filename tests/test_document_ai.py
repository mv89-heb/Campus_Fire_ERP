import json
import unittest
from app import create_app
from app.config import Config
from app.extensions import db
from app.models import Document
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
    def test_json(self):
        d=Document(file_name="x.pdf",file_path="x.pdf",file_hash="b"*64,
                   ai_findings_json=json.dumps([{"title":"ליקוי"}],ensure_ascii=False),
                   ai_actions_json=json.dumps({"missing_items":["אישור"]},ensure_ascii=False))
        self.assertEqual(findings(d)[0]["title"],"ליקוי")
        self.assertEqual(actions(d)["missing_items"],["אישור"])
if __name__=="__main__": unittest.main()
