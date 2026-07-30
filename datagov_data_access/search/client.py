import os
from urllib.parse import urlparse

from botocore.credentials import Credentials
from opensearchpy import AWSV4SignerAuth, OpenSearch, RequestsHttpConnection

from datagov_data_access.search.config import (
    DEFAULT_CATALOG_BASE_URL,
    DEFAULT_CLIENT_MAX_RETRIES,
    INDEX_NAME,
    KEYWORD_NORMALIZER,
    SETTINGS,
    STOP_FILTER,
    TEXT_ANALYZER,
)
from datagov_data_access.search.mappings import MAPPINGS


class OpenSearchClient:
    INDEX_NAME = INDEX_NAME
    MAPPINGS = MAPPINGS
    SETTINGS = SETTINGS
    KEYWORD_NORMALIZER = KEYWORD_NORMALIZER
    TEXT_ANALYZER = TEXT_ANALYZER
    STOP_FILTER = STOP_FILTER
    DEFAULT_CATALOG_BASE_URL = DEFAULT_CATALOG_BASE_URL

    @staticmethod
    def _create_test_opensearch_client(host):
        """Get an OpenSearch client instance configured for our test cluster."""
        return OpenSearch(
            hosts=[{"host": host, "port": 9200}],
            http_compress=True,
            http_auth=("admin", "admin"),
            use_ssl=True,
            verify_certs=False,
            ssl_assert_hostname=False,
            ssl_show_warn=False,
            timeout=10,
            max_retries=DEFAULT_CLIENT_MAX_RETRIES,
            retry_on_timeout=True,
        )

    @staticmethod
    def _create_aws_opensearch_client(host, access_key=None, secret_key=None):
        """Get an OpenSearch client instance configured for an AWS cluster.

        Credentials fall back to ``OPENSEARCH_ACCESS_KEY`` / ``OPENSEARCH_SECRET_KEY``
        when not supplied, so existing callers are unaffected. Pass them explicitly to
        reach a cluster other than the one those variables name -- see
        :meth:`for_host`.
        """
        if access_key is None:
            access_key = os.getenv("OPENSEARCH_ACCESS_KEY")
        if secret_key is None:
            secret_key = os.getenv("OPENSEARCH_SECRET_KEY")
        auth = AWSV4SignerAuth(
            Credentials(access_key=access_key, secret_key=secret_key),
            "us-gov-west-1",
            "es",
        )
        return OpenSearch(
            hosts=[{"host": host, "port": 443}],
            http_auth=auth,
            use_ssl=True,
            verify_certs=True,
            connection_class=RequestsHttpConnection,
            pool_maxsize=20,
            timeout=60,
            max_retries=DEFAULT_CLIENT_MAX_RETRIES,
            retry_on_timeout=True,
        )

    @staticmethod
    def _extract_hostname(host_or_url: str) -> str | None:
        """
        Extract a hostname from a value that may be a bare host or a full URL.

        This helps ensure that host-based checks are performed on the actual
        hostname portion, not on an arbitrary string containing a host.
        """
        if not host_or_url:
            return None
        # If a scheme is present, parse as a URL to get the hostname.
        if "://" in host_or_url:
            parsed = urlparse(host_or_url)
            return parsed.hostname
        # Otherwise, treat the value as a bare hostname.
        return host_or_url

    @classmethod
    def is_aws_host(cls, host_or_url: str | None) -> bool:
        """Whether ``host_or_url`` selects the signed AWS transport.

        Public because callers need to make the same determination the factories do --
        for example to decide whether a set of credentials is required at all -- and
        duplicating the suffix test lets it drift.
        """
        parsed_host = cls._extract_hostname(host_or_url)
        if not parsed_host:
            return False
        return parsed_host == "es.amazonaws.com" or parsed_host.endswith(
            ".es.amazonaws.com"
        )

    @classmethod
    def for_host(cls, host, access_key=None, secret_key=None, ensure_index=True):
        """Return an instance for an explicitly named cluster.

        The transport is chosen from the host the same way :meth:`from_environment`
        chooses it, so a caller does not have to know whether it is addressing a real
        AWS cluster or a local one.

        This exists so that talking to a *second* cluster -- a replacement being filled
        during a migration, say -- is a matter of passing its host and credentials
        rather than mutating ``OPENSEARCH_HOST`` and friends around the constructor.
        Rebinding those globals affects every consumer in the process, including any
        live write path, which makes "which cluster does this write to?" depend on
        timing.

        ``ensure_index=False`` skips the create-if-missing side effect, for callers that
        are about to manage the index themselves (a rebuild that drops and recreates it)
        or that only read.
        """
        if not host:
            raise ValueError("host is required")
        if cls.is_aws_host(host):
            return cls(
                aws_host=host,
                access_key=access_key,
                secret_key=secret_key,
                ensure_index=ensure_index,
            )
        return cls(test_host=host, ensure_index=ensure_index)

    @classmethod
    def from_environment(cls, ensure_index=True):
        """Factory method to return a best-guess instance from environment variables."""
        opensearch_host = os.getenv("OPENSEARCH_HOST")
        if not opensearch_host:
            raise ValueError("OPENSEARCH_HOST is not set")
        return cls.for_host(opensearch_host, ensure_index=ensure_index)

    def _ensure_index(self):
        """Ensure that the named index exists."""
        # Read through the class rather than the module so a subclass overriding
        # INDEX_NAME/MAPPINGS/SETTINGS actually takes effect. The class attributes
        # default to these same module-level values.
        if not self.client.indices.exists(index=self.INDEX_NAME):
            body = {"mappings": self.MAPPINGS}
            if self.SETTINGS:
                body["settings"] = self.SETTINGS
            self.client.indices.create(index=self.INDEX_NAME, body=body)

    def __init__(
        self,
        test_host=None,
        aws_host=None,
        access_key=None,
        secret_key=None,
        ensure_index=True,
    ):
        """Interface for our OpenSearch cluster."""
        if aws_host is not None:
            if test_host is not None:
                raise ValueError("Cannot specify both test_host and aws_host")
            # Only forward the credential kwargs when they were actually supplied.
            # Tests in both this repo and the consumers stub this factory with a
            # single-argument callable, and unconditionally passing keywords would
            # break every one of them for no benefit -- omitted credentials are read
            # from the environment inside the real factory anyway.
            if access_key is None and secret_key is None:
                self.client = self._create_aws_opensearch_client(aws_host)
            else:
                self.client = self._create_aws_opensearch_client(
                    aws_host, access_key=access_key, secret_key=secret_key
                )
        else:
            if test_host is not None:
                self.client = self._create_test_opensearch_client(test_host)
            else:
                raise ValueError("Must specify either test_host or aws_host")

        self.host = aws_host or test_host
        if ensure_index:
            self._ensure_index()
