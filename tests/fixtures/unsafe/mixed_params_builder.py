from typing import Literal

from piccolo.table import Table


class MyModel(Table):
    pass


def build_query(
    table: Literal["my_model", "other_model"],
    sort_col: str,
) -> str:
    return f"SELECT * FROM {table} ORDER BY {sort_col}"


async def query(
    table: Literal["my_model", "other_model"],
    sort_col: str,
) -> None:
    await MyModel.raw(build_query(table, sort_col))
