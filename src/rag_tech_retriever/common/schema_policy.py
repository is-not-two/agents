"""Production never authorizes startup DDL; migration is a separate operator action."""

from rag_tech_retriever.common.config_loader import ConfigError, ConfigLoader, load_yaml_mapping


def resolve_schema_mode(profile: str, requested: str = "") -> str:
    """Empty means verify in production and legacy auto only in local development."""
    if profile not in {"local", "production"} or requested not in {"", "auto", "verify"}:
        raise ConfigError("部署模式或WORKSPACE_SCHEMA_MODE无效")
    selected = requested or ("verify" if profile == "production" else "auto")
    if profile == "production" and selected != "verify":
        raise ConfigError("生产启动只允许verify；结构迁移需管理员独立执行")
    return selected


def configured_schema_mode(config: ConfigLoader) -> tuple[str, str]:
    """Direct scripts and the Web app observe the same environment/YAML profile."""
    path = config.settings_path.parent / "web.yaml"
    operations = load_yaml_mapping(path).get("operations", {}) if path.exists() else {}
    if not isinstance(operations, dict): raise ConfigError("operations配置无效")
    profile = str(config.env("WORKSPACE_PROFILE", str(operations.get("profile", "local"))))
    return profile, resolve_schema_mode(profile, str(config.env("WORKSPACE_SCHEMA_MODE", "")))


def schema_timeouts(config: ConfigLoader) -> dict[str, int]:
    """Bound metadata checks and administrator locks; invalid settings never relax limits."""
    path = config.settings_path.parent / "web.yaml"
    operations = load_yaml_mapping(path).get("operations", {}) if path.exists() else {}
    if not isinstance(operations, dict): raise ConfigError("operations配置无效")
    defaults = {"schema_verify_timeout_ms": 3000, "schema_lock_timeout_ms": 5000, "schema_migration_timeout_ms": 60000}
    values = {key: operations.get(key, default) for key, default in defaults.items()}
    if any(type(value) is not int or not 100 <= value <= (10000 if key == "schema_verify_timeout_ms" else 300000)
           for key, value in values.items()):
        raise ConfigError("结构核验、锁或迁移超时配置无效")
    return values
