"""Readonly PostgreSQL catalog verification of the workspace's actual resolved tables."""

import re
from typing import Any

RECORD_COLUMNS = {"id": "text", "kind": "text", "version": "integer", "data": "jsonb",
                  "deleted": "boolean", "created_at": "timestamp with time zone", "updated_at": "timestamp with time zone"}
VERSION_COLUMNS = {"record_id": "text", "version": "integer", "data": "jsonb", "deleted": "boolean",
                   "action": "text", "created_at": "timestamp with time zone"}


class SchemaValidationError(Exception):
    """Public diagnostic text contains no data rows, credentials or connection strings."""


def managed_kind_check(expression: str, kinds: set[str]) -> bool:
    """Recognize the full managed ANY/ARRAY expression, not a bag of quoted words."""
    tokens = re.findall(r"'(?:[^']|'')*'|::|[A-Za-z_][A-Za-z_0-9]*|[^\s]", expression)
    # pg_get_expr returns enclosing parentheses. Remove only a complete outer pair.
    while len(tokens) >= 2 and tokens[0] == "(" and tokens[-1] == ")":
        depth = 0; complete = True
        for index, token in enumerate(tokens):
            depth += (token == "(") - (token == ")")
            if depth == 0 and index != len(tokens)-1: complete = False; break
        if not complete: break
        tokens = tokens[1:-1]
    if tokens[:6] != ["kind", "=", "ANY", "(", "ARRAY", "["] or tokens[-2:] != ["]", ")"]:
        return False
    items = tokens[6:-2]; found = []
    while items:
        if len(items) < 3 or not re.fullmatch(r"'[a-z_]+\d*'", items[0]) or items[1:3] != ["::", "text"]:
            return False
        found.append(items[0][1:-1]); items = items[3:]
        if items:
            if items[0] != ",": return False
            items = items[1:]
            if not items: return False
    return len(found) == len(kinds) and set(found) == kinds


def _layout(cur: Any, name: str, expected: dict, *, required_privileges: tuple[str, ...]) -> tuple[dict, dict, list]:
    cur.execute("SELECT c.oid,c.relkind,c.relpersistence,c.relowner,c.relnamespace,c.relrowsecurity,c.relispartition,n.nspowner "
                "FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.oid=to_regclass(%s)", (name,))
    relation = cur.fetchone()
    if (not relation or relation["relkind"] != "r" or relation["relpersistence"] != "p"
            or relation["relrowsecurity"] or relation["relispartition"]):
        raise SchemaValidationError("工作台表缺失或不是受支持的普通永久表；请管理员检查迁移")
    oid = relation["oid"]
    cur.execute("SELECT count(*) AS count FROM pg_inherits WHERE inhrelid=%s OR inhparent=%s", (oid, oid))
    if cur.fetchone()["count"]: raise SchemaValidationError("工作台不支持未经审核的继承或分区关系")
    cur.execute("SELECT a.attnum,a.attname,format_type(a.atttypid,a.atttypmod) AS type,a.attnotnull,a.attidentity,a.attgenerated,"
                "pg_get_expr(d.adbin,d.adrelid) AS default_expr FROM pg_attribute a LEFT JOIN pg_attrdef d "
                "ON d.adrelid=a.attrelid AND d.adnum=a.attnum WHERE a.attrelid=%s AND a.attnum>0 AND NOT a.attisdropped ORDER BY a.attnum", (oid,))
    attributes = {row["attname"]: dict(row) for row in cur.fetchall()}
    if set(attributes) != set(expected) or any(attributes[k]["type"] != v or not attributes[k]["attnotnull"]
            or attributes[k]["attidentity"] or attributes[k]["attgenerated"] for k,v in expected.items()):
        raise SchemaValidationError("工作台列类型、必填或生成策略不兼容；未自动修复")
    for key in ("created_at", "updated_at"):
        if key in attributes and attributes[key]["default_expr"] != "now()":
            raise SchemaValidationError("工作台时间默认值不兼容")
    cur.execute("SELECT contype,conkey,confkey,confrelid,convalidated,condeferrable,confupdtype,confdeltype,conname,"
                "pg_get_expr(conbin,conrelid) AS expression FROM pg_constraint WHERE conrelid=%s ORDER BY conname", (oid,))
    constraints = [dict(row) for row in cur.fetchall()]
    wanted = [attributes[k]["attnum"] for k in (("id",) if "id" in expected else ("record_id", "version"))]
    primary = [row for row in constraints if row["contype"] == "p"]
    if len(primary) != 1 or list(primary[0]["conkey"]) != wanted or primary[0]["condeferrable"]:
        raise SchemaValidationError("工作台主键不兼容")
    cur.execute("SELECT count(*) AS count FROM pg_index WHERE indrelid=%s AND (NOT indisvalid OR NOT indisready OR (indisunique AND NOT indisprimary))", (oid,))
    if cur.fetchone()["count"]: raise SchemaValidationError("工作台索引未就绪或存在额外唯一限制")
    cur.execute("SELECT count(*) AS count FROM pg_trigger WHERE tgrelid=%s AND NOT tgisinternal AND tgenabled<>'D'", (oid,))
    if cur.fetchone()["count"]: raise SchemaValidationError("工作台存在未审核的用户触发器")
    cur.execute("SELECT count(*) AS count FROM pg_rewrite WHERE ev_class=%s", (oid,))
    if cur.fetchone()["count"]: raise SchemaValidationError("工作台存在未审核的重写规则")
    for privilege in required_privileges:
        cur.execute("SELECT has_table_privilege(%s::oid,%s) AS allowed", (oid, privilege))
        if not cur.fetchone()["allowed"]: raise SchemaValidationError("工作台运行所需的" + "/".join(required_privileges) + "权限不完整")
    return dict(relation), attributes, constraints


def verify_workspace_schema(cur: Any, records: str, versions: str, kinds: set[str], *,
                            require_runtime_role: bool = False, verify_kind: bool = True) -> dict:
    """Read catalogs only; callers enforce readonly transaction for startup checks."""
    record, cols, checks = _layout(cur, records, RECORD_COLUMNS, required_privileges=("SELECT", "INSERT", "UPDATE"))
    version, version_cols, version_checks = _layout(cur, versions, VERSION_COLUMNS, required_privileges=("SELECT", "INSERT"))
    if record["relnamespace"] != version["relnamespace"]:
        raise SchemaValidationError("记录与历史表必须位于同一已审核schema")
    fks = [row for row in version_checks if row["contype"] == "f"]
    if (len(fks) != 1 or fks[0]["confrelid"] != record["oid"] or not fks[0]["convalidated"]
            or list(fks[0]["conkey"]) != [version_cols["record_id"]["attnum"]]
            or list(fks[0]["confkey"]) != [cols["id"]["attnum"]] or fks[0]["condeferrable"]
            or fks[0]["confupdtype"] != "a" or fks[0]["confdeltype"] != "a"):
        raise SchemaValidationError("历史表外键缺失、未验证或未指向实际记录表")
    kind_checks = [row for row in checks if row["contype"] == "c"]
    if ((len(kind_checks) != 1 if verify_kind else len(kind_checks) > 1)
            or (kind_checks and kind_checks[0]["conname"] != records.lower() + "_kind_check")
            or any(row["contype"] not in {"p", "c"} for row in checks)
            or any(row["contype"] not in {"p", "f"} for row in version_checks)):
        raise SchemaValidationError("工作台有未知或冲突约束，需管理员独立审核")
    if verify_kind and (not kind_checks[0]["convalidated"] or not managed_kind_check(kind_checks[0]["expression"], kinds)):
        raise SchemaValidationError("工作台kind约束未完整迁移或未验证")
    if require_runtime_role:
        cur.execute("SELECT rolsuper,rolcreatedb,rolcreaterole,rolreplication,rolbypassrls FROM pg_roles WHERE rolname=current_user")
        if any(cur.fetchone().values()): raise SchemaValidationError("生产运行账号权限过高，不能使用管理员账号启动")
        cur.execute("SELECT has_database_privilege(current_database(),'CREATE') AS allowed")
        if cur.fetchone()["allowed"]: raise SchemaValidationError("生产运行账号不得拥有数据库CREATE权限")
        for relation in (record, version):
            cur.execute("SELECT pg_has_role(current_user,%s::oid,'MEMBER') OR pg_has_role(current_user,%s::oid,'MEMBER') "
                        "OR has_schema_privilege(%s::oid,'CREATE') AS excessive", (relation["relowner"], relation["nspowner"], relation["relnamespace"]))
            if cur.fetchone()["excessive"]: raise SchemaValidationError("生产运行账号不能拥有表/schema或继承owner角色及CREATE权限")
            for privilege in ("DELETE", "TRUNCATE", "TRIGGER", "REFERENCES"):
                cur.execute("SELECT has_table_privilege(%s::oid,%s) AS allowed", (relation["oid"], privilege))
                if cur.fetchone()["allowed"]: raise SchemaValidationError("生产运行账号存在非必要的删除或结构权限")
        # History is append-only: table grants and per-column UPDATE grants both
        # permit rewriting audit rows, although RecordStore never needs either.
        cur.execute("SELECT has_any_column_privilege(%s::oid,'UPDATE') AS allowed", (version["oid"],))
        if cur.fetchone()["allowed"]: raise SchemaValidationError("生产运行账号存在非必要的历史UPDATE权限")
        cur.execute("SELECT count(*) AS count FROM pg_roles WHERE rolname=ANY(%s) AND pg_has_role(current_user,oid,'MEMBER')", (
            ["pg_read_server_files", "pg_write_server_files", "pg_execute_server_program", "pg_read_all_data", "pg_write_all_data", "pg_signal_backend", "pg_checkpoint"],))
        if cur.fetchone()["count"]: raise SchemaValidationError("生产运行账号继承了非必要的全局或服务器权限")
    return {"verified": True, "tables": [records, versions], "kinds": sorted(kinds),
            "runtime_role_checked": require_runtime_role, "ddl_executed": False}
