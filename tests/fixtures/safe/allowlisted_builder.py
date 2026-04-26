from piccolo.table import Table


class MyModel(Table):
    pass


def build_my_model_sql() -> str:
    return "SELECT * FROM my_model ORDER BY id"


async def query() -> None:
    sql = build_my_model_sql()
    await MyModel.raw(sql)
