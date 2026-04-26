class DjangoModel:
    @classmethod
    def raw(cls, sql: str, *args: object) -> None:
        pass


async def query(user_id: str) -> None:
    await DjangoModel.raw(f"SELECT * FROM user WHERE id = {user_id}")


async def indirect(user_id: str) -> None:
    sql = f"SELECT * FROM user WHERE id = {user_id}"
    await DjangoModel.raw(sql)
