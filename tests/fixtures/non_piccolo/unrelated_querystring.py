class QueryString:
    def __init__(self, template: str, *args: object) -> None:
        self.template = template


def direct(col: str) -> QueryString:
    return QueryString(f"SELECT {col}")


def indirect(col: str) -> QueryString:
    template = f"SELECT {col}"
    return QueryString(template)
