from typing import Literal

from piccolo.table import Table


class MyModel(Table):
    pass


_BASE = "SELECT * FROM my_model"


def build_query(
    order_by: Literal["created_at_desc", "created_at_asc"],
    has_cursor: bool,
) -> str:
    direction = "DESC" if order_by == "created_at_desc" else "ASC"
    cursor_clause = " AND cursor < %s" if has_cursor else ""
    return f"{_BASE}{cursor_clause} ORDER BY created_at {direction}"


async def query(
    order_by: Literal["created_at_desc", "created_at_asc"],
    has_cursor: bool,
) -> None:
    await MyModel.raw(build_query(order_by, has_cursor))
