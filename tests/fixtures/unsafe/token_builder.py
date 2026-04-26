from piccolo.table import Table


class MyModel(Table):
    pass


async def unsafe_order_by(sort_col: str) -> None:
    order_by = f"ORDER BY {sort_col}"
    await MyModel.raw("SELECT * FROM my_model " + order_by)


async def unsafe_where_operator(operator: str, value: str) -> None:
    sql = f"SELECT * FROM my_model WHERE value {operator} '{value}'"
    await MyModel.raw(sql)
