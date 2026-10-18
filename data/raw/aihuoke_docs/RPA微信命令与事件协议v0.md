# RPA 微信命令与事件协议 v0（交接契约）

> 状态：**v0 交接契约（后端侧已落地 A：事件 52/54/58；主动加好友命令 739 待接入；自动通过好友 56/740 为占位、保留现用 Jubo 通道；B：微信命令 4 条号段 + 回执映射）**。本文定义"取消 / 替代 Jubo 通道"后，微信侧自研协议下的**命令族**（服务器 → 设备）与**事件族**（设备 → 服务器 主动上报）。
> 文内 JSON 格式与字段均为**固定契约**（类型、必填、取值约束一次定死，不含"建议 / 待复核 / 可为空"类模糊判断）。标注 **CONFIRMED（已落地）** 表示代码已注册并通过语法校验；标注 **CONFIRMED（号段需客户端确认）** 表示后端已注册命令/回执号段，但号段与动作字段口径由微信团队确认为准后方作为线上契约；标注 **占位（暂不落地）** 表示号段/事件仅作保留登记、**不实现、不 dispatch、不接入业务**，并保留现用 Jubo 通道；标注 **约定（待注册）** 表示字段已按代码既有口径定死为契约，但对应 `WorkerEnum` / `DeviceCommandEnum` 类型号尚未注册、handler 未实现，需按 §12 落地。
> 交付约定：本文为后端（服务器）侧当前画面，设备端由微信团队按 §6/§7 契约实现；凡标注"需客户端确认"的号段与字段，以微信团队书面确认结果为最终线上口径。

***

## 1. 目的与背景

现有微信能力一部分经 Jubo（`_transport=wechat.protobuf`）下发/回传。本方案将微信侧统一走**自研 RPA socket**：

- **命令（下发执行类）**：复用 `sv_device_command` 命令账本（幂等 / lane 串行 / 状态机 / 超时 / 对账），下发编码从 Jubo protobuf 改为 RPA JSON 命令。

- **事件（设备主动上报类）**：复用 `RpaSocketService` 已具备的事件分发骨架，微信实时事件（收到消息、加好友请求、朋友圈动态）主动上报，服务端决策后回传要执行的命令。

***

## 2. 相关文件与既有协议基线

| 关注点           | 位置                                                                                                                                    |
| ------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| 常规事件入口 / 安全校验 | `app/common/workerman/rpa/RpaSocketService.php`                                                                                       |
| RPA 消息号段常量    | `app/common/workerman/rpa/WorkerEnum.php`                                                                                             |
| 事件 handler    | `app/common/workerman/rpa/handlers/wechat/`（`AddWechatTaskNoticeHandler`、`CircleLikeCommentHandler`、`CircleLikeCommentResultHandler`） |
| 命令账本          | `app/common/service/device/DeviceCommandService.php`、`DeviceCommandDispatcher.php`、`handlers/rpa/V2DeviceCommandReceiptHandler.php`   |
| 命令协议基线        | `docs/设备端V2命令下发与回传协议.md`                                                                                                              |
| RPA 外层包基线     | `docs/RPA微信Android任务回传协议.md`                                                                                                          |
| 状态仲裁          | `app/common/enum/DeviceCommandEnum.php`、`DeviceEnum.php`                                                                              |

***

## 3. 传输与安全基线（CONFIRMED）

1. **连接认证**：设备 TCP/WS 连入，`type=1`（`RPA_DEVICE_INFO`）完成认证，连接对象绑定 `deviceId`。
2. **防伪装**：`verifyClientRequest` 强制"用于上报的 `deviceId` 必须等于当前已认证连接绑定的 `deviceId`"（[RpaSocketService.php#L246-L259](file:///d:/Work/new_server/app/common/workerman/rpa/RpaSocketService.php#L246-L259)）；并校验设备在线（Redis `xhs:device:{id}:status=online`）。
3. **下发授权**：服务器主动下发走 Channel `{type}.{deviceId}.message`（`registerChannelListener`）；下发前 `canReceiveDeviceCommand` 校验 `sv_device_authorization`（`enabled=1`、无 `banned_at`、`expires_at` 未过期、`device_code` 匹配）（[BaseMessageHandler.php#L326-L340](file:///d:/Work/new_server/app/common/workerman/rpa/BaseMessageHandler.php#L326-L340)）。
4. **心跳**：`ping` / `type=0`（`RPA_DEVICE_HEARTBEAT`）不验证在线，仅保活。

> 新增命令/事件均自动复用以上安全模型，无需另行实现。

***

## 4. 两种消息范式

### 4.1 命令范式（服务器 → 设备，走 `sv_device_command`）

流程：**建命令（携带幂等键）→** **`dispatchNext`（lane 串行下发）→ 设备执行 → 回执（V2 receipt）→ 收敛终态**。
约定（对齐现有 `DeviceCommandService`）：

- 终态唯一：成功/失败只允许进入一次；

- 迟到真实回执：经 `reconcile` 接受，拒绝覆盖已落真实结果；

- 超时：120s 无进度 → `UNCERTAIN`（保留 lane，等待迟到回执），不误判成功；

- 回执身份校验：`deviceId / appType / account`。

### 4.2 事件范式（设备 → 服务器，走 RPA type 上报）

流程：**设备上报事件 → handler 决策（幂等去重、频控、AI 生成）→ 在** **`reply`** **回传要执行的命令 → 设备执行 → 回传 result → 收敛**。
已实现样例：`CircleLikeCommentHandler`（`type=52`）上报朋友圈动态 → 服务端去重 / 当日次数限制 / 生成回复 → `reply` 携带 `(content,isLike,isComment)`（[CircleLikeCommentHandler.php#L176-L185](file:///d:/Work/new_server/app/common/workerman/rpa/handlers/wechat/CircleLikeCommentHandler.php#L176-L185)）。

***

## 5. 外层消息包格式（CONFIRMED）

下发给设备与设备上报均使用同一包裹（参考 `BaseMessageHandler::sendError` 与 `RpaSocketService::send`）：

```jsonc
{
  "code": 0,               // 0=成功；非 0 见 WorkerEnum
  "reply": { },             // 服务器对事件的决策命令 / 错误说明
  "appType": 1,             // 平台，微信个微=1
  "type": 55,               // RPA 消息号（数字）
  "messageId": 123,         // 关联消息号
  "deviceId": "wx_xxx",     // 设备码（认证绑定）
  "appVersion": "2.4.1",
  "content": { }            // 业务载荷
}
```

说明：`content` 在传输层可为 JSON **字符串**，各 handler 内 `json_decode` 后使用（与现有 handler 一致）。

***

## 6. 命令族（服务器 → 设备，JSON 下发）

微信命令统一使用《设备端V2命令下发与回传协议.md》的 **JSON 下发信封**，并复用 `sv_device_command` 账本（幂等 / lane 串行 / 状态机 / 对账）。`type` 为固定命令号。

- §6.1（个微接管 + AI 私信回复）为既有落地链路。AI 私信回复走 `TalkToFriendTask` protobuf，不入命令族；**发媒体私信/群发/打招呼/阶段推送（SOP）同样经** **`wxPush`** **走** **`TalkToFriendTask`** **protobuf**，也不入命令族（见 §10 映射）。

- §6.2–§6.5 微信命令**已在** **`DeviceCommandEnum`** **注册**（命令 `739–742`、回执 `842–845`，避开 720–738/820–841 已占用号段），并已在 `V2DeviceCommandReceiptHandler::assertProtocolType` 建立回执↔命令的 `protocol_type` 映射（`842=>[739]`、`843=>[740]`、`844=>[741]`、`845=>[742]`），回执经通用 `else` 分支收敛终态（CONFIRMED（号段需客户端确认））。**业务侧 handler 与触发接入见 §12**。

- §6.6 发朋友圈为**新增命令（待注册）**：命令 `743`、回执 `846`、事件 `type=59` 尚未在 `DeviceCommandEnum`/`WorkerEnum` 注册，handler 未实现。需按 §12.1 注册并实现后方为线上契约，否则无法下发。

> **字段契约总则（适用于 §6 命令与 §7 事件，不以「留空」为设计目标）**：
>
> 1. 每个字段必须**明确「必填/可选」**，必填字段给出**非空取值规则**与**该取值对应的返回/回执行为**；可选字段给出**为空时的既定分支**（不报错，但行为确定）。
> 2. **必填字段为空或缺失 = 明确报错**（命令回 `failed` + 具体 `resultMessage`；事件回 `4012 DEVICE_ERROR` + 具体文案），**不产生业务副作用、不落库、不 dispatch**。
> 3. 不存在"留空当作功能"的字段。任何保留号段/暂不 dispatch 的命令或事件，其字段契约**仍完整定义**（必填规则 + 返回），空值一律走第 2 条报错路径。
> 4. 遗留通道（protobuf/Jubo）与本协议并行时，涉及记账/副作用必须互斥或幂等，避免双写（见 §6.3、§7.5 的记账说明）。

### 6.0 下发信封（固定，与 V2 第 2 节一致）

```jsonc
{
  "type": 723,
  "requestId": "32位hex",       // 后端唯一动作 ID，所有回执原样回带
  "deviceId": "wx_xxx",          // 必须等于已认证连接绑定的 deviceId
  "appType": 1,                  // 微信个微=1
  "account": "wxid_main",
  "sequence": 18,                // 当前设备执行线序号
  "status": "dispatch_attempted",
  "errorCode": "",
  "errorMessage": "",
  "content": "{\"...\"" }         // JSON 字符串，具体字段见下
}
```

### 6.1 已落地命令（CONFIRMED）

| 命令类型号       | 操作                            | 回执号                            | 回执允许 `status`        |
| ----------- | ----------------------------- | ------------------------------ | -------------------- |
| `723`       | 个微接管启动                        | `823`                          | `accepted`、`failed`  |
| `727`       | 个微接管停止                        | `827`                          | `succeeded`、`failed` |
| 私信发送（AI 回复） | 走 protobuf `TalkToFriendTask` | `TalkToFriendTaskResultNotice` | —                    |

**`723`** **/** **`727`** **的** **`content`（固定）**

```jsonc
{
  "taskId": 12345,
  "deviceId": "wx_xxx",
  "account": "wxid_main",
  "accountType": 1,
  "startTime": "2026-09-01 10:00:00",
  "endTime": "2026-09-01 11:00:00",
  "readOnly": 0
}
```

启动命令填 `startTime/endTime/readOnly`；停止命令只需 `taskId/deviceId/account/accountType`。启动回执 `accepted` 表示设备已确认账号、接管配置与页面状态均可用并已实际启用接管；停止回执 `succeeded` 表示已真实关闭本次 `requestId` 对应的接管流程。

**AI 私信回复（CONFIRMED，非 RPA JSON）**：个微 AI 回复仍走既有 `socket.{deviceId}.message` protobuf 通道，消息为 `TalkToFriendTask`，`TaskId` 与 `MsgId` 均置为 `requestId`；设备在 `TalkToFriendTaskResultNotice` 中原样回传该 `MsgId`，后端以 `MsgId` 关联命令账本写入真实终态（[TalkToFriendTaskResultNoticeHandler.php#L94-L129](file:///d:/Work/new_server/app/common/workerman/wechat/handlers/device/TalkToFriendTaskResultNoticeHandler.php#L94-L129)）。`Success=false` 时只写失败，不伪造成功；AI 上下文仅在 `succeeded` 后落盘（同一文件 `persistDeliveredHistory`）。

### 6.2 主动加好友（命令已注册，号段需客户端确认）

命令 `wechat.add_friend` = `TYPE_WECHAT_ADD_FRIEND=739`；回执 `TYPE_WECHAT_ADD_FRIEND_RESULT=842`。下发 `content`（固定）：

```jsonc
{ "wechatId": "wxid_main", "targetWechat": "wxid_friend", "remark": "备注", "source": 1 }
```

| `content` 字段   | 必填 | 规则              |
| -------------- | -- | --------------- |
| `wechatId`     | 是  | 执行加好友的个微账号 ID。  |
| `targetWechat` | 是  | 目标微信号，非空字符串。    |
| `remark`       | 否  | 好友备注，允许为空字符串。   |
| `source`       | 否  | 加好友来源标识，默认 `1`。 |

幂等键：`sha256(deviceId+wechatId+targetWechat+source)`。
回执：`accepted / running / succeeded / failed`；`succeeded` 后设备按压 `type=50` 定义回传 `status`（见 §7.1）。

> **设备端实现步骤见 §13**（面向微信团队设备端开发的完整分步指引）。

### 6.3 自动通过好友（wechat.accept\_friend=740；当前由 WeChatPadPro 承接，RPA 命令不 dispatch）

> **决策（2026-09-16 更新）**：自动通过加好友**当前由 WeChatPadPro 网关承接**（`WechatPadAcceptFriendCron` + `WechatPadFriendService` + `FriendLogic::acceptFriend` / `FriendActionController::accept`），记账走网关链路。原 Jubo 服务端路径（`FriendLogic` 策略判定 → `WechatAcceptFriendJob` → `AcceptFriendAddRequestTask`）**已整体下线并删除该类**。因此 RPA 命令 `740` 与回执 `843` 仅保留号段，**不创建、不 dispatch、不接入业务副作用**；待后续确认迁往 RPA 时再按本契约启用，届时必须与 WeChatPadPro 记账**互斥/幂等**，避免双拍。
>
> **字段契约（固定，不以留空为目标）**：
>
> | `content` 字段 | 必填 | 取值 / 返回规则                                                                  |
> | ------------ | -- | -------------------------------------------------------------------------- |
> | `wechatId`   | 是  | 通过请求的个微账号 ID，**非空字符串**；为空/缺失 → 直接回 `failed` + 明确 `resultMessage`，不产生任何副作用。 |
> | `friendId`   | 是  | 请求方 wechatId，**非空字符串**；为空/缺失 → `failed` + 明确原因。                            |
> | `nickname`   | 否  | 请求方昵称，允许空字符串；为空按既定分支处理，不报错。                                                |
> | `remark`     | 否  | 验证来源/备注，允许空字符串；为空按既定分支处理，不报错。                                              |
>
> 幂等键：`sha256(deviceId+wechatId+friendId)`。
> 回执：`accepted / succeeded / failed`。**当前不 dispatch**：命令不会被创建，故不存在回执链；启用 RPA 后，`succeeded` 的记账须按 `user_id/wechat_id/friend_id` 当日幂等并与 Jubo 记账互斥（对齐 §7.5），防止 `AiWechatLog TYPE_ACCEPT_FRIEND` 双写。

### 6.4 朋友圈点赞 / 评论（命令已注册，号段需客户端确认）

命令 `wechat.circle_interact` = `TYPE_WECHAT_CIRCLE_INTERACT=741`；回执 `TYPE_WECHAT_CIRCLE_INTERACT_RESULT=844`。下发 `content`（固定）：

```jsonc
{
  "wechatId": "wxid_main",
  "friendId": "wxid_friend",
  "nickname": "张三",
  "content": "朋友圈正文",
  "isLike": 1,
  "isComment": 0,
  "replyText": ""
}
```

| `content` 字段 | 必填 | 规则                      |
| ------------ | -- | ----------------------- |
| `wechatId`   | 是  | 执行互动的个微账号 ID。           |
| `friendId`   | 是  | 朋友圈作者 wechatId。         |
| `nickname`   | 是  | 作者昵称，用于去重与留痕。           |
| `content`    | 是  | 朋友圈正文，用于 AI 生成评论。       |
| `isLike`     | 是  | `1` 点赞 / `0` 不点赞。       |
| `isComment`  | 是  | `1` 评论 / `0` 不评论。       |
| `replyText`  | 否  | `isComment=1` 时必填的评论文本。 |

幂等键：`sha256(deviceId+wechatId+friendId+content+isLike+isComment)`。
回执：`accepted / running / succeeded / failed`；最终结果按 `type=54` 定义回传 `status`（见 §7.3）。

### 6.5 拉取朋友圈（命令已注册，号段需客户端确认）

命令 `wechat.pull_circle` = `TYPE_WECHAT_PULL_CIRCLE=742`；回执 `TYPE_WECHAT_PULL_CIRCLE_RESULT=845`。下发 `content`（固定）：

```jsonc
{ "wechatId": "wxid_main", "friendId": "wxid_friend" }
```

| `content` 字段 | 必填 | 规则                  |
| ------------ | -- | ------------------- |
| `wechatId`   | 是  | 拉取方个微账号 ID。         |
| `friendId`   | 是  | 待拉取朋友圈的作者 wechatId。 |

幂等键：`sha256(deviceId+wechatId+friendId)`（同一好友同周期只拉一次）。
回执：`accepted / running / succeeded / failed`；结果按 `type=58` 回传（见 §7.4）。

### 6.6 发朋友圈（待注册命令号，需新建）

> **现状变更**：当前"及时/定时发朋友圈"实际仍走 Jubo protobuf（[WechatTrait.php#L316-L331](file:///d:/Work/new_server/app/common/traits/WechatTrait.php#L316-L331) 构造 `PostSNSNewsTask` 经 channel 下发，`TASK_TYPE_WECHAT_CIRCLE(7)` 调度），并非 V2 JSON 命令。为实现"全量替代 Jubo"，本协议将发朋友圈纳入 RPA 命令族。

命令 `wechat.publish_circle` = `TYPE_WECHAT_PUBLISH_CIRCLE=743`；回执 `TYPE_WECHAT_PUBLISH_CIRCLE_RESULT=846`。下发 `content`（固定，对齐 `PostSNSNewsTaskMessage` 字段）：

```jsonc
{
  "wechatId": "wxid_main",
  "content": "朋友圈文案",
  "attachment": { "type": 3, "content": [ { "url": "https://.../a.jpg", "thumb": "" } ] },
  "comment": "关联评论",
  "extComment": ["评论1", "评论2"],
  "visible": { "type": 0, "labels": [], "friends": [] },
  "sendSlow": 0,
  "poi": { "city": "深圳", "name": "地点", "address": "地址", "lat": 22.5, "lng": 113.9 }
}
```

| `content` 字段 | 必填 | 规则                                                                      |
| ------------ | -- | ----------------------------------------------------------------------- |
| `wechatId`   | 是  | 发布朋友圈的个微账号 ID。                                                          |
| `content`    | 否  | 文案，允许为空字符串。                                                             |
| `attachment` | 否  | 资源，`type` 与 `content` 对齐 `PostSNSNewsTask.Attachment` 语义（图片/视频/链接/小程序）。 |
| `comment`    | 否  | 发布时附带的一条评论，允许为空字符串。                                                     |
| `extComment` | 否  | 多条评论数组，允许为空数组。                                                          |
| `visible`    | 否  | 可见范围，`type=0` 公开 / `1` 指定好友 / `2` 指定标签。                                 |
| `sendSlow`   | 否  | `1` 慢速发送（按字数最多 40 秒）/ `0` 快速。                                           |
| `poi`        | 否  | 位置信息，缺省不带位置（当前 `PostSNSNewsTaskHandler` 的 Poi 为"TODO 待实现"）。             |

幂等键：`sha256(deviceId+wechatId+content+attachment序列化+sendSlow)`。
回执：`accepted / running / succeeded / failed`；业务副作用在 `succeeded` 后执行（同步 `TASK_TYPE_WECHAT_CIRCLE` 发布明细与设备任务状态）。

> 回执通用约束：每条命令必须按 V2 回执信封回 `accepted / running / succeeded / failed` 之一，并携带 `requestId`、`eventId`、`status`；业务副作用（写业务表 / 记账 / 发聊记录）**必须在** **`succeeded`** **之后**执行，设备拒绝 / 掉线时不得伪装为已发送（对齐"回执驱动写入"）。

***

## 7. 事件族（设备 → 服务器主动上报）

事件对应"设备侧发生了需后端响应的事"。以下 **CONFIRMED** 事件为代码已注册并按字段解析；其余为本协议约定的固定契约，需在 `WorkerEnum` 注册相应 `type` 并实现 handler 后生效（注册状态见 §8 与 §12.1）。

### 7.1 加微信任务回执（`type=50`，CONFIRMED）

加好友动作的真实单条结果。字段由 [WechatAddReceiptService](file:///d:/Work/new_server/app/common/service/ai/WechatAddReceiptService.php) 严格校验：三者缺一或取值非法即整体报错，不写库。

```jsonc
{
  "type": 50,
  "appType": 1,
  "deviceId": "wx_xxx",
  "messageId": "add-result-1001",
  "appVersion": "2.4.1",
  "content": {
    "recordId": 1001,
    "userId": 88,
    "isManual": 0,
    "status": 0
  }
}
```

| `content` 字段 | 必填 | 规则                                                                                                 |
| ------------ | -- | -------------------------------------------------------------------------------------------------- |
| `recordId`   | 是  | 正整数。`isManual=0` 对应 `sv_add_wechat_record.id`；`isManual=1` 对应 `sv_crawling_manual_task_record.id`。 |
| `userId`     | 否  | 若传，必须等于记录 `user_id`，否则报所有权不符而不写库。                                                                  |
| `isManual`   | 是  | `0` 自动加好友记录 / `1` 手动任务记录。                                                                          |
| `status`     | 是  | 固定取 `0`–`4`：`0` 加好友成功；`1` 用户不存在；`2` 已是好友；`3` 触发频控；`4` 安全风险。仅 `status=0` 写成功。                       |

处理规则：记录当前必须为 `status=2`（待处理），否则视为终止/重复回执直接幂等返回；成功后写 `sv_add_wechat_log`、累加 `sv_crawling_task.completed_add_count`（`isManual=0` 且带 `crawling_task_id` 时），不在此处计费。

### 7.2 朋友圈动态事件（`type=52`，CONFIRMED）

设备上报好友朋友圈动态，后端决策是否点赞/评论并在 `reply` 回传。校验逻辑见 [CircleLikeCommentHandler.php](file:///d:/Work/new_server/app/common/workerman/rpa/handlers/wechat/CircleLikeCommentHandler.php)。

```jsonc
{
  "type": 52,
  "appType": 1,
  "deviceId": "wx_xxx",
  "content": {
    "userId": 88,
    "taskId": 21001,
    "nickname": "张三",
    "content": "朋友圈正文",
    "image": ""
  }
}
```

| `content` 字段 | 必填 | 规则                                                 |
| ------------ | -- | -------------------------------------------------- |
| `userId`     | 是  | 任务所属用户 ID。                                         |
| `taskId`     | 是  | `sv_device_circle_like_reply_account.id`，据此定位任务配置。 |
| `nickname`   | 是  | 好友昵称，用于同任务该好友的互动次数去重。                              |
| `content`    | 是  | 朋友圈正文，非空；作为 AI 生成评论的输入。                            |
| `image`      | 否  | 动态图片，Base64（可能为空字符串）。                              |

后端去重与限次：按 `userId + like_reply_account + device_code + account + hash(nickname+content) + action` 判重；同一 `nickname` 在本任务的互动次数达到配置上限后不再触发。成功后写 `sv_device_circle_like_reply_record`。

`reply`（固定，随响应回传）：

```jsonc
{
  "type": 1,
  "content": ["AI 生成评论"],
  "link": "",
  "isLike": 1,
  "isComment": 1,
  "msg": "互动成功",
  "targetRecipient": "张三",
  "lastMessageContent": "朋友圈正文"
}
```

`isLike`=1 表示下发点赞，`isComment`=1 表示下发评论；`content` 为要执行的评论数组。不需要互动时同样以该结构返回，`isLike/isComment` 为 `0`。

### 7.3 朋友圈互动结果回执（`type=54`，CONFIRMED）

设备执行点赞/评论后的回执。校验逻辑见 [CircleLikeCommentResultHandler.php](file:///d:/Work/new_server/app/common/workerman/rpa/handlers/wechat/CircleLikeCommentResultHandler.php)。

```jsonc
{
  "type": 54,
  "appType": 1,
  "deviceId": "wx_xxx",
  "content": {
    "taskId": 21001,
    "status": 1,
    "msg": "朋友圈互动完成",
    "imageUrl": ""
  }
}
```

| `content` 字段 | 必填 | 规则                                                   |
| ------------ | -- | ---------------------------------------------------- |
| `taskId`     | 是  | 正整数，对应 `sv_device_circle_like_reply_account.id`。     |
| `status`     | 是  | 固定取 `1` 成功 / `2` 失败 / `3` 执行中。`status=2` 时 `msg` 必填。 |
| `msg`        | 是  | 失败必须带可读原因；成功/执行中缺省时服务器补默认文案。                         |
| `imageUrl`   | 否  | 结果截图或动态图片地址，允许为空字符串。                                 |

处理规则：`status` 映射为 `1→任务完成`、`2→任务失败`、`3→执行中`；`3` 仅允许从待执行转移，`1/2` 从待执行或执行中转移。`taskId` 必须属于该 `deviceId` 且存在设备任务，否则报错。

### 7.4 收到好友消息/私信（`type=55`，不登记 RPA 事件，AI 回复走 protobuf）

> **决策（CONFIRMED）**：本协议**不登记独立 RPA 事件** **`type=55`**。个微 AI 实时回复继续走既有 `socket.{deviceId}.message` protobuf 通道（`TalkToFriendTask`），见 §6.1 与 §6.1 "AI 私信回复"段。本节字段仅作为微信团队在客户端做消息上报时的参照基准：

字段以 `FriendTalkNotice` 实际内容为准（[FriendTalkNoticeHandler.php#L47-L87](file:///d:/Work/new_server/app/common/workerman/wechat/handlers/device/FriendTalkNoticeHandler.php#L47-L87)）。

```jsonc
{
  "type": 55,
  "appType": 1,
  "deviceId": "wx_xxx",
  "content": {
    "wechatId": "wxid_abc",
    "friendId": "wxid_friend",
    "nickname": "张三",
    "contentType": 1,
    "content": "你好",
    "msgSvrId": "1234567890",
    "createTime": 1756800000
  }
}
```

| `content` 字段  | 必填 | 规则                                                                     |
| ------------- | -- | ---------------------------------------------------------------------- |
| `wechatId`    | 是  | 收到消息的个微账号 ID。                                                          |
| `friendId`    | 是  | 发来消息的好友 wechatId。                                                      |
| `nickname`    | 是  | 发送者昵称。                                                                 |
| `contentType` | 是  | 消息内容类型：`1` 文本 / `2` 图片 / `3` 文件 / `22` 视频/语音等；仅 `1/2/3/22` 进入 AI 回复判定。 |
| `content`     | 是  | 消息文本（二进制类消息此处放备注）。                                                     |
| `msgSvrId`    | 是  | 消息唯一 ID，作为幂等键组成部分。                                                     |
| `createTime`  | 否  | 消息时间戳（秒），允许缺省。                                                         |

幂等键：`sha256(deviceId+wechatId+friendId+msgSvrId+contentType)`。
后端决策：不去重则不重复回复；按设备、个微、机器人配置复用 [AichatTrait](file:///d:/Work/new_server/app/common/workerman/wechat/traits/AichatTrait.php) 生成回复，随后按下发 `TalkToFriendTask` 私信命令（§6.1）。

`reply`（固定）：

```jsonc
{ "action": "reply", "targetRecipient": "张三", "lastMessageContent": "你好" }
// 无需回复时：
{ "action": "none", "msg": "不触发AI回复的原因" }
```

### 7.5 收到加好友请求（`type=56`；当前由 WeChatPadPro 承接，RPA 链路不 dispatch）

> **决策（2026-09-16 更新）**：收到加好友请求的通过处理**当前由 WeChatPadPro 网关承接**（`WechatPadAcceptFriendCron` 轮询申请 + `WechatPadFriendService` 票据通过，记账走网关链路）；原 Jubo 路径（`FriendLogic` → `WechatAcceptFriendJob` → `AcceptFriendAddRequestTask`）**已下线并删除该类**。本 RPA 事件保留号段与路由，服务端**仅做入参校验并返回固定** **`reply`**，**不创建、不 dispatch** **`wechat.accept_friend`，也不在此写账**。
>
> **字段契约（固定，不以留空为目标；必填为空即报错）**：
>
> | `content` 字段       | 必填 | 取值 / 返回规则                                  |
> | ------------------ | -- | ------------------------------------------ |
> | `payload.deviceId` | 是  | 非空字符串；为空/缺失 → 返回明确错误（`4012 DEVICE_ERROR`）。 |
> | `wechatId`         | 是  | 收到请求的个微账号 ID，**非空字符串**；为空/缺失 → 返回明确错误。     |
> | `friendId`         | 是  | 请求方 wechatId，**非空字符串**；为空/缺失 → 返回明确错误。     |
> | `nickname`         | 否  | 请求方昵称，允许空字符串；为空按既定分支处理，不报错。                |
> | `remark`           | 否  | 请求附带的验证来源/备注，允许空字符串；为空按既定分支处理，不报错。         |
>
> **reply（固定契约）**：
>
> ```jsonc
> { "action": "defer", "remark": "自动通过好友当前经 Jubo 通道处理，RPA accept_friend 不 dispatch" }
> ```
>
> 幂等键：`sha256(deviceId+wechatId+friendId)`。**当前不 dispatch**：服务端收到本事件后校验必填字段、返回上述固定 `reply`，不产生 `wechat.accept_friend(740)` 命令，不写 `AiWechatLog`（记账归 WeChatPadPro 的 `WechatPadFriendService`）。设备端当前可不上报 `type=56`；若上报，必填字段不得为空，否则收到明确错误码。

### 7.6 朋友圈动态（`type=57` ≡ `type=52`）

与 `type=52`（§7.2）完全等价，实际沿用 `52`，本协议不分配独立 `type=57`。

### 7.7 拉取朋友圈结果回传（`type=58`，CONFIRMED（已落地））

设备响应"拉取朋友圈"命令（§6.5）的异步结果。handler：`WechatCirclePulledHandler`（`WorkerEnum::RPA_WECHAT_CIRCLE_PULLED=58`，已在 `RpaSocketService` 路由注册），依据 `requestId` 找到下发命令并调用 `DeviceCommandService::complete` 回写成功终态。

> 当前仓库**未发现"拉取朋友圈"的下发触发方**（谁构造 `wechat.pull_circle` 命令未落地，UNKNOWN），仅有 `type=58` 回执收敛；下发触发待微信团队确认后按批次C接入。

```jsonc
{
  "type": 58,
  "appType": 1,
  "deviceId": "wx_xxx",
  "content": {
    "requestId": "32位hex",
    "wechatId": "wxid_abc",
    "friendId": "wxid_f",
    "content": "朋友圈正文",
    "images": [],
    "publishTime": 1756800000
  }
}
```

| `content` 字段  | 必填 | 规则                            |
| ------------- | -- | ----------------------------- |
| `requestId`   | 是  | 回执对应当前"拉取朋友圈"命令的 `requestId`。 |
| `wechatId`    | 是  | 拉取方个微账号 ID。                   |
| `friendId`    | 是  | 作者 wechatId。                  |
| `content`     | 是  | 朋友圈正文，可为空字符串。                 |
| `images`      | 否  | 图片地址数组，允许为空数组。                |
| `publishTime` | 否  | 发布时间戳（秒），允许缺省。                |

幂等键：`sha256(requestId)`；后端回写该命令终态，供朋友圈策略消费。

### 7.8 发朋友圈结果回执（`type=59`，约定，待注册）

设备响应"发朋友圈"命令（§6.6 `wechat.publish_circle`）的结果回执。字段对齐 `PostSNSNewsTaskResultNotice`（[PostSNSNewsTaskResultNoticeHandler.php#L71-L79](file:///d:/Work/new_server/app/common/workerman/wechat/handlers/device/PostSNSNewsTaskResultNoticeHandler.php#L71-L79)）：

```jsonc
{
  "type": 59,
  "appType": 1,
  "deviceId": "wx_xxx",
  "content": {
    "requestId": "32位hex",
    "wechatId": "wxid_main",
    "success": true,
    "code": 0,
    "errMsg": "",
    "taskId": 123,
    "circleId": "wxid_..._145"
  }
}
```

| `content` 字段 | 必填 | 规则                                    |
| ------------ | -- | ------------------------------------- |
| `requestId`  | 是  | 回执对应当前"发朋友圈"命令的 `requestId`。          |
| `wechatId`   | 是  | 发布账号 ID。                              |
| `success`    | 是  | `true` 成功 / `false` 失败。               |
| `code`       | 否  | 错误码，`success=true` 时忽略（缺省 `0`）。       |
| `errMsg`     | 是  | 失败时必须带可读原因。                           |
| `taskId`     | 否  | 业务 `task_id`（通用）。                     |
| `circleId`   | 否  | 发布成功后的朋友圈 ID（`success=true` 时用于业务留痕）。 |

幂等键：`sha256(requestId)`；后端按 `success` 回写 `wechat.publish_circle`（§6.6）命令终态，`succeeded` 后同步 `TASK_TYPE_WECHAT_CIRCLE` 发布明细与任务状态。

***

## 8. 类型号段（状态）

| 号段                                      | 用途          | 状态                                             |
| --------------------------------------- | ----------- | ---------------------------------------------- |
| 0–14                                    | 通用/媒体状态     | CONFIRMED                                      |
| 20–26                                   | 视频号 sph     | CONFIRMED                                      |
| 30–32                                   | 接管任务        | CONFIRMED                                      |
| 40–42                                   | 养号/活动任务     | CONFIRMED                                      |
| **50**                                  | 加微信任务回执     | CONFIRMED（§7.1）                                |
| **52**                                  | 朋友圈动态事件     | CONFIRMED（§7.2）                                |
| **54**                                  | 朋友圈互动结果回执   | CONFIRMED（§7.3）                                |
| **55**                                  | 收到好友消息/私信   | **不登记 RPA 事件，AI 回复走 protobuf（§7.4）**           |
| **56**                                  | 收到加好友请求     | 保留 Jubo 通道，RPA 不 dispatch（§7.5，字段契约完整、必填为空即报错） |
| **57**                                  | —           | 不分配（≡52，§7.6）                                  |
| **58**                                  | 拉取朋友圈结果回传   | CONFIRMED（§7.7，已落地）                            |
| **59**                                  | 发朋友圈结果回执    | 约定（§7.8，待注册）                                   |
| 90–92、101–107、200–203、701–707、1001–1004 | 其余平台/画面/评论区 | CONFIRMED                                      |

> 命令族并入 V2 命令号段（`sv_device_command`）。§6.2–§6.5 微信命令后端已注册：**命令** **`739–742`、回执** **`842–845`**（避开已占用命令 720–738 / 回执 820–841 与协议内部专用 839/840/841）。其中：**`739`**
> 为当前要接入的主动加好友命令（号段需客户端确认），回执 `842`；**`740`**（自动通过好友）与 `843` 为**占位**，不 dispatch、不接入业务。**§6.6 发朋友圈**为待注册：**命令** **`743`、回执** **`846`**（需在 `DeviceCommandEnum` 注册并实现 handler）。号段为后端预留值，需微信团队确认后作为线上契约（对齐《设备端V2命令下发与回传协议.md》）。

***

## 9. 幂等 / 回执 / 状态机 / 对账约定（复用 `DeviceCommandService`）

1. 幂等键在建命令前计算，落 `sv_device_command`，重复创建被拒。
2. 每设备 lane 串行（`sv_device_command_lane`），同设备命令排队，避免并发/乱序。
3. 终态（`succeeded/failed`）只进入一次；重复回执经 `sv_device_command_event` 去重。
4. 无进度 > 120s → `UNCERTAIN`；不立即失败（等待可能迟到的真实回执）。
5. 迟到真实回执：`reconcile` 允许补齐终态，成功结果不因超时被覆盖。
6. 业务副作用（写业务表 / 记账 / 发聊记录）**必须在命令** **`succeeded`** **之后执行**，设备拒绝或掉线时不伪装成已发送。

***

## 10. 原 Jubo 功能 → RPA 命令/事件 映射表

| 原 Jubo 功能                           | 新实现（命令 / 事件）                                                 | 复用业务逻辑                                                      | 状态 / 迁移动作                  |
| ----------------------------------- | ------------------------------------------------------------ | ----------------------------------------------------------- | -------------------------- |
| AI 实时客服回复                           | §6.1 protobuf `TalkToFriendTask`                             | `AichatTrait`                                               | 已落地（CONFIRMED）             |
| SOP/群发/打招呼/发媒体私信（文本/图/视频/链接/小程序/文件） | §6.1 protobuf `TalkToFriendTask`（`ContentType` 1/2/4/6/13/8） | `PushContentLogic::wxPush`/`WechatTrait`                    | 已落地（CONFIRMED），不入命令族       |
| 自动通过好友                              | 占位（§7.5 事件56 + §6.3 `wechat.accept_friend`=740，**不落地**）      | 保留现用 Jubo 通道 `AcceptFriendAddRequestTask`/`TaskNoticeTrait` | 占位保留，不实现、不 dispatch        |
| 加好友执行                               | §6.2 `wechat.add_friend`=739 + 回执842                         | `TASK_TYPE_FRIENDS(5)`                                      | 命令已注册（号段需客户端确认），待接入下发触发    |
| 加好友成功落库 + 主动加友账本                    | §7.1 事件50 + §6.2 命令账本（payload 带 `recordId`/`isManual`）       | `WechatAddReceiptService`（事件50 落库）+ 主动加友命令账本                | 事件50 已落地；命令账本见 §12.4（C2）   |
| 朋友圈动态决策（点赞/评论）                      | §7.2 事件52 + `reply` 回传                                       | `CircleLikeCommentHandler`                                  | 已落地（CONFIRMED）             |
| 朋友圈点赞 / 评论 / 评论回复                   | §6.4 `wechat.circle_interact`=741 + 回执844                    | `AiCircleTrait`（`CircleLikeTask`/`CircleCommentReplyTask`）  | 命令已注册（号段需客户端确认）            |
| 拉取朋友圈                               | §6.5 `wechat.pull_circle`=742 + §7.7 事件58回执                  | `WechatCirclePulledHandler`                                 | 回执已落地；下发触发方 UNKNOWN（§12.2） |
| 发朋友圈                                | §6.6 `wechat.publish_circle`=743 + §7.8 事件59回执               | `WechatTrait`/`PostSNSNewsTask`                             | 待注册命令，需实现 handler（§12.1）   |
| 视频号发布 / 回执                          | 已走 sph 全套                                                    | 现有                                                          | 无                          |
| OTA 设备升级                            | 另行按 RPA 命令机制重做                                               | —                                                           | 不入本文命令族（§12.5）             |

***

## 11. 落地点与下线顺序（建议）

1. **M1（基座）**：`DeviceCommandDispatcher` 弃 `_transport=wechat.protobuf`，确立 JSON 命令下发；以「接管 / 加好友」为样板切 JSON，AI 私信回复按 §6.1 **继续走 protobuf** `TalkToFriendTask`，由事件 55 触发打通。
2. **M2（低垂果实）**：加好友、点赞/评论、发圈、视频号命令/事件已覆盖项直切（生成对应命令/task\_type）。
3. **M3（补实时事件）**：事件55/56/58 与客户端联调（57 沿用 52，不新建）。
4. **M4（收敛）**：所有回执统一进 `sv_device_command` 状态机，双协议过渡收敛（按设备在线的客户端类型路由）。
5. **M5（下线 Jubo）**：确认无设备走 Jubo 后，停 `start_wechat.php`/`start_device.php`/`WorkermanServie` 聚聊分支，删除 Jubo protobuf 构造。

***

## 12. 未落地项 / 需注册 / 交付跟进（UNKNOWN）

1. **发朋友圈命令待注册（§6.6/§7.8）**：`wechat.publish_circle`=`743`、回执 `846`、事件 `type=59` 尚未在 `DeviceCommandEnum`/`WorkerEnum` 注册，**handler 未实现**。落地步骤：注册命令号段 + 回执映射 + 实现 `type=59` 事件 handler（`WechatCirclePublishHandler`），在命令 `succeeded` 后写发圈明细并同步 `TASK_TYPE_WECHAT_CIRCLE` 任务状态。未落地前不得下发。
2. **拉取朋友圈下发触发方（§6.5，UNKNOWN）**：`type=58` 回执收敛已落地（`WechatCirclePulledHandler`），但当前仓库**未发现**构造 `wechat.pull_circle`=`742` 命令的下发触发方。何时/如何触发拉圈需微信团队确认后接入，避免臆造调用入口。
3. **主动加好友命令账本接入（§6.2，C2）**：`DeviceTaskTrait::cluesAddWechatFriendTask` 每笔线索通过校验后，除保持 Legacy protobuf 通道外，额外建立 `wechat.add_friend`=`739` 命令账本（`STATUS_PENDING`，幂等 `sha256(deviceId+wechatId+targetWechat+source)`，payload 带 `recordId`/`isManual`）。**当前不 dispatch**，避免未经验证切通道；微信团队确认号段后切 `dispatchNext` 即可。Legacy `type=50` 业务写入不动。
4. **命令号段 / 动作字段待客户端书面确认（§6）**：命令 `739`、回执 `842` 后端已注册但**号段需客户端确认**后才作为线上契约；这些是当前要接入的主动加好友号段。`740`（自动通过好友，§6.3）与事件 `type=56`（§7.5）为**占位**，不实现、不 dispatch。§6.6/§7.8 的 `743/846/59` 发朋友圈待注册同理。事件 `type=55` 不登记 RPA 事件，AI 回复走 protoobuf（§7.4）。
5. **媒体 / 群发私信通道（§10 澄清）**：SOP/群发/打招呼/发媒体私信统一走 §6.1 `TalkToFriendTask` protobuf（`ContentType` 1/2/4/6/13/8，见 `PushContentLogic::format_content`），**无独立 JSON 命令**。媒体 URL 由 `FileService::getFileUrl` 输出；`PublishMediaUrlService` 用于视频号（sph）媒体，与微信私信媒体无直接关系，本协议据此修正。
6. **OTA 迁移**：需按 RPA 命令机制重做，未纳入本文命令族范围。

***

## 13. 设备端开发详细步骤：主动加好友（wechat.add\_friend）

> 本节为微信团队设备端实现 **§6.2 主动加好友** 的完整分步契约。核心结论：**这是一个"多目标逐条命令 + 单条结果事件"链路**——服务器对每个加好友目标单独建立一条 `wechat.add_friend` 命令，设备逐条执行，执行完成后用 `type=50` 上报单条业务结果，再用命令终态回执 `842` 收敛命令账本。**不涉及自动通过加好友**（自动通过好友为占位，见 §6.3/§7.5，沿用现用 Jubo 通道，本设备端链路不处理）。

### 13.1 端到端时序

```text
服务器                                                 设备端
  │ 1.建命令 wechat.add_friend=739（单目标）                 │
  │ 2.dispatchNext，按 device.lane 串行下发                  │
  │     ─── type=739 JSON 信封 ────────────────────→          │
  │                                                          │ 3.接收并解析信封
  │                                                          │ 4.校验入参
  │ ←── 842 accepted（持续执行：running）──── |                │
  │                                                          │ 5.在 wechatId 上对 targetWechat 加好友
  │                                                          │   （附 remark），等待真实结果
  │ ←── type=50（单条业务结果，recordId）──── |                │
  │                                                          │ 6.执行完成
  │ ←── 842 succeeded / failed ────────────── |               │
  │ 7.收敛命令终态；type=50 落主动加友账本                     │
```

节奏要点：

- **一条命令 = 一个目标**：`content.targetWechat` 为单个微信号。服务器对有 N 个目标会建立 N 条命令并靠 lane 串行下发；设备端**不得**把多目标合并成一条命令返回。

- **两条回传各司其职**：`842`（命令终态，收敛 `sv_device_command`）与 `type=50`（单条业务结果，落账本）是**并列的两条独立回传**，设备端两者都要发，顺序无强约束但必须在真实执行后。

- **自动通过好友与本链路无关**：本设备端接收的是"主动加好友"命令，不存在自动通过 `type=56`；`type=56` 设备端无需上报。

### 13.2 步骤 1：接收命令（type=739）

设备从 `device.{deviceId}.message` Channel 收到 V2 JSON 信封（§6.0 下发信封）。`type` 即为命令号，业务参数在 `content`（JSON 字符串，需先反序列化）：

```jsonc
{
  "type": 739,                       // wechat.add_friend
  "requestId": "32位hex",            // 本动作唯一 ID，所有回执原样回带
  "deviceId": "wx_xxx",
  "appType": 1,                      // 微信个微=1
  "account": "wxid_main",
  "sequence": 18,
  "content": "{\"wechatId\":\"wxid_main\",\"targetWechat\":\"wxid_friend\",\"remark\":\"备注\",\"source\":1}"
}
```

`content` 字段（固定契约，§6.2）：

| 字段             | 必填 | 规则                          |
| -------------- | -- | --------------------------- |
| `wechatId`     | 是  | 执行加好友的个微账号 ID，非空。           |
| `targetWechat` | 是  | 目标微信号，非空字符串；空则直接回 `failed`。 |
| `remark`       | 否  | 好友备注，允许为空字符串。               |
| `source`       | 否  | 加好友来源标识，默认 `1`。             |

### 13.3 步骤 2：入参校验与 `842 accepted / failed`

校验通过（`wechatId` 为本机已登录可操作的账号、`targetWechat` 非空）后，立即按 V2 回传信封回 `842`：

```jsonc
{
  "type": 842, "requestId": "同一requestId", "deviceId": "wx_xxx",
  "appType": 1, "account": "wxid_main",
  "eventId": "add-result-<requestId>-1", "status": "accepted",
  "resultCode": "", "resultMessage": ""
}
```

- `accepted` 仅表示"已确认账号可用并准备执行"，**不代表已加好友成功**。

- 校验失败（账号不存在 / `targetWechat` 为空）直接回 `failed` + `resultMessage` 说明；不要进入执行。

- 长时间执行未完成可补发 `running`；`running` 无限次、可随进度多次发送，后端只作进度记录。

### 13.4 步骤 3：执行加好友动作

在 `account` 指定的个微账号上，对 `targetWechat` 发起加好友请求（附 `remark`）。**必须真实执行到产生结果为止**：

- 成功加好友 / 已是好友 / 查无此用户 / 触发频控 / 安全风险 → 都视为本命令已得到真实结果，进入步骤 4/5。

- 页面找不到账号、应用异常、掉线导致无法判定 → 不得本地猜测，按 §13.5 以 `failed` 上报并说明原因。

- 对 `running` 进度：执行中掉线后重连，收到相同 `requestId` 的设备不得更换 `requestId` 重试旧动作（对齐 V2 规则 3/5/6）。

### 13.5 步骤 4：单条业务结果上报（type=50）

每次加好友动作得到确定结果后，用 **§7.1 事件 50** 上报单条结果（`content` 反序列化，字段固定）：

```jsonc
{
  "type": 50, "appType": 1, "deviceId": "wx_xxx",
  "messageId": "add-result-1001", "appVersion": "2.4.1",
  "content": { "recordId": 1001, "userId": 88, "isManual": 0, "status": 0 }
}
```

| `content` 字段 | 必填 | 规则                                                                                                                |
| ------------ | -- | ----------------------------------------------------------------------------------------------------------------- |
| `recordId`   | 是  | 正整数。`isManual=0` 对 `sv_add_wechat_record.id`；`isManual=1` 对 `sv_crawling_manual_task_record.id`。服务器下发时自带该值作为业务归属。 |
| `userId`     | 否  | 若传必须等于记录 `user_id`，否则报所有权不符不写库。                                                                                   |
| `isManual`   | 是  | `0` 自动加好友记录 / `1` 手动任务记录。                                                                                         |
| `status`     | 是  | 固定 `0`–`4`：`0` 加好友成功；`1` 用户不存在；`2` 已是好友；`3` 触发频控；`4` 安全风险。仅 `status=0` 写成功。                                       |

- 服务器对同一 `recordId` 的重复 `type=50` 幂等（记录当前非"待处理"即直接返回），设备端**不得**用更换 `messageId` 绕过去重。

- 这是业务账本落库的依据（`WechatAddReceiptService`）；后端据此写 `sv_add_wechat_log`、累加 `completed_add_count`。

### 13.6 步骤 5：命令终态回执 `842 succeeded / failed`

执行动作结束后，按 V2 回传信封发命令终态，**必须在真实结果出现后才发**：

```jsonc
{ "type": 842, "requestId": "同一requestId", "deviceId": "wx_xxx",
  "appType": 1, "account": "wxid_main",
  "eventId": "add-result-<requestId>-final", "status": "succeeded",
  "resultCode": "", "resultMessage": "", "resultData": { "recordId": 1001, "status": 0 } }
```

- `succeeded`：仅当加好友动作产生确定终态（成功 / 已是好友 / 查无此用户 / 频控 / 安全风险之一，对应 `type=50` 的 `status`）。后端在 `succeeded` 后才执行命令级业务副作用。

- `failed`：无法完成/无法判定（页面找不到账号、应用异常、掉线）时回 `failed` + `resultMessage`，**不要**以超时或猜测回 `succeeded`。

- 成功与否的"业务成功"口径以 `type=50` 的 `status=0` 为准；`842 succeeded` 表示"命令端的执行已到真实结果"，两者配合而非互相替代。

### 13.7 幂等 / 重传 / 边界约束（设备端必守）

1. `requestId`、`deviceId/appType/account` 必须与下发信封完全一致，不一致的回执被拒。
2. `eventId` 为稳定唯一 ID：同一结果重传沿用原值；新结果必须换新值。服务器以 `requestId+eventId` 去重。
3. 服务器侧幂等键为 `sha256(deviceId+wechatId+targetWechat+source)`，重复命令会拒建——设备端对 **相同目标的重复命令** 应视为重复请求，不得重复执行加好友动作。
4. 掉线重连收到**相同** **`requestId`**：若本动作已有确定结果则重传原回执；若未完成且结果已产生则补发；**不得换** **`requestId`** **重生动作**。
5. `accepted / running / succeeded / failed` 状态含义与 V2 协议完全一致；`succeeded/failed` 只允许进入一次。
6. 本链路**不接收、不处理**自动通过加好友（`740`/`type=56`）；收到该命令号时应原样返回未知/不支持，等待微信团队后续确认启用（当前不 dispatch）。
7. 媒体/群发/打招呼/SOP 私信**不走本命令**，仍走 §6.1 `TalkToFriendTask` protobuf。

