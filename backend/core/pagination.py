from rest_framework.pagination import PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """`?page=&page_size=` -> `{count, next, previous, results}`."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
