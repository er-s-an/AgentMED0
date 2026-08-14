# 人提交 kotaemon #758

AgentMED 默认只留本地 `draft.patch`。下面这条命令才会碰 GitHub。

## 先看

- `PR.md`：标题和正文（含 `Closes #758`）
- `upstream.patch`：打在 `Cinnamon/kotaemon` 的 `libs/ktem/ktem/index/file/graph/lightrag_pipelines.py`
- `harness.patch`（若有）：Gate 验过的 harness，**不要**当成上游路径
- `manifest.json`：`ready_to_submit` 必须是 true 才该交

## 本机准备

1. 安装并登录 `gh`（`gh auth status`）。
2. 对 `Cinnamon/kotaemon` 有开 PR 的权限，或先 fork。
3. 基线 commit：`ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`。若上游已经挪过这两个函数，先重放补丁再改。

## 提交

```bash
# 先看将要执行的 gh，不推送
agentmed pr submit CASE_ID --i-am-human --dry-run

# 人确认后再开 PR
agentmed pr submit CASE_ID --i-am-human
```

或：

```bash
./scripts/submit-upstream-pr.sh --i-am-human --pack data/pr-packs/CASE_ID
```

没有 `--i-am-human` 会退出码 2。不要从 AgentTeams skill 里调这个脚本。
