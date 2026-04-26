from typing import Literal

from piccolo.table import Table


class MyModel(Table):
    pass


# Operator constrained by Literal; search value passed via {} placeholder
def build_ilike(op: Literal["LIKE", "ILIKE"]) -> str:
    return f"SELECT * FROM my_model WHERE name {op} {{}}"


async def search(term: str) -> None:
    await MyModel.raw(build_ilike("ILIKE"), [f"%{term}%"])
