from piccolo.table import Table


class MyModel(Table):
    pass


def build_query(table_name: str, order_by: str) -> str:
    return f"SELECT * FROM {table_name} ORDER BY {order_by}"


async def query(table_name: str, order_by: str) -> None:
    await MyModel.raw(build_query(table_name, order_by))
