---
name: digital-twin-builder
description: |
  搭建「个人数字分身 / 部门数字员工」聊天机器人的端到端方法论与可复用资产，从一个飞书个人数字分身（示例代号 示例Agent）的真实搭建 + 迭代过程抽象而来。
  覆盖：五层架构（感知/大脑/知识/行动/状态）、大脑选型（Claude Code headless / 企业 LLM via Codex / OpenAI 兼容）、
  知识库 RAG、人格框架协议（PROTOCOL）、身份分权铁律（本人 vs 访客）、技能体系、卡片样式、飞书 lark-cli 平台细节与坑位；
  以及进阶能力（后台长任务执行器 / 定时任务 / 授权自愈 / 只读白名单闸门 / 大脑健壮性 / DM 代答 / 观测自愈 / 自我改造安全）
  和「一套底座复制给多人/多部门」的规模化推广方法。
  Use when: 要给某个人或某部门搭数字分身/数字员工飞书机器人（读其知识库、替他答疑/收集需求/查业务系统/调技能/定时产出），
  或帮同事、其他业务中心批量复制这套能力，或把它移植到其他 Agent 平台/IM 渠道；
  需要现成的 config 模板、PROTOCOL 人格协议模板、runner 骨架思路、权限模型、进阶能力配方、推广清单时。
argument-hint: 描述要给谁/哪个部门搭、用什么大脑、什么渠道、连哪个知识库、是单个还是批量复制
---

# 数字分身搭建手册（Digital-Twin Builder）

> 从一个飞书个人数字分身（示例代号 示例Agent）的真实搭建过程提炼。参考实现：本地 `your-digital-twin/` 项目。
> 本 skill 教"怎么搭一个分身"，把**通用能力**与**平台特定实现**分开，便于复用到不同的人、不同的渠道/平台。

## 何时用
- 给某人搭建他个人的飞书数字分身（基于他的知识库答疑、收集需求、按身份分权、调技能）。
- 给一个部门/业务中心搭"数字员工"（对内答疑 + 查业务系统 + 定时产出报告）。
- **帮同事、其他业务中心批量复制这套能力**（一套底座、N 个分身）——见 [references/scaling-playbook.md](references/scaling-playbook.md)。
- 把分身能力移植到其他 IM（企业微信、Slack…）或其他 Agent 平台（HiAgent 等）。
- 需要现成模板（config、PROTOCOL 人格协议）、架构决策、进阶能力配方、上线/推广清单。

## 两个成熟度阶段
- **阶段一 · 跑通基础分身**：五层架构 + 知识库 + 人格 + 分权 + 上线。本文件正文 + [references/architecture.md](references/architecture.md) + [references/feishu-platform.md](references/feishu-platform.md)。
- **阶段二 · 长出进阶能力**：后台长任务、定时晨报/周报、授权自愈、观测自愈、DM 代答等。全部配方见 [references/advanced-capabilities.md](references/advanced-capabilities.md)（从 示例Agent 2026-07 真实迭代提炼，每节含反模式与血泪坑）。别一次全上，按对方的痛点排优先级（先"提速稳定"，再"后台执行器"这个地基，再定时/写作类）。

## 核心理念（务必先读）
1. **先预研，后搭建**：先用 [[ai-agent-product-research]] 把"给谁、解决什么、什么渠道、什么大脑、连什么知识"想清楚，别上来写代码。
2. **通用 vs 平台特定要分层**：分身的"大脑/知识/人格/权限"是通用的；"收发消息/卡片/认证"是平台特定的。换平台只换最外层壳。见 [references/architecture.md](references/architecture.md)。
3. **知识库先行**：先把这个人的知识沉淀成可检索的仓库（RAG），再搭对话；没有数据源就明确降级，绝不编造。
4. **人格即协议**：用一份 PROTOCOL 框架文档约束分身行为（身份/知识源/回答流程/技能/权限/输出格式），作为系统提示注入，每轮重注入防稀释。
5. **身份分权是铁律**：分身用的是"本人"的权限，所以必须识别当前对话者、对访客严格限权（只读、只看该公开的、不暴露隐私与来源、不替本人操作）。
6. **写操作必须确认**：建任务/发消息/改配置等一律先讲清再征得同意；高风险默认本人专属。
7. **每一步都验证**：发真实消息、读真实回复、看真实卡片渲染，别只看代码。

## 五层架构（通用骨架）
```
渠道消息 → [感知层] 订阅/接收事件
        → [大脑层] headless LLM agent（Claude Code 或 Codex/企业LLM），cwd=知识库
        →   ├ [知识层] RAG 检索仓库，命中引用来源、未命中降级
        →   └ [护栏] 身份分权 + 反幻觉 + 写操作确认
        → [行动层] 调平台 CLI/API 回复、建任务、出文档
        → [状态层] 会话续聊（多轮）、去重、待确认草稿
```
每层的通用职责与可替换点见 [references/architecture.md](references/architecture.md)。

## 搭建流程（按阶段）

### 阶段 0 · 预研与决策
跑 [[ai-agent-product-research]]，产出：目标用户、高频任务、渠道、成功指标、不做范围。然后定三个关键选型：
- **大脑**：用 Claude Code（Anthropic token）还是企业 LLM（经 Codex 对接企业内部的 OpenAI 兼容网关，省 token、合规）？见 [references/architecture.md](references/architecture.md#大脑选型)。
- **渠道**：飞书 / 企业微信 / Slack / Web…（本 skill 以飞书 lark-cli 为参考实现）。
- **知识库**：用哪个仓库做 RAG？是否已同步、覆盖是否够。

### 阶段 1 · 知识库
把这个人的资料整理成一个可检索仓库（按 类别/业务线/产品 归档 + 一个 `rag_search.py` 关键词检索脚本即可起步，不必一上来上向量库）。给每篇从云文档来的文件打"源链接标签"，让回答的「来源」可点击追溯。

### 阶段 2 · 骨架与配置
复制参考实现的项目结构，按 [assets/config.template.json](assets/config.template.json) 填配置（机器人名、owner、知识库路径、大脑 provider、访问策略、卡片文案）。

### 阶段 3 · 人格协议
用 [assets/PROTOCOL.template.md](assets/PROTOCOL.template.md) 生成这个分身的 PROTOCOL（替换名字/owner/知识库/业务），作为系统提示。它已内置：身份、知识源铁律、回答流程、附件分析、云文档、技能调度、身份分权三铁律、输出格式。

### 阶段 4 · runner（感知+行动）
按 [references/feishu-platform.md](references/feishu-platform.md) 写守护进程：事件消费→过滤（渠道/身份/去重/@）→大脑→回复。飞书要点：表情回执、思考过程流式卡片、卡片 2.0 样式、附件分析、回复引用消息、多轮 resume。换平台时只重写这一层。

### 阶段 5 · 身份分权
识别 owner vs 访客（比对 open_id），按身份给不同系统提示 + 不同沙箱（访客 read-only）。访客铁律：只读、只看产品/公开库、不暴露隐私与来源、不借本人身份操作。详见 PROTOCOL 模板第二章。

### 阶段 6 · 技能体系
给分身装技能（CLI 型 skill：放 `skills/<name>/SKILL.md` + 二进制，runner 启动扫描建「可用技能清单」注入系统提示）。写操作类技能默认 owner-only。可建"自动化测试体系"等自有技能。

### 阶段 7 · 上线
飞书自建应用需**发布 + 管理员审核 + 配可用范围 + 开群消息权限**才能对外/拉群。见 [references/feishu-platform.md](references/feishu-platform.md#上线)。上线后用真实账号回放验证。

## 关键坑位（血泪）
- 事件订阅 `event consume` 必须显式 `--as bot`，子进程保持 stdin 打开（EOF=退出）。
- 启 runner 前先杀干净旧进程，确认 consumers=1，否则重复回复。
- 飞书卡片 2.0：`note`/`ud_icon` 不可用；表格/折叠面板/markdown 图片(需先上传换 img_key)可用；卡片更新用 `api PATCH /im/v1/messages/{id}`。
- 大脑被检索内容稀释 → 人格每轮重注入；反幻觉是产品规则不是模型能力。
- 企业 LLM 经 Codex：session id 在 `--json` 的 `thread.started` 事件；访客用 `-s read-only` 沙箱物理拦写/网络。
- 用户身份操作（如测别的机器人）要额外 OAuth scope，token 会过期需续期。

## 跨平台移植
通用层（大脑/知识/人格/权限/技能）直接复用；只重写"感知+行动"壳：把 lark-cli 的收消息/发卡片换成目标平台的 SDK/API。映射表见 [references/architecture.md](references/architecture.md#跨平台映射)。

## 帮别人搭：规模化推广（阶段二核心场景）
你的目标常常不是"给自己搭一个"，而是"帮一堆同事/部门各搭一个"。这是**复制问题**，不是重新发明：
1. **一套底座、按人/部门实例化**：runner 逻辑通用，差异全部收敛到 `config.json`（机器人 app、owner、知识库路径、大脑 provider、业务系统凭证、定时任务、访问策略）+ 各自的 PROTOCOL + 各自的知识库。
2. **每个分身要素清单**：独立飞书自建应用（app_id/secret）、独立 launchd/systemd 服务、独立知识库仓库、独立凭证目录。别共用 app（一个 app 只能一个事件消费者）。
3. **先预研再复制**：每个对象都先跑 [[ai-agent-product-research]] 的"数字员工快速预研"——他的高频任务、要连的业务系统、要不要对访客开放、要不要定时产出，可能和 示例Agent 完全不同，别无脑套。
4. **推广的真正门槛不是代码，是知识库和权限**：对方有没有可沉淀的知识源、业务系统 CLI/API 是否可得、飞书应用发布审核走不走得通——这些先摸清。
完整清单、常见反模式、交付物模板见 [references/scaling-playbook.md](references/scaling-playbook.md)。

## 可复用资产
- [assets/config.template.json](assets/config.template.json) — 配置模板（占位）
- [assets/PROTOCOL.template.md](assets/PROTOCOL.template.md) — 人格框架协议模板（含三条身份分权铁律）
- [references/architecture.md](references/architecture.md) — 五层架构、大脑选型、跨平台映射
- [references/feishu-platform.md](references/feishu-platform.md) — 飞书 lark-cli 细节、卡片 2.0、事件、认证、上线
- [references/advanced-capabilities.md](references/advanced-capabilities.md) — **进阶能力 12 配方**（后台执行器/定时/授权自愈/白名单闸/大脑健壮性/DM代答/观测/自我改造，含反模式与坑）
- [references/scaling-playbook.md](references/scaling-playbook.md) — **规模化推广手册**（帮多人/多部门复制：要素清单、实例化流程、交付物、反模式）
