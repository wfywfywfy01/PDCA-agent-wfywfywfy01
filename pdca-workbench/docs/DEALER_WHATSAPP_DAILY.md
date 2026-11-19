# 经销商 WhatsApp 新品话术日报

独立任务 `dealer_whatsapp_script_daily`，每天 Asia/Shanghai 09:00 调度。
默认关闭，不修改任何已有督战配置。仅发固定群
`7065d7ec-8b7a-4006-93ff-459d4d1671ad`。

复用现有正常登录的 `vps-work` 和个人 AINativeSales 配置，不传 vps_user_id；
catalog 必须映射已验证业务用户 38。文本模型固定校验为现有 DeepSeek flash。
用户已在 2026-11-19 明确授权所选 WhatsApp 原文发送至该模型并在服务器保存证据。
不导出凭据，不提取机器人或管理员身份。

部署已通过发布门禁的精确 main commit 后，先执行：

```sh
python -m app.dealer_whatsapp_daily
```

预演只在 `/app/data/dealer-whatsapp-daily/preview/` 保存当天正文与审计，不发消息。
核对 audit.error_type 为空、分项引用有效、覆盖及分页完整性已披露。

验收后创建 `/app/data/dealer-whatsapp-daily/enabled`，文件内容为上述固定群 ID。
此文件在持久 data 卷，容器重启与后续发布不会丢失。删除本任务 enabled 文件即可停用，
不影响其他任务。可通过 PDCA_DEALER_DAILY_DIR 指定独立持久目录。

运行台账复用 scheduled_job_run；发送前遍历当天群历史，同标题或日期幂等键命中则跳过。
发送失败后复用已落盘正文和同一幂等键，不重新评分换正文。
发送回执和复读历史一致才记成功。数据或模型失败发送一次未评分状态，不伪造正常日报。
群组入口未提供时保留覆盖未知；图片和视频不做内容识别。

原 Codex 任务需在服务器验收后停用。切换过渡期两端使用相同日期幂等键，
即使同时触发也不应产生两条发送；不以此替代正式停用旧调度。
