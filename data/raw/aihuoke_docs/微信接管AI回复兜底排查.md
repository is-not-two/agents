# 个微「AI 接管」固定回复同一句话 — 排查记录

日期：2026-09-16
现象：客户发送任意内容（"不谢"、"我很喜欢"、"我收到的货有破损怎么办"），AI 接管一律回复
`请稍等，该问题我不太清楚，为您转接给对应的部门同事`，且与配置的系统提示词无关。

## 结论

回复逻辑里确实存在**硬编码兜底文案**，且**接管智能体的 AI 调用链本身是断的**。
在「机器人未挂载知识库」这条分支上，代码调用的是一个固定返回失败的桩函数，因此每次都会走到兜底文案，
你的系统提示词虽然被正确拼进了 `messages`，但从未真正发给大模型。

## 证据链

### 1. 兜底文案是硬编码的函数初值

`app/common/workerman/wechat/traits/AichatTrait.php:590`

```php
private function _beforeSend(array $payload)
{
    $log = ChatLog::where('task_id', $payload['task_id'])->findOrEmpty();
    $reply = '请稍等，该问题我不太清楚，为您转接给对应的部门同事';   // ← 初值即"转人工"文案
    if ($log->isEmpty()) {
        ... // 成功取到 AI 回复才会覆盖 $reply
    } else {
        $reply = $log->reply;
    }
    // 无论取没取到，后面都会把 $reply 原样发给客户
}
```

只要 AI 分支没有被成功赋值，**这句话就必须被发出去**——没有任何"取不到就别发"的保护。

### 2. 无知识库分支调用的是桩函数，永远失败

`AichatTrait.php:591-633` 的分支条件：

```php
if (!empty($payload['knowledge']) || ($payload['robot']['kb_type'] == 2 && !empty($payload['robot']['kb_ids']))) {
    [$chatStatus, $response] = KnowledgeLogic::socketChat([...]);   // 真实大模型，能正常出话
} else {
    $response = app(ToolsServiceClient::class)->wechat->chat($payload['request']); // ← 桩
    if (isset($response['code']) && $response['code'] == 10000) {
        $reply = $this->_handleResponse($response, $payload['request']);
    } else {
        $this->withChannel('wechat_socket')->withLevel('msg')->withTitle('chat 错误')->...->log();
        // $reply 保持初值 → 发出兜底文案
    }
}
```

而被调用的实现是空的：`app/common/service/ai/WechatService.php:19-22、62-65`

```php
public function chat(array $params): array
{
    return $this->unavailable('WeChat chat requires an approved AI and device receipt contract');
}
private function unavailable(string $reason): array
{
    return ['code' => 0, 'data' => [], 'msg' => "SERVICE_UNAVAILABLE: {$reason}"];
}
```

`code` 恒为 `0`，永远不等于 `10000`，所以 `_handleResponse()` 永远不会被调用。
同类桩还有 `accept()` / `circle()` / `push()` / `online()`。

这与文件头注释自相矛盾：注释写「actual AI processing happens in workerman handlers (AichatTrait)」，
但 AichatTrait 自己又反过来调用了这个桩——链路首尾相接，中间没有真正的模型调用。

### 3. 该状态在全部分支一致，不是某个分支的产物

`master` / `release` / `dev/*` 等分支上 `AichatTrait.php` 与 `WechatService.php` 内容一致，
`WechatService` 自首个提交 `f7e802a`（2026-07-31 外呼业务内部化重构）起就是桩实现。
即：这是**重构后遗留的未接回能力**，不是最近改坏的。

### 4. 同一问题还影响其他入口

| 文件 | 行 | 场景 |
| --- | --- | --- |
| `app/common/workerman/wechat/traits/AichatTrait.php` | 590 / 622 | 个微接管、群聊接管（主链路） |
| `app/common/workerman/wechat/traits/AiCircleTrait.php` | 288 | 朋友圈评论 AI 回复 |
| `app/common/workerman/rpa/handlers/wechat/CircleLikeCommentHandler.php` | 432 | 朋友圈评赞 AI 回复 |
| `app/common/Jobs/WechatAIMessageJob.php` | 100 | 旧队列版 AI 回复（`WechatBaseLogic::parseAiPrompt` 派发） |

### 5. 排除项：提示词模板本身没问题

`_parseAiPrompt`（`AichatTrait.php:482-585`）取 `la_chat_prompt` 中 `prompt_name='微信客服'` 的模板，
把 `【角色设定】` 替换为 `$robot->roles_prompt`（即你在「接管机器人」里配置的系统提示词），
再与历史记录合并进 `request.messages`。

- 若该模板记录缺失会抛 `提示词不存在` 并**只记日志、不发消息**；现在有回复发出，说明模板存在、拼装成功。
- 所以「提示词没生效」只是表象，真正的断点在模型调用。

## 线上确认方法

1. **看日志**（决定走哪条分支）
   `runtime/log/structured/YYYYMM/DD.log`，找 `event = wechat_socket.event`：

   | 日志 message | 含义 |
   | --- | --- |
   | `chat 错误` | 走到桩函数分支（未挂载知识库），**本次现象的判定依据** |
   | `串行请求知识库失败` | 走了知识库分支但检索/调用失败 |
   | `智能体说话` + `请求数据` | 提示词已拼好（这两条两条分支都会打） |
   | `请设置机器人` / `人工接管中` / `未开启ai` | 前置守卫拦截，不回复 |

2. **对照实验**（最快）
   给该接管机器人挂一个知识库（绑定任意内容），再发消息：
   - 回复开始变化 → 确认是「无知识库 + 桩函数」导致；
   - 回复仍是同一句 → 查知识库检索是否返回空（`socketChat` 返回字符串 `知识库未检索到内容`，
     `isset($response['choices'][0])` 为 false，仍会落到兜底文案）。

3. **看账单**：桩函数分支下 `ChatLog` 不落库、token 不扣费。若这段时间没有任何 AI 微信扣费记录，
   同样佐证模型调用没发生。

## 修复方向

`OwnApiClient::chat()`（`app/common/service/ai/OwnApiClient.php:25`）是**真实可用**的火山方舟调用，
已有调用方在跑：`ToolsService::Sv()->openaiChat()`（`SvAutomationService.php:22`）。
其返回结构 `{code:10000, data:{message, usage}, msg}` 与 `_handleResponse()` 的取值完全匹配。

最小改动：把无知识库分支的桩调用换成真实对话调用。

```php
// AichatTrait.php:622
$response = \app\common\service\ToolsService::Sv()->openaiChat($payload['request']);
```

需要同时确认/处理：

1. `payload['request']` 已含 `messages` / `model` / `temperature` 等，
   `OwnApiClient::request()` 会按白名单过滤字段，无需额外转换。
2. `OwnApiClient` 走 `ToolsCapabilityGate` 能力开关与 ARK 凭证（`.env [ARK] API_KEY` 或后台 AI 供应商配置），
   需确认线上 `ark_chat` 能力为开启、凭证有效，否则会返回 `SERVICE_UNAVAILABLE: ...`，现象不变。
3. **兜底策略要改**：建议区分「调用失败」与「模型要求转人工」，不要再用同一句文案；
   至少把兜底文案改成中性提示 + 记录失败原因，避免故障期静默发出误导性话术。
4. 建议给该分支补一条结构化日志（含 `response.msg`），当前只打了 `chat 错误` 不带返回值，
   排障时看不到真实原因。
5. 若产品希望保留"未挂知识库也要能闲聊"，则第 3 步修完后还需回归 `AiCircleTrait`、`WechatAIMessageJob`、
   `CircleLikeCommentHandler` 三处同类调用，避免只修主链路。

## 修复实施（2026-09-16）

前提确认：ARK 凭证有效（本地 `.env.local` 的 `[ARK] API_KEY` 实测可调用方舟对话）。
兜底话术按要求**保持复用转人工话术**，不新增中性文案，只补"让人工知道"的环节。

### 改动 1：`app/common/workerman/wechat/traits/AichatTrait.php`

- `_beforeSend()` 第 639 行：无知识库分支的 `app(ToolsServiceClient::class)->wechat->chat(...)`
  → `ToolsService::Sv()->openaiChat($payload['request'])`（真实方舟对话，入参契约不变）。
- `_beforeSend()` 增加 `$aiReplied` / `$failReason` / `$lastResponse` 三个追踪变量，
  并统一"未取到可发送内容"的判定：知识库调用失败、知识库无内容、方舟调用失败、
  方舟返回内容不可用（`_handleResponse` 抛错）——四种情况都会走转人工。
  其中 `_handleResponse()` 原先抛错会冒泡到 `_parseAiPrompt` 的 catch，导致"既不给客户回复、也不通知人工"，
  现在改为就地降级到兜底话术 + 转人工。
- 新增 `_handOverToHuman()`：AI 失败时
  1. 把 `ai_wechat_contact.takeover_mode` 置 0（人工接管）——控制台会话头部开关显示「人工接管」，
     且后续客户消息不再交给 AI（`sendFriendTalkNoticeMessage` 里的「人工接管中」守卫）；
  2. 写一条 `ai_wechat_todo`（`todo_type=0` 代办提醒，内容 "AI 回复失败，请人工跟进：…"）——
     控制台「待办」可见、可跟单；同一好友已有未处理待办时不重复插入；
  3. 打 error 级结构化日志 `AI 回复失败，已转人工接管`。
- 新增 `_failureReason()`：从上游返回里取 `msg` / `message` / `error.message`，取不到用兜底原因。
- 三处失败日志（`串行请求知识库失败`、`知识库未返回可发送内容`、`chat 错误`）均补上 `msg` 字段。

### 改动 2：`app/common/workerman/wechat/traits/AiCircleTrait.php`

`createReplyContent()` 第 288 行同样是同一个桩（朋友圈评论/回复 AI），
一并换成 `\app\common\service\ToolsService::Sv()->openaiChat($request)`，并给 `chat 错误` 日志补 `msg`。

> 注意：`AiCircleTrait` 与 `AichatTrait` 被同一个 `MessageService` 组合使用，
> 因此**不能在两个 trait 里定义同名私有方法**（PHP 会 fatal），`AiCircleTrait` 里没有复用 `_failureReason`。

### 验证（本地实跑，脚本：`runtime/tmp_wechat_ai_chain_check.php`）

```
php -d curl.cainfo=<ca-bundle.crt> runtime/tmp_wechat_ai_chain_check.php
```

| 检查项 | 结果 |
| --- | --- |
| `_failureReason` 取 msg（含 `msg` / `error.message` / `message` / 字符串 / 空数组） | 5/5 正确 |
| `ToolsService::Sv()->openaiChat()` 真实方舟调用 | `code=10000`、`data.message=正常`、`usage.total_tokens=2963` |
| 返回结构匹配 `_handleResponse()`（`data.message` + `data.usage.total_tokens`） | yes |
| `MessageService`（双 trait 组合）编译 | yes，两个新方法均已注入 |
| 两个 trait 内残留 `->wechat->chat(` 桩调用 | 无 |
| 桩本体 `WechatService::chat()` | 未改动，仅不再被引用 |

Windows 本地跑脚本需显式给 curl 指定 CA（本机 PHP 无 cacert.pem）：
`-d curl.cainfo="<PortableGit>/mingw64/etc/ssl/certs/ca-bundle.crt"`；
本地凭证在 `.env.local`，脚本内用 `$app->loadEnv('local')` 叠加加载。

### 改动 3：`app/common/Jobs/WechatAIMessageJob.php`（旧队列版 AI 回复）

控制台"AI 回复"入口（`useTalkReplyTask`）走这条队列链路，此前是**死链路**：

- 第 104 行：`app(ToolsServiceClient::class)->wechat->chat($this->request)`
  → `ToolsService::Sv()->openaiChat($this->request)`。
  这里有两个叠加的 bug：① 文件在 `app\common\Jobs` 命名空间下 `app(ToolsServiceClient::class)`
  解析为 `app\common\Jobs\ToolsServiceClient`（**类不存在 → 抛错**）；② `WechatService::chat` 是恒定 `code=0` 的桩。
- 第 110-114 行：方舟返回 `code != 10000` 时**不再就地 `retryJob()`**，改由下方统一分支处理。
  原先"方舟失败先 release 一次、空内容再 release 一次"会让同一个 job 被重复入队。
- 第 122-136 行：新增"未取到可发送内容"守卫。原实现此处 `$reply` 在失败路径上**未定义**，
  直接 `sendMessage($reply)` 会抛 `TypeError`，被外层 catch 当成"参数异常"重试，
  真实原因（上游 msg）被完全掩盖。现在：空内容 → 记录 `msg` → `retryJob()`；重试耗尽 → 转人工。
- 新增 `notifyHumanFollowUp()`（与主链路 `_handOverToHuman` 行为一致）：
  置 `ai_wechat_contact.takeover_mode=0` + 写 `ai_wechat_todo`（`todo_type=0`，同一好友去重）+ 打日志。
- `markAsFailed()` 开头调用 `notifyHumanFollowUp($errorMessage)`：
  **所有**走到"队列重试耗尽"的失败（含 `handleResponse` 抛错）都会在 Web 控制台留下人工处理入口。

### 改动 4：`app/common/workerman/rpa/handlers/wechat/CircleLikeCommentHandler.php`

`auto_type=0`（手动任务）分支第 432 行同样是同一个桩，一并换成 `ToolsService::Sv()->openaiChat($request)`，
移除已失效的 `use ...ToolsServiceClient;`，并在 AI 调用失败分支的日志里补上 `msg=`。

> 该文件只有 `auto_type=0`（手动任务）分支受影响；`auto_type!=0`（自动任务）走的是可用的
> `ToolsService::Automation()->friendsCircleComments`，未改动。

### 验证结果（2026-09-16，本地实跑）

| 检查项 | 结果 |
| --- | --- |
| 四个改动文件 `php -l` | 全部 No syntax errors |
| `WechatAIMessageJob::notifyHumanFollowUp` 存在且为 `protected(string $reason, array $response)` | yes |
| `WechatAIMessageJob` 内 `$this->notifyHumanFollowUp(` 调用点 | yes（守卫 + `markAsFailed`） |
| `WechatAIMessageJob` 残留 `ToolsServiceClient` 引用 | 无（仅注释） |
| `CircleLikeCommentHandler` 残留 `use ToolsServiceClient` / `->wechat->chat(` | 无 / 无 |
| `CircleLikeCommentHandler` 失败日志含 `msg=` | yes |
| `AiWechatTodo` / `AiWechatContact` 模型可加载 | yes |

### 未改动、需要产品确认的同类桩

以下两处是**同一类缺陷**：`app(ToolsServiceClient::class)->wechat->*()` 最终落到 `WechatService` 的桩方法，
桩本体恒定返回 `code=0`（附 `SERVICE_UNAVAILABLE`），而调用方既不校验 `code` 也不校验 `msg`
→ **静默空跑**。它们**不是 AI 对话**，而是设备指令下发（会在真实微信账号上产生副作用），
因此先查清落点再动。

> **更正（2026-09-16）**：本节此前写「`app\common\Jobs` 下的 `app(ToolsServiceClient::class)`
> 解析失败 → 抛类不存在」。**该结论错误**：两个 Job 文件都写了
> `use app\common\service\ToolsServiceClient;`，`::class` 展开为完整类名，**类存在、可解析、不抛错**。
> 真实缺陷是「静默空跑」，其中 `WechatAcceptFriendJob` 还会在空跑后**写一条假的成功账**。

> **通道已定，落点也已改造（2026-09-16）——详见 `docs/微信设备指令通道划分与现状.md`。**
> 政策：自动通过好友改由 **WeChatPadPro 网关**承接（**已实施**）；自动化设备指令走 **RPA 通道**；
> 小程序 / Web 手动操控走 **WeChatPad 通道**。

| 位置 | 现状 | 结论 |
| --- | --- | --- |
| `app/common/Jobs/WechatAcceptFriendJob.php` | 桩返回 `code=0` 被调用方当成成功 → 空跑后仍写 `AiWechatLog TYPE_ACCEPT_FRIEND`（假账，还会吃掉当日 `accept_numbers` 额度） | ✅ **已处理（2026-09-16）**：`fire()` 改为校验 `code === 10000`，非成功即抛错走既有重试/失败路径，不再写账；`FriendLogic::acceptFriend` 已改走 `WechatPadFriendService` 网关票据流程，本 Job **已无任何派发方**，随后该类**整体删除** |
| `app/common/Jobs/WechatSendCircleJob.php` | 同上，死代码 | 🗑️ **已删除（2026-09-16）**：唯一派发点 `CircleLogic.php:449` 早已注释，`runtime/` 无运行痕迹。实际发圈走 `CircleLogic.php:422` 的同步 `self::wxCircle()`；自动化发圈走 `DeviceTaskScheduler` → `wechatCirclePublishTask`（**RPA，已落地**） |

> `WechatService`（`app/common/service/ai/WechatService.php`）整个类及其两个工厂入口
> `ToolsServiceClient->wechat` / `ToolsService::Wechat()` 已确认**零真实调用方**并**整体删除**；
> 其 `unavailable()` 桩曾返回 `code=0`，**调用方必须按 `code === 10000` 判定成功**，
> 不得把 `code=0` 当成功——这正是本次两处缺陷的共同成因，该约定继续适用于 `PlatformService`
> 等仍保留的桩。

### 上线后确认点

1. 客户消息能拿到真实 AI 回复（不再固定一句）。
2. 制造一次 AI 失败（如临时改错模型名），确认：控制台会话头部变「人工接管」+「待办」里出现"AI 回复失败，请人工跟进"。
3. 日志中 `chat 错误` 现在带 `msg`，可直接看到上游原因。
4. 该分支成功回复会走 `_handleResponse()` 扣费（`ai_wechat` 场景）与 `ChatLog` 落库，确认计费口径正常。
