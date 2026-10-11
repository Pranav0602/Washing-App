"""Pagination defaults."""

from __future__ import annotations

from collections import OrderedDict

from rest_framework.pagination import LimitOffsetPagination, PageNumberPagination
from rest_framework.response import Response

MAX_PAGE_SIZE = 100


class DefaultPagination(PageNumberPagination):
    """Page-number pagination with a hard ceiling on page size."""

    page_size_query_param = "page_size"
    max_page_size = MAX_PAGE_SIZE

    def get_paginated_response(self, data) -> Response:
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count),
                    ("page", self.page.number),
                    ("page_size", self.get_page_size(self.request)),
                    ("total_pages", self.page.paginator.num_pages),
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )


class LargePagination(LimitOffsetPagination):
    """Used by ops listings that can legitimately return many rows."""

    default_limit = 50
    max_limit = MAX_PAGE_SIZE