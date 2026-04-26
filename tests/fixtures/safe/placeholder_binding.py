from piccolo.table import Table


class User(Table):
    pass


async def get_user(user_id: int) -> None:
    sql = "SELECT * FROM user WHERE id = {}"
    await User.raw(sql, [user_id])


async def search(term: str, limit: int) -> None:
    await User.raw(
        "SELECT * FROM user WHERE name LIKE {} LIMIT {}",
        [term, limit],
    )
