from piccolo.table import Table


class MyModel(Table):
    pass


def _make_where_clause(condition: str) -> str:
    return f"WHERE {condition}"


def build_query(condition: str) -> str:
    where = _make_where_clause(condition)
    return f"SELECT * FROM my_model {where}"


async def query(condition: str) -> None:
    await MyModel.raw(build_query(condition))

