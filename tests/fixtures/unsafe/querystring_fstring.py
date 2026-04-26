from piccolo.querystring import QueryString


def direct_fstring(col: str) -> QueryString:
    return QueryString(f"SELECT {col} FROM my_model")


def indirect_fstring(col: str) -> QueryString:
    template = f"SELECT {col} FROM my_model"
    return QueryString(template)


def concat_template(table: str) -> QueryString:
    return QueryString("SELECT * FROM " + table)


def percent_format_template(table: str) -> QueryString:
    return QueryString("SELECT * FROM %s" % table)


def dot_format_template(table: str) -> QueryString:
    return QueryString("SELECT * FROM {}".format(table))
