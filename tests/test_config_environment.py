import unittest

from app.config import _is_production_environment


class ProductionEnvironmentDetectionTests(unittest.TestCase):
    def test_render_runtime_is_production_even_without_flask_env(self):
        self.assertTrue(_is_production_environment('development', True))

    def test_explicit_production_environment_is_recognized(self):
        self.assertTrue(_is_production_environment('prod', False))

    def test_local_testing_environment_remains_non_production(self):
        self.assertFalse(_is_production_environment('testing', False))


if __name__ == '__main__':
    unittest.main()
