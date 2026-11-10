"""工作流与 Agent 的自动编排：规则 / 模型双模式，产物必须过现有校验器。

边界
- 工具只能来自服务器已登记的白名单；AI 不能新增工具、MCP 服务或修改配置。
- 代码工作区只能引用管理员登记的根目录，不能填绝对路径。
- 自动创建的 Agent 只是 agent_profile 数据记录，不改服务器配置。
- 模型输出先解析、再逐条校验，非法即拒绝；不自动重试、不落库。
- 草稿无状态返回；修订只产生新草稿与结构差异，确认后才保存。
"""
from __future__ import annotations

import json

from rag_tech_retriever.common.provider import ProviderError, post_chat
from rag_tech_retriever.domains.automation import validate_agent
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.domains.workflow_graph import validate_graph_workflow
from rag_tech_retriever.platform.agent_capabilities import BUILTINS
from rag_tech_retriever.platform.code_workspace import TOOL_NAMES as CODE_TOOLS

CONFIRMATION = "生成工作流并直接运行"
MAX_AGENTS = 8
TEMPLATES = {"generic", "code"}
AGENT_FIELDS = {"key", "title", "system_prompt", "tools", "workspace", "scopes"}
WORKSPACE_FIELDS = {"root", "write", "shell"}

SYSTEM_PROMPT = (
    "你是多 Agent 工作流编排器。只返回一个 JSON 对象，不要代码块、解释或前后缀。"
    '格式：{"agents":[{"key":"planner","title":"需求拆解","system_prompt":"角色指令",'
    '"tools":["knowledge_search"],"workspace":{"root":"","write":"each","shell":false}}],'
    '"workflow":{"title":"...","nodes":[{"id":"input","type":"input"},'
    '{"id":"plan","type":"agent","agent":"planner","query":"..."}],'
    '"edges":[["input","plan"],["plan","merge"]],"max_parallel":1}}。'
    "节点 type 只能用 input/retrieve/tool/agent/merge/approval；agent 节点用 agent 字段引用 agents 的 key。"
    "模板里引用上游正文用 {{nodes.<节点id>.answer}}，引用任务输入用 {{input.goal}}，不要自造 output 字段。"
    "必须恰好一个 input、至少一个终止节点、无环、所有节点从 input 可达。"
    "agents 最多 8 个，key 只能用小写字母、数字、下划线或连字符；每个 Agent 的 system_prompt 要写清职责与交付物。"
    "只使用白名单里的工具名；代码工具由 workspace 绑定自动授予，不要写进 tools。"
    "workspace.root 只能填给定的工作区标识或空字符串。不要输出 URL、密钥或任何配置字段。"
)

TEMPLATE_HINTS = {
    "generic": "这是一次通用任务编排：优先拆成分析、产出、校验三段，产出节点要写明交付物。",
    "code": "这是一次代码改动任务：需要规划、实现、验证三段，实现者需要有代码工作区权限，"
            "验证者要核对差异与测试结果，不要在规划阶段编造未读过的代码。",
}


class WorkflowComposer:
    """生成并保存 Agent 配置与 DAG；不负责执行，执行仍走既有 workflow run 端点。"""

    def __init__(self, store, capabilities, connection=None) -> None:
        self.store = store
        self.capabilities = capabilities
        self.connection = connection

    def catalog(self) -> list[str]:
        """已登记工具白名单：内置 + 管理员登记的 HTTP 工具。"""
        names = set(BUILTINS)
        names.update(getattr(getattr(self.capabilities, "http", None), "tools", {}) or {})
        return sorted(names)

    def workspaces(self) -> list[dict]:
        getter = getattr(self.capabilities, "code_roots", None)
        return getter() if callable(getter) else []

    def _writable_root(self) -> str:
        return next((row["name"] for row in self.workspaces() if row.get("writable")), "")

    def rules_draft(self, goal: str, template: str = "generic") -> dict:
        """确定性拆解：不调用模型，本地可完整验证。"""
        title = text(goal, "目标", 160, True)
        if template == "code" and self._writable_root():
            root = self._writable_root()
            agents = [
                {"key": "planner", "title": "改动规划", "tools": ["knowledge_search"],
                 "system_prompt": "把目标拆成可执行的改动清单：涉及文件、改动点、验收方式；"
                                  "没读过的代码不要编造，先说明需要确认的信息。"},
                {"key": "coder", "title": "代码实现",
                 "workspace": {"root": root, "write": "run"},
                 "system_prompt": "按改动清单读代码并落地修改；每次写入前先读当前内容，"
                                  "改完报告差异、备份位置与未完成项。"},
                {"key": "reviewer", "title": "差异审查",
                 "workspace": {"root": root, "write": "each"},
                 "system_prompt": "只读复核改动：检查是否符合目标、是否引入回归、是否遗漏测试；"
                                  "给出通过或需修改的结论。"},
            ]
            nodes = [
                {"id": "input", "type": "input"},
                {"id": "plan", "type": "agent", "agent": "planner",
                 "query": "拆解改动清单：{{input.goal}}"},
                {"id": "code", "type": "agent", "agent": "coder",
                 "query": "按清单实施：{{nodes.plan.answer}}"},
                {"id": "review", "type": "agent", "agent": "reviewer",
                 "query": "复核以下改动是否达成目标：{{nodes.code.answer}}"},
                {"id": "merge", "type": "merge", "strategy": "concat"},
            ]
            edges = [["input", "plan"], ["plan", "code"], ["code", "review"], ["review", "merge"]]
        else:
            agents = [
                {"key": "planner", "title": "任务规划", "tools": ["knowledge_search"],
                 "system_prompt": "把目标拆成有序步骤，每步写明交付物与验收标准；只基于给定资料。"},
                {"key": "producer", "title": "任务执行", "tools": ["knowledge_search"],
                 "system_prompt": "按规划产出正文，逐条对应验收标准；不编造事实，缺口要写明。"},
            ]
            nodes = [
                {"id": "input", "type": "input"},
                {"id": "plan", "type": "agent", "agent": "planner",
                 "query": "拆解任务：{{input.goal}}"},
                {"id": "produce", "type": "agent", "agent": "producer",
                 "query": "按规划产出结果：{{nodes.plan.answer}}"},
                {"id": "merge", "type": "merge", "strategy": "concat"},
            ]
            edges = [["input", "plan"], ["plan", "produce"], ["produce", "merge"]]
        return {"mode": "rules", "template": template,
                "agents": agents,
                "workflow": {"title": title, "kind": "graph", "nodes": nodes, "edges": edges,
                             "max_parallel": 1, "max_retries": 1, "node_timeout_seconds": 60}}

    def _normalize_agents(self, raw: object) -> list[dict]:
        """模型给的 agents 数组逐条过白名单与既有权限校验。"""
        if not isinstance(raw, list) or not 1 <= len(raw) <= MAX_AGENTS:
            raise DomainError(f"agents 必须是 1–{MAX_AGENTS} 个对象的数组")
        catalog = set(self.catalog())
        roots = {row["name"]: row for row in self.workspaces()}
        agents, keys = [], set()
        for index, item in enumerate(raw):
            if not isinstance(item, dict) or set(item) - AGENT_FIELDS:
                raise DomainError(f"第 {index + 1} 个 Agent 包含无效字段")
            key = item.get("key")
            if not isinstance(key, str) or key in keys:
                raise DomainError("Agent key 缺失或重复")
            keys.add(key)
            tools = item.get("tools", [])
            if not isinstance(tools, list) or any(name not in catalog for name in tools):
                raise DomainError(f"Agent {key} 选择了未登记的工具")
            if set(tools) & CODE_TOOLS:
                raise DomainError("代码工具由工作区绑定授予，不能写进 tools")
            workspace = item.get("workspace") or {}
            if not isinstance(workspace, dict) or set(workspace) - WORKSPACE_FIELDS:
                raise DomainError(f"Agent {key} 的工作区配置字段无效")
            root = workspace.get("root", "")
            if root:
                if root not in roots:
                    raise DomainError(f"Agent {key} 引用了未登记的工作区")
                if not roots[root]["writable"] and workspace.get("write") == "run":
                    raise DomainError(f"Agent {key} 的工作区只读")
            profile = validate_agent({
                "title": item.get("title") or key,
                "system_prompt": item.get("system_prompt", ""),
                "scopes": item.get("scopes") or ["personal", "docs", "planning"],
                "mode": "text",
                "generate": True,
                "tool_ids": tools,
                "workspace": {"root": root,
                              "write": workspace.get("write", "each"),
                              "shell": bool(workspace.get("shell", False))},
            })
            agents.append({"key": key, "profile": self.capabilities.validate_binding(profile)})
        return agents

    def _normalize_workflow(self, raw: dict, keys: list[str]) -> dict:
        if not isinstance(raw, dict):
            raise DomainError("模型输出缺少工作流")
        nodes = raw.get("nodes")
        if not isinstance(nodes, list):
            raise DomainError("工作流缺少节点")
        clean, mapping = [], {}
        for node in nodes:
            if not isinstance(node, dict):
                raise DomainError("工作流节点格式错误")
            item = {key: value for key, value in node.items() if key not in {"agent", "role", "agent_id"}}
            target = node.get("agent") or node.get("role")
            if item.get("type") == "agent":
                if target not in keys:
                    raise DomainError("Agent 节点引用了不存在的 Agent")
                mapping[item.get("id")] = target
                item["agent_id"] = "draft-" + str(target)
            elif target is not None:
                raise DomainError("只有 Agent 节点可以引用 Agent")
            clean.append(item)
        workflow = validate_graph_workflow({**raw, "nodes": clean})
        return {"workflow": workflow, "mapping": mapping}

    def model_draft(self, goal: str, post=None, template: str = "generic") -> dict:
        config = self.connection.load() if self.connection else {}
        if not (config.get("api_key") and config.get("base_url") and config.get("model")):
            raise ProviderError("尚未配置模型连接，未发起请求")
        roots = [row["name"] for row in self.workspaces()]
        system = (SYSTEM_PROMPT + " 工具白名单：" + ", ".join(self.catalog())
                  + " 可用工作区：" + (", ".join(roots) if roots else "无")
                  + " 编排要求：" + TEMPLATE_HINTS[template])
        body = {"model": config["model"],
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": text(goal, "目标", 1000, True)}],
                "temperature": 0, "max_tokens": 2000}
        return self._parse_reply((post or post_chat)(config, body, timeout=60, max_chars=24000))

    def _parse_reply(self, reply: dict) -> dict:
        choices = reply.get("choices") or []
        message = choices[0].get("message") if choices and isinstance(choices[0], dict) else {}
        content = (message or {}).get("content") if isinstance(message, dict) else ""
        if not isinstance(content, str) or not content.strip():
            raise DomainError("模型未返回可解析的编排结果")
        try:
            raw = json.loads(content.strip())
        except (ValueError, TypeError) as exc:
            raise DomainError("模型输出不是合法 JSON") from exc
        if not isinstance(raw, dict) or not isinstance(raw.get("workflow"), dict):
            raise DomainError("模型输出缺少工作流")
        return raw

    def _materialize(self, raw: dict, mode: str, template: str) -> dict:
        """统一收口：Agent 数组与 DAG 都过一遍校验器，规则与模型产物走同一条路。"""
        agents = self._normalize_agents(raw.get("agents"))
        normalized = self._normalize_workflow(raw["workflow"], [item["key"] for item in agents])
        return {"mode": mode, "template": template, "agents": agents,
                "workflow": normalized["workflow"], "mapping": normalized["mapping"]}

    def build_draft(self, goal: str, mode: str = "rules", post=None,
                    template: str = "generic") -> dict:
        if mode not in {"rules", "model"}:
            raise DomainError("编排模式只支持 rules / model")
        if template not in TEMPLATES:
            raise DomainError("编排模板只支持 generic / code")
        if mode == "rules":
            return self._materialize(self.rules_draft(goal, template), "rules", template)
        return self._materialize(self.model_draft(goal, post, template), "model", template)

    @staticmethod
    def diff(before: dict, after: dict) -> dict:
        """结构差异：只比对可审阅字段，供界面并排展示。"""
        def nodes_of(draft):
            return {node["id"]: node for node in draft["workflow"]["nodes"]}

        def agents_of(draft):
            return {item["key"]: item["profile"] for item in draft["agents"]}

        def edge_set(draft):
            return {tuple(edge) for edge in draft["workflow"]["edges"]}

        old_nodes, new_nodes = nodes_of(before), nodes_of(after)
        old_agents, new_agents = agents_of(before), agents_of(after)
        changed_nodes = sorted(key for key in old_nodes.keys() & new_nodes.keys()
                               if old_nodes[key] != new_nodes[key])
        changed_agents = sorted(key for key in old_agents.keys() & new_agents.keys()
                                if old_agents[key] != new_agents[key])
        return {
            "title": {"before": before["workflow"].get("title", ""),
                      "after": after["workflow"].get("title", "")},
            "nodes_added": sorted(new_nodes.keys() - old_nodes.keys()),
            "nodes_removed": sorted(old_nodes.keys() - new_nodes.keys()),
            "nodes_changed": changed_nodes,
            "edges_added": sorted([list(edge) for edge in edge_set(after) - edge_set(before)]),
            "edges_removed": sorted([list(edge) for edge in edge_set(before) - edge_set(after)]),
            "agents_added": sorted(new_agents.keys() - old_agents.keys()),
            "agents_removed": sorted(old_agents.keys() - new_agents.keys()),
            "agents_changed": changed_agents,
        }

    def revise(self, draft: dict, feedback: str, post=None) -> dict:
        """按意见重出草稿；返回新草稿与结构差异，不落库。"""
        current = self._validated_draft(draft)
        note = text(feedback, "修改意见", 2000, True)
        config = self.connection.load() if self.connection else {}
        if not (config.get("api_key") and config.get("base_url") and config.get("model")):
            raise ProviderError("尚未配置模型连接，未发起请求")
        roots = [row["name"] for row in self.workspaces()]
        system = (SYSTEM_PROMPT + " 工具白名单：" + ", ".join(self.catalog())
                  + " 可用工作区：" + (", ".join(roots) if roots else "无")
                  + " 现在给你一份已有草稿和修改意见：保留未提及的部分，只改需要改的，仍然只返回完整 JSON。")
        body = {"model": config["model"], "temperature": 0,
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": "已有草稿："
                     + json.dumps(self._portable(current), ensure_ascii=False)},
                    {"role": "user", "content": "修改意见：" + note},
                ], "max_tokens": 2500}
        raw = self._parse_reply((post or post_chat)(config, body, timeout=60, max_chars=26000))
        revised = self._materialize(raw, "model", current["template"])
        return {"draft": revised, "changes": self.diff(current, revised)}

    @staticmethod
    def _portable(draft: dict) -> dict:
        """回传给模型时只给可编辑字段，不回传 agent_id 与内部占位。"""
        return {
            "agents": [{"key": item["key"],
                        "title": item["profile"]["title"],
                        "system_prompt": item["profile"]["system_prompt"],
                        "tools": item["profile"]["tool_ids"],
                        "workspace": item["profile"]["workspace"]} for item in draft["agents"]],
            "workflow": {"title": draft["workflow"]["title"],
                         "nodes": [{"id": node["id"], "type": node["type"],
                                    **({"agent": draft["mapping"].get(node["id"])}
                                       if node["type"] == "agent" else {}),
                                    **{key: node[key] for key in ("query", "strategy", "message",
                                                                  "tool_id", "arguments", "limit")
                                       if key in node}} for node in draft["workflow"]["nodes"]],
                         "edges": draft["workflow"]["edges"],
                         "max_parallel": draft["workflow"]["max_parallel"],
                         "join_policy": draft["workflow"]["join_policy"]},
        }

    def _validated_draft(self, draft: object) -> dict:
        """客户端回传的草稿一律重新校验，权限不能靠前端声称。"""
        if not isinstance(draft, dict):
            raise DomainError("草稿格式不正确")
        raw_agents = draft.get("agents")
        if not isinstance(raw_agents, list) or not raw_agents:
            raise DomainError("草稿缺少 Agent")
        agents = []
        for item in raw_agents:
            if not isinstance(item, dict) or not isinstance(item.get("key"), str):
                raise DomainError("草稿 Agent 格式不正确")
            profile = item.get("profile") if isinstance(item.get("profile"), dict) else item
            agents.append({"key": item["key"],
                           "profile": self.capabilities.validate_binding(validate_agent(profile))})
        keys = [item["key"] for item in agents]
        workflow = draft.get("workflow")
        if not isinstance(workflow, dict):
            raise DomainError("草稿缺少工作流")
        nodes, mapping = [], {}
        for node in workflow.get("nodes") or []:
            if not isinstance(node, dict):
                raise DomainError("草稿节点格式不正确")
            item = {key: value for key, value in node.items() if key not in {"agent", "role"}}
            if item.get("type") == "agent":
                mapping_hint = draft.get("mapping") if isinstance(draft.get("mapping"), dict) else {}
                target = node.get("agent") or mapping_hint.get(item.get("id"))
                if target not in keys:
                    raise DomainError("草稿 Agent 引用不一致")
                mapping[item["id"]] = target
                item["agent_id"] = "draft-" + str(target)
            nodes.append(item)
        clean = validate_graph_workflow({**workflow, "nodes": nodes})
        return {"mode": draft.get("mode", "model"),
                "template": draft.get("template") if draft.get("template") in TEMPLATES else "generic",
                "agents": agents, "workflow": clean, "mapping": mapping}

    def save(self, draft: dict) -> dict:
        """落库 Agent 与工作流；节点里的 Agent 引用替换为真实 ID。"""
        current = self._validated_draft(draft)
        saved = {}
        for item in current["agents"]:
            row = self.store.save("agent_profile", item["profile"])
            saved[item["key"]] = row["id"]
        default_id = next(iter(saved.values()))
        nodes = []
        for node in current["workflow"]["nodes"]:
            item = dict(node)
            if item.get("type") in {"agent", "retrieve", "tool"}:
                key = current["mapping"].get(item["id"])
                item["agent_id"] = saved.get(key, default_id)
            nodes.append(item)
        workflow = self.store.save("workflow", {**current["workflow"], "nodes": nodes})
        return {"mode": current["mode"], "agent_ids": list(saved.values()),
                "agents": [{"key": key, "id": value} for key, value in saved.items()],
                "workflow_id": workflow["id"], "version": workflow["version"],
                "title": current["workflow"]["title"]}
