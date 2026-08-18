# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：Hermes 报告路径解析
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def latest_hermes_report(topic, started_at=0):
    if not DATA_REPORTS.exists():
        return None
    candidates = sorted(
        DATA_REPORTS.glob(f"*_{topic}_summary.md"),
        key=lambda item: item.stat().st_mtime,
        reverse=True,
    )
    for candidate in candidates:
        if candidate.stat().st_mtime >= started_at - 5:
            return candidate
    return candidates[0] if candidates else None


def resolve_hermes_output_path(output, topic, started_at):
    if output:
        for line in reversed(output.splitlines()):
            text = line.strip().strip('"')
            if not text:
                continue
            path = Path(text)
            if path.exists():
                return path
    return latest_hermes_report(topic, started_at)
