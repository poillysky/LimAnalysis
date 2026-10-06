# 框架范围 vs 做到再说

问答暂停。先落地可运行骨架，细需求在对应模块开工时再定。

## 已经拍板（框架必须遵守）

- 测试项目：`eagle_rcvr`、`whale_spkr`
- 一项目一张宽表（外观+注塑已合并）
- 一切可配置，禁止硬编码；代码只给默认值
- 默认同步 10 分钟、全量、SN 覆盖
- 登录与参照 `sfc-crawler` 一致（账号池 + SSO），实现采集时再接线
- 三套存储：SQLite meta + 独立 PG `lim_raw` + 独立 PG `lim_dwh`
- 第一期告警只做日志和页面
- **离线车间**：现场不联网；数据提前下载到本机；前端禁止 CDN / 在线图标

## 框架要做出的

- 目录职责不变（collector / processor / app / deploy）
- Compose：两个 Postgres 容器
- API 能启动；三套库连接可探测
- **项目元数据在 SQLite**；用 `POST /api/v1/system/projects` 初始化，无 YAML

## 明确不做（做到再定）

- Playwright/SSO 真爬
- 正式 ODS 宽表 DDL、Timescale 超表
- 柏拉图/NG 列表/大屏业务
- FACA 流程字段
- 企微/钉钉
