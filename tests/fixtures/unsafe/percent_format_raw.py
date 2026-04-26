from piccolo.table import Table


class MyModel(Table):
    pass


async def percent_format(user_id: str) -> None:
    await MyModel.raw("SELECT * FROM my_model WHERE id = '%s'" % user_id)


async def indirect_percent(user_id: str) -> None:
    sql = "SELECT * FROM my_model WHERE id = '%s'" % user_id
    await MyModel.raw(sql)
