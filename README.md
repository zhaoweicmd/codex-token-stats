# Codex Token 统计

本地统计 Codex 的 token 消耗，按任务、项目、供应商、模型和统计时段汇总，并根据本地价格配置计算费用。数据不离开本机。

## 环境要求

- Python 3.9+
- macOS 或 Windows
- Codex 数据目录保持默认位置（`~/.codex`，Windows 为 `%USERPROFILE%\.codex`）

## 快速开始

```bash
./run.sh scan
./run.sh report --period month
./run.sh serve
```

Windows 在命令行中执行：

```bat
run.bat scan
run.bat report --period month
run.bat serve
```

网页面板默认地址为 `http://127.0.0.1:8765`。

面板运行期间默认每 60 秒自动扫描一次 Codex 会话，新增任务会自动入库；也可以点击页面上的“刷新数据”立即扫描。间隔可在 `config.json` 的 `scan_interval` 中调整。

## 价格与费用

- 网页面板和命令行报表会显示总体、项目、任务及轮次费用
- 价格配置位于 `codex_stats/pricing.py`，按模型名称配置输入、缓存读取和输出价格，供应商信息单独统计
- 未配置价格的模型仍会统计 token，但费用显示为“未配置”，汇总中会提示未配置任务数
- 费用仅在本机根据 token 记录和价格配置计算，不会向外部服务发送统计数据

## 修正项目归属

Codex 只记录任务的工作目录，不记录正式项目名，所以同一目录里的多个任务可能被归到同一个目录名。

- 打开任务明细后，在“项目归属”输入框填写正确项目名并保存
- 点击“恢复自动”可清除手动修正，重新按目录、Git 仓库或任务标题自动归组
- 手动修正会保存在统计库中，之后扫描不会覆盖

## 常用命令

- `scan`：扫描 Codex 会话文件，写入本地 SQLite 统计库
- `report --period today|7d|month|year|all`：输出总体报表
- `report --dimension project`：按项目汇总
- `report --dimension provider`：按供应商汇总
- `report --dimension task`：按任务汇总
- `report --dimension model`：按模型汇总并显示费用
- `report --dimension day`：按日期汇总并显示费用
- `report --from "2026-08-01 10:00" --to "2026-08-03 18:00" --dimension day`：自定义时段按天汇总，时间精确到分钟
- `serve --port 8765`：启动网页统计面板
- `report --csv report.csv`、`report --json report.json`：导出结果

所有报表命令都支持 `--from`、`--to`、`--project`、`--provider` 过滤。

## 数据口径

- 每个会话文件对应一个任务，任务内每一轮对话单独记录
- 项目优先按配置别名归组，其次按任务标题中的仓库地址归组，再次按 Git 仓库归组，最后按工作目录归组
- 若配置了 `project_rules` 和 `default_project`，规则匹配命中后直接归入指定项目，其余任务统一归入默认项目
- 供应商来自 Codex 会话中的 `model_provider` 字段，模型来自任务元数据
- 统计时段按每轮 token 记录的发生时间归入对应日期

## 配置

复制 `config.example.json` 为 `config.json` 后按需修改：

- `codex_home`：Codex 数据目录，默认取 `~/.codex` 或 `CODEX_HOME`
- `db_path`：统计数据库路径，默认保存在工具目录下
- `provider_names`：供应商显示名称
- `project_aliases`：把指定目录映射为自定义项目名
- `project_rules`：按目录或任务标题关键词归入指定项目
- `default_project`：未命中任何规则时的默认项目名
- `project_rules_mac` / `project_rules_win`：分别只对 macOS / Windows 生效，优先于通用 `project_rules`
- `default_project_mac` / `default_project_win`：分别指定 macOS / Windows 的默认项目

模型价格配置直接维护在 `codex_stats/pricing.py`。同一模型如果在不同供应商下价格不同，应使用不同的模型标识或扩展价格配置逻辑，避免混用价格。

`config.json` 按系统分别配置项目规则：macOS 和 Windows 可各自指定默认项目与项目规则，未填写的一侧使用通用配置或按目录自动归组。示例见 `config.example.json`。

## 自动扫描

macOS 可用 `launchd` 定时运行 `run.sh scan`，Windows 可用任务计划程序定时运行 `run.bat scan`。统计面板启动时会自动扫描一次，也可以点击页面上的“刷新数据”。
