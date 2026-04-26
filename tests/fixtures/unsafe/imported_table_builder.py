from framework.db.tables import Projects


def build_query(condition: str) -> str:
    return f"SELECT * FROM my_model WHERE {condition}"


async def query(condition: str) -> None:
    await Projects.raw(build_query(condition))
