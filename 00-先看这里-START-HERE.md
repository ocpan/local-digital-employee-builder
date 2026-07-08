# 🚀 从零搭一个属于你的飞书 AI 机器人

你手里这个包，能让你在 **1-2 小时内**搭出一个飞书 AI 机器人：
别人在飞书里问它问题，它基于你给的知识库自动回答，还能分清“是你本人还是访客”给不同权限。

**你几乎不用自己写代码**——全程让 **Claude Code**（或任何 AI 编码工具：Cursor / Codex / Windsurf / GitHub Copilot 等）帮你做。你只需要复制粘贴、点几下飞书后台。

> 💡 本包是 **方法论 + 骨架版**：包含完整的架构设计、文件结构、配置模板、人格协议和知识库示例，
> `runner.py` 给出了**完整的函数接口 + 详细注释**，但不含具体实现——
> AI 工具会读 `skills/digital-twin-builder/SKILL.md` 里的完整方法论，**帮你现场生成所有代码**。
>
> 想搞懂设计理念？看 **`02-架构设计与项目全解析.md`**。

---

## 一、先装 4 样东西（30 分钟）

不确定怎么装？没关系，**装好你的 AI 编码工具（Claude Code、Cursor 等均可）后，直接把下面这段话发给它，它会一步步带你装完剩下的**：

> 我要搭一个飞书 AI 机器人。请检查我电脑上有没有装好这几样，没有的就带我装：
> ① AI 编码工具（Claude Code/Cursor/Codex 等，你自己选一个）② lark-cli（飞书命令行工具）③ python3 ④ 大脑后端 CLI（Codex CLI 或 claude，按你选的 LLM API 决定）。
> 装完帮我确认每个都能正常运行。

手动清单（供参考）：
1. **AI 编码工具** — Claude Code（官网安装）或 Cursor / Windsurf / GitHub Copilot 等任意一个，这是你的"施工队长"。
2. **lark-cli** — 飞书官方命令行：`npm install -g @larksuite/cli`（连不上就加 `--registry https://registry.npmjs.org/`）。
3. **python3** — mac 一般自带；`python3 --version` 能出版本就行。
4. **大脑后端** — 按你选的 LLM API 决定：用个人 OpenAI/Claude API Key 或企业内网 LLM 网关均可。具体见 `bot/brain_home/` 说明。让 AI 工具帮你配最省事。

> ⚠️ **大脑网络要求**：如果你选择接企业内网 LLM 网关，你的电脑必须能访问该地址；如果用个人 API Key（OpenAI/Claude），有互联网即可。
> 企业网关需在公司网络内/VPN，个人 API 无此限制。
> 用企业网关时，先确认网络能连通再往下走。

---

## 二、放好大脑钥匙（2 分钟）

打开 `bot/brain_home/` 目录，你会看到一个文件：
`auth.json.填入你的KEY后改名为auth.json`

1. 用文本编辑器打开它，把 `<在这里粘贴 API Key>` 换成你的 LLM API Key（OpenAI / Claude / 企业网关均可）（提供包的人会单独把 Key 发给你）。
2. 把文件**改名为 `auth.json`**（去掉后面那串中文）。

> Key 是敏感凭证，别截图、别发群、别提交到 GitHub。

---

## 三、申请一个飞书机器人（20 分钟）

打开同目录的 **`01-申请飞书机器人指引.md`**，跟着图文步骤走一遍。
拿到两样东西就行：**App ID**（cli_ 开头）和 **App Secret**。

搞不定也没关系——第四步让 AI 工具陪你一起弄。

---

## 四、让 AI 工具帮你搭起来（30 分钟）★核心★

1. 用你的 AI 编码工具（Claude Code / Cursor / Codex 等）打开这个包所在的**整个文件夹**。
2. 把下面这段话**原样发给它**（它会读取包里的方法论文档，一步步带你生成代码并部署）：

> 我要用这个包搭一个飞书 AI 机器人，我是小白。请先读 `skills/digital-twin-builder/SKILL.md`，
> 然后按下面的顺序带我做，每步做完等我确认再下一步：
> 1. 读 `bot/runner.py` 的骨架注释，结合 `skills/digital-twin-builder/references/feishu-platform.md`，帮我把 runner.py **从骨架补全为完整实现**；
> 2. 帮我把 `bot/config.json` 里带 `<...>` 的都填好（app_id、我的 open_id、机器人名字等，用 lark-cli 查我的 open_id）；
> 3. 用我的飞书 App ID / Secret 帮我配置 lark-cli 的 bot 身份，并确认 `lark-cli auth status` 的 bot 是 ready；
> 4. 确认 `bot/brain_home/auth.json` 里的 Key 能连通（跑一个最小测试）；
> 5. 帮我在飞书开发者后台配好“事件订阅 im.message.receive_v1（长连接模式）”和机器人消息权限，告诉我具体点哪里；
> 6. 全部就绪后，帮我启动 `bot/runner.py`，我在飞书里给机器人发一句“你好”测试；
> 7. 我确认能收到回复后，帮我配好 7×24 常驻（launchd）。
> 遇到需要我去飞书后台点的操作，请给我明确的"点哪里、填什么"。

3. 之后就是**它说一步、你做一步**。卡住了就把报错截图/文字发给它。

---

## 五、验收：能对话就成了

- 在飞书里找到你的机器人，发"你好"——它该回一张卡片。
- 发"请假制度是怎么规定的？"——它该基于 `bot/knowledge_base/` 里的示例文档回答，并标注来源。
- 把示例文档换成你自己的真实文档，重新问，它就变成"你的领域专家"了。

---

## 六、包里都有什么

```
数字员工快速搭建包/
├── 00-先看这里-START-HERE.md      ← 你正在看的（怎么跑起来）
├── 01-申请飞书机器人指引.md        ← 申请飞书机器人的图文步骤
├── 02-架构设计与项目全解析.md      ← 深入：每个文件的作用 + 设计理念
├── skills/                        ← 3 个方法论技能（AI 工具会用到）
│   ├── digital-twin-builder/       核心：教怎么搭 + 进阶能力配方
│   ├── ai-agent-product-research/  预研：该不该搭、搭到哪一层
│   └── product-methodology/       产品方法论底座
└── bot/                           ← 机器人本体（跑起来的就是它）
    ├── runner.py                   主程序（收消息→大脑→回复）
    ├── config.json                 配置（填你的信息，唯一必改）
    ├── prompts/PROTOCOL.md         机器人的人格与规则
    ├── knowledge_base/             知识库（换成你的文档）
    ├── brain_home/                 大脑配置（OpenAI 兼容 API 的网关+Key，可换任意服务）
    ├── state/                      运行状态（本地 JSON，重启可恢复）
    ├── logs/                       运行日志
    └── deploy/                     启动 / 常驻脚本
```

> 📖 想逐个文件看懂“它是什么、干什么、要不要改”，以及理解这套架构的设计理念，看 **`02-架构设计与项目全解析.md`**。

---

## 想让它更强？

基础版只做"知识问答"。想加**附件分析、后台长任务、每日晨报、查业务系统**等进阶能力，
对你的 AI 编码工具说：

> 读 `skills/digital-twin-builder/references/advanced-capabilities.md`，帮我给机器人加上 <某个能力>。

那份文档里有 12 个进阶能力的完整配方和踩坑记录。慢慢长，别一次全上。
