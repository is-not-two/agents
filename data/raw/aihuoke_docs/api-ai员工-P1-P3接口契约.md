# AI员工后续接口契约（B6、B7、B11、B14）

说明：仓库未找到需求指定的 `docs/api-doc-template.md`，本契约按 P0 接口契约现有结构编写。通用分页字段沿用 `BaseApiDataLists`。

## B6 人设素材分组

### `GET /aiPersona.MaterialGroup/lists`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | int | 是 | 当前用户 AI员工 ID |
| name | string | 否 | 分组名称模糊搜索 |
| page_no | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

返回 `lists/count`；每个 list 项含 `id, persona_id, user_id, name, sort, material_count, create_time, update_time`。

### `POST /aiPersona.MaterialGroup/add`

参数：`persona_id:int` 必填，`name:string` 必填（最多100字符），`sort:int` 可选（默认0）。返回分组对象。

### `POST /aiPersona.MaterialGroup/update`

参数：`id:int`、`persona_id:int`、`name:string` 必填，`sort:int` 可选。返回更新后的分组对象。

### `POST /aiPersona.MaterialGroup/delete`

参数：`id:int`、`persona_id:int` 必填。删除分组时其素材移至未分组 `group_id=0`；返回空 data。

### `POST /aiPersona.MaterialGroup/move`

参数：`persona_id:int` 必填；`ids:int[]` 必填，素材 ID 列表；`group_id:int` 可选，0 表示移至未分组。返回 `{count, group_id}`。

错误与边界：员工、分组、素材必须属于当前用户和传入员工；目标分组不属于该员工时报错；空素材列表报错；删除分组不删除素材。

### 素材接口扩展

`POST /aiPersona.Material/add`、`addBatch`、`update` 增加可选 `group_id:int`（默认0）；列表增加可选 `group_id:int` 精确筛选。非零分组须属于该员工。`addBatch` 每项的 `group_id` 通过同一规则校验。

示例：`{"code":1,"msg":"操作成功","data":{"count":2,"group_id":0}}`。

自检：1) 方法路径已列；2) 参数类型/必填列出；3) 返回字段列出；4) 给出 JSON 示例；5) 错误与边界列出；6) 用户及员工隔离说明；7) 删除/未分组语义说明；8) 分页沿用既有封装并说明素材兼容字段。

## B11 设备任务员工筛选

`GET /device.CalendarTask/lists` 增加可选 `persona_id:int`；传入时按 `sv_device_task.persona_id` 精确筛选，不传保持原列表。分页和返回结构不变，仍按当前用户隔离。参数/错误沿用全局列表校验。

## B8 视频模板列表复用确认

复用 `GET /shanjian.ClipTemplate/lists`，不新建 AI员工 专属模板或详情接口。列表项字段为 `id:int`、`name:string`、`cover_url:string`、`demo_url:string`、`scene:string`；模板预览使用 `demo_url`。支持按 `scene` 筛选，scene 值 `virtualman`（数字人口播）、`realMan`（真人口播）、`oralMixCutting`（素材混剪）、`newsMixCutting`（新闻体）。模板为共享数据，不需要人设参数。

## B7 AI员工发布文案生成

### `POST /aiPersona.AiPersona/generatePublishCopywriting`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | int | 是 | 当前用户 AI员工 ID；用于员工身份与文风 |
| groups | object[] | 是 | 图片组，1–20 组 |
| groups[].image_urls | string[] | 是 | 每组 1–9 个 HTTP/HTTPS 图片地址 |
| publish_scene | string | 否 | 发布场景，默认“发布图文” |
| platform | string | 否 | 发布平台提示 |

返回 `persona_id` 及 `items[]`；每项含 `title:string`、`content:string`、`topic:string[]`。标题最多20字，正文最多800字，话题最多5个。

示例：`{"code":1,"msg":"操作成功","data":{"persona_id":7,"items":[{"title":"周末轻松出发","content":"按图片内容生成的文案","topic":["周末","日常"]}]}}`。

错误与边界：员工需属于当前用户；图片组数量、每组图片数量或 URL 不符合上述范围时报错；外部 AI 失败或返回格式/长度无效时报错且不扣算力；成功后按生成条数扣费，scene 为 `ai_persona_publish_copywriting`，默认 1 算力/条。请求将员工名称、简介、行业、人设描述及已生成报告作为文案上下文发送至当前配置的 AI 文案服务。

自检：1) 方法路径已列；2) 参数类型/必填/数量限制列出；3) 返回字段及长度列出；4) JSON 示例完整；5) 员工权限、图片及模型错误列出；6) 扣费 scene 和时机列出；7) AI员工数据用途与外发字段列出；8) 输出限制、算力单价及外部服务配置边界列出。

## AI员工文案库

数据独立存储在 `la_ai_persona_copy_library`，所有读写按当前 `user_id + persona_id` 隔离。标准响应字段为 `code,msg,data`；成功 code=1，错误 code=0；列表额外含分页字段。

| 方法与路径 | 请求参数 | 返回 data |
| --- | --- | --- |
| `GET /aiPersona.copyLibrary/lists` | `persona_id:int` 必填；`copy_type:int`、`copy_style:int`、`keyword:string`、`page_no:int`、`page_size:int` 可选 | `{lists:Copy[],count:int,page_no:int,page_size:int,extend:[]}` |
| `GET /aiPersona.copyLibrary/detail` | `id:int`、`persona_id:int` 必填 | `Copy` |
| `POST /aiPersona.copyLibrary/add` | `persona_id:int`、`copy_type:int`、`copy_style:int`、`title:string` 必填；`content:string`、`topic:string`、`source:int` 可选 | 新建的 `Copy` |
| `POST /aiPersona.copyLibrary/addBatch` | `persona_id:int`、`items:CopyInput[]` 必填 | `{count:int}` |
| `POST /aiPersona.copyLibrary/update` | `id:int`、`persona_id:int` 必填；`title:string`、`content:string`、`topic:string` 可选 | 更新后的 `Copy` |
| `POST /aiPersona.copyLibrary/delete` | `id:int`、`persona_id:int` 必填 | 空对象 |
| `POST /aiPersona.copyLibrary/deleteBatch` | `persona_id:int`、`ids:int[]` 必填 | `{count:int}` |
| `POST /aiPersona.copyLibrary/import` | `persona_id:int`、`copy_type:int`、`copy_style:int`、multipart 文件 `file` 必填 | `{count:int}` |

`Copy` 字段：`id, persona_id, user_id, copy_type, copy_style, title, content, topic, source, create_time, update_time`。`copy_type`：1 视频驱动文案、2 发布文案；`copy_style`：0 无、1 新闻体、2 口播、3 素材混剪口播。发布文案必须使用 style=0；视频驱动文案必须使用 style=1/2/3。`source`：1 AI生成、2 手动新增（默认）、3 文件导入。

`CopyInput` 字段：`copy_type:int`、`copy_style:int`、`title:string` 必填；`content:string`、`topic:string`、`source:int` 可选。

长度限制：新闻体 title≤1000，不接收 content/topic；口播及素材混剪口播 title≤50、content≤600，不接收 topic；发布文案 title≤50、content≤1000、topic≤200。导入文件支持 xlsx/xls/csv，首行为表头且必须包含英文列名 `title`；`content`、`topic` 列可选。上传大小由 PHP 当前运行环境的 `upload_max_filesize` / `post_max_size` 限制；本接口不额外限制行数。

示例：`{"code":1,"msg":"success","data":{"id":8,"persona_id":7,"user_id":2,"copy_type":2,"copy_style":0,"title":"春日上新","content":"新品介绍","topic":"春日,上新","source":2}}`。

错误与边界：员工须属于当前用户；指定记录须同时匹配当前用户和 persona_id；非法 type/style/source、字段长度超限、空批量 ID、文件格式错误或缺少所需表头返回错误；批量新增和删除全部校验通过后再执行。

自检：1) 八个方法路径已列；2) 请求参数类型与必填状态已列；3) 成功返回字段已列；4) 给出可解析示例；5) 错误及边界已列；6) 用户/员工隔离已列；7) 类型、风格、来源和长度口径已列；8) 导入格式、上传限制和分页封装已列。

## B13 首页统计员工筛选

`GET /display.display` 增加可选 `persona_id:int`。省略时沿用原全局统计；传入时先校验员工归属。任务/发布记录按 `persona_id` 筛选，设备和设备关联线索、私信、加微、爬取数据按该员工绑定设备筛选。无绑定设备时设备关联指标为0。返回字段结构沿用原 `display` 响应。错误：`AI员工不存在或无权查看`。

## B14 AI员工作品

### `GET /aiPersona.Works/lists`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | int | 是 | 当前用户 AI员工 ID |
| status | int | 否 | 发布任务状态 |
| platform | string/int | 否 | `video_channel`、`wechat`、`xiaohongshu`、`douyin`、`kuaishou` 或数值码1–5 |
| account_id | int | 否 | `la_sv_account.id`；该账号必须属于当前用户且设备绑定到传入 AI员工 |
| period | string | 否 | `7d`、`30d`、`90d`；省略时不限制时间 |
| account_type | int | 否 | 账号类型 |
| page_no | int | 否 | 页码 |
| page_size | int | 否 | 每页数量 |

返回 `lists/count/page_no/page_size/extend`；list 项保留发布记录字段并增加 `cover:string`、`title:string`、`period:string(YYYY-MM-DD)`、`media_urls:string[]`、`platform_code:int`。封面优先取发布记录 `pic`，为空时取第一条有序媒体 URL。`media_urls` 按 `sort_order ASC`，可以有多条。`publish_time` 返回数据库日期时间字符串。`views/praises` 是当前发布记录保存的快照值，不承诺实时同步平台数据。status 原始值：0未执行、1已发布、2发布失败、3发布中、4已删除；account_type 数值：1视频号、3小红书、4抖音、5快手。`platform` 对外返回字符串，`platform_code` 保留数据库码。

### `GET /aiPersona.Works/detail`

参数：`id:int`、`persona_id:int` 均必填。返回对应发布记录字段及同列表定义的 `cover/title/period/platform/platform_code`，以及按 `sort_order ASC` 排列的 `media_urls:string[]`。

### `GET /aiPersona.Works/overview`

| 参数 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | int | 是 | 当前用户 AI员工 ID |
| period | string | 否 | `7d`/`30d`/`90d`，默认 `7d` |
| platform | string/int | 否 | 同作品列表的平台值 |
| account_id | int | 否 | 同作品列表；按该账号汇总并生成趋势 |

返回 `{period,summary,compare,trend,unavailable_metrics}`。summary 为所选周期内作品发布记录快照值之和，`play_count` 对应 views，`like_count` 对应 praises；comment/collect/share/fans 字段当前数据源不存在，返回0并在 unavailable_metrics 标明。compare 为与前一同长度周期相比的百分比；前一周期为0时返回0。trend 按自然日补齐，按作品 `publish_time` 日期汇总当前 views/praises 快照，不代表平台每日历史曲线。

示例：`{"code":1,"msg":"","data":{"period":"7d","summary":{"play_count":120,"like_count":8,"comment_count":0,"collect_count":0,"share_count":0,"fans_count":0},"compare":{"play_count":12.3,"like_count":-4.0},"trend":[{"date":"2026-09-18","play_count":20,"like_count":1},{"date":"2026-09-19","play_count":0,"like_count":0},{"date":"2026-09-20","play_count":0,"like_count":0},{"date":"2026-09-21","play_count":0,"like_count":0},{"date":"2026-09-22","play_count":0,"like_count":0},{"date":"2026-09-23","play_count":0,"like_count":0},{"date":"2026-09-24","play_count":100,"like_count":7}],"unavailable_metrics":["comment_count","collect_count","share_count","fans_count"]}}`。

错误与边界：员工必须属于当前用户；period 仅支持 7d/30d/90d；平台数值码1–5或已列字符串；无前期基数时环比返回0。员工作品、账号及快照值按当前用户与 persona_id 隔离。

自检：1) 路径与方法已列；2) 请求参数及默认值已列；3) 汇总/环比/趋势返回字段已列；4) JSON 示例完整；5) 无权和非法参数错误已列；6) 指标来源及缺失指标已列；7) 周期边界、零基数与趋势含义已说明；8) 媒体排序、平台映射和快照非实时限制已说明。

示例：`{"code":1,"msg":"","data":{"lists":[{"id":123,"persona_id":7,"status":1,"platform":"douyin","platform_code":4,"publish_time":"2026-09-18 10:00:00","views":20,"praises":3,"cover":"https://example.com/cover.jpg","title":"作品标题","period":"2026-09-18","media_urls":[]}],"count":1,"page_no":1,"page_size":25,"extend":[]}}`。

错误与边界：员工必须属于当前用户；作品按 `user_id + persona_id + id` 隔离；无权或不存在返回“作品不存在或无权操作”；列表参数沿用通用分页边界。

自检：1) 方法路径已列；2) 请求字段类型/必填列出；3) 返回主要字段列出；4) JSON 示例可解析；5) 无权错误列出；6) 当前用户/员工范围明确；7) 媒体子表排序及指标快照性质说明；8) 分页和字段兼容边界说明。

## B9 AI员工定时发布任务流

任务流是发布计划的管理容器，不编排 Coze/AI 工作流。面板通过现有发布接口创建具体定时发布计划，再将这些计划 ID 关联到员工任务流；发布仍由现有发布计划、`SvPublishSettingDetail` 和 `PublishDetailCron` 执行。

### `GET /aiPersona.TaskFlow/lists`

请求参数：`persona_id:int` 必填。返回任务流数组，每项含 `id:int`、`persona_id:int`、`name:string`、`description:string`、`status:int`（0暂停、1启用）、`task_count:int`、`next_publish_time:string`。

### `GET /aiPersona.TaskFlow/detail`

请求参数：`id:int` 必填。返回任务流字段及 `tasks:Task[]`；Task 含 `id:int`、`publish_id:int`、`publish_setting:object`、`record_count:int`、`finished_count:int`。发布记录字段沿用 `SvPublishSettingDetail`。

### `POST /aiPersona.TaskFlow/add`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | int | 是 | 当前用户 AI员工 ID |
| name | string | 是 | 任务流名称 |
| description | string | 否 | 描述 |
| publish_ids | int[] | 否 | 已创建的定时发布计划 ID 数组 |

新建状态为启用。每个计划必须属于当前用户，且计划中的全部账号设备都绑定到该员工；同一发布计划不能关联多个任务流。

### `POST /aiPersona.TaskFlow/update`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| id | int | 是 | 任务流 ID |
| name | string | 否 | 新名称 |
| description | string | 否 | 描述 |
| publish_ids | int[] | 否 | 提供时整体替换关联计划；移除的计划账号暂停 |

### `POST /aiPersona.TaskFlow/setStatus`

请求参数：`id:int`、`status:int` 必填；`status` 仅支持 0 暂停或 1 启用。节点排期任务流启用时，同一 AI员工不能有另一个启用中的任务流，且至少包含一个已接入设备调度器的任务类型。暂停把关联发布账号的运行状态保存快照并置为0，现有发布调度因此跳过该计划；恢复时还原快照状态。启用节点排期后，固定时段自动任务按任务流节点生成。

### `POST /aiPersona.TaskFlow/delete`

请求参数：`id:int` 必填。删除任务流时先暂停关联发布账号，再软删除任务流；发布计划及记录保留。

### `GET /aiPersona.TaskFlow/logs`

请求参数：`id:int` 必填；`page_no:int` 默认1，`page_size:int` 默认20、最大100。返回 `{lists:SvPublishSettingDetail[],count:int,page_no:int,page_size:int}`，按计划发布时间倒序。发布状态、失败原因和执行时间沿用发布记录字段。

示例：`{"code":1,"msg":"","data":{"id":12,"persona_id":7,"name":"周更发布","status":1,"task_count":2,"next_publish_time":"2026-09-30 10:00:00","tasks":[{"id":30,"publish_id":801,"record_count":4,"finished_count":1}]}}`。

错误与边界：员工、任务流及发布计划按当前用户隔离；计划设备必须全部属于该员工；状态值仅为0/1；暂停计划会改变计划账号状态，恢复时按状态快照还原；删除仅暂停计划并软删除任务流，不删除既有发布记录。实际发布执行依赖现有发布调度服务运行。

自检：1) 接口方法、路径和请求字段已列；2) 各字段类型、必填和默认值已列；3) 列表、详情、日志返回字段已列；4) JSON 示例完整；5) 用户、员工、计划归属错误已说明；6) 启停、移除和删除的状态副作用已说明；7) 执行复用现有发布调度链路已说明；8) 分页上限及软删除保留边界已说明。

## B10 工作流模板

工作流模板列表、详情与应用接口由 `TaskFlow/templateLists`、`templateDetail`、`applyTemplate` 提供。模板应用为当前 AI员工克隆一个暂停态任务流；可执行节点复用现有业务配置和设备任务生成器，暂定的评论接管、视频号评论点赞节点保留但不生成任务。字段级模板节点契约见 `docs/api-ai-employee-task-flow-templates.md`。

## B12 AI员工内容流

### `GET /aiPersona.ContentFeed/lists`

请求参数：`persona_id:int` 必填；`page_no:int` 默认1；`page_size:int` 默认20、最大100。返回 `{lists:Content[],count:int,page_no:int,page_size:int}`。Content 为员工本人已发布作品，按 `views`、`praises`、`publish_time` 倒序，包含作品记录字段及 `cover`、`title`、`media_urls`、`platform_code`、`is_favorite`、`is_disliked`。

### `GET /aiPersona.ContentFeed/detail`

请求参数：`persona_id:int`、`work_id:int` 必填。返回 Content 详情。

### `POST /aiPersona.ContentFeed/notInterested`

请求参数：`persona_id:int`、`work_id:int` 必填。标记当前员工作品为不感兴趣；之后该作品不再出现在此员工内容流中。

### `POST /aiPersona.ContentFeed/favorite`

请求参数：`persona_id:int`、`work_id:int`、`value:int` 必填；`value` 为1收藏、0取消收藏。返回 `{work_id:int,is_favorite:int}`。

示例：`{"code":1,"msg":"","data":{"lists":[{"id":321,"persona_id":7,"title":"作品标题","cover":"https://example.com/cover.jpg","views":12000,"praises":800,"platform":"douyin","platform_code":4,"is_favorite":0,"is_disliked":0}],"count":1,"page_no":1,"page_size":20}}`。

错误与边界：作品必须属于当前用户和指定员工，且发布状态为已发布；互动状态按 `user_id + persona_id + work_id` 隔离。本接口的数据源是当前员工自己的已发布作品，不是跨用户或平台全网热门内容。

自检：1) 四个接口路径及方法已列；2) 参数类型和默认值已列；3) 列表、详情、互动返回字段已列；4) JSON 示例完整；5) 所有作品按用户和员工校验；6) 收藏取消和不感兴趣语义已说明；7) 排序和数据来源已说明；8) 分页上限及已发布状态边界已说明。

## B15 AI员工算力消耗明细

### `GET /aiPersona.Consumption/lists`

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | int | 是 | 当前用户 AI员工 ID |
| page_no | int | 否 | 默认1 |
| page_size | int | 否 | 默认20，最大100 |

返回 `{lists:TokenLog[],count:int,page_no:int,page_size:int}`，按流水 ID 倒序。TokenLog 保留算力流水字段，`extra` 解码为对象。仅包含员工分析、员工报告、员工发布文案三类流水，并且流水 `extra.persona_id` 与请求员工 ID 一致。

报告与发布文案生成会写入 `persona_id`；员工分析接口只有在调用方提供已归属当前用户的 `persona_id` 时才关联员工。无员工归属信息的历史流水不会猜测归属，因此不会出现在此明细中。

示例：`{"code":1,"msg":"","data":{"lists":[{"id":9001,"change_type":10207,"action":1,"change_amount":2,"left_tokens":38,"status":1,"remark":"AI员工发布文案生成减少算力","extra":{"persona_id":7,"实际消耗算力":2},"create_time":1790216400}],"count":1,"page_no":1,"page_size":20}}`。

错误与边界：员工按当前用户校验；仅统计 `10314`、`10315`、`10207` 三种算力类型；历史未记录 `persona_id` 的流水不归因；分页大小最大100。

自检：1) 路径、方法和参数已列；2) 默认值和分页边界已列；3) 返回字段及 extra 解码已列；4) JSON 示例完整；5) 员工归属错误已说明；6) 流水类型范围已列；7) 历史归因限制已说明；8) 新流水 persona_id 写入策略已说明。

## AI员工详情完善度聚合

### `GET /aiPersona.aiPersona/setupProgress`

请求参数：`persona_id:int` 必填且大于0。仅允许读取当前用户拥有且未删除的 AI员工。

返回字段：

| 字段 | 类型 | 口径 |
| --- | --- | --- |
| keyword_count | int | 该员工获客词与截流词数组中的非空词条数之和；不统计评论/私信话术 |
| material_count | int | 该员工启用且未删除、发布模式1、素材类型1/2的素材数 |
| direct_material_count | int | 该员工启用且未删除、发布模式2、素材类型1/2的素材数 |
| avatar_count | int | 员工已关联且未删除，公共形象状态为2、对应闪剪形象状态为6的形象数 |
| voice_count | int | 员工已关联且未删除，并且当前用户的 `human_voice` 记录为闪剪版本8、状态1的音色数 |
| music_count | int | 该员工启用且未删除、`ai_persona_material.material_type=3` 的音乐数 |
| copywriting_count | int | 该员工文案库中未删除的记录数 |
| device_count | int | 当前用户绑定到该员工的设备数 |
| account_count | int | 当前用户的平台账号中，设备编号属于该员工已绑定设备的账号数 |
| run_mode | int | 1手机模式；2云端无手机模式。老数据通过 v2.9.53 默认迁移为1 |
| publish_mode | int | 1普通素材自动生成；2指定素材内容 |
| publish_plan_done | int | 至少存在一条当前用户、该员工关联且未删除的发布计划明细时为1，否则为0 |

示例：`{"code":1,"msg":"","data":{"keyword_count":6,"material_count":8,"direct_material_count":1,"avatar_count":1,"voice_count":2,"music_count":1,"copywriting_count":20,"device_count":1,"account_count":2,"run_mode":1,"publish_mode":1,"publish_plan_done":1}}`

错误与边界：`persona_id` 无效时返回参数错误；员工不存在、已删除或不属于当前用户时返回无权/不存在错误。所有计数均由关联表全量聚合，不使用分页列表的 `count`，也不把话术、音乐或其他员工数据混入素材和关键词计数。

必做项由前端按五类合并计算：关键词不少于3；普通模式素材不少于5或指定素材模式不少于1；形象与音色各不少于1；手机模式要求至少绑定设备，云端模式只在普通素材模式下满足运行模式项；发布计划已确认（`publish_plan_done=1`）。七项补充建议由前端按关键词8、形象2、音乐1、账号2、文案20、音色2、素材20计数。服务端只返回原始计数与模式值，不返回百分比。

`POST /aiPersona.aiPersona/update` 接受 `run_mode:int`，只允许1或2。`POST /aiPersona.material/add` 接受 `material_type=3` 作为员工背景音乐，必须提供 `persona_id` 并由登录用户归属校验；音乐缩略图可不提供。v2.9.53 需在启用 `run_mode` 写入前执行。

自检：1) 方法路径与请求参数已列；2) 请求类型和必填限制已列；3) 十二个返回字段和类型已列；4) 成功 JSON 示例完整；5) 参数错误和员工权限边界已列；6) 每项计数的数据表与状态口径已列；7) 五项必做及七项建议门槛、模式值已列；8) run_mode 迁移依赖、素材类型3及非分页聚合边界已说明。

## AI员工直接发布素材来源

`GET /api/aiPersona.materialRule/detail?persona_id=7` 与 `POST /api/aiPersona.materialRule/update` 只持久化取材来源与分组；弹窗中的运行模式、生成类型、文案、模板和封面配置尚不由此接口保存。

更新请求：`{"persona_id":7,"material_source":2,"material_group_id":12}`。`material_source` 仅允许 `1`（显式全部素材）或 `2`（指定分组）；来源为2时必须传当前用户、该员工下未删除的分组，允许该组当前视频数为0。来源为1时 `material_group_id` 保存为 `NULL`。

查询响应示例：`{"persona_id":7,"material_source":2,"material_group_id":12,"material_group_name":"A组","valid":true,"available_video_count":2,"required_video_count":2,"supported_fields":["material_source","material_group_id"]}`。素材组列表保留原 `material_count`，新增 `available_video_count`。

当前直接发布候选条件为同一用户和员工、`group_id` 与配置一致（指定组时）、视频类型1、启用状态1、未软删除、`publish_mode=2`、`file_url` 非空，并且该设备对素材的成功创建任务占用记录少于3次。旧 Redis 计数没有 TTL，故此处按设备与素材累计上限3次；文件地址非空只验证数据库字段，不代表远端文件可访问。至少需要2份符合额度条件的候选视频；普通视频发布和朋友圈发布均适用。任务流每个节点只抽取1份，并让节点内平台共用；不同节点分别抽取。固定排期保留每轮抽取2份的旧行为。

额度按成功创建业务发布任务计占用，任务创建回滚时占用记录一起回滚；这不表示设备执行成功或平台发布成功。真实发布成功回执与来源素材的可靠关联当前未确认，因此不以成功回执统计。

旧 Redis 累计值和历史 `task_id=0` 使用日志无法可靠还原“设备 + 素材 + 已成功创建任务”的占用关系，因此不回填到新额度；上线后从新占用记录开始统计。任务快照使用独立的 `material_source_id` / `material_group_id` 字段；设备协议中的 `material_id` 仍保持发布明细 ID 语义。

任务流就绪检查中，非旧流程必须选择指定分组；旧任务流通过迁移标记保留既有全部素材兼容。分组未选择、分组失效、可用候选不足分别返回 `MATERIAL_GROUP_NOT_SELECTED`、`MATERIAL_GROUP_NOT_FOUND`、`MATERIAL_GROUP_VIDEO_INSUFFICIENT`；非直接发布模式单独返回 `PUBLISH_MODE_NOT_DIRECT`。素材原因项包含 `flow_id`、`node_id`、`material_group_id`、`material_group_name`、`current_count`、`required_count`。

### 迁移执行

代码发布前在实际后端数据库执行 `public/update/v2.9.64_ai_persona_material_rule.sql`，不要依赖 `deploy.sh`。在部署工作目录可用 MySQL 客户端执行：

```bash
mysql --default-character-set=utf8mb4 -h "$DB_HOST" -u "$DB_USER" -p "$DB_NAME" < public/update/v2.9.64_ai_persona_material_rule.sql
```

先备份数据库；迁移脚本会打印迁移前后的表结构并可重复执行。`DB_HOST`、`DB_USER`、`DB_NAME` 和实际后端发版命令由部署环境提供；当前仓库文档未确认生产发布机的代码同步命令。迁移成功后再部署 PHP 代码，并确认 `ai_persona.material_source` 旧员工值为1、后续新建员工保持NULL，`legacy_material_compat` 仅迁移前任务流为1。
