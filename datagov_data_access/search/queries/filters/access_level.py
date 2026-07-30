from __future__ import annotations

from datagov_data_access.search.queries.filters.base import (
    API_CONTEXT,
    MAIN_CONTEXT,
    ApiQueryParam,
    FilterDefinition,
    parse_string,
)


def _clause(criteria, value: str) -> dict:
    return {"term": {"access_level": value}}


ACCESS_LEVEL_FILTER = FilterDefinition(
    name="access_level",
    query_params=("access_level",),
    parse_contexts=(MAIN_CONTEXT, API_CONTEXT),
    api_query_params=(
        ApiQueryParam(
            "access_level", enum_values=("public", "restricted public", "non-public")
        ),
    ),
    parse=lambda args: parse_string(args, "access_level"),
    to_query_pairs=lambda value: [("access_level", value)],
    clause_builder=_clause,
)
