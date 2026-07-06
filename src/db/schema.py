from sqlalchemy import Engine, MetaData, Table, inspect

metadata = MetaData()


def create_tables(engine: Engine, tables: list[Table] | None = None) -> None:
    """Create tables (all registered on `metadata` by default) if they don't exist."""
    metadata.create_all(bind=engine, tables=tables, checkfirst=True)


def table_exists(engine: Engine, table_name: str) -> bool:
    return inspect(engine).has_table(table_name)
