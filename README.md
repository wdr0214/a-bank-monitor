# A股银行股小时监控

这个项目用于监控上市满 5 年的 A 股银行股。GitHub Actions 生成最新数据，Vercel 部署网页，cron-job.org 定时触发刷新。

## 数据口径

- 当前股息率：2026 当前口径使用近 12 个月已除权现金分红 / 当前股价。
- 股息率百分位：2025 年及以前历史样本使用对应归属年度总分红 / 当日收盘价，不使用 TTM。
- 业绩增速：截至统计时点可见的最新报告期归母净利润同比。
- 股票池：上市满 5 年的 A 股银行股。

## 本地运行

```powershell
python -m pip install -r requirements-actions.txt
python scripts/update_bank_data.py
python -m http.server 8000
```

然后打开 `http://localhost:8000/web/index.html`。

## Vercel 环境变量

手动刷新按钮需要在 Vercel 配置：

- `GITHUB_TRIGGER_TOKEN`：GitHub Fine-grained PAT，只授权当前仓库 Actions 写权限。
- `GITHUB_OWNER`：GitHub 用户名或组织名。
- `GITHUB_REPO`：`a-bank-monitor`。
- `GITHUB_WORKFLOW_FILE`：`refresh-bank-data.yml`。
- `GITHUB_REF`：`main`。

## cron-job.org 触发

创建 4 个 POST 任务，请求：

```text
https://api.github.com/repos/<OWNER>/a-bank-monitor/actions/workflows/refresh-bank-data.yml/dispatches
```

Headers：

```text
Authorization: Bearer <GITHUB_FINE_GRAINED_PAT>
Accept: application/vnd.github+json
X-GitHub-Api-Version: 2022-11-28
Content-Type: application/json
```

Body：

```json
{"ref":"main","inputs":{"source":"cron-job.org"}}
```

北京时间触发时间：`10:00 / 11:00 / 13:30 / 14:30`。
若 cron-job.org 使用 UTC，则配置：`02:00 / 03:00 / 05:30 / 06:30`。
