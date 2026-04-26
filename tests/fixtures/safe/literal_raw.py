from piccolo.table import Table


class MyModel(Table):
    pass


async def query() -> None:
    await MyModel.raw("SELECT * FROM my_model")


async def query_with_placeholder(user_id: int) -> None:
    await MyModel.raw("SELECT * FROM my_model WHERE id = {}", [user_id])
