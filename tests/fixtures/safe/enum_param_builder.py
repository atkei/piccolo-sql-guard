import enum

from piccolo.table import Table


class SortDir(enum.StrEnum):
    ASC = "ASC"
    DESC = "DESC"


class MyModel(Table):
    pass


def build_query(direction: SortDir) -> str:
    return f"SELECT * FROM my_model ORDER BY id {direction}"


async def query(direction: SortDir) -> None:
    await MyModel.raw(build_query(direction))
