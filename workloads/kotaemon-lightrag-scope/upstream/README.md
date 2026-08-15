# kotaemon #758 给人看的上游包

这不是已合并的 PR，也不是 AgentMED 自动开的 PR。

Gate 验过的是 harness：`workloads/kotaemon-lightrag-scope/app/lightrag_store.py`（insert 必须留下 file_id，query 必须按选中文件过滤）。这个目录把同一条合同写到 kotaemon 作者点名的两个调用点：

- https://github.com/Cinnamon/kotaemon/issues/758
- 文件：`libs/ktem/ktem/index/file/graph/lightrag_pipelines.py`
- 基线 commit：`ffe766f24d4ef8a91f8c61871d2b5a1930aa204e`

`lightrag_pipelines.base.py` 是该 commit 的快照，只用来生成 / 校验 `upstream.patch`。

## 人怎么交

1. 读 `PR.md` 和 `upstream.patch`。
2. 有 VerifiedCandidate 时再跑 `agentmed pr pack <case_id>`，把 Gate 证据装进数据包。
3. 人自己执行：

```bash
agentmed pr submit <case_id> --i-am-human
# 或
./scripts/submit-upstream-pr.sh --i-am-human --pack <pack-dir>
```

没有 `--i-am-human` 会直接拒绝。Kernel / AgentTeams 不会走这条命令。
