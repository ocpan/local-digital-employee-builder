#!/usr/bin/env python3
"""数字员工机器人 · 骨架版（runner skeleton）

本文件是 runner 的完整接口骨架——展示了所有模块和函数该做什么，但**不含具体实现**。
让你的 AI 编码工具（Claude Code / Cursor / Codex / 任何支持读文件的工具）读取
skills/digital-twin-builder/SKILL.md，它就能根据这份骨架 + 方法论文档帮你补全所有实现。

用法：对 AI 说——
> 读 skills/digital-twin-builder/SKILL.md 和 skills/digital-twin-builder/references/feishu-platform.md，
> 然后把 bot/runner.py 从骨架补全为完整实现。config.json 和 prompts/PROTOCOL.md 已经写好了。

=== 数据流 ===
  lark-cli event consume im.message.receive_v1 (NDJSON)
    → 过滤（P2P / 群聊@ + 访问控制 + message_id 去重）
    → 大脑（headless LLM，cwd=知识库，人格=PROTOCOL.md，每轮重注入）
    → 知识库预检索（rag_search.py，命中注入来源，未命中降级不编造）
    → lark-cli 回复飞书卡片（2.0 schema，支持思考过程流式 PATCH）
    → 会话续聊 / 状态持久化（本地 JSON）

=== 五层职责 ===
  L1 感知层：事件消费 · 过滤去重 · @识别 · 访问控制 · 即时表情回执
  L2 大脑层：headless LLM 沙箱调用（本人 full-access / 访客 read-only）· 会话 resume · 超时看门狗 · 后端抖动自愈
  L3 知识层：知识库预检索 · 结果注入 · 未命中降级话术
  L4 行动层：飞书卡片发送与更新 · 思考过程可视化 · 图片上传
  L5 状态层：processed_ids 去重 · sessions 续聊 · 后台/定时任务队列

=== 依赖 ===
  - python3（标准库即可，无第三方依赖）
  - lark-cli（飞书命令行，npm install -g @larksuitecli）
  - 大脑后端 CLI（codex 或 claude，按 config.json brain.provider 选择）
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# ─────────────────────── 初始化 ───────────────────────

PROJECT = Path(__file__).resolve().parent
CONFIG = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
PERSONA = (PROJECT / "prompts" / "PROTOCOL.md").read_text(encoding="utf-8")
STATE_FILE = PROJECT / "state" / "processed_ids.json"
SESSIONS_FILE = PROJECT / "state" / "sessions.json"
LOG_FILE = PROJECT / "logs" / "runner.log"
STATE_LOCK = threading.Lock()

# 知识库路径解析
_kb = Path(os.path.expanduser(CONFIG.get("kb_root", "knowledge_base")))
CONFIG["kb_root"] = str(_kb if _kb.is_absolute() else PROJECT / _kb)

SESSION_TTL_SEC = int(float(CONFIG.get("session_ttl_hours", 2)) * 3600)
MAX_PROCESSED_IDS = 2000
BRAIN_TIMEOUT = "__BRAIN_TIMEOUT__"
BRAIN_BACKEND_ERR = "__BRAIN_BACKEND_ERR__"


def log(msg: str) -> None:
    """统一日志：同时打印 stdout + 追加到 logs/runner.log"""
    ...


# ─────────────────────── L1 感知层 ───────────────────────

def claim_event(event: dict) -> bool:
    """原子 claim：用 message_id 去重，防重复处理同一条消息。
    返回 True = 首次处理；False = 已处理过。
    状态存 state/processed_ids.json，滚动保留最近 2000 条。"""
    ...


def handle_event(event: dict) -> None:
    """单条消息的完整处理流程：
    1. 解析 chat_id / sender / chat_type / content
    2. 群聊判断是否 @机器人（非@忽略）
    3. 访问控制（open/whitelist，名单外发引导话术）
    4. 非文本消息回复不支持提示
    5. 打表情回执（即时反馈 Get）
    6. 判断身份（本人/访客）
    7. 发"思考中"卡片 → 知识库预检索 → 调大脑 → PATCH 为最终答案卡片
    """
    ...


def main() -> None:
    """主循环：
    1. 启动 lark-cli event consume im.message.receive_v1 --as bot --quiet（NDJSON 长连接）
    2. 逐行读 stdout → json.loads → claim_event → 线程池提交 handle_event
    3. 断线自愈：EOF/错误 5s 重连；"another event bus already connected" 退避 60s
    4. KeyboardInterrupt 优雅退出
    """
    ...


# ─────────────────────── L2 大脑层 ───────────────────────

def ask_brain(question: str, key: str, progress, is_owner: bool, name: str) -> str | None:
    """分发大脑调用（按 config.json brain.provider）：
    - provider='codex'：调 _ask_codex
    - provider='claude'：调 _ask_claude
    后端抖动自愈：失败 5s 后自动 resume 重试一次，二连败才报错。
    返回答案文本 / None / BRAIN_TIMEOUT / BRAIN_BACKEND_ERR 哨兵。"""
    ...


def _ask_codex(question: str, key: str, progress, is_owner: bool, name: str) -> str | None:
    """经 Codex CLI 调用 OpenAI 兼容大脑：
    - 读 brain_home 配置（CODEX_HOME 环境变量）
    - 会话 resume（按 key 隔离，TTL 超时开新）
    - 沙箱：本人 danger-full-access / 访客 read-only
    - 人格 + 身份块 + 知识预检结果拼入 prompt（每轮重注入防稀释）
    - 流式解析 --json 输出，翻译步骤到 progress（思考可视化）
    - 捕获 response.failed/流断等后端错误 → BRAIN_BACKEND_ERR 哨兵
    """
    ...


def _ask_claude(question: str, key: str) -> str | None:
    """经 Claude CLI 调用 Anthropic API：
    - claude -p <prompt> --output-format json --session-id / --resume
    - cwd=知识库，人格注入 --append-system-prompt
    - 超时 300s，失败 drop session
    """
    ...


# ─────────────────────── L3 知识层 ───────────────────────

def prefetch_kb(question: str, is_owner: bool, progress) -> str:
    """知识库预检索：
    - 触发判定：问题含知识类关键词（流程/制度/为什么…）且长度≥6
    - 调 knowledge_base/scripts/rag_search.py
    - 分区过滤：访客强制 --part 公开区
    - 命中返回 '【知识库预检结果】...' 供注入大脑
    - 未命中返回降级提示（不编造）
    """
    ...


# ─────────────────────── L4 行动层 ───────────────────────

def build_card(body_md: str, template: str = "blue", footer: str | None = None,
               steps_md: str | None = None) -> str:
    """构建飞书卡片 2.0 JSON（schema 2.0）：
    - header: title + text_tag_list（紫色"AI 自动回复"标签）
    - body: markdown 正文 + 可折叠思考过程面板 + hr + 灰色署名脚注
    """
    ...


def send_card(chat_id: str, body_md: str, **kwargs) -> bool:
    """发送卡片到指定 chat：lark-cli im +messages-send --as bot --msg-type interactive"""
    ...


def send_card_get_id(chat_id: str, body_md: str, **kwargs) -> str | None:
    """发送卡片并返回 message_id（用于后续 PATCH 更新）"""
    ...


def patch_card(message_id: str, body_md: str, **kwargs) -> bool:
    """更新已有卡片（思考中→最终答案）：lark-cli api PATCH /im/v1/messages/{id}"""
    ...


def react(message_id: str) -> None:
    """打表情回执（默认 Get）：即时反馈用户"已收到，正在处理" """
    ...


class Progress:
    """思考过程可视化：收集大脑步骤 → 节流 PATCH 到"思考中"卡片。"""

    def __init__(self, mid: str | None):
        self.mid = mid
        self.steps: list[str] = []

    def step(self, label: str) -> None:
        """追加步骤并节流更新卡片（≥1s 间隔）"""
        ...

    def steps_md(self) -> str:
        """返回步骤列表的 markdown 文本"""
        ...


# ─────────────────────── L5 状态层 ───────────────────────

def resolve_session(key: str, provider: str) -> tuple[str | None, bool]:
    """读取会话 ID（按 chat_id:sender 键隔离）。
    未过期返回 (session_id, False)；过期/不存在返回 (None, True)。"""
    ...


def touch_session(key: str, session_id: str, provider: str) -> None:
    """写入/刷新会话映射（state/sessions.json）"""
    ...


def drop_session(key: str) -> None:
    """丢弃会话（大脑连续失败时重置）"""
    ...


# ─────────────────────── 辅助：身份 & 技能 ───────────────────────

def resolve_name(open_id: str) -> str:
    """通过 lark-cli contact 反查飞书用户姓名（缓存避免重复调用）"""
    ...


def build_identity_block(is_owner: bool, name: str) -> str:
    """生成身份分权注入块（主人=完整权限 / 访客=三条铁律）"""
    ...


def build_skills_index() -> str:
    """扫描 skill_roots 下所有 SKILL.md，生成技能清单注入系统提示"""
    ...


# ─────────────────────── 入口 ───────────────────────

if __name__ == "__main__":
    main()
