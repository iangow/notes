#!/usr/bin/env python3
"""Export evidence as immutable Parquet snapshots or rebuild a working DuckDB."""

import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import tempfile

import duckdb


def ident(value):
    return '"' + value.replace('"', '""') + '"'


def literal(value):
    return "'" + str(value).replace("'", "''") + "'"


def digest(path):
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def fingerprint(con, relation):
    return con.execute(
        f'SELECT count(*), coalesce(bit_xor(hash(r)), 0) FROM {relation} r'
    ).fetchone()


def columns(con, relation):
    rows = con.execute(f'DESCRIBE SELECT * FROM {relation}').fetchall()
    return [r[0] for r in rows], [r[1] for r in rows]


def configure(con, memory_limit='2GB'):
    con.execute("SET TimeZone='UTC'; SET threads=4; SET preserve_insertion_order=false")
    con.execute(f'SET memory_limit={literal(memory_limit)}')


def parquet_relation(con, path, names, types):
    relation = f'read_parquet({literal(path)})'
    storage_types = ['DECIMAL(38,0)' if t == 'HUGEINT' else t for t in types]
    if columns(con, relation) != (names, storage_types):
        raise ValueError(f'Parquet type mismatch: {path.name}')
    projection = ', '.join(f'{ident(n)}::{t} AS {ident(n)}' for n, t in zip(names, types))
    return f'(SELECT {projection} FROM {relation})'


def export_snapshot(database, output, tables=None):
    database, output = Path(database).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.parquet-export-', dir=output.parent) as tmp:
        stage = Path(tmp) / 'snapshot'
        stage.mkdir()
        with duckdb.connect(str(database), read_only=True) as source, duckdb.connect() as meta:
            configure(source)
            configure(meta)
            source.execute('BEGIN TRANSACTION')
            catalog = source.execute('''SELECT schema_name, table_name, sql
                FROM duckdb_tables() WHERE NOT internal ORDER BY table_name''').fetchall()
            if any(schema != 'main' for schema, _, _ in catalog):
                raise ValueError('Only main-schema databases are supported')
            if tables is not None:
                missing = set(tables) - {name for _, name, _ in catalog}
                if missing:
                    raise ValueError(f'Unknown tables: {sorted(missing)}')
                catalog = [row for row in catalog if row[1] in tables]
            meta.execute('''CREATE TABLE manifest (
                table_name VARCHAR PRIMARY KEY, filename VARCHAR, table_sql VARCHAR,
                column_names VARCHAR[], column_types VARCHAR[], row_count BIGINT,
                row_hash UBIGINT, sha256 VARCHAR)''')
            reserved = {'manifest.parquet', 'metadata.parquet', 'objects.parquet'}
            filenames = {f'{name}.parquet' for _, name, _ in catalog}
            for number, (_, name, ddl) in enumerate(catalog):
                filename = f'{name}.parquet'
                if Path(filename).name != filename:
                    raise ValueError(f'Unsupported table name: {name}')
                if filename in reserved:
                    filename = f'table_{name}.parquet'
                    while filename in filenames or filename in reserved:
                        filename = 'table_' + filename
                    filenames.add(filename)
                path = stage / filename
                relation = ident(name)
                names, types = columns(source, relation)
                expected = fingerprint(source, relation)
                # DuckDB otherwise writes HUGEINT as lossy DOUBLE in Parquet.
                projection = ', '.join(
                    f'{ident(n)}::DECIMAL(38,0) AS {ident(n)}' if t == 'HUGEINT' else ident(n)
                    for n, t in zip(names, types)
                )
                source.execute(f'COPY (SELECT {projection} FROM {relation}) TO {literal(path)} (FORMAT PARQUET, COMPRESSION ZSTD)')
                parquet = parquet_relation(source, path, names, types)
                if fingerprint(source, parquet) != expected:
                    raise ValueError(f'Parquet row fingerprint mismatch: {name}')
                meta.execute('INSERT INTO manifest VALUES (?, ?, ?, ?, ?, ?, ?, ?)',
                             [name, filename, ddl, names, types, *expected, digest(path)])
                print(f'Export {number + 1}/{len(catalog)}: {name}: {expected[0]:,} rows verified', flush=True)
            meta.execute('CREATE TABLE objects(kind VARCHAR, name VARCHAR, sql VARCHAR)')
            # Partial exports deliberately omit dependent views and indexes.
            if tables is None:
                for kind, catalog_name, name_column in [
                    ('index', 'duckdb_indexes', 'index_name'),
                    ('view', 'duckdb_views', 'view_name'),
                ]:
                    condition = ' WHERE NOT internal' if kind == 'view' else ''
                    rows = source.execute(f'SELECT {name_column}, sql FROM {catalog_name}(){condition}').fetchall()
                    for name, ddl in rows:
                        meta.execute('INSERT INTO objects VALUES (?, ?, ?)', [kind, name, ddl])
            stat = database.stat()
            meta.execute('''CREATE TABLE metadata(format_version INTEGER, source_database VARCHAR,
                source_size BIGINT, source_mtime_ns BIGINT, exported_at TIMESTAMPTZ,
                duckdb_version VARCHAR, partial_export BOOLEAN)''')
            meta.execute('INSERT INTO metadata VALUES (1, ?, ?, ?, ?, ?, ?)',
                         [str(database), stat.st_size, stat.st_mtime_ns,
                          datetime.now(timezone.utc), duckdb.__version__, tables is not None])
            for name in ('manifest', 'metadata', 'objects'):
                meta.execute(f'COPY {name} TO {literal(stage / (name + ".parquet"))} (FORMAT PARQUET, COMPRESSION ZSTD)')
            source.execute('COMMIT')
        if output.exists():
            raise FileExistsError(output)
        stage.rename(output)
    return output


def restore_snapshot(snapshot, con, memory_limit='2GB'):
    """Load a trusted local archive into an empty connection; includes saved DDL."""
    snapshot = Path(snapshot).resolve()
    if con.execute('SELECT count(*) FROM duckdb_tables() WHERE NOT internal').fetchone()[0]:
        raise ValueError('Restore requires an empty database')
    configure(con, memory_limit)
    metadata = con.execute('SELECT format_version, duckdb_version FROM read_parquet(?)',
                           [str(snapshot / 'metadata.parquet')]).fetchall()
    if len(metadata) != 1 or metadata[0][0] != 1:
        raise ValueError('Unsupported archive version')
    manifest = con.execute('SELECT * FROM read_parquet(?) ORDER BY table_name',
                           [str(snapshot / 'manifest.parquet')]).fetchall()
    con.execute('BEGIN TRANSACTION')
    try:
        for name, filename, ddl, names, types, count, row_hash, sha256 in manifest:
            if Path(filename).name != filename:
                raise ValueError('Archive paths must be local filenames')
            path = snapshot / filename
            if digest(path) != sha256:
                raise ValueError(f'Checksum mismatch: {name}')
            parquet = parquet_relation(con, path, names, types)
            con.execute(ddl)
            con.execute(f'INSERT INTO {ident(name)} BY NAME SELECT * FROM {parquet}')
            actual = fingerprint(con, ident(name))
            # DuckDB's row hash is an extra check, not a cross-version file format.
            if actual[0] != count or (metadata[0][1] == duckdb.__version__ and actual[1] != row_hash):
                raise ValueError(f'Restored row fingerprint mismatch: {name}')
            print(f'Restore: {name}: {count:,} rows verified', flush=True)
        pending = con.execute('SELECT sql FROM read_parquet(?) ORDER BY kind, name',
                              [str(snapshot / 'objects.parquet')]).fetchall()
        while pending:
            deferred = []
            for (ddl,) in pending:
                try:
                    con.execute(ddl)
                except duckdb.CatalogException:
                    deferred.append((ddl,))
            if len(deferred) == len(pending):
                raise ValueError('Unresolved view/index dependencies')
            pending = deferred
        con.execute('COMMIT')
    except Exception:
        con.execute('ROLLBACK')
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    export = sub.add_parser('export')
    export.add_argument('--database', type=Path, required=True)
    export.add_argument('--output', type=Path, required=True)
    export.add_argument('--tables', nargs='+', help='Partial export; excludes views and indexes')
    restore = sub.add_parser('restore', help='Restore a trusted archive (executes its saved schema SQL)')
    restore.add_argument('--snapshot', type=Path, required=True)
    restore.add_argument('--output', type=Path, required=True)
    restore.add_argument('--memory-limit', default='2GB', help='DuckDB memory cap; large indexed archives may need 8GB')
    args = parser.parse_args()
    if args.command == 'export':
        print(f'Published snapshot: {export_snapshot(args.database, args.output, args.tables)}')
    else:
        output = args.output.resolve()
        if output.exists():
            raise FileExistsError(output)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix='.parquet-restore-', dir=output.parent) as tmp:
            working = Path(tmp) / 'working.duckdb'
            with duckdb.connect(str(working)) as con:
                restore_snapshot(args.snapshot, con, args.memory_limit)
            if output.exists():
                raise FileExistsError(output)
            working.rename(output)
        print(f'Rebuilt database: {output}')


if __name__ == '__main__':
    main()
