# AI员工 24h 自动任务流模板接口

## 范围

系统内置模板保存截图中能确认的排期节点。套用模板会为指定 AI员工新建一个暂停态任务流副本，不会调用外部工作流平台或立即启动设备任务。启用后，已接入的任务类型通过现有业务配置与设备任务生成器排期；评论接管、评论点赞仍为待接入节点。

节点来源为工作流模板预览截图及已提供的逐条转录。存在模板卡片数量与截图明细不一致时，列表的 `node_count` 是可确认明细数，`expected_node_count` 保留卡片/来源预期数，`is_complete=0` 表示不能确认完整。

## 1. 模板列表

**GET** `/aiPersona.TaskFlow/templateLists`

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| category | string | 否 | 分类精确值：`综合`、`偏养号`、`偏获客`、`偏运营`；空或 `0` 表示全部 |
| keyword | string | 否 | 模板名包含检索 |

### 返回字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| lists | array | 模板元数据，不含节点 |
| lists[].code | string | 模板唯一编码 |
| lists[].name | string | 模板名称 |
| lists[].category | string | 分类 |
| lists[].description | string | 模板描述 |
| lists[].is_custom | integer | 是否自定义；内置模板固定为 `0` |
| lists[].is_complete | integer | 已确认的节点明细是否完整 |
| lists[].node_count | integer | 当前可确认节点数 |
| lists[].expected_node_count | integer | 来源显示或预期节点数 |
| lists[].card_node_count | integer/null | 截图模板卡显示的节点数；来源未提供时省略 |
| lists[].source_note | string/null | 数量冲突或转录限制；无备注时省略 |
| count | integer | 列表记录数 |

### 返回示例

```json
{
  "lists": [
    {
      "code": "tpl_internal_lead",
      "name": "内部获客1天一条",
      "category": "偏获客",
      "description": "内部",
      "is_custom": 0,
      "is_complete": 0,
      "node_count": 12,
      "expected_node_count": 15,
      "card_node_count": 15
    }
  ],
  "count": 1
}
```

### 错误与边界

- 未传分类/关键词时返回全部内置模板。
- 分类按精确字符串匹配；不支持模糊匹配分类。
- 关键词为空时不筛选；没有匹配项时返回空列表和 `count=0`。

### 备注

模板元数据来自后端目录 `TaskFlowTemplateCatalog`，不依赖前端本地枚举。`source_note` 仅作核对说明，前端可以不展示。

## 2. 模板详情

**GET** `/aiPersona.TaskFlow/templateDetail`

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| template_code | string | 是 | 模板唯一编码，如 `tpl_internal_lead` |

### 返回字段

返回模板列表的全部元数据，并增加 `nodes`：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| nodes | array | 已转录的节点，按 `sort` 升序 |
| nodes[].sort | integer | 节点顺序，从 1 开始 |
| nodes[].task_type | string | 任务类型展示名 |
| nodes[].start_time | string | 开始时间，`HH:mm` |
| nodes[].end_time | string/null | 结束时间；来源未提供时为 null |
| nodes[].platforms | integer[] | 平台枚举：微信 1、小红书 3、抖音 4、快手 5 |
| nodes[].config | object | 当前为空对象；业务参数沿用 AI员工已有配置 |
| nodes[].config_complete | integer | 已映射现有调度器的任务类型为1；评论接管、评论点赞等待接入类型为0 |

### 返回示例

```json
{
  "code": "tpl_internal_lead",
  "name": "内部获客1天一条",
  "category": "偏获客",
  "description": "内部",
  "is_custom": 0,
  "is_complete": 0,
  "node_count": 12,
  "expected_node_count": 15,
  "nodes": [
    { "sort": 7, "task_type": "留痕获客", "start_time": "12:20", "end_time": "12:50", "platforms": [4], "config": {}, "config_complete": 1 }
  ]
}
```

### 错误与边界

- `template_code` 不存在时返回“工作流模板不存在”。
- 明细不完整的模板仅返回已确认节点；不会用卡片数量生成占位节点。

### 备注

字段 `platforms` 使用项目现有平台枚举值。可执行节点通过既有 AI员工业务配置生成设备任务；暂定新增节点不生成设备任务。

## 3. 套用模板

**POST** `/aiPersona.TaskFlow/applyTemplate`

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| persona_id | integer | 是 | 当前用户拥有的 AI员工 ID |
| template_code | string | 是 | 模板唯一编码 |

### 返回字段

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| flow_id | integer | 新建任务流 ID |
| template_code | string | 来源模板编码 |
| node_count | integer | 克隆的已确认节点数 |
| expected_node_count | integer | 模板预期节点数 |
| is_complete | integer | 来源节点明细完整性 |
| flow | object | 新建任务流详情，含 `nodes`、`tasks`、`template_code` |

### 返回示例

```json
{
  "flow_id": 321,
  "template_code": "tpl_internal_lead",
  "node_count": 12,
  "expected_node_count": 15,
  "is_complete": 0,
  "flow": {
    "id": 321,
    "persona_id": 7,
    "name": "内部获客1天一条",
    "status": 0,
    "template_code": "tpl_internal_lead",
    "tasks": [],
    "nodes": []
  }
}
```

### 错误与边界

- AI员工不存在或不属于当前用户时返回“AI员工不存在或无权操作”。
- 模板编码无效时返回“工作流模板不存在”。
- 套用每次新建独立任务流，不覆盖已有任务流。
- 新建任务流状态为 `0`（暂停）；节点业务参数继续使用 AI员工已有配置。
- 数据库写入在一个事务内完成；写入异常时回滚任务流与节点。

### 备注

本接口仅克隆任务流和静态排期节点，不绑定发布计划，不触发设备命令，也不接入 Coze 或其他工作流编排服务。启用并由常驻任务生成器扫描后，任务会按节点时间生成。

## 4. 保存排期节点

**POST** `/aiPersona.TaskFlow/saveNodes`

### 请求参数

| 字段 | 类型 | 必填 | 说明 |
| --- | --- | --- | --- |
| id | integer | 是 | 当前用户拥有的任务流 ID |
| nodes | object[] | 是 | 保存后的完整节点数组；未传回的原节点会删除，最多100项 |
| nodes[].id | integer | 否 | 已有节点 ID；新增节点不传或传0 |
| nodes[].task_type | string | 是 | 节点展示名称，1至64字符 |
| nodes[].start_time | string | 是 | `HH:mm`，范围00:00至23:59 |
| nodes[].end_time | string/null | 否 | 空值表示无结束时间；非空时须晚于开始时间 |
| nodes[].platforms | integer[] | 否 | 微信1、小红书3、抖音4、快手5；默认为空数组 |

### 返回字段

返回保存后的任务流详情，与 `/detail` 同结构。节点配置 `config` 由服务端保留；节点是否映射到现有设备任务生成器由服务端计算并返回 `config_complete`。

### 返回示例

```json
{
  "id": 321,
  "status": 0,
  "nodes": [
    { "id": 81, "sort": 1, "task_type": "视频发布", "start_time": "09:00", "end_time": "09:30", "platforms": [4, 1], "config": {}, "config_complete": 1 }
  ]
}
```

### 错误与边界

- 非本用户任务流或节点 ID 不属于该任务流时拒绝保存。
- 节点类型、时间格式/顺序、平台值或节点数不符合约束时返回校验错误。
- 保存会将任务流状态置为 `0`（暂停）；事务失败时回滚节点改动。
- 启用要求任务流至少有一个已接入任务类型，且同一 AI员工不能同时启用多个任务流；待接入节点保留在排期展示中，不映射到其他任务。

### 备注

启用后，任务流节点成为该 AI员工固定时段自动任务的排期来源，并在当天生成一次：视频发布、朋友圈发布、私信接管、自动养号、截流/截流评论及留痕获客复用现有生成器。启用任务流时跳过原固定时段生成；员工已有任务流但处于暂停时不回退到默认固定时段。启停或修改排期时会将当天尚未执行的相关自动任务置为中断，已开始的任务继续执行。未配置过任务流的员工保持原行为。评论接管和视频号评论点赞为暂定需求，当前只保留节点，不创建任务。发布节点仍依赖 AI员工现有素材、账号及业务配置。当天已生成过任务时，调整后的排期从次日生成。

## 文档自检（8 项）

1. 请求方法和完整接口路径已给出。
2. 每个请求参数均列出类型、必填性和含义。
3. 返回字段逐项定义，包含嵌套节点结构。
4. 每个接口均提供 JSON 返回示例。
5. 错误消息与关键边界已列出。
6. 状态值、平台枚举、时间格式和数量口径已说明。
7. 用户数据归属与套用的事务边界已说明。
8. 已映射节点的任务生成路径与暂定未接入节点已明确。
