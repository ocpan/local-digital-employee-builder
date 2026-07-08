# 飞书 lark-cli 平台细节与坑位

参考实现用 [[lark-im]]/[[lark-doc]]/[[lark-task]] 等 lark-cli 技能。本文汇总搭分身时踩过的飞书特定要点。

## 事件感知
- 消费消息：`lark-cli event consume im.message.receive_v1 --as bot --quiet`，输出 NDJSON（一行一事件）。
- **必须 `--as bot`**：auto 会解析成 user 而报错（该事件仅 bot）。
- **子进程必须保持 stdin 打开**：consume 把 stdin EOF 当退出信号；nohup/Popen 下要给 `stdin=PIPE`，否则瞬间退出。
- 精简事件字段：chat_id/chat_type/content/message_id/message_type/sender_id/timestamp。**不含** parent_id 等；要判"回复了哪条消息"需 `api GET /im/v1/messages/{id}` 看 `parent_id`/`upper_message_id`。
- 群聊：标准权限下飞书只把 @机器人 的群消息推给 bot；content 里 @ 占位用 `@\w+` 正则清掉。
- 启 runner 前先 `pkill -9 -f runner.py`，`lark-cli event status` 确认 consumers=1，否则重复回复。

## 回复与卡片（JSON 2.0）
- 发卡片：`im +messages-send --as bot --chat-id <oc> --msg-type interactive --content '<card json>'`。
- 引用回复（群里防刷屏）：`im +messages-reply --message-id <om> ...`。
- 表情回执：`im reactions create --params '{"message_id":..}' --data '{"reaction_type":{"emoji_type":"Get"}}'`（185 个表情，无"了解"，最近的是 Get/OK/DONE/OnIt）。
- **卡片 2.0 实测**：
  - ✅ 可用：`schema:"2.0"`、header 的 `title`/`subtitle`/`template`/`text_tag_list`、body 的 `markdown`（含**表格**、`<font color='grey'>`）、`collapsible_panel`（折叠面板）、`hr`、`img`、markdown 图片。
  - ❌ 不可用：`note` 元素、`ud_icon`（用 emoji 进标题代替；脚注用灰色 markdown 代替）。
  - 图片：URL 不能直接嵌；先 `im images create --as bot --file image=<文件名>`（**cwd 切到图片目录传文件名**，不收绝对路径）拿 img_key，再 `![](img_key)`。
- **更新卡片**（思考过程流式滚动→落地为答案）：`lark-cli api PATCH /open-apis/im/v1/messages/{message_id} --as bot --data '{"content":"<card json>"}'`。
- 思考过程可视化：大脑用 `codex exec --json` 流式输出，runner 把 `command_execution`/`agent_message` 事件翻成中文步骤，节流 PATCH 到「思考中」卡，完成后 PATCH 成答案+折叠思考。

## 身份与认证
- bot 身份：app secret 拿 tenant token，长期稳定，发消息/收事件用它。
- user 身份：OAuth，access token 短期、refresh ~7 天；以本人身份操作（如读私有云文档、测别的机器人）才需要。
- 反查姓名：`contact +get-user --as bot --user-id <open_id> -q .data.user.name`。
- 读 P2P 历史：`im +messages-search --as user --chat-id <oc> --query <常用字> --start <ISO>`（`+chat-messages-list` 对 bot P2P 常返回空）。需 scope `search:message`。
- 常用 user scope：`im:message.send_as_user`（代发）、`search:message`（搜消息）、`contact:user.base:readonly`（解析用户/读会话）。缺 scope 时 `auth login --scope "<scope>" --no-wait --json` 拿设备码 URL→生成二维码(`auth qrcode`)→用户授权→`auth login --device-code <code>` 完成。

## 上线（对外/拉群必做）
飞书自建应用默认只有开发者本人能用。要对外/被拉群：开发者后台→机器人能力→权限（`im:message`/`im:message.p2p_msg`/`im:message.group_msg`/`im:message.reactions:write_only` 等）→事件订阅选**长连接**→设**可用范围**→创建版本**申请发布**→**企业管理员审核**。未发布时事件 precheck 提示 "app has no published version"，只有本人能用。

## 安全
- 多机器人/多身份隔离：用 `lark-cli config bind --identity bot-only` 把某 app 绑到工作目录，bot-only 不冒用个人权限。
- 凭证不入库：key/auth.json gitignore；日志对含 cookie/token 迹象的内容脱敏。
- 访客硬隔离：访客大脑用 `-s read-only` 沙箱（拦写+网络），叠加人格铁律。

## 机器人↔机器人（测试别的机器人）
飞书不把机器人消息推给另一个机器人，无法直连。要测目标机器人：以**本人 user 身份**给它发消息（`+messages-send --as user`）→ 它正常回复 → `+messages-search` 读回回复分析。可自建 bot-tester skill。仅本人可用（用本人身份发消息）。
