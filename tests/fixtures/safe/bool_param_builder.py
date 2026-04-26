from piccolo.table import Table


class MyModel(Table):
    pass


def build_query(has_filter: bool, limit: int) -> str:
    condition = " WHERE active = TRUE" if has_filter else ""
    return f"SELECT * FROM my_model{condition} LIMIT {limit}"


async def query(has_filter: bool, limit: int) -> None:
    await MyModel.raw(build_query(has_filter, limit))
