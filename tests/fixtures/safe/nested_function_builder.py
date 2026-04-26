"""Outer builder is safe. An inner nested function has an unsafe f-string,
but it is never called — its returns must not be attributed to the outer."""
from piccolo import Table


class MyModel(Table):
    pass


def build_safe(direction: str = "ASC") -> str:
    def _never_called(col: str) -> str:
        # Would trigger PQS004 *if* misattributed to ``build_safe``.
        return f"ORDER BY {col}"

    return "SELECT * FROM my_model ORDER BY id"
