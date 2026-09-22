# 迁移说明

Alembic 迁移目录。应用启动时仍会执行 `SQLModel.metadata.create_all()` +
`app/database.py::_migrate_schema()` 的兜底补丁；本目录是正式迁移通道，
两者内容保持等价（幂等）。

## 已有库首次接入 Alembic

已有数据库（由 create_all/运行时补丁建出）没有 `alembic_version` 表，
直接 `alembic upgrade head` 会因 001 与现有表冲突而失败。使用显式迁移入口；
它会补齐历史结构、标记到安全基线 010，再实际执行后续约束和数据迁移：

```powershell
cd pdca-workbench
python scripts/migrate.py
```

## 全新库

```powershell
cd pdca-workbench
alembic upgrade head
```

## 版本

- `001_initial`：初始表结构
- `002_security_hardening`：token_revocations / login_fail_records 表，
  以及历史运行时 schema 补丁的正式化（幂等，可用 inspector 检查列存在性）
