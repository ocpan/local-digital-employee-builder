# 架构、大脑选型与跨平台映射

## 五层架构（每层职责 + 可替换点）

| 层 | 职责 | 示例Agent 实现 | 可替换点 |
|---|---|---|---|
| 感知 | 接收用户消息/事件 | `lark-cli event consume im.message.receive_v1 --as bot`（NDJSON 流） | 换平台=换事件源（企微回调、Slack Events API、Web WS） |
| 大脑 | 理解+检索+生成+工具编排 | headless LLM agent：`claude -p` 或 `codex exec`，cwd=知识库 | 换模型=换 provider；换 agent 框架=Claude Code/Codex/自研 ReAct |
| 知识 | RAG 检索本人知识库 | `rag_search.py` 关键词检索 + 源链接标签 | 起步用关键词，规模化再上向量库 |
| 护栏 | 身份分权/反幻觉/写确认 | 每轮注入身份块 + 访客 read-only 沙箱 + PROTOCOL 规则 | 通用，跨平台不变 |
| 行动 | 回复/建任务/出文档 | `lark-cli im`（卡片）、`lark-task`、`lark-doc` | 换平台=换发送 API |
| 状态 | 多轮续聊/去重/草稿 | 会话 resume（session_id 按 chat+sender 隔离）+ 已处理 id | 通用 |

**通用 vs 平台特定**：大脑/知识/护栏/状态是通用的，跨平台直接复用；感知+行动是平台特定壳层，换平台只重写这两层。

## 大脑选型

| 方案 | 何时用 | 要点 |
|---|---|---|
| **Claude Code headless**（`claude -p`） | 有 Anthropic 额度、要最强 agent 能力 | `--append-system-prompt` 注入人格；`--session-id`/`--resume` 多轮；`--output-format json` 取结果；`--disallowedTools` 限权 |
| **Codex + 企业 LLM**（`codex exec`） | 要用企业 LLM 额度/合规（企业内部的 OpenAI 兼容网关） | 隔离的 `CODEX_HOME`（独立 config，只放该 provider，不带个人插件）；`--json` 流式事件（`thread.started`=session_id，`command_execution`/`agent_message`=步骤）；`-o` 取最终回答；resume 续聊；本人 `--dangerously-bypass-approvals-and-sandbox`，访客 `-s read-only`（物理拦写/网络） |
| **直连 LLM API** | 简单问答、无需 agent 工具循环 | runner 自己做 RAG 检索喂 prompt，单次调用；失去自主工具调用 |

**做成可切换**：config `brain.provider`，两套都保留，先跑通再决定主用。Codex 接 OpenAI 兼容网关只需 config.toml 写 `base_url`/`wire_api=responses` + auth.json 放 key（key 用文件存、gitignore、不入库、日志脱敏）。

## 人格注入与多轮
- 人格(PROTOCOL) 每轮重注入：resume 后上下文被检索内容稀释，靠首轮注入不够。
- 会话按 `chat_id:sender` 隔离：群聊多人不串上下文。
- 身份块每轮注入：群聊里发送者逐条变化，权限必须按本条消息的 sender 判定。

## 跨平台映射（把分身移到别的渠道/平台）

| 能力 | 飞书(lark-cli) | 企业微信 | Slack | 通用 Agent 平台(HiAgent 等) |
|---|---|---|---|---|
| 收消息 | event consume | 回调 URL | Events API | 平台内置触发 |
| 发消息/卡片 | im +messages-send（interactive 2.0） | 应用消息(图文/模板卡) | chat.postMessage(Block Kit) | 平台消息组件 |
| 身份 | open_id | userid | user id | 平台用户体系 |
| 大脑 | 同上（通用） | 同上 | 同上 | 平台内置 LLM/编排 |
| 知识 | RAG 仓库（通用） | 同 | 同 | 平台知识库 |
| 权限 | 沙箱+人格（通用） | 同 | 同 | 平台权限+人格 |

移植步骤：保留 大脑/知识/护栏/PROTOCOL/技能；重写 感知+行动 两个适配函数（收事件→统一 message dict；统一 reply()→平台 API）。卡片样式按目标平台的卡片 schema 重映射。
