import json
import unittest
from types import SimpleNamespace

from app.api.fire_forms_routes import _has_valid_fire_form_mapping


def template(fields, page_count=2):
    return SimpleNamespace(fields_schema=json.dumps(fields), page_count=page_count)


def valid_field(key="institution_name", page=0):
    return {
        "key": key,
        "label": "שם המוסד",
        "page": page,
        "x": 0.5,
        "y": 0.4,
        "font_size": 10,
    }


class FireFormMappingValidationTests(unittest.TestCase):
    def test_accepts_complete_valid_mapping(self):
        item = template([valid_field(), valid_field("address", 1)])
        self.assertTrue(_has_valid_fire_form_mapping(item))

    def test_rejects_mapping_when_any_field_has_no_coordinates(self):
        invalid = valid_field("address")
        invalid.pop("x")
        item = template([valid_field(), invalid])
        self.assertFalse(_has_valid_fire_form_mapping(item))

    def test_rejects_empty_mapping(self):
        self.assertFalse(_has_valid_fire_form_mapping(template([])))

    def test_rejects_non_object_field(self):
        self.assertFalse(_has_valid_fire_form_mapping(template([valid_field(), "bad"])))

    def test_rejects_out_of_range_page(self):
        self.assertFalse(_has_valid_fire_form_mapping(template([valid_field(page=2)])))


if __name__ == "__main__":
    unittest.main()
