from piccolo.table import Table


class MyModel(Table):
    pass


async def direct_concat(table_suffix: str) -> None:
    await MyModel.raw("SELECT * FROM my_model_" + table_suffix)


async def indirect_concat(table_suffix: str) -> None:
    sql = "SELECT * FROM my_model_" + table_suffix
    await MyModel.raw(sql)


async def augmented_assign(fragment: str) -> None:
    sql = "SELECT * FROM my_model"
    sql += " WHERE name = " + fragment
    await MyModel.raw(sql)
