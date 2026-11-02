"""Native PostgreSQL backup and empty-target recovery; no Docker or database creation."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

PROJECT = "rag-tech-doc-retriever"
IDENTIFIER = re.compile(r"[a-z_][a-z0-9_]{0,62}\Z")
RECORD_COLUMNS = {
    "id": "text",
    "kind": "text",
    "version": "integer",
    "data": "jsonb",
    "deleted": "boolean",
    "created_at": "timestamp with time zone",
    "updated_at": "timestamp with time zone",
}
VERSION_COLUMNS = {
    "record_id": "text",
    "version": "integer",
    "data": "jsonb",
    "deleted": "boolean",
    "action": "text",
    "created_at": "timestamp with time zone",
}


class NativeBackupError(ValueError):
    """Redacted fail-closed backup/recovery failure."""


class NativeRestoreCommittedError(NativeBackupError):
    """pg_restore succeeded, but subsequent verification could not confirm the result."""


def _identity(database: str, role: str, project: str, prefix: str, timeout: int) -> None:
    if (
        project != PROJECT
        or not all(isinstance(v, str) and IDENTIFIER.fullmatch(v) for v in (database, role, prefix))
        or len(prefix) > 45
    ):
        raise NativeBackupError("必须显式指定本项目及合法 database/role/prefix 身份")
    if isinstance(timeout, bool) or not isinstance(timeout, int) or not 1 <= timeout <= 3600:
        raise NativeBackupError("timeout 必须为 1–3600 秒整数")


def _options(connection: dict | None, database: str, role: str, timeout: int) -> dict:
    source = (
        connection
        if connection is not None
        else {
            "host": os.environ.get("POSTGRES_HOST", "127.0.0.1"),
            "port": os.environ.get("POSTGRES_PORT", "5432"),
            "dbname": os.environ.get("POSTGRES_DB", ""),
            "user": os.environ.get("POSTGRES_USER", ""),
            "password": os.environ.get("POSTGRES_PASSWORD", ""),
        }
    )
    if set(source) - {"host", "port", "dbname", "user", "password", "sslmode"}:
        raise NativeBackupError("连接配置含不支持的字段")
    if source.get("dbname") != database or source.get("user") != role:
        raise NativeBackupError("连接配置与显式 database/role 身份不符")
    if (
        not str(source.get("host", ""))
        or not str(source.get("port", "")).isdigit()
        or not 1 <= int(source["port"]) <= 65535
    ):
        raise NativeBackupError("必须显式指定合法 host/port")
    return {
        **source,
        "connect_timeout": min(timeout, 10),
        "options": f"-c statement_timeout={timeout * 1000} -c lock_timeout={min(timeout, 10) * 1000}",
    }


def _environment(options: dict, timeout: int) -> dict:
    env = {
        k: v for k, v in os.environ.items() if not k.startswith("PG") and k != "POSTGRES_PASSWORD"
    }
    env.update(
        {
            "PGHOST": str(options["host"]),
            "PGPORT": str(options["port"]),
            "PGDATABASE": options["dbname"],
            "PGUSER": options["user"],
            "PGPASSWORD": str(options.get("password", "")),
            "PGCONNECT_TIMEOUT": str(min(timeout, 10)),
            "PGOPTIONS": options["options"],
        }
    )
    if options.get("sslmode"):
        env["PGSSLMODE"] = options["sslmode"]
    return env


def _run(runner: Callable, command: list[str], env: dict, timeout: int, **kwargs):
    try:
        result = runner(
            command, env=env, timeout=timeout, check=False, stderr=subprocess.PIPE, **kwargs
        )
    except (OSError, subprocess.TimeoutExpired):
        raise NativeBackupError("原生 PostgreSQL 工具不可用或超时；未输出连接凭据") from None
    if result.returncode:
        raise NativeBackupError("原生 PostgreSQL 工具失败；未输出底层错误或连接凭据")
    return result


def _major(runner: Callable, executable: str, env: dict, timeout: int) -> int:
    result = _run(runner, [executable, "--version"], env, timeout, stdout=subprocess.PIPE)
    match = re.search(r"PostgreSQL\)?\s+(\d+)(?:\.\d+)*", result.stdout.decode("utf-8", "replace"))
    if not match:
        raise NativeBackupError("无法核验 PostgreSQL 工具主版本")
    return int(match[1])


def _catalog(connection) -> dict:
    """Read database/role/OID and non-extension user objects, never user row values."""
    with connection.cursor() as cur:
        cur.execute("""SELECT current_database() AS database,current_user AS role,session_user AS session_role,
            d.oid::text AS database_oid,current_setting('server_version_num')::int AS server_version_num,
            pg_encoding_to_char(d.encoding) AS encoding,d.datcollate AS collate,d.datctype AS ctype,
            inet_server_addr()::text AS server_address,inet_server_port() AS server_port,
            pg_is_in_recovery() AS in_recovery FROM pg_database d WHERE d.datname=current_database()""")
        value = dict(cur.fetchone())
        cur.execute(
            "SELECT e.extname AS name,e.extversion AS version,n.nspname AS schema FROM pg_extension e JOIN pg_namespace n ON n.oid=e.extnamespace ORDER BY e.extname"
        )
        value["extensions"] = [dict(row) for row in cur.fetchall()]
        cur.execute("""SELECT n.nspname AS schema,c.relname AS name,c.relkind AS kind FROM pg_class c
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_'
            AND c.relkind IN ('r','p','v','m','S','f') AND NOT EXISTS (SELECT 1 FROM pg_depend d
            WHERE d.classid='pg_class'::regclass AND d.objid=c.oid AND d.deptype='e') ORDER BY n.nspname,c.relname""")
        value["relations"] = [dict(row) for row in cur.fetchall()]
        cur.execute("""SELECT n.nspname AS schema,c.relname AS relation,a.attname AS name,format_type(a.atttypid,a.atttypmod) AS type
            FROM pg_attribute a JOIN pg_class c ON c.oid=a.attrelid JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND a.attnum>0 AND NOT a.attisdropped ORDER BY c.relname,a.attnum""")
        value["columns"] = [dict(row) for row in cur.fetchall()]
        cur.execute("""SELECT n.nspname AS schema,c.relname AS relation,con.contype AS type,con.convalidated AS validated,
            pg_get_constraintdef(con.oid) AS definition FROM pg_constraint con JOIN pg_class c ON c.oid=con.conrelid
            JOIN pg_namespace n ON n.oid=c.relnamespace WHERE n.nspname='public' ORDER BY c.relname,con.conname""")
        value["constraints"] = [dict(row) for row in cur.fetchall()]
        cur.execute("""SELECT 'function' AS kind,n.nspname AS schema,p.proname AS name FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
            WHERE n.nspname <> 'information_schema' AND n.nspname !~ '^pg_' AND NOT EXISTS
            (SELECT 1 FROM pg_depend d WHERE d.classid='pg_proc'::regclass AND d.objid=p.oid AND d.deptype='e')
            UNION ALL SELECT 'type',n.nspname,t.typname FROM pg_type t JOIN pg_namespace n ON n.oid=t.typnamespace
            WHERE t.typtype IN ('e','d') AND n.nspname <> 'information_schema' AND n.nspname !~ '^pg_' AND NOT EXISTS
            (SELECT 1 FROM pg_depend d WHERE d.classid='pg_type'::regclass AND d.objid=t.oid AND d.deptype='e')
            UNION ALL SELECT 'schema',n.nspname,n.nspname FROM pg_namespace n WHERE n.nspname NOT IN ('public','information_schema')
            AND n.nspname !~ '^pg_' AND NOT EXISTS (SELECT 1 FROM pg_depend d
            WHERE d.classid='pg_namespace'::regclass AND d.objid=n.oid AND d.deptype='e') ORDER BY 1,2,3""")
        value["other_objects"] = [dict(row) for row in cur.fetchall()]
        cur.execute(
            "SELECT count(*) AS count FROM pg_stat_activity WHERE datid=(SELECT oid FROM pg_database WHERE datname=current_database()) AND pid<>pg_backend_pid()"
        )
        value["other_connections"] = int(cur.fetchone()["count"])
        cur.execute(
            "SELECT has_function_privilege(current_user,'pg_catalog.pg_control_system()','EXECUTE') AS allowed"
        )
        value["cluster_identifier"] = None
        if cur.fetchone()["allowed"]:
            cur.execute("SELECT system_identifier::text AS identifier FROM pg_control_system()")
            value["cluster_identifier"] = cur.fetchone()["identifier"]
    return value


def _database_matches(catalog: dict, database: str, role: str) -> None:
    if (
        catalog["database"] != database
        or catalog["role"] != role
        or catalog["session_role"] != role
    ):
        raise NativeBackupError("实际连接 catalog 的 database/role 身份不符")


def _source_matches(catalog: dict, database: str, role: str, prefix: str) -> None:
    _database_matches(catalog, database, role)
    relations = {(row["schema"], row["name"], row["kind"]) for row in catalog["relations"]}
    for suffix, expected in (("records", RECORD_COLUMNS), ("versions", VERSION_COLUMNS)):
        name = prefix + "_" + suffix
        columns = {
            row["name"]: row["type"]
            for row in catalog["columns"]
            if row["schema"] == "public" and row["relation"] == name
        }
        if ("public", name, "r") not in relations or columns != expected:
            raise NativeBackupError("指定 prefix 的项目表结构不匹配")
        key = "PRIMARY KEY (id)" if suffix == "records" else "PRIMARY KEY (record_id, version)"
        if not any(
            row["relation"] == name
            and row["type"] == "p"
            and row["validated"]
            and row["definition"] == key
            for row in catalog["constraints"]
        ):
            raise NativeBackupError("指定 prefix 的项目主键不匹配")


def _paths(file: Path) -> tuple[Path, Path, Path]:
    return (
        file,
        file.with_suffix(file.suffix + ".sha256"),
        file.with_suffix(file.suffix + ".manifest.json"),
    )


def _filename(file: Path) -> None:
    if not file.name or any(
        ord(character) < 32 or ord(character) == 127 for character in file.name
    ):
        raise NativeBackupError("备份文件名不得包含控制字符或换行")


def _hash_stream(source, destination=None) -> tuple[str, int]:
    """Bound peak memory independently of archive size; optionally freeze the bytes."""
    digest, size = hashlib.sha256(), 0
    while chunk := source.read(1024 * 1024):
        digest.update(chunk)
        if destination is not None:
            destination.write(chunk)
        size += len(chunk)
    return digest.hexdigest(), size


def _bounded_read(path: Path, limit: int) -> bytes:
    with path.open("rb") as stream:
        value = stream.read(limit + 1)
    if len(value) > limit:
        raise NativeBackupError("备份 sidecar 超出上限")
    return value


def _unique_object(pairs: list[tuple[str, object]]) -> dict:
    value = {}
    for key, item in pairs:
        if key in value:
            raise NativeBackupError("manifest 不允许重复 JSON 字段")
        value[key] = item
    return value


def _own_unlink(path: Path, staged: Path) -> None:
    try:
        current, original = path.lstat(), staged.lstat()
    except FileNotFoundError:
        return
    if stat.S_ISREG(current.st_mode) and (current.st_dev, current.st_ino) == (
        original.st_dev,
        original.st_ino,
    ):
        path.unlink(missing_ok=True)


def _stage(directory: Path, data: bytes | None, staged: list[Path]):
    """Return a stream owned by the caller, or write and close a small sidecar."""
    stream = tempfile.NamedTemporaryFile(  # noqa: SIM115 - caller owns the returned stream
        dir=directory, prefix=".native-backup-", suffix=".tmp", delete=False
    )
    staged.append(Path(stream.name))
    if data is not None:
        with stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    return stream


def _toc(runner: Callable, pg_restore: str, archive, env: dict, timeout: int, prefix: str) -> bytes:
    archive.seek(0)
    result = _run(
        runner, [pg_restore, "--list"], env, timeout, stdin=archive, stdout=subprocess.PIPE
    )
    text = result.stdout.decode("utf-8", "strict")
    for suffix in ("records", "versions"):
        if not re.search(
            r"^\d+;\s+\d+\s+\d+\s+TABLE public " + re.escape(prefix + "_" + suffix) + r"\s",
            text,
            re.MULTILINE,
        ):
            raise NativeBackupError("备份不是含指定项目表结构的完整归档")
    # Never install extensions or change their administrator-owned comments.
    return (
        "\n".join(
            line
            for line in text.splitlines()
            if not re.match(r"^\d+;\s+\d+\s+\d+\s+(?:EXTENSION\b|COMMENT\s+-\s+EXTENSION\b)", line)
        )
        + "\n"
    ).encode("utf-8")


def native_backup(
    file: Path,
    *,
    expected_database: str,
    expected_role: str,
    expected_project: str,
    prefix: str,
    connection: dict | None = None,
    timeout: int = 300,
    pg_dump: str = "pg_dump",
    pg_restore: str = "pg_restore",
    runner: Callable = subprocess.run,
    connect: Callable = psycopg2.connect,
) -> dict:
    """Export a read-only snapshot and no-clobber publish dump/SHA/manifest.

    Three paths are individually atomic, not a crash-atomic group. Output directory
    must be trusted; hard links are required. Passwords are child environment only.
    """
    _identity(expected_database, expected_role, expected_project, prefix, timeout)
    options = _options(connection, expected_database, expected_role, timeout)
    env, file = _environment(options, timeout), Path(file)
    _filename(file)
    targets = _paths(file)
    if any(os.path.lexists(path) for path in targets):
        raise NativeBackupError("备份、SHA 或 manifest 已存在，拒绝覆盖")
    file.parent.mkdir(parents=True, exist_ok=True)
    staged, published, committed, db = [], [], False, None
    try:
        db = connect(**options, cursor_factory=RealDictCursor)
        db.set_session(readonly=True, isolation_level="REPEATABLE READ")
        catalog = _catalog(db)
        _source_matches(catalog, expected_database, expected_role, prefix)
        major = catalog["server_version_num"] // 10000
        if (
            _major(runner, pg_dump, env, timeout) != major
            or _major(runner, pg_restore, env, timeout) != major
        ):
            raise NativeBackupError("工具与数据库主版本必须一致")
        with db.cursor() as cur:
            cur.execute("SELECT pg_export_snapshot() AS snapshot")
            snapshot = cur.fetchone()["snapshot"]
        with _stage(file.parent, None, staged) as stream:
            _run(
                runner,
                [
                    pg_dump,
                    "--no-password",
                    "--format=custom",
                    "--no-owner",
                    "--no-privileges",
                    "--snapshot=" + snapshot,
                ],
                env,
                timeout,
                stdout=stream,
            )
            stream.flush()
            os.fsync(stream.fileno())
        # subprocess inherits the OS file offset, not BufferedReader's logical
        # offset after read-ahead + seek(0). Keep pg_restore input unbuffered.
        with staged[0].open("rb", buffering=0) as archive:
            if archive.read(5) != b"PGDMP":
                raise NativeBackupError("pg_dump 未生成 custom 归档")
            _toc(runner, pg_restore, archive, env, timeout, prefix)
        with staged[0].open("rb") as archive:
            digest, size = _hash_stream(archive)
        manifest = {
            "schema": 1,
            "project": expected_project,
            "prefix": prefix,
            "file": file.name,
            "sha256": digest,
            "bytes": size,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "snapshot": snapshot,
            "source": catalog,
            "pg_dump_major": major,
            "endpoint": {"host": str(options["host"]), "port": str(options["port"])},
        }
        _stage(file.parent, (digest + "  " + file.name + "\n").encode("utf-8"), staged)
        _stage(
            file.parent,
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2).encode("utf-8"),
            staged,
        )
        for temporary, target in zip(staged, targets):
            os.link(temporary, target)
            published.append((target, temporary))
        committed = True
        return {
            "status": "backed_up",
            "file": str(file.resolve()),
            "sha256": digest,
            "manifest": str(targets[2].resolve()),
            "bytes": size,
            "snapshot_consistent": True,
        }
    except psycopg2.Error:
        raise NativeBackupError("数据库备份身份/目录核验失败；未输出连接凭据") from None
    finally:
        if db is not None:
            db.close()
        try:
            if not committed:
                for target, temporary in reversed(published):
                    _own_unlink(target, temporary)
        finally:
            for temporary in staged:
                temporary.unlink(missing_ok=True)


def _verified_archive(
    file: Path, archive, database: str, role: str, project: str, prefix: str
) -> dict:
    _filename(file)
    for path in _paths(file):
        if not stat.S_ISREG(path.lstat().st_mode):
            raise NativeBackupError("备份三文件须为普通文件，拒绝符号链接")
    manifest = json.loads(
        _bounded_read(_paths(file)[2], 4 * 1024 * 1024).decode("utf-8"),
        object_pairs_hook=_unique_object,
    )
    if (
        not isinstance(manifest, dict)
        or type(manifest.get("schema")) is not int
        or manifest.get("schema") != 1
        or manifest.get("project") != project
        or manifest.get("prefix") != prefix
        or manifest.get("file") != file.name
        or type(manifest.get("bytes")) is not int
    ):
        raise NativeBackupError("manifest 项目/prefix/文件身份不符")
    _source_matches(manifest["source"], database, role, prefix)
    with file.open("rb") as source:
        digest, size = _hash_stream(source, archive)
    expected = (digest + "  " + file.name + "\n").encode("utf-8")
    if (
        manifest.get("sha256") != digest
        or manifest.get("bytes") != size
        or _bounded_read(_paths(file)[1], len(expected)) != expected
    ):
        raise NativeBackupError("备份 SHA/manifest 校验失败")
    archive.seek(0)
    if archive.read(5) != b"PGDMP":
        raise NativeBackupError("不是 PostgreSQL custom 归档")
    archive.seek(0)
    return manifest


def _empty_target(catalog: dict, manifest: dict, database: str, role: str) -> None:
    _database_matches(catalog, database, role)
    source = manifest["source"]
    if database == source["database"]:
        raise NativeBackupError("目标数据库名必须与源库不同")
    same_cluster = catalog.get("cluster_identifier") and catalog[
        "cluster_identifier"
    ] == source.get("cluster_identifier")
    if same_cluster and catalog["database_oid"] == source["database_oid"]:
        raise NativeBackupError("拒绝原数据库身份")
    if (
        catalog["relations"]
        or catalog["other_objects"]
        or catalog["other_connections"]
        or catalog["in_recovery"]
    ):
        raise NativeBackupError("仅允许无其他连接的独立空数据库")
    if catalog["server_version_num"] // 10000 != manifest["pg_dump_major"]:
        raise NativeBackupError("目标 PostgreSQL 主版本不匹配")
    if any(catalog[key] != source[key] for key in ("encoding", "collate", "ctype")):
        raise NativeBackupError("目标编码/locale 不匹配")
    available = {row["name"]: (row["version"], row["schema"]) for row in catalog["extensions"]}
    if any(
        available.get(row["name"]) != (row["version"], row["schema"])
        for row in source["extensions"]
    ):
        raise NativeBackupError("目标须预装同版本同 schema 扩展（含 pgvector）")


def native_restore(
    file: Path,
    *,
    expected_source_database: str,
    expected_source_role: str,
    expected_database: str,
    expected_role: str,
    expected_project: str,
    prefix: str,
    connection: dict | None = None,
    apply: bool = False,
    timeout: int = 300,
    pg_restore: str = "pg_restore",
    runner: Callable = subprocess.run,
    connect: Callable = psycopg2.connect,
    workdir: Path | None = None,
) -> dict:
    """Preflight by default; transactional recovery only into an explicit empty target.

    Freeze verified bytes before listing/recovery. Require an exclusive maintenance
    window: advisory locking coordinates this tool, not arbitrary external writers.
    """
    _identity(expected_database, expected_role, expected_project, prefix, timeout)
    _identity(expected_source_database, expected_source_role, expected_project, prefix, timeout)
    if not isinstance(apply, bool):
        raise NativeBackupError("apply 必须为布尔值")
    options = _options(connection, expected_database, expected_role, timeout)
    env, db, listing = _environment(options, timeout), None, None
    try:
        with tempfile.TemporaryFile(dir=workdir, buffering=0) as archive:
            manifest = _verified_archive(
                Path(file),
                archive,
                expected_source_database,
                expected_source_role,
                expected_project,
                prefix,
            )
            if _major(runner, pg_restore, env, timeout) != manifest["pg_dump_major"]:
                raise NativeBackupError("恢复工具主版本不匹配")
            toc = _toc(runner, pg_restore, archive, env, timeout, prefix)
            db = connect(**options, cursor_factory=RealDictCursor)
            db.set_session(readonly=True, isolation_level="READ COMMITTED")
            with db.cursor() as cur:
                cur.execute(
                    "SELECT pg_try_advisory_lock(hashtext('shilie:native-restore')) AS locked"
                )
                if not cur.fetchone()["locked"]:
                    raise NativeBackupError("目标已有恢复任务")
            _empty_target(_catalog(db), manifest, expected_database, expected_role)
            if not apply:
                return {
                    "status": "preflight",
                    "applied": False,
                    "database": expected_database,
                    "sha256": manifest["sha256"],
                    "empty_target_verified": True,
                }
            with tempfile.NamedTemporaryFile(
                dir=workdir, prefix=".native-restore-", suffix=".list", delete=False
            ) as stream:
                listing = Path(stream.name)
                stream.write(toc)
            _empty_target(_catalog(db), manifest, expected_database, expected_role)
            archive.seek(0)
            _run(
                runner,
                [
                    pg_restore,
                    "--no-password",
                    "--single-transaction",
                    "--exit-on-error",
                    "--no-owner",
                    "--no-privileges",
                    "--use-list=" + str(listing),
                    "--dbname=" + expected_database,
                ],
                env,
                timeout,
                stdin=archive,
                stdout=subprocess.PIPE,
            )
            try:
                _source_matches(_catalog(db), expected_database, expected_role, prefix)
            except (NativeBackupError, psycopg2.Error, KeyError, TypeError):
                raise NativeRestoreCommittedError(
                    "pg_restore 已成功提交，但恢复后核验失败；目标可能已写入，未自动回滚，须人工核验"
                ) from None
            return {
                "status": "restored",
                "applied": True,
                "database": expected_database,
                "sha256": manifest["sha256"],
            }
    except psycopg2.Error:
        raise NativeBackupError("恢复目标身份/目录核验失败；未输出连接凭据") from None
    except (KeyError, TypeError, json.JSONDecodeError, UnicodeError):
        raise NativeBackupError("备份 manifest/归档格式无效") from None
    finally:
        if db is not None:
            db.close()
        if listing is not None:
            listing.unlink(missing_ok=True)


def main() -> int:
    """Require explicit identities; do not load .env or invoke Docker implicitly."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["backup", "restore"])
    parser.add_argument("--file", type=Path, required=True)
    for flag in ("expected-database", "expected-role", "expected-project", "prefix"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--expected-source-database")
    parser.add_argument("--expected-source-role")
    parser.add_argument("--timeout", type=int, default=300)
    parser.add_argument("--pg-dump", default="pg_dump")
    parser.add_argument("--pg-restore", default="pg_restore")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    common = {
        "expected_database": args.expected_database,
        "expected_role": args.expected_role,
        "expected_project": args.expected_project,
        "prefix": args.prefix,
        "timeout": args.timeout,
        "pg_restore": args.pg_restore,
    }
    try:
        if args.command == "backup":
            if args.apply:
                raise NativeBackupError("backup 不接受 --apply")
            result = native_backup(args.file, pg_dump=args.pg_dump, **common)
        else:
            if not args.expected_source_database or not args.expected_source_role:
                raise NativeBackupError("restore 须指定源 database/role")
            result = native_restore(
                args.file,
                expected_source_database=args.expected_source_database,
                expected_source_role=args.expected_source_role,
                apply=args.apply,
                **common,
            )
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except NativeRestoreCommittedError:
        print(
            "NATIVE_RESTORE_COMMITTED_UNVERIFIED: pg_restore 已成功提交，恢复后核验失败；"
            "未自动回滚，勿盲目重试，须人工核验目标",
            file=sys.stderr,
        )
        return 2
    except (NativeBackupError, OSError):
        print(
            "NATIVE_BACKUP_BLOCKED: 身份、归档、工具或目标状态核验失败；未输出凭据", file=sys.stderr
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
