#!/usr/bin/env python3
"""数字员工机器人 · 完整实现

数据流：
  lark-cli event consume im.message.receive_v1 (NDJSON)
    → 过滤（P2P / 群聊@ + 访问控制 + message_id 去重）
    → 大脑（Claude CLI headless，cwd=知识库，人格=PROTOCOL.md，每轮重注入）
    → 知识库预检索（rag_search.py，命中注入来源，未命中降级不编造）
    → lark-cli 回复飞书卡片（2.0 schema，支持思考过程流式 PATCH）
    → 会话续聊 / 状态持久化（本地 JSON）

依赖：python3（标准库）+ lark-cli + claude CLI
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

# ─────────────────────── 初始化 ───────────────────────

PROJECT = Path(__file__).resolve().parent
CONFIG = json.loads((PROJECT / "config.json").read_text(encoding="utf-8"))
PERSONA = (PROJECT / "prompts" / "PROTOCOL.md").read_text(encoding="utf-8")
STATE_DIR = PROJECT / "state"
STATE_DIR.mkdir(exist_ok=True)
STATE_FILE = STATE_DIR / "processed_ids.json"
SESSIONS_FILE = STATE_DIR / "sessions.json"
LOG_DIR = PROJECT / "logs"
LOG_DIR.mkdir(exist_ok=True)
LOG_FILE = LOG_DIR / "runner.log"
STATE_LOCK = threading.Lock()

# 知识库路径解析
_kb = Path(os.path.expanduser(CONFIG.get("kb_root", "knowledge_base")))
KB_ROOT = str(_kb if _kb.is_absolute() else PROJECT / _kb)
CONFIG["kb_root"] = KB_ROOT

# lark-cli profile（如配置了独立 profile 则使用，环境变量 LARK_PROFILE 指定）
LARK_PROFILE = os.environ.get("LARK_PROFILE", "")
LARK_PROFILE_ARGS = ["--profile", LARK_PROFILE] if LARK_PROFILE else []

SESSION_TTL_SEC = int(float(CONFIG.get("session_ttl_hours", 2)) * 3600)
MAX_PROCESSED_IDS = 2000
BRAIN_TIMEOUT = "__BRAIN_TIMEOUT__"
BRAIN_BACKEND_ERR = "__BRAIN_BACKEND_ERR__"

# 名字缓存
_name_cache: dict[str, str] = {}


def log(msg: str) -> None:
    """统一日志：同时打印 stdout + 追加到 logs/runner.log"""
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


# ─────────────────────── L1 感知层 ───────────────────────

def _load_processed_ids() -> list[str]:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []
    return []


def _save_processed_ids(ids: list[str]) -> None:
    STATE_FILE.write_text(json.dumps(ids[-MAX_PROCESSED_IDS:], ensure_ascii=False), encoding="utf-8")


def claim_event(event: dict) -> bool:
    """原子 claim：用 message_id 去重。返回 True=首次处理。"""
    msg_id = event.get("message_id", "") or event.get("message", {}).get("message_id", "")
    if not msg_id:
        return False
    with STATE_LOCK:
        ids = _load_processed_ids()
        if msg_id in ids:
            return False
        ids.append(msg_id)
        _save_processed_ids(ids)
        return True


def handle_event(event: dict) -> None:
    """单条消息的完整处理流程"""
    try:
        # 兼容两种格式：扁平（lark-cli --quiet）和嵌套（标准 webhook）
        if "message" in event and isinstance(event["message"], dict):
            msg = event["message"]
            sender = event.get("sender", {})
            chat_id = msg.get("chat_id", "")
            chat_type = msg.get("chat_type", "")
            message_id = msg.get("message_id", "")
            message_type = msg.get("message_type", "")
            sender_id = sender.get("sender_id", {}).get("open_id", "")
            content_raw = msg.get("content", "{}")
            try:
                content_obj = json.loads(content_raw)
            except Exception:
                content_obj = {}
            text = content_obj.get("text", "").strip()
        else:
            # 扁平格式（lark-cli event consume --quiet 输出）
            chat_id = event.get("chat_id", "")
            chat_type = event.get("chat_type", "")
            message_id = event.get("message_id", "")
            message_type = event.get("message_type", "")
            sender_id = event.get("sender_id", "")
            content_raw = event.get("content", "")
            # content 在扁平格式下可能直接是文本，也可能是 JSON
            if content_raw.startswith("{"):
                try:
                    content_obj = json.loads(content_raw)
                    text = content_obj.get("text", "").strip()
                except Exception:
                    text = content_raw.strip()
            else:
                text = content_raw.strip()

        # 群聊：判断是否 @机器人
        if chat_type == "group":
            if CONFIG.get("group", {}).get("require_mention", True):
                # 扁平格式下没有 mentions 字段，但飞书标准权限只推 @bot 的群消息
                # 所以收到群消息即认为已被 @
                pass
            # 清理 @ 占位符
            text = re.sub(r"@\w+\s*", "", text).strip()

        if not text:
            return

        # 访问控制
        access_mode = CONFIG.get("access_mode", "open")
        if access_mode == "whitelist":
            whitelist = CONFIG.get("whitelist", [])
            if sender_id not in whitelist and sender_id != CONFIG["owner_open_id"]:
                _send_text(chat_id, CONFIG.get("redirect_text", "抱歉，我目前未对你开放。"))
                return

        # 非文本消息
        if message_type != "text":
            _send_text(chat_id, CONFIG.get("unsupported_text", "我目前只支持文本消息。"))
            return

        # 表情回执（即时反馈）
        react(message_id)

        # 判断身份
        is_owner = (sender_id == CONFIG["owner_open_id"])
        name = CONFIG["owner_name"] if is_owner else resolve_name(sender_id)

        log(f"收到消息: chat={chat_id}, sender={name}({'主人' if is_owner else '访客'}), text={text[:50]}")

        # 发"思考中"卡片
        thinking_mid = send_card_get_id(chat_id, "⏳ 正在思考中…",
                                         template="blue", footer="请稍候")

        progress = Progress(thinking_mid)

        # 知识库预检索
        progress.step("📚 检索知识库")
        kb_context = prefetch_kb(text, is_owner, progress)

        # 调大脑
        progress.step("🧠 正在思考")
        session_key = f"{chat_id}:{sender_id}"
        answer = ask_brain(text, session_key, progress, is_owner, name, kb_context)

        # 处理结果
        if answer is None or answer == BRAIN_TIMEOUT:
            final_md = CONFIG.get("error_text", "抱歉，处理出了点问题。")
            if answer == BRAIN_TIMEOUT:
                final_md = "⏰ 思考超时了，请稍后重试或简化问题。"
        elif answer == BRAIN_BACKEND_ERR:
            final_md = CONFIG.get("error_text", "抱歉，大脑后端暂时不可用，请稍后重试。")
        else:
            final_md = answer

        # PATCH 为最终答案卡片
        if thinking_mid:
            patch_card(thinking_mid, final_md, steps_md=progress.steps_md())
        else:
            send_card(chat_id, final_md, steps_md=progress.steps_md())

        log(f"回复完成: chat={chat_id}, answer_len={len(final_md)}")

    except Exception as e:
        log(f"handle_event 异常: {e}")
        import traceback
        traceback.print_exc()


def _send_text(chat_id: str, text: str) -> None:
    """发送纯文本消息"""
    content = json.dumps({"text": text}, ensure_ascii=False)
    subprocess.run(
        ["lark-cli", "im", "+messages-send", "--as", "bot",
         "--chat-id", chat_id, "--msg-type", "text", "--content", content] + LARK_PROFILE_ARGS,
        capture_output=True, timeout=15
    )


def main() -> None:
    """主循环：事件消费 + 断线自愈"""
    bot_name = CONFIG.get('bot_name', '数字员工')
    log(f"{bot_name} 启动 | app_id={CONFIG['app_id']} | brain={CONFIG['brain']['provider']}")
    log(f"知识库: {KB_ROOT}")

    pool = ThreadPoolExecutor(max_workers=CONFIG.get("max_workers", 4))
    backoff = 5

    while True:
        try:
            log("启动事件消费: lark-cli event consume im.message.receive_v1 --as bot --quiet")
            proc = subprocess.Popen(
                ["lark-cli", "event", "consume", "im.message.receive_v1",
                 "--as", "bot", "--quiet"] + LARK_PROFILE_ARGS,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.PIPE,  # 必须保持 stdin 打开
                text=True,
                bufsize=1
            )

            backoff = 5  # 连接成功后重置退避
            for line in proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    if "another" in line.lower() or "already connected" in line.lower():
                        log("检测到另一个消费者已连接，退避 60s")
                        backoff = 60
                        break
                    continue

                # 事件即顶层 JSON（lark-cli --quiet 扁平输出）
                if not claim_event(event):
                    continue

                pool.submit(handle_event, event)

            # stdout 结束 = 断线
            proc.wait()
            stderr_out = proc.stderr.read() if proc.stderr else ""
            if "another" in stderr_out.lower():
                backoff = 60
                log("另一个消费者已连接，退避 60s 后重试")
            else:
                log(f"事件流断开 (exit={proc.returncode})，{backoff}s 后重连")

        except KeyboardInterrupt:
            log("收到 Ctrl+C，优雅退出")
            pool.shutdown(wait=False)
            sys.exit(0)
        except Exception as e:
            log(f"主循环异常: {e}")

        time.sleep(backoff)
        if backoff < 60:
            backoff = min(backoff * 2, 60)


# ─────────────────────── L2 大脑层 ───────────────────────

def ask_brain(question: str, key: str, progress: "Progress",
              is_owner: bool, name: str, kb_context: str) -> str | None:
    """调用 Claude CLI 大脑，支持后端抖动自愈"""
    for attempt in range(2):
        try:
            result = _ask_claude(question, key, is_owner, name, kb_context)
            if result is not None:
                return result
        except Exception as e:
            log(f"大脑调用失败 (attempt={attempt+1}): {e}")
            if attempt == 0:
                progress.step("🔄 重试中…")
                time.sleep(5)
                drop_session(key)
            else:
                return BRAIN_BACKEND_ERR
    return BRAIN_BACKEND_ERR


def _ask_claude(question: str, key: str, is_owner: bool, name: str,
                kb_context: str) -> str | None:
    """经 Claude CLI 调用 Anthropic API"""
    claude_bin = CONFIG.get("claude_bin", "claude")
    timeout = CONFIG.get("claude_timeout_sec", 300)

    # 构建系统提示：人格 + 身份块 + 知识预检结果
    identity_block = build_identity_block(is_owner, name)
    skills_index = build_skills_index()

    system_parts = [PERSONA, "", identity_block]
    if skills_index:
        system_parts.append(f"\n## 可用技能\n{skills_index}")
    if kb_context:
        system_parts.append(f"\n{kb_context}")

    system_prompt = "\n".join(system_parts)

    # 会话 resume
    session_id, is_new = resolve_session(key, "claude")

    cmd = [claude_bin, "-p", question, "--output-format", "json"]
    if session_id and not is_new:
        cmd.extend(["--resume", session_id])
    cmd.extend(["--append-system-prompt", system_prompt])
    cmd.extend(["--max-turns", str(CONFIG.get("claude_max_turns", 25))])

    log(f"调用 Claude: session={'resume' if not is_new else 'new'}, q={question[:40]}...")

    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, cwd=KB_ROOT
        )

        if result.returncode != 0:
            log(f"Claude exit={result.returncode}, stderr={result.stderr[:200]}")
            return None

        output = result.stdout.strip()
        if not output:
            return None

        try:
            data = json.loads(output)
            answer = data.get("result", data.get("content", ""))
            new_session_id = data.get("session_id", "")
            if new_session_id:
                touch_session(key, new_session_id, "claude")
            return answer if answer else None
        except json.JSONDecodeError:
            # 非 JSON 输出，直接当文本
            return output if output else None

    except subprocess.TimeoutExpired:
        log(f"Claude 超时 ({timeout}s)")
        drop_session(key)
        return BRAIN_TIMEOUT


# ─────────────────────── L3 知识层 ───────────────────────

_KB_TRIGGERS = re.compile(
    r"(流程|制度|规则|规定|政策|怎么|如何|什么是|为什么|哪些|多少|请假|报销|审批|标准|要求|规范)",
    re.IGNORECASE
)


def prefetch_kb(question: str, is_owner: bool, progress: "Progress") -> str:
    """知识库预检索"""
    kb_cfg = CONFIG.get("kb_prefetch", {})
    if not kb_cfg.get("enabled", False):
        return ""

    if len(question) < 6 or not _KB_TRIGGERS.search(question):
        return ""

    script = Path(KB_ROOT) / "scripts" / "rag_search.py"
    if not script.exists():
        return ""

    top_k = kb_cfg.get("top_k", 6)
    part = kb_cfg.get("part_guest", "公开") if not is_owner else kb_cfg.get("part_owner", "")

    cmd = ["python3", str(script), "--query", question, "--top-k", str(top_k)]
    if part:
        cmd.extend(["--part", part])

    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=15, cwd=KB_ROOT)
        output = result.stdout.strip()
        if output and result.returncode == 0:
            progress.step("📚 知识库命中")
            return f"【知识库预检结果（基于关键词检索，供参考）】\n{output}"
        else:
            progress.step("📚 知识库未命中")
            return "【知识库预检结果】未检索到直接相关内容。请基于你的通用知识回答，如果确实不知道，请如实告知。"
    except Exception as e:
        log(f"知识库检索异常: {e}")
        return ""


# ─────────────────────── L4 行动层 ───────────────────────

def build_card(body_md: str, template: str = "blue", footer: str | None = None,
               steps_md: str | None = None) -> str:
    """构建飞书卡片 2.0 JSON"""
    if footer is None:
        footer = CONFIG.get("card_footer", "")

    card_title = CONFIG.get("card_title", "🤖 Nova")
    card_tag = CONFIG.get("card_tag", "AI 自动回复")

    elements = []
    elements.append({"tag": "markdown", "content": body_md})

    # 折叠思考过程
    if steps_md:
        elements.append({"tag": "hr"})
        elements.append({
            "tag": "collapsible_panel",
            "expanded": False,
            "header": {"tag": "markdown", "content": "💭 **思考过程**"},
            "vertical_spacing": "8px",
            "elements": [{"tag": "markdown", "content": steps_md}]
        })

    # 脚注
    if footer:
        elements.append({"tag": "hr"})
        elements.append({"tag": "markdown", "content": f"<font color='grey'>{footer}</font>"})

    card = {
        "schema": "2.0",
        "header": {
            "title": {"tag": "plain_text", "content": card_title},
            "template": template,
            "text_tag_list": [{
                "tag": "text_tag",
                "text": {"tag": "plain_text", "content": card_tag},
                "color": "purple"
            }]
        },
        "body": {"elements": elements}
    }
    return json.dumps(card, ensure_ascii=False)


def send_card(chat_id: str, body_md: str, **kwargs) -> bool:
    """发送卡片到指定 chat"""
    card_json = build_card(body_md, **kwargs)
    try:
        result = subprocess.run(
            ["lark-cli", "im", "+messages-send", "--as", "bot",
             "--chat-id", chat_id, "--msg-type", "interactive",
             "--content", card_json] + LARK_PROFILE_ARGS,
            capture_output=True, text=True, timeout=15
        )
        return result.returncode == 0
    except Exception as e:
        log(f"send_card 失败: {e}")
        return False


def send_card_get_id(chat_id: str, body_md: str, **kwargs) -> str | None:
    """发送卡片并返回 message_id"""
    card_json = build_card(body_md, **kwargs)
    try:
        result = subprocess.run(
            ["lark-cli", "im", "+messages-send", "--as", "bot",
             "--chat-id", chat_id, "--msg-type", "interactive",
             "--content", card_json] + LARK_PROFILE_ARGS,
            capture_output=True, text=True, timeout=15
        )
        if result.returncode == 0:
            output = result.stdout.strip()
            try:
                data = json.loads(output)
                return data.get("data", {}).get("message_id") or data.get("message_id")
            except json.JSONDecodeError:
                m = re.search(r'"message_id"\s*:\s*"(om_[^"]+)"', output)
                return m.group(1) if m else None
    except Exception as e:
        log(f"send_card_get_id 失败: {e}")
    return None


def patch_card(message_id: str, body_md: str, **kwargs) -> bool:
    """更新已有卡片（思考中→最终答案）"""
    card_json = build_card(body_md, **kwargs)
    payload = json.dumps({"msg_type": "interactive", "content": card_json}, ensure_ascii=False)
    try:
        result = subprocess.run(
            ["lark-cli", "api", "PATCH",
             f"/open-apis/im/v1/messages/{message_id}",
             "--as", "bot", "--data", payload] + LARK_PROFILE_ARGS,
            capture_output=True, text=True, timeout=15
        )
        if result.returncode != 0:
            log(f"patch_card 失败: {result.stderr[:100]}")
            return False
        return True
    except Exception as e:
        log(f"patch_card 异常: {e}")
        return False


def react(message_id: str) -> None:
    """打表情回执（Get）"""
    emoji = CONFIG.get("ack_emoji", "Get")
    try:
        subprocess.run(
            ["lark-cli", "im", "reactions", "create",
             "--params", json.dumps({"message_id": message_id}),
             "--data", json.dumps({"reaction_type": {"emoji_type": emoji}})] + LARK_PROFILE_ARGS,
            capture_output=True, timeout=10
        )
    except Exception:
        pass


class Progress:
    """思考过程可视化"""

    def __init__(self, mid: str | None):
        self.mid = mid
        self.steps: list[str] = []
        self._last_patch = 0.0

    def step(self, label: str) -> None:
        self.steps.append(label)
        now = time.time()
        if self.mid and (now - self._last_patch) >= 1.5:
            self._last_patch = now
            steps_text = "\n".join(f"- {s}" for s in self.steps)
            try:
                patch_card(self.mid, f"⏳ 正在处理…\n\n{steps_text}",
                          template="blue", footer="请稍候")
            except Exception:
                pass

    def steps_md(self) -> str:
        if not self.steps:
            return ""
        return "\n".join(f"- {s}" for s in self.steps)


# ─────────────────────── L5 状态层 ───────────────────────

def _load_sessions() -> dict:
    if SESSIONS_FILE.exists():
        try:
            return json.loads(SESSIONS_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_sessions(sessions: dict) -> None:
    SESSIONS_FILE.write_text(json.dumps(sessions, ensure_ascii=False, indent=2), encoding="utf-8")


def resolve_session(key: str, provider: str) -> tuple[str | None, bool]:
    """读取会话 ID。未过期返回 (session_id, False)；过期/不存在返回 (None, True)。"""
    with STATE_LOCK:
        sessions = _load_sessions()
        entry = sessions.get(key)
        if entry:
            ts = entry.get("ts", 0)
            if (time.time() - ts) < SESSION_TTL_SEC:
                return entry.get("session_id"), False
            del sessions[key]
            _save_sessions(sessions)
    return None, True


def touch_session(key: str, session_id: str, provider: str) -> None:
    """写入/刷新会话映射"""
    with STATE_LOCK:
        sessions = _load_sessions()
        sessions[key] = {"session_id": session_id, "provider": provider, "ts": time.time()}
        _save_sessions(sessions)


def drop_session(key: str) -> None:
    """丢弃会话"""
    with STATE_LOCK:
        sessions = _load_sessions()
        if key in sessions:
            del sessions[key]
            _save_sessions(sessions)


# ─────────────────────── 辅助：身份 & 技能 ───────────────────────

def resolve_name(open_id: str) -> str:
    """通过 lark-cli contact 反查飞书用户姓名"""
    if open_id in _name_cache:
        return _name_cache[open_id]
    try:
        result = subprocess.run(
            ["lark-cli", "contact", "+get-user", "--as", "bot",
             "--user-id", open_id, "-q", ".data.user.name"] + LARK_PROFILE_ARGS,
            capture_output=True, text=True, timeout=10
        )
        name = result.stdout.strip().strip('"')
        if name:
            _name_cache[open_id] = name
            return name
    except Exception:
        pass
    return "访客"


def build_identity_block(is_owner: bool, name: str) -> str:
    """生成身份分权注入块"""
    if is_owner:
        return (
            f"## 当前对话者身份\n"
            f"**主人本人**：{name}\n"
            f"你拥有完整权限，可以执行任意技能、访问全部知识库。"
        )
    else:
        return (
            f"## 当前对话者身份\n"
            f"**访客**：{name}\n"
            f"严格执行三条铁律：只读问答 / 仅限公开文档 / 保护本人隐私与身份。"
        )


def build_skills_index() -> str:
    """扫描 skill_roots 下所有 SKILL.md，生成技能清单"""
    skill_roots = CONFIG.get("skill_roots", [])
    exclude = set(CONFIG.get("skill_exclude", []))
    skills_list = []

    for root in skill_roots:
        root_path = Path(root) if Path(root).is_absolute() else PROJECT / root
        if not root_path.exists():
            continue
        for skill_dir in sorted(root_path.iterdir()):
            if not skill_dir.is_dir():
                continue
            if skill_dir.name in exclude:
                continue
            skill_file = skill_dir / "SKILL.md"
            if skill_file.exists():
                content = skill_file.read_text(encoding="utf-8")
                desc = ""
                if content.startswith("---"):
                    end = content.find("---", 3)
                    if end > 0:
                        fm = content[3:end]
                        for line in fm.split("\n"):
                            if line.strip().startswith("description:"):
                                desc = line.split(":", 1)[1].strip().strip("|").strip()
                                break
                if not desc:
                    for line in content.split("\n"):
                        line = line.strip()
                        if line and not line.startswith("#") and not line.startswith("---"):
                            desc = line[:80]
                            break
                skills_list.append(f"- **{skill_dir.name}**: {desc}")

    return "\n".join(skills_list) if skills_list else ""


# ─────────────────────── 入口 ───────────────────────

if __name__ == "__main__":
    main()
