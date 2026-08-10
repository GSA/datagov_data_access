import pytest

from datagov_data_access.shared.constants import RECORD_TYPE_VALUES


def test_record_type_values_includes_all_dcat_types():
    assert "dataset" in RECORD_TYPE_VALUES
    assert "catalog_record" in RECORD_TYPE_VALUES
    assert "data_service" in RECORD_TYPE_VALUES
    assert "dataset_series" in RECORD_TYPE_VALUES
    assert "catalog" in RECORD_TYPE_VALUES


def test_record_type_values_has_expected_count():
    assert len(RECORD_TYPE_VALUES) == 5
