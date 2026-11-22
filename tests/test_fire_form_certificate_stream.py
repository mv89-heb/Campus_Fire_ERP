import io
import unittest

from werkzeug.test import EnvironBuilder

from app import InMemoryCertificateRequest


class FireFormCertificateStreamTests(unittest.TestCase):
    def test_batch_print_certificate_is_streamed_in_memory(self):
        request = InMemoryCertificateRequest(
            EnvironBuilder(path="/api/fire-form-templates/print-package", method="POST").get_environ()
        )
        stream = request._get_file_stream(1024, "application/pdf", "certificate.pdf", 1024)
        try:
            self.assertIsInstance(stream, io.BytesIO)
        finally:
            stream.close()

    def test_single_template_print_certificate_is_streamed_in_memory(self):
        request = InMemoryCertificateRequest(
            EnvironBuilder(path="/api/fire-form-templates/42/print-package", method="POST").get_environ()
        )
        stream = request._get_file_stream(1024, "application/pdf", "certificate.pdf", 1024)
        try:
            self.assertIsInstance(stream, io.BytesIO)
        finally:
            stream.close()


if __name__ == "__main__":
    unittest.main()
