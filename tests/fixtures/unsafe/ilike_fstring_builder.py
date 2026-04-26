from piccolo.table import Table


class MyModel(Table):
    pass


# Builder interpolates search value directly — unsafe
def build_ilike(term: str) -> str:
    return f"SELECT * FROM my_model WHERE name ILIKE '%{term}%'"


async def search_via_builder(term: str) -> None:
    await MyModel.raw(build_ilike(term))


# Direct f-string passed to raw() — also unsafe
async def search_direct(term: str) -> None:
    await MyModel.raw(f"SELECT * FROM my_model WHERE name ILIKE '%{term}%'")
