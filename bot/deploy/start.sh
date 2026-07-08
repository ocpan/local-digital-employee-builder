#!/bin/bash
# 前台启动机器人（Ctrl+C 停止）。窗口保持打开机器人就一直在线。
# 想 7×24 常驻（关窗口也不停）→ 用同目录的 launchd 方案（见 START-HERE 引导）。
cd "$(dirname "$0")/.." || exit 1

echo "启动前先确认：lark-cli auth status 的 bot 身份是 ready"
echo "同一个飞书应用同时只能有一个事件消费者，别开两个。"
echo

# 保活：断线自动重连（runner 内部也有重连，这里是进程级兜底）
while true; do
  python3 runner.py
  echo "runner 退出，5 秒后重启…（Ctrl+C 彻底停止）"
  sleep 5
done
