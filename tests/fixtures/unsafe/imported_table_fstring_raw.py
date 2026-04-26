from framework.db.tables import Projects


async def query(user_id: str) -> None:
    await Projects.raw(f"SELECT * FROM my_model WHERE id = {user_id}")
