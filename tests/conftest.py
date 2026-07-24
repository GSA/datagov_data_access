import copy
import json
import os
import uuid
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import List
from unittest.mock import Mock

import pytest
from opensearchpy.exceptions import NotFoundError
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Import models so Base.metadata knows about all tables.
import datagov_data_access.db.models  # noqa: F401
from datagov_data_access.db.interfaces.harvest import HarvesterDBInterface
from datagov_data_access.db.models import (
    Base,
    Dataset,
    HarvestJob,
    HarvestRecord,
    HarvestSource,
    Locations,
    Organization,
)
from datagov_data_access.search.client import OpenSearchClient
from datagov_data_access.search.config import INDEX_NAME
from datagov_data_access.search.reader import OpenSearchReader
from datagov_data_access.search.writer import OpenSearchWriter
from tests.catalog_fixtures import generate_catalog_dynamic_fixtures
from tests.harvester_fixtures import generate_harvester_dynamic_fixtures

############## HARVESTER FIXTURES ######################
HARVEST_SOURCE_URL = "http://localhost"


def create_future_date(frequency):
    FREQUENCY_ENUM = {"daily": 1, "weekly": 7, "biweekly": 14, "monthly": 30}
    interval = FREQUENCY_ENUM[frequency]
    dt = datetime.now()
    td = timedelta(days=interval)
    return dt + td


@pytest.fixture(scope="session")
def engine():
    database_url = os.environ.get("DATABASE_URI")

    engine = create_engine(database_url, future=True)

    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    yield engine

    Base.metadata.drop_all(bind=engine)
    engine.dispose()


@pytest.fixture
def db_session(engine):
    connection = engine.connect()
    transaction = connection.begin()

    SessionTesting = sessionmaker(
        expire_on_commit=False,
        future=True,
    )

    session = SessionTesting(
        bind=connection,
        join_transaction_mode="create_savepoint",
    )

    # Add US location, used in multiple tests
    us = Locations(
        **{
            "id": "34315",
            "type": "country",
            "name": "United States",
            "display_name": "United States",
            "the_geom": "0103000020E6100000010000000500000069ACFD9DED2E5FC0F302ECA3538B384069ACFD9DED2E5FC0D4EE5701BEB148401CB7989F1BBD50C0D4EE5701BEB148401CB7989F1BBD50C0F302ECA3538B384069ACFD9DED2E5FC0F302ECA3538B3840",  # noqa E501
            "type_order": "1",
        }
    )
    session.add(us)
    session.commit()

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()


@pytest.fixture
def interface(db_session):
    return HarvesterDBInterface(session=db_session)


@pytest.fixture
def fixtures_json():
    return generate_harvester_dynamic_fixtures()


## ORGS
@pytest.fixture
def organization_data(fixtures_json) -> dict:
    return fixtures_json["organization"][0]


## HARVEST SOURCES
@pytest.fixture
def source_data_dcatus(fixtures_json) -> dict:
    return fixtures_json["source"][0]


## HARVEST JOBS
@pytest.fixture
def job_data_dcatus(fixtures_json) -> dict:
    return fixtures_json["job"][0]


## HARVEST RECORDS
@pytest.fixture
def record_data_dcatus(fixtures_json) -> List[dict]:
    return fixtures_json["record"]


## HARVEST JOB ERRORS
@pytest.fixture
def job_error_data(fixtures_json) -> dict:
    return fixtures_json["job_error"][0]


## HARVEST RECORD ERRORS
@pytest.fixture
def record_error_data(fixtures_json) -> List[dict]:
    return fixtures_json["record_error"]


@pytest.fixture
def source_data_dcatus_2(organization_data: dict) -> dict:
    return {
        "id": "3f2652de-91df-4c63-8b53-bfced20b276b",
        "name": "Test Source 2",
        "notification_emails": ["email@example.com"],
        "organization_id": organization_data["id"],
        "frequency": "daily",
        "url": f"{HARVEST_SOURCE_URL}/dcatus/dcatus_2.json",
        "schema_type": "dcatus1.1: federal",
        "source_type": "document",
        "notification_frequency": "always",
    }


@pytest.fixture
def job_data_dcatus_2(source_data_dcatus_2: dict) -> dict:
    return {
        "id": "392ac4b3-79a6-414b-a2b3-d6c607d3b8d4",
        "status": "new",
        "harvest_source_id": source_data_dcatus_2["id"],
    }


@pytest.fixture
def record_data_dcatus_2(job_data_dcatus_2):
    return [
        {
            "id": "72bae4b2-336e-49df-bc4c-410dc73dc316",
            "identifier": "test_identifier-2",
            "harvest_job_id": job_data_dcatus_2["id"],
            "harvest_source_id": job_data_dcatus_2["harvest_source_id"],
            "action": "create",
            "status": "error",
            "source_raw": "example data 2",
        }
    ]


@pytest.fixture
def record_error_data_2(record_data_dcatus_2) -> dict:
    return [
        {
            "harvest_record_id": record_data_dcatus_2[0]["id"],
            "harvest_job_id": record_data_dcatus_2[0]["harvest_job_id"],
            "message": "record is invalid",
            "type": "ValidationException",
        }
    ]


@pytest.fixture
def interface_no_jobs(interface, organization_data, source_data_dcatus):
    interface.add_organization(organization_data)
    interface.add_harvest_source(source_data_dcatus)

    return interface


@pytest.fixture
def interface_with_fixture_json(
    interface_no_jobs,
    job_data_dcatus,
    job_error_data,
    record_data_dcatus,
    record_error_data,
):
    interface_no_jobs.add_harvest_job(job_data_dcatus)
    interface_no_jobs.add_harvest_job_error(job_error_data)
    for record in record_data_dcatus:
        interface_no_jobs.add_harvest_record(record)
    for error in record_error_data:
        interface_no_jobs.add_harvest_record_error(error)

    return interface_no_jobs


@pytest.fixture
def interface_with_multiple_jobs(interface_no_jobs, source_data_dcatus):
    statuses = ["new", "in_progress", "complete", "error"]
    frequencies = ["daily", "monthly"]
    jobs = [
        {
            "status": status,
            "harvest_source_id": source_data_dcatus["id"],
            "date_created": create_future_date(frequency),
        }
        for status in statuses
        for frequency in frequencies
    ]
    jobs_2 = [
        {
            "status": status,
            "harvest_source_id": source_data_dcatus["id"],
        }
        for status in statuses
    ]

    for job in jobs + jobs_2:
        interface_no_jobs.add_harvest_job(job)

    return interface_no_jobs


@pytest.fixture
def interface_with_multiple_sources(
    interface_with_fixture_json,
    source_data_dcatus_2,
    job_data_dcatus_2,
    record_data_dcatus_2,
    record_error_data_2,
):
    interface_with_fixture_json.add_harvest_source(source_data_dcatus_2)
    interface_with_fixture_json.add_harvest_job(job_data_dcatus_2)
    for record in record_data_dcatus_2:
        interface_with_fixture_json.add_harvest_record(record)
    for error in record_error_data_2:
        interface_with_fixture_json.add_harvest_record_error(error)

    return interface_with_fixture_json


@pytest.fixture
def latest_records(
    source_data_dcatus, source_data_dcatus_2, job_data_dcatus, job_data_dcatus_2
):
    return [
        {
            "identifier": "a",
            "date_created": "2024-01-01T00:00:00.001Z",
            "source_raw": "data",
            "status": "success",
            "action": "create",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "a",
            "date_created": "2024-03-01T00:00:00.001Z",
            "source_raw": "data_1",
            "status": "success",
            "action": "update",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "b",
            "date_created": "2024-03-01T00:00:00.001Z",
            "source_raw": "data_10",
            "status": "success",
            "action": "create",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "b",
            "date_created": "2022-05-01T00:00:00.001Z",
            "source_raw": "data_30",
            "status": "error",
            "action": "update",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "c",
            "date_created": "2024-05-01T00:00:00.001Z",
            "source_raw": "data_12",
            "status": "success",
            "action": "create",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "d",
            "date_created": "2024-05-01T00:00:00.001Z",
            "source_raw": "data_2",
            "status": "success",
            "action": "delete",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "d",
            "date_created": "2024-04-01T00:00:00.001Z",
            "source_raw": "data_5",
            "status": "success",
            "action": "create",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "e",
            "date_created": "2024-04-01T00:00:00.001Z",
            "source_raw": "data_123",
            "status": "success",
            "action": "create",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "e",
            "date_created": "2024-04-02T00:00:00.001Z",
            "source_raw": "data_123",
            "status": "success",
            "action": "delete",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "e",
            "date_created": "2024-04-03T00:00:00.001Z",
            "source_raw": "data_123",
            "status": "success",
            "action": "create",
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_job_id": job_data_dcatus["id"],
        },
        {
            "identifier": "f",
            "date_created": "2024-04-03T00:00:00.001Z",
            "source_raw": "data_123",
            "status": "success",
            "action": "create",
            # different harvest source and job
            "harvest_source_id": source_data_dcatus_2["id"],
            "harvest_job_id": job_data_dcatus_2["id"],
        },
        {
            "identifier": "f",
            "date_created": "2024-04-04T00:00:00.001Z",
            "source_raw": "data_123456",
            "status": "success",
            "action": "update",
            "harvest_source_id": source_data_dcatus_2["id"],
            "harvest_job_id": job_data_dcatus_2["id"],
        },
    ]


@pytest.fixture
def named_location_us():
    return (
        '{"type":"MultiPolygon","coordinates":[[[[-124.733253,24.544245],[-124.733253,49.388611],'
        "[-66.954811,49.388611],[-66.954811,24.544245],[-124.733253,24.544245]]]]}"
    )


@pytest.fixture
def named_location_stoneham():
    return (
        '{"type":"MultiPolygon","coordinates":[[[[-71.1192,42.444],[-71.1192,42.5022],'
        "[-71.0749,42.5022],[-71.0749,42.444],[-71.1192,42.444]]]]}"
    )


@pytest.fixture
def source_data_waf_csdgm(organization_data: dict) -> dict:
    return {
        "id": "55dca495-3b92-4fe4-b9c5-d433cbc3c82d",
        "name": "Test Source (WAF CSDGM)",
        "notification_emails": ["wafl@example.com"],
        "organization_id": organization_data["id"],
        "frequency": "daily",
        "url": f"{HARVEST_SOURCE_URL}/waf/",
        "schema_type": "csdgm",
        "source_type": "waf",
        "notification_frequency": "always",
    }


@pytest.fixture
def view_count_datasets():
    return [
        {"dataset_slug": "b", "view_count": 5},
        {"dataset_slug": "c", "view_count": 10},
        {"dataset_slug": "d", "view_count": 1},
    ]


@pytest.fixture()
def slug_protection_dataset(
    interface,
    organization_data,
    source_data_dcatus,
    job_data_dcatus,
):
    """
    Complete dataset with existing slug.
    """
    interface.add_organization(organization_data)
    interface.add_harvest_source(source_data_dcatus)
    job_data_dcatus["harvest_source_id"] = source_data_dcatus["id"]
    interface.add_harvest_job(job_data_dcatus)
    record = interface.add_harvest_record(
        {
            "identifier": "slug-protection-reindex",
            "harvest_job_id": job_data_dcatus["id"],
            "harvest_source_id": source_data_dcatus["id"],
            "status": "success",
            "action": "create",
            "source_raw": "{}",
        }
    )
    dataset = interface.insert_dataset(
        {
            "slug": "original-slug",
            "dcat": {"title": "original-slug"},
            "organization_id": organization_data["id"],
            "harvest_source_id": source_data_dcatus["id"],
            "harvest_record_id": record.id,
            "last_harvested_date": datetime.now(timezone.utc),
        }
    )
    return dataset


class DummyOrg:
    def to_dict(self):
        return {"id": "org-1", "name": "Test Org"}


@pytest.fixture()
def sample_dataset():
    return SimpleNamespace(
        id="dataset-1",
        slug="dataset-1",
        dcat={
            "title": "Dataset Title",
            "description": "Dataset description",
            "publisher": {"name": "Publisher"},
            "accessLevel": "public",
            "keyword": ["kw-1"],
            "theme": ["theme-1"],
            "identifier": "id-1",
            "spatial": "POINT(1 2)",
            "modified": date(2024, 1, 2),
            "isPartOf": "collection-1",
            "distribution": [
                {"title": "CSV download"},
                {"title": "API endpoint"},
                {"accessURL": "https://example.com/no-title"},
            ],
        },
        last_harvested_date=datetime(2024, 1, 3, 4, 5, 6),
        translated_spatial={"type": "Point", "coordinates": [1, 2]},
        organization=DummyOrg(),
        popularity=7,
        harvest_record_id="hr-1",
        harvest_record=SimpleNamespace(source_transform={"title": "Transformed"}),
    )


class FakeIndices:
    def __init__(self, exists=True):
        self._exists = exists
        self.created = None
        self.refreshed = []

    def exists(self, index):
        return self._exists

    def create(self, index, body):
        self.created = {"index": index, "body": body}
        return {"acknowledged": True}

    def refresh(self, index, request_timeout):
        self.refreshed.append((index, request_timeout))
        return {"result": "refreshed"}


class FakeClient:
    def __init__(self, exists=True):
        self.indices = FakeIndices(exists=exists)
        self.deleted = []

    def delete(self, index, id, ignore, request_timeout):
        self.deleted.append((index, id, ignore, request_timeout))
        return {"result": "deleted"}


def dataset_payload(
    slug,
    record,
    organization_data,
    source_data_dcatus,
    translated_spatial=None,
):
    payload = {
        "slug": slug,
        "dcat": {"title": slug},
        "organization_id": organization_data["id"],
        "harvest_source_id": source_data_dcatus["id"],
        "harvest_record_id": record.id,
        "last_harvested_date": datetime.now(timezone.utc),
    }

    if translated_spatial is not None:
        payload["translated_spatial"] = translated_spatial

    return payload


def create_record_for_dataset(
    interface,
    organization_data,
    source_data_dcatus,
    job_data_dcatus,
    identifier="dataset-popularity-record",
):
    interface.add_organization(organization_data)
    interface.add_harvest_source(source_data_dcatus)
    job_data_dcatus["harvest_source_id"] = source_data_dcatus["id"]
    interface.add_harvest_job(job_data_dcatus)
    return interface.add_harvest_record(
        {
            "identifier": identifier,
            "harvest_job_id": job_data_dcatus["id"],
            "harvest_source_id": source_data_dcatus["id"],
            "status": "success",
            "action": "create",
            "source_raw": "{}",
        }
    )


############## CATALOG FIXTURES ######################


@pytest.fixture
def fixture_data():
    return generate_catalog_dynamic_fixtures()


@pytest.fixture
def fixture_data_with_filter_demos():
    return generate_catalog_dynamic_fixtures(include_filter_demos=True)


@pytest.fixture
def interface_with_location(interface, fixture_data):
    for location_data in fixture_data["locations"]:
        interface.db.add(Locations(**location_data))
    interface.db.commit()
    return interface


@pytest.fixture
def interface_with_organization(interface, fixture_data):
    for organization_data in fixture_data["organization"]:
        interface.db.add(Organization(**organization_data))
    interface.db.commit()
    return interface


@pytest.fixture
def interface_with_harvest_source(interface_with_organization, fixture_data):
    interface_with_organization.db.add(HarvestSource(**fixture_data["harvest_source"]))
    for extra_source in fixture_data.get("extra_harvest_source", []):
        interface_with_organization.db.add(HarvestSource(**extra_source))
    interface_with_organization.db.commit()
    return interface_with_organization


@pytest.fixture
def interface_with_harvest_job(interface_with_harvest_source, fixture_data):
    interface_with_harvest_source.db.add(HarvestJob(**fixture_data["harvest_job"]))
    interface_with_harvest_source.db.commit()
    return interface_with_harvest_source


@pytest.fixture
def interface_with_harvest_record(interface_with_harvest_job, fixture_data):
    harvest_records = fixture_data["harvest_record"]
    if isinstance(harvest_records, dict):
        harvest_records = [harvest_records]
    for harvest_record in harvest_records:
        interface_with_harvest_job.db.add(HarvestRecord(**harvest_record))
    interface_with_harvest_job.db.commit()
    return interface_with_harvest_job


@pytest.fixture
def interface_with_dataset(interface_with_harvest_record, fixture_data):
    # add generic dataset record
    for dataset_data in fixture_data["dataset"]:
        interface_with_harvest_record.db.add(Dataset(**dataset_data))
    interface_with_harvest_record.db.commit()
    return interface_with_harvest_record


@pytest.fixture
def catalog_datasets(interface_with_dataset):
    return interface_with_dataset.db.query(Dataset)


@pytest.fixture(scope="session")
def opensearch_client():
    client = OpenSearchClient.from_environment()
    yield client
    client.client.close()


@pytest.fixture
def clean_opensearch_index(opensearch_client):
    def clean():
        client = opensearch_client.client

        try:
            if client.indices.exists(index=INDEX_NAME):
                client.delete_by_query(
                    index=INDEX_NAME,
                    body={"query": {"match_all": {}}},
                    conflicts="proceed",
                    refresh=True,
                    wait_for_completion=True,
                )
                client.indices.refresh(index=INDEX_NAME)
        except NotFoundError:
            pass

    clean()
    yield opensearch_client
    clean()


@pytest.fixture
def opensearch_reader(clean_opensearch_index):
    return OpenSearchReader(clean_opensearch_index)


@pytest.fixture
def opensearch_writer(clean_opensearch_index):
    return OpenSearchWriter(clean_opensearch_index)


@pytest.fixture
def opensearch_reader_with_datasets(
    catalog_datasets, opensearch_reader, opensearch_writer
):
    opensearch_writer.index_datasets(catalog_datasets)
    return opensearch_reader


@pytest.fixture
def mock_organization():
    """Mock organization for dataset tests."""
    mock_org = Mock()
    mock_org.to_dict.return_value = {
        "id": "org-123",
        "name": "Test Org",
        "slug": "test-org",
    }
    return mock_org


@pytest.fixture
def mock_dataset_with_datetime(mock_organization):
    """Mock dataset with datetime object in DCAT."""
    mock_dataset = Mock()
    mock_dataset.id = "test-id-123"
    mock_dataset.slug = "test-dataset"
    mock_dataset.dcat = {
        "title": "Test Dataset",
        "description": "Test description",
        "modified": datetime(2023, 6, 22, 20, 25, 39, 652070),
        "keyword": ["health", "education"],
        "publisher": {"name": "Test Publisher"},
    }
    mock_dataset.popularity = 100
    mock_dataset.organization = mock_organization
    return mock_dataset


@pytest.fixture
def mock_dataset_with_date(mock_organization):
    """Mock dataset with date object in DCAT."""
    mock_dataset = Mock()
    mock_dataset.id = "test-id-456"
    mock_dataset.slug = "test-dataset-2"
    mock_dataset.dcat = {
        "title": "Test Dataset 2",
        "description": "Test description 2",
        "issued": date(2006, 5, 31),
        "keyword": [],
        "publisher": {"name": "Test Publisher"},
    }
    mock_dataset.popularity = 50
    mock_dataset.organization = mock_organization
    return mock_dataset


@pytest.fixture
def mock_dataset_with_string_dates(mock_organization):
    """Mock dataset with string dates in DCAT."""
    mock_dataset = Mock()
    mock_dataset.id = "test-id-789"
    mock_dataset.slug = "test-dataset-3"
    mock_dataset.dcat = {
        "title": "Test Dataset 3",
        "description": "Test description 3",
        "modified": "2023-06-22T20:25:39.652070",
        "issued": "2006-05-31",
        "keyword": [],
        "publisher": {},
    }
    mock_dataset.popularity = None
    mock_dataset.organization = mock_organization
    return mock_dataset


@pytest.fixture
def mock_dataset_with_spatial(mock_organization):
    """Mock dataset with spatial data and datetime in DCAT."""
    mock_dataset = Mock()
    mock_dataset.id = "test-id-spatial"
    mock_dataset.slug = "test-spatial-dataset"
    mock_dataset.dcat = {
        "title": "Spatial Dataset",
        "description": "Dataset with spatial info",
        "modified": datetime(2023, 1, 15, 10, 30, 0),
        "spatial": "United States",
        "keyword": ["geography", "maps"],
        "publisher": {},
    }
    mock_dataset.popularity = 200
    mock_dataset.organization = mock_organization
    return mock_dataset


def make_mock_dataset(
    doc_id: str,
    slug: str,
    keywords: list[str],
    mock_organization: Mock,
) -> Mock:
    """Return a minimal mock Dataset with the given keywords."""
    dataset = Mock()
    dataset.id = doc_id
    dataset.slug = slug
    dataset.last_harvested_date = Mock()
    dataset.last_harvested_date.isoformat.return_value = "2024-01-01"
    dataset.translated_spatial = None
    dataset.harvest_record_id = "harvest-rec-id"
    dataset.harvest_record = None
    dataset.popularity = 0
    dataset.organization = mock_organization
    dataset.dcat = {
        "title": f"Dataset {slug}",
        "description": "Test dataset for keyword case-insensitivity",
        "keyword": keywords,
        "publisher": {"name": "Test Agency"},
    }
    return dataset


def make_dataset_by_dcat(dcat: dict, mock_organization: Mock) -> Mock:
    """Return a minimal mock dataset whose dcat is the supplied dict."""
    dataset = Mock()
    dataset.id = "dist-test-id"
    dataset.slug = "dist-test-dataset"
    dataset.last_harvested_date = Mock()
    dataset.last_harvested_date.isoformat.return_value = "2024-01-01"
    dataset.translated_spatial = None
    dataset.harvest_record_id = "harvest-rec-id"
    dataset.harvest_record = None
    dataset.popularity = 0
    dataset.organization = mock_organization
    dataset.dcat = dcat
    return dataset


def unique_harvest_record_id(dataset_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"datagov-catalog-test:{dataset_id}"))


def add_dataset_with_harvest_record(interface, dataset_data):
    dataset_data = copy.deepcopy(dataset_data)
    dataset_data["harvest_record_id"] = unique_harvest_record_id(dataset_data["id"])

    dcat = dataset_data.get("dcat", {})
    interface.db.add(
        HarvestRecord(
            id=dataset_data["harvest_record_id"],
            harvest_source_id=dataset_data["harvest_source_id"],
            harvest_job_id="1",
            identifier=dcat.get("identifier", dataset_data["slug"]),
            source_raw=json.dumps(dcat, default=str),
            source_transform=dcat,
        )
    )

    dataset = Dataset(**dataset_data)
    interface.db.add(dataset)
    return dataset
