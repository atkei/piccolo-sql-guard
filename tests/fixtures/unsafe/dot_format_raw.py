from piccolo.table import Table


class MyModel(Table):
    pass


async def dot_format(user_id: str) -> None:
    await MyModel.raw("SELECT * FROM my_model WHERE id = '{}'".format(user_id))


async def indirect_dot_format(user_id: str) -> None:
    sql = "SELECT * FROM my_model WHERE id = '{}'".format(user_id)
    await MyModel.raw(sql)
