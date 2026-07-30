import os

import pytest

from datagov_data_access.search.client import OpenSearchClient
from tests.conftest import FakeClient


def test_init_creates_index_when_missing(monkeypatch):
    fake_client = FakeClient(exists=False)
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_test_opensearch_client",
        staticmethod(lambda host: fake_client),
    )

    OpenSearchClient(test_host="localhost")

    created = fake_client.indices.created
    assert created is not None
    assert created["index"] == OpenSearchClient.INDEX_NAME
    assert created["body"]["mappings"] == OpenSearchClient.MAPPINGS
    assert created["body"]["settings"] == OpenSearchClient.SETTINGS


def test_mappings_include_catalog_compatible_fields():

    client = OpenSearchClient.from_environment()
    mappings = client.MAPPINGS["properties"]
    normalizer = client.SETTINGS["analysis"]["normalizer"][client.KEYWORD_NORMALIZER]

    assert mappings["dcat"]["properties"]["isPartOf"] == {"type": "keyword"}
    assert mappings["theme"] == {
        "type": "text",
        "analyzer": client.TEXT_ANALYZER,
        "search_analyzer": client.TEXT_ANALYZER,
    }
    assert mappings["distribution_titles"]["type"] == "text"
    assert mappings["publisher"]["fields"]["raw"] == {"type": "keyword"}
    assert mappings["publisher"]["fields"]["normalized"] == {
        "type": "keyword",
        "normalizer": client.KEYWORD_NORMALIZER,
    }
    assert mappings["keyword"]["fields"]["normalized"] == {
        "type": "keyword",
        "normalizer": client.KEYWORD_NORMALIZER,
    }
    assert normalizer == {
        "type": "custom",
        "filter": ["lowercase"],
    }


def test_from_environment_uses_aws_client(monkeypatch):
    fake_client = FakeClient(exists=True)
    captured = {}

    def fake_aws_client(host):
        captured["host"] = host
        return fake_client

    monkeypatch.setenv("OPENSEARCH_HOST", "search.example.es.amazonaws.com")
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_aws_opensearch_client",
        staticmethod(fake_aws_client),
    )
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_test_opensearch_client",
        staticmethod(lambda host: FakeClient(exists=True)),
    )

    iface = OpenSearchClient.from_environment()

    assert iface.client is fake_client
    assert captured["host"] == "search.example.es.amazonaws.com"


def test_from_environment_requires_host(monkeypatch):
    monkeypatch.delenv("OPENSEARCH_HOST", raising=False)

    with pytest.raises(ValueError):
        OpenSearchClient.from_environment()

    with pytest.raises(ValueError):
        # both hostnames
        OpenSearchClient(test_host="not-empty", aws_host="also-not-empty")


def test_for_host_targets_a_cluster_the_environment_does_not_name(monkeypatch):
    """The point of for_host: reach a second cluster without mutating globals.

    Rebinding OPENSEARCH_HOST affects every consumer in the process, including any live
    write path, so "which cluster does this write to?" would depend on timing.
    """
    fake_client = FakeClient(exists=True)
    captured = {}

    def fake_aws_client(host, access_key=None, secret_key=None):
        captured.update(host=host, access_key=access_key, secret_key=secret_key)
        return fake_client

    monkeypatch.setenv("OPENSEARCH_HOST", "live.example.es.amazonaws.com")
    monkeypatch.setenv("OPENSEARCH_ACCESS_KEY", "live-access")
    monkeypatch.setenv("OPENSEARCH_SECRET_KEY", "live-secret")
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_aws_opensearch_client",
        staticmethod(fake_aws_client),
    )

    iface = OpenSearchClient.for_host(
        "next.example.es.amazonaws.com",
        access_key="next-access",
        secret_key="next-secret",
    )

    assert iface.client is fake_client
    assert captured == {
        "host": "next.example.es.amazonaws.com",
        "access_key": "next-access",
        "secret_key": "next-secret",
    }
    # The environment still describes the live cluster.
    assert os.environ["OPENSEARCH_HOST"] == "live.example.es.amazonaws.com"


def test_for_host_falls_back_to_environment_credentials(monkeypatch):
    captured = {}

    def fake_aws_client(host, access_key=None, secret_key=None):
        captured.update(access_key=access_key, secret_key=secret_key)
        return FakeClient(exists=True)

    monkeypatch.setattr(
        OpenSearchClient,
        "_create_aws_opensearch_client",
        staticmethod(fake_aws_client),
    )

    OpenSearchClient.for_host("only.example.es.amazonaws.com")

    # Omitted rather than explicitly None, so the real factory reads the environment.
    assert captured == {"access_key": None, "secret_key": None}


def test_for_host_picks_the_transport_from_the_host(monkeypatch):
    """Callers should not have to know whether a host is a real AWS cluster."""
    used = []
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_aws_opensearch_client",
        staticmethod(lambda host, **kwargs: used.append("aws") or FakeClient()),
    )
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_test_opensearch_client",
        staticmethod(lambda host: used.append("test") or FakeClient()),
    )

    OpenSearchClient.for_host("search.example.es.amazonaws.com")
    OpenSearchClient.for_host("localhost")

    assert used == ["aws", "test"]


def test_for_host_requires_a_host():
    with pytest.raises(ValueError):
        OpenSearchClient.for_host("")


def test_ensure_index_can_be_skipped(monkeypatch):
    """For callers that manage the index themselves, or only read.

    Creating an index as a side effect of connecting means a read-only consumer can
    resurrect an index someone is deliberately rebuilding.
    """
    fake_client = FakeClient(exists=False)
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_test_opensearch_client",
        staticmethod(lambda host: fake_client),
    )

    OpenSearchClient(test_host="localhost", ensure_index=False)

    assert fake_client.indices.created is None


def test_for_host_can_skip_ensure_index(monkeypatch):
    fake_client = FakeClient(exists=False)
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_test_opensearch_client",
        staticmethod(lambda host: fake_client),
    )

    OpenSearchClient.for_host("localhost", ensure_index=False)

    assert fake_client.indices.created is None


def test_client_records_the_host_it_connected_to(monkeypatch):
    """So a caller can log or assert which cluster it actually reached."""
    monkeypatch.setattr(
        OpenSearchClient,
        "_create_test_opensearch_client",
        staticmethod(lambda host: FakeClient(exists=True)),
    )

    assert OpenSearchClient.for_host("localhost").host == "localhost"


@pytest.mark.parametrize(
    "host,is_aws",
    [
        ("vpc-x.us-gov-west-1.es.amazonaws.com", True),
        ("es.amazonaws.com", True),
        ("https://vpc-x.us-gov-west-1.es.amazonaws.com", True),
        ("localhost", False),
        ("opensearch-next", False),
        # A lookalike domain must not select the signed transport.
        ("evil.es.amazonaws.com.attacker.net", False),
        ("", False),
        (None, False),
    ],
)
def test_is_aws_host_classification(host, is_aws):
    assert OpenSearchClient.is_aws_host(host) is is_aws


def test_dcat_modified_field_mapping(opensearch_client):
    """Test that DCAT modified field is mapped as keyword type."""
    mappings = opensearch_client.MAPPINGS

    assert "dcat" in mappings["properties"]
    assert mappings["properties"]["dcat"]["type"] == "nested"
    assert "properties" in mappings["properties"]["dcat"]

    dcat_properties = mappings["properties"]["dcat"]["properties"]
    assert "modified" in dcat_properties
    assert dcat_properties["modified"]["type"] == "keyword"


def test_dcat_issued_field_mapping(opensearch_client):
    """Test that DCAT issued field is mapped as keyword type."""
    mappings = opensearch_client.MAPPINGS
    dcat_properties = mappings["properties"]["dcat"]["properties"]

    assert "issued" in dcat_properties
    assert dcat_properties["issued"]["type"] == "keyword"


def test_other_mappings_unchanged(opensearch_client):
    """Test that other field mappings are preserved."""
    mappings = opensearch_client.MAPPINGS

    # Verify other fields are still present
    assert mappings["properties"]["title"]["type"] == "text"
    assert mappings["properties"]["slug"]["type"] == "keyword"
    assert mappings["properties"]["keyword"]["type"] == "text"
    assert mappings["properties"]["keyword"]["fields"]["raw"]["type"] == "keyword"
    assert mappings["properties"]["organization"]["type"] == "nested"


def test_keyword_normalized_sub_field_exists(opensearch_client):
    """
    keyword.normalized sub-field must be present for case-insensitive search.
    """
    keyword_fields = opensearch_client.MAPPINGS["properties"]["keyword"]["fields"]

    assert "normalized" in keyword_fields
    assert keyword_fields["normalized"]["type"] == "keyword"
    assert keyword_fields["normalized"]["normalizer"] == (
        opensearch_client.KEYWORD_NORMALIZER
    )


def test_lowercase_normalizer_defined_in_settings(opensearch_client):
    """
    The lowercase_normalizer must be declared in SETTINGS so OpenSearch
    can apply it when doing index.
    """
    normalizers = opensearch_client.SETTINGS.get("analysis", {}).get("normalizer", {})

    assert opensearch_client.KEYWORD_NORMALIZER in normalizers
    normalizer_cfg = normalizers[opensearch_client.KEYWORD_NORMALIZER]
    assert normalizer_cfg["type"] == "custom"
    assert "lowercase" in normalizer_cfg["filter"]


def test_spatial_centroid_mapping(opensearch_client):
    """Test that spatial centroid field is mapped as geo_point."""
    mappings = opensearch_client.MAPPINGS
    assert mappings["properties"]["spatial_centroid"]["type"] == "geo_point"
