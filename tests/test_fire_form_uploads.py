import unittest

import fitz
from flask import Flask

from app.api.fire_forms_routes import _as_pdf, fire_forms_bp


class FireFormUploadValidationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config['MAX_PDF_BYTES'] = 10 * 1024 * 1024
        self.context = self.app.app_context()
        self.context.push()

    def tearDown(self):
        self.context.pop()

    def test_accepts_valid_pdf_and_preserves_page_count(self):
        doc = fitz.open()
        doc.new_page()
        doc.new_page()
        data = doc.tobytes()
        doc.close()

        normalized, page_count = _as_pdf(data, "fire-form.pdf")
        self.assertTrue(normalized.startswith(b"%PDF-"))
        self.assertEqual(page_count, 2)

    def test_rejects_renamed_non_pdf_payload(self):
        with self.assertRaises(ValueError):
            _as_pdf(b"not a pdf", "fire-form.pdf")

    def test_rejects_unsupported_extension(self):
        with self.assertRaises(ValueError):
            _as_pdf(b"content", "certificate.docx")

    def test_rejects_empty_upload(self):
        with self.assertRaises(ValueError):
            _as_pdf(b"", "certificate.pdf")

    def test_page_preview_route_is_registered_once(self):
        app = Flask("fire-form-route-test")
        app.register_blueprint(fire_forms_bp)
        routes = [
            rule for rule in app.url_map.iter_rules()
            if rule.rule.endswith("/pages/<int:page_number>.png")
        ]
        self.assertEqual(len(routes), 1)


if __name__ == "__main__":
    unittest.main()
