from typing import Literal

from piccolo.table import Table


class MyModel(Table):
    pass


def _make_order_clause(direction: Literal["ASC", "DESC"]) -> str:
    return f"ORDER BY id {direction}"


def build_query(direction: Literal["ASC", "DESC"]) -> str:
    order = _make_order_clause(direction)
    return f"SELECT * FROM my_model {order}"


async def query(direction: Literal["ASC", "DESC"]) -> None:
    await MyModel.raw(build_query(direction))
