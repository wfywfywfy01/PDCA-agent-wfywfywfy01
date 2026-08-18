# -*- coding: utf-8 -*-
# 由 pdca_workbench.py 按域拆分生成：IM 表格渲染
# 本文件不单独 import：由 pdca_workbench/__init__.py 以共享命名空间按原顺序 exec，
# 与拆分前单文件语义完全一致。所有符号请通过 `import pdca_workbench` 访问。


def im_table_rows(channels, date_text):
    return "".join(
        "<tr>"
        f"<td><a href=\"{esc(route_url('/open-im-channel', date_text, channel_id=channel.get('id')))}\">{esc(channel.get('name'))}</a></td>"
        f"<td>{esc(channel.get('unread_count'))}</td>"
        f"<td>{esc(compact_text((channel.get('latest_message') or {}).get('body_preview') or (channel.get('latest_message') or {}).get('body_text')))}</td>"
        f"<td>{esc(channel.get('last_interest_dt'))}</td>"
        "</tr>"
        for channel in channels
    )
