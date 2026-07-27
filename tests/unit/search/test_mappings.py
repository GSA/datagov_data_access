from datagov_data_access.search.mappings import MAPPINGS


def test_access_level_field_mapping():
    assert MAPPINGS["properties"]["access_level"]["type"] == "keyword"
