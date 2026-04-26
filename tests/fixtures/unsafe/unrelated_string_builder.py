from piccolo.table import Table


class MyModel(Table):
    pass


def build_label(name: str) -> str:
    return "label:" + name


def build_query(order_by: str) -> str:
    return f"SELECT id FROM my_model ORDER BY {order_by}"


async def query(order_by: str) -> None:
    _ = build_label("preview")
    await MyModel.raw(build_query(order_by))
