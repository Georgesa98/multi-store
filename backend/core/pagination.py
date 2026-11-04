from rest_framework.pagination import CursorPagination, PageNumberPagination


class StandardResultsSetPagination(PageNumberPagination):
    """`?page=&page_size=` -> `{count, next, previous, results}`."""

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100


class HistoryCursorPagination(CursorPagination):
    """`?cursor=&page_size=` -> `{next, previous, results}` for append-only lists.

    An order history grows while a client reads it. With offset paging a new
    order landing between two page requests shifts every later row by one: the
    client sees a duplicate or misses an order. A cursor is a position in the
    ordered set, not an offset, so an insert cannot move it.

    The trade is that there is no `count` — a cursor page cannot know the total
    without scanning — and the ordering is fixed, which is why the views that
    use this also drop `OrderingFilter`. `-created_at` is the history order;
    rows are a microsecond apart because every model sets it on save.
    """

    page_size = 20
    page_size_query_param = "page_size"
    max_page_size = 100
    ordering = "-created_at"
