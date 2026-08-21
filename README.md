# ContextPatch

**Creator content correction propagation across platforms**

> **Live Minds evidence:** one real store plus two recalls passed across three distinct official
> conversations on the same Mind. See [docs/LIVE_MINDS_EVIDENCE.md](docs/LIVE_MINDS_EVIDENCE.md).

ContextPatch 用来处理一个很具体的问题：创作者的源内容中某个事实改变后，哪些 X、LinkedIn、YouTube 版本需要更正，为什么现在要做，以及哪个草稿已经人工批准。

> 安全边界：ContextPatch **没有自动发布代码**。批准一个更正只会改变本地 SQLite 状态，不会向任何社交平台发帖。

## 能做什么

- 载入明确标注 `SYNTHETIC_DEMO_ONLY` 的源内容与 X / LinkedIn / YouTube 版本。
- 录入 `old_fact → new_fact` 和更正期限。
- 通过声明的 `fact_key` 和旧事实精确文本匹配，确定性找出受影响版本。
- 生成更正队列、`WHY NOW` 到期跟进、人工批准/拒绝和审计记录。
- 用 Pause / kill switch 停止新变更、决策和 Minds 请求。
- 把人工批准的事实与披露原则准备成 Minds 记忆写入包。
- 在新会话中给 Minds 一项 `change`、`memory_key` 以及最多 3 条受影响版本，要求精确召回原则并生成独立的 X / LinkedIn / YouTube 更正草稿。

## 1 分钟本地运行

要求：Python 3.10+ 和 [`uv`](https://docs.astral.sh/uv/)。

```bash
cd ContextPatch
uv sync --all-groups
uv run uvicorn app.main:app --host 127.0.0.1 --port 8010
```

然后在 Chrome 打开 `http://127.0.0.1:8010`。页面上的最短演示流程：

1. 点击 **Load synthetic demo**。
2. 使用预填的 `launch_date: September 30 → October 7`，点击 **Record & detect impacts**。
3. 审批事实与披露原则；系统会准备记忆写入包，但不会自动发送。
4. 配置后显式点击发送。生产流程不接受本地粘贴回复，防止伪造 Minds 证据。
5. 只有从已绑定会话的官方历史中精确配对回复，并先持久化运输哈希和时间证据，才会解析严格 schema。
6. 记忆写入回执通过后，系统才准备一个全新会话的召回包。受影响版本原文只作为明确不可信的当次起草语境，不得写入长期记忆。Minds 必须返回键集精确匹配的逐平台草稿，才能进入队列。

## 定义“受影响”

这里不让 AI 猜。对同一源内容的每个平台版本，只要满足任一条就入队：

1. 版本的 `fact_keys` 显式声明依赖本次 `fact_key`；
2. 规范化后的版本文本精确包含规范化后的 `old_fact`。

匹配原因会被写入 `impacts` 和审计日志，便于人工复查。

## Minds 设计

### 两阶段记忆流

1. `store_principle`：只在人工批准事实和披露原则后准备。
2. `recall_and_draft`：使用随机 `cp-recall-*` 新会话；不重发原则，传递一项已批准变更、`memory_key` 和 1–3 条合成/已批准作用域版本（每条最长 4,000 字符）。版本原文只用于当次起草，禁止长期记忆。

### 安全控制

- 用 JSON 字符串封装外部文本，明确声明其是“数据，不是指令”；本地还会标记常见 prompt injection 语言。
- 回复必须精确符合指定字段集和类型，`platform_patches` 键集必须与受影响平台完全一致，每个草稿必须非空且最长 2,000 字符。`operation` / `memory_key` 必须匹配。
- 召回的 `recalled_principle` 必须经规范化后与人工批准原则精确相等；不可用、改写或猜测都不得解锁草稿。界面会显示召回原则供人工复核。
- 只有官方运输已严格配对时才允许正文省略 `request_id`；如果正文带了错误 ID，仍会拒绝。官方历史中的出站原文哈希也必须与本地 `request_hash` 精确一致。
- `semantic_hash` 阻止相同语义请求重复创建；`request_hash` 和 `response_hash` 防止运输证据重复绑定。
- 发送前查实时余额；余额 **≤ 10** 立即停止。同进程 `asyncio` 锁和 SQLite 全局租约会串行化“余额检查 + 发送”，防止不同请求并发穿透安全线。没有充值、绑卡或自动重试代码。
- 发送超时标记 `UNCERTAIN`，只读历史并精确关联远程 message/conversation，禁止盲目重发。官方时间戳若齐全必须满足请求早于回复；若官方缺失时间戳，会明确记录 evidence limitation，不伪称已验证时序。

### 可选的真实 3 调用证据脚本

正常测试绝不访问网络。只有账户所有者明确授权时，才运行：

```bash
uv run python scripts/run_live_minds_proof.py --confirm-live
```

脚本复用父项目 `.env` 中现有 `MINDS_BUILDER_API_KEY` / `MINDS_MIND_ID`，完成一次写入和两个不同新会话召回。写入原则含随机不可猜测连续性标记；两个召回都必须精确包含该标记或完整批准原则，否则不得写入 `continuity_verified=true` 或输出 PASS。每次只发一次，之后只轮询历史；余额≤10停止。证据文件只保存哈希、余额和布尔验证结果，不保存密钥、Mind UUID、alias、远程 ID、请求正文或原始回复。

## 验证

```bash
uv sync --all-groups
make verify
```

`make verify` 依次运行 pytest + coverage、Ruff、mypy 和 Bandit。测试使用临时 SQLite 和 mock transport，不会真实调用 Minds。

## 目录

- `app/`：FastAPI、SQLite 领域流程、Minds 协议、HTML/CSS。运行应用时使用。
- `data/`：合成演示 JSON；运行后的 SQLite 文件被 Git 忽略。
- `scripts/`：只有显式授权才运行的真实 Minds 连续性证据脚本，以及演示媒体的素材生成、渲染和验证脚本。
- `tests/`：确定性规则、状态机、schema、运输安全和 Web 烟雾测试。
- `output/`：可选真实证据的脱敏输出位置。

## 事实边界

- 仓库内数据全是合成演示；不代表真实创作者、帖子、修正、触达或收入。
- 测试通过只能证明本地工程状态，不能证明市场需求、平台发布或 Minds 真实运行。
- 更正草稿的人工批准不等于已发布；实际平台操作由账户所有者完成。
