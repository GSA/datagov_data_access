# README - TODO

## Connecting to OpenSearch

`OpenSearchClient` has three factories. Prefer the most specific one that fits.

```python
from datagov_data_access.search.client import OpenSearchClient

# The cluster this app is configured for: OPENSEARCH_HOST plus, for an AWS host,
# OPENSEARCH_ACCESS_KEY and OPENSEARCH_SECRET_KEY.
client = OpenSearchClient.from_environment()

# A specific cluster, named at the call site. Credentials fall back to the same
# environment variables when omitted.
client = OpenSearchClient.for_host(
    "vpc-replacement.us-gov-west-1.es.amazonaws.com",
    access_key=...,
    secret_key=...,
)
```

Both pick the transport from the host: a `*.es.amazonaws.com` host gets the SigV4-signed
AWS transport, anything else gets the local `admin:admin` one. `OpenSearchClient.is_aws_host(host)`
exposes that same test if a caller needs to make the decision itself.

### Reaching a second cluster

Use `for_host` rather than rebinding `OPENSEARCH_HOST` around a `from_environment()` call.
Those variables are process-wide, and every consumer in the process reads them — including
any live write path — so mutating them makes "which cluster does this write to?" depend on
timing. Passing the host explicitly keeps the choice scoped to the one client.

This is what makes a zero-impact cluster migration possible: build and verify a replacement
cluster while the live one keeps serving, then cut over.

### `ensure_index`

By default, constructing a client creates the `datasets` index if it is missing. That is
convenient for an app that expects the index to exist, but it means *connecting* has a
write side effect — a read-only consumer can recreate an index that something else is
deliberately rebuilding, and a caller cannot inspect a cluster without changing it.

Pass `ensure_index=False` when the caller manages the index itself (a rebuild that drops
and recreates it with a current mapping) or only reads:

```python
client = OpenSearchClient.for_host(host, ensure_index=False)
```

## Releasing

Consumers (`datagov-harvester`, `datagov-catalog`) install from git by tag, so a change
here reaches them only once it is released:

1. Open a PR with the change **and** a `version` bump in `pyproject.toml` (bare semver, no
   `v` prefix). Check the other open branches first — more than one has claimed the same
   version before.
2. Merge, then cut a GitHub Release on the new tag. `.github/workflows/notify-consumers.yml`
   fires on release and opens a dependency PR in each consumer.
3. Pair that dependency PR with the app-side change that needs it.

Search changes usually affect both consumers, so coordinate the two deploys.

## Contributing

See [CONTRIBUTING](CONTRIBUTING.md) for additional information.

## Public domain

This project is in the worldwide [public domain](LICENSE.md). As stated in [CONTRIBUTING](CONTRIBUTING.md):

> This project is in the public domain within the United States, and copyright and related rights in the work worldwide are waived through the [CC0 1.0 Universal public domain dedication](https://creativecommons.org/publicdomain/zero/1.0/).
>
> All contributions to this project will be released under the CC0 dedication. By submitting a pull request, you are agreeing to comply with this waiver of copyright interest.
