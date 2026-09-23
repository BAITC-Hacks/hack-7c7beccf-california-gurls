"""Загрузка результатов в PostgreSQL (для API). CSV-выгрузки от БД не зависят."""
import io

import pandas as pd
import psycopg

PG_TYPES = {"int64": "BIGINT", "int32": "INTEGER", "int8": "SMALLINT", "float64": "DOUBLE PRECISION",
            "bool": "BOOLEAN", "datetime64[ns]": "DATE", "datetime64[us]": "DATE", "datetime64[ms]": "DATE"}


def _pg_type(dtype) -> str:
    return PG_TYPES.get(str(dtype), "TEXT")


def write_table(cur, name: str, df: pd.DataFrame, pk: str | None = None):
    cols = ", ".join(f'"{c}" {_pg_type(t)}' for c, t in df.dtypes.items())
    if pk:
        cols += f", PRIMARY KEY ({pk})"
    cur.execute(f'DROP TABLE IF EXISTS "{name}" CASCADE')
    cur.execute(f'CREATE TABLE "{name}" ({cols})')
    buf = io.StringIO()
    df.to_csv(buf, index=False, header=False, na_rep="\\N")
    buf.seek(0)
    with cur.copy(f'COPY "{name}" FROM STDIN WITH (FORMAT csv, NULL \'\\N\')') as cp:
        cp.write(buf.read())


def load_all(dsn: str, tables: dict):
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        for name, (df, pk) in tables.items():
            write_table(cur, name, df, pk)
        cur.execute('CREATE INDEX ON edges (src)')
        cur.execute('CREATE INDEX ON edges (dst)')
        cur.execute('CREATE INDEX ON transactions (src)')
        cur.execute('CREATE INDEX ON transactions (dst)')
        cur.execute('CREATE INDEX ON nodes (cluster_id)')
        conn.commit()
