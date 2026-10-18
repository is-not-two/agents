# 火山方舟统一适配层配置

适配层使用方舟固定 API 路径，调用方不能提交 URL 或覆盖 API Key。

| 能力 | 方舟固定路径 | 现有调用入口 |
| --- | --- | --- |
| 对话 | `POST /api/v3/chat/completions` | `Sv()->openaiChat()`、`Chat()->message()` |
| OCR（图片理解） | `POST /api/v3/chat/completions` | `Sv()->ocr()`、`Automation()->ocrImg()` |
| 图像生成 | `POST /api/v3/images/generations` | `HiDream()->setRequest()->send()` |
| 视频生成任务 | `POST /api/v3/contents/generations/tasks` | `Doubao()/Sora()/Volc()->setRequest()->send()` |

部署前在运行环境设置：

```dotenv
[ARK]
BASE_URL=https://ark.cn-beijing.volces.com
API_KEY=<ark-api-key>
VISION_MODEL=<vision-model-id-or-endpoint-id>

[EGRESS]
ALLOWLIST=ark.cn-beijing.volces.com
```

也可以通过后台 AI Provider 配置保存 `ark` 的加密 Key 与 `chat`、`ocr`、`image`、`video` 的模型/接入点 ID；适配层在环境变量未设置时会读取该配置。环境变量优先。

对话、图片和视频请求必须包含方舟要求的 `model`（Model ID 或推理接入点 ID）。OCR 使用支持图片理解的方舟对话模型，并要求业务传入 `image_url`（也兼容 `url` 或 `image`）。适配层将方舟对话响应的 `choices[0].message.content` 额外映射为 `data.message`，兼容现有调用方。

Coze 工作流没有方舟的一对一等价 API，仍需独立的 Coze 合同与配置，不能用方舟 API Key 替代。上线前分别验证成功、鉴权失败、限流和超时；视频还需补充任务查询、回调验签和结果 URL 失效策略。适配层只记录操作名和 HTTP 状态码，绝不记录密钥或请求内容。
