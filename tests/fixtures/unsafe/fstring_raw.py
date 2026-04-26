from piccolo.table import Table


class MyModel(Table):
    pass


async def direct_fstring(user_id: str) -> None:
    await MyModel.raw(f"SELECT * FROM my_model WHERE id = {user_id}")


async def indirect_fstring(user_id: str) -> None:
    sql = f"SELECT * FROM my_model WHERE id = {user_id}"
    await MyModel.raw(sql)
