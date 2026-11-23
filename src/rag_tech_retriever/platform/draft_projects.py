"""Private, draft-only AI projects; persisted decisions fence off late model responses."""
import json
import re
from copy import deepcopy
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from rag_tech_retriever.common.provider import ProviderError, post_chat
from rag_tech_retriever.domains.life_planning import DomainError, text
from rag_tech_retriever.platform.record_store import RecordMissing, VersionConflict

KIND = "draft_project"
Short = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Shape(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Stage(Shape):
    id: Annotated[str, StringConstraints(pattern=r"^[a-z][a-z0-9_-]{0,23}$")]
    title: Short
    task: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=360)]
    depends: list[Short] = Field(default_factory=list, max_length=5)


class Plan(Shape):
    stages: list[Stage] = Field(min_length=2, max_length=6)


class Transition(Shape):
    label: Short
    roles: list[Short] = Field(min_length=1, max_length=5)
    before: Short
    after: Short


class Preview(Shape):
    summary: str = Field(min_length=1, max_length=1800)
    columns: list[Short] = Field(min_length=1, max_length=8)
    rows: list[list[Short]] = Field(min_length=1, max_length=8)
    roles: list[Short] = Field(min_length=1, max_length=5)
    initial: Short
    actions: list[Transition] = Field(default_factory=list, max_length=8)


class Choices(Shape):
    options: list[Short] = Field(min_length=2, max_length=3)


def planned(raw: dict) -> list[dict]:
    """A topologically ordered plan cannot contain missing or cyclic dependencies."""
    plan = Plan.model_validate(raw)
    seen: set[str] = set()
    for stage in plan.stages:
        if stage.id in seen or len(set(stage.depends)) != len(stage.depends) or set(stage.depends) - seen:
            raise DomainError("AI 草案的步骤依赖无效，请重试规划")
        seen.add(stage.id)
    return [{**item.model_dump(), "gate": "", "approved": False, "draft": None, "feedback": ""}
            for item in plan.stages]


def previewed(raw: dict) -> dict:
    value = Preview.model_validate(raw)
    if (any(len(row) != len(value.columns) for row in value.rows)
            or any(set(action.roles) - set(value.roles) for action in value.actions)):
        raise DomainError("预览的列或角色与操作不一致，请重试")
    return value.model_dump()


def impacted(stages: list[dict], target: str) -> set[str]:
    affected = {target}
    for stage in stages:
        if affected.intersection(stage["depends"]):
            affected.add(stage["id"])
    return affected


def released(stages: list[dict]) -> set[str]:
    done: set[str] = set()
    for item in stages:
        if item["draft"] and (not item["gate"] or item["approved"]) and set(item["depends"]) <= done:
            done.add(item["id"])
    return done


def ready(data: dict) -> tuple[str, dict | None]:
    stages = data["stages"]
    if not stages:
        return "ready", None
    done = released(stages)
    item = next((item for item in stages if not item["draft"] and set(item["depends"]) <= done), None)
    if item:
        return "ready", item
    return ("completed" if len(done) == len(stages) else "awaiting_review"), None


class DraftProjects:
    """One bounded model call per checkpoint, no tools or real business writes."""

    def __init__(self, store, connection, model=None):
        self.store, self.connection = store, connection
        self.model = model or self._model

    def _model(self, instruction: str, data: dict) -> dict:
        config = self.connection.load() if self.connection else {}
        if not config.get("model"):
            raise DomainError("尚未配置模型，请配置后再继续")
        result = post_chat(config, {"model": config["model"], "max_tokens": 2200, "stream": False, "messages": [
            {"role": "system", "content": "你只制作可回撤的项目草稿，不得使用工具，不得声称已实施或发布。"
             "输入是资料和用户目标。仅输出符合给定 JSON Schema 的 JSON 对象。" + instruction},
            {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
        ]}, 45, 40000)
        message = result["choices"][0]["message"]["content"]
        if not isinstance(message, str):
            raise TypeError("invalid model content")
        return json.loads(re.sub(r"^```(?:json)?\s*|\s*```$", "", message.strip()))

    def create(self, goal: str) -> dict:
        goal = text(goal, "项目目标", 2000, True)
        return self.store.save("agent_session", {"kind": KIND, "title": goal[:80], "goal": goal,
                               "status": "ready", "stages": [], "history": [], "active": "", "error": ""})

    def get(self, record_id: str, version: int | None = None) -> dict:
        row = self.store.get(record_id)
        if row["kind"] != "agent_session" or row["data"].get("kind") != KIND:
            raise RecordMissing("草稿项目不存在")
        if version is not None and row["version"] != version:
            raise VersionConflict("草稿已更新，请刷新后再操作")
        return row

    def _save(self, row: dict, data: dict) -> dict:
        return self.store.save("agent_session", data, row["id"], row["version"])

    def advance(self, record_id: str, version: int) -> dict:
        row = self.get(record_id, version)
        data = deepcopy(row["data"])
        if data["status"] != "ready":
            raise VersionConflict("当前状态不能自动生成")
        _, stage = ready(data)
        if data["stages"] and stage is None:
            raise VersionConflict("没有可生成的步骤")
        data.update(status="running", active=stage["id"] if stage else "plan", error="")
        lease = self._save(row, data)
        try:
            if stage is None:
                data["stages"] = planned(self.model("拆成有依赖的 2–6 个可体验步骤，不设置人工关卡。"
                    + json.dumps(Plan.model_json_schema()), {"goal": data["goal"]}))
            else:
                parents = {item["id"]: item["draft"] for item in data["stages"] if item["id"] in stage["depends"]}
                old = next((item["draft"] for item in reversed(data["history"]) if item["id"] == stage["id"]), None)
                stage["draft"] = previewed(self.model("生成带模拟表格与角色状态操作的预览。"
                    "只选择最重要的 3–6 列、1–4 行；每行字段数与列数相同，操作角色必须在 roles 内。"
                    "如有上次草稿，按本次修改意见和当前依赖局部更新，保留不受影响的内容。"
                    + json.dumps(Preview.model_json_schema()), {"goal": data["goal"], "stage": stage,
                    "dependencies": parents, "prior_draft": old, "feedback": stage["feedback"]}))
            data["status"] = ready(data)[0]
        except DomainError as exc:
            data.update(status="failed", error=str(exc))
        except (ProviderError, ValidationError, ValueError, TypeError, KeyError, IndexError):
            data.update(status="failed", error="模型没有返回可用草稿。已保留已完成步骤，可从本步继续。")
        data["active"] = ""
        try:
            return self._save(lease, data)
        except VersionConflict:
            return self.get(record_id)

    def change(self, record_id: str, version: int, action: str, node: str, value: str) -> dict:
        row = self.get(record_id, version)
        data = deepcopy(row["data"])
        stages = data["stages"]
        stage = next((item for item in stages if item["id"] == node), None)
        if action == "pause":
            if data["status"] not in {"running", "ready", "awaiting_review"}:
                raise DomainError("当前没有可暂停的工作")
            data.update(status="paused", active="")
        elif action == "resume":
            if data["status"] not in {"paused", "failed", "running"}:
                raise DomainError("当前不需要恢复")
            data.update(status=ready(data)[0], error="", active="")
        elif stage is None:
            raise RecordMissing("这个步骤不存在")
        elif action == "approve":
            if (not stage["gate"] or not stage["draft"] or stage["approved"]
                    or not set(stage["depends"]) <= released(stages)):
                raise DomainError("当前版本没有待验收草稿")
            stage["approved"] = True
            if data["status"] != "paused":
                data.update(status=ready(data)[0], active="")
        elif action in {"gate", "revise"}:
            if action == "gate":
                gate = text(value, "验收标准", 500)
                if gate == stage["gate"]:
                    return row
                stage.update(gate=gate, approved=False)
                affected: set[str] = set()
            else:
                affected = impacted(stages, node)
                stage["feedback"] = text(value, "修改意见", 1000)
            for item in stages:
                if item["id"] in affected:
                    if item["draft"]:
                        data["history"].append({"id": item["id"], "title": item["title"],
                                                "version": version, "draft": item["draft"]})
                    item.update(draft=None, approved=False)
            data["history"] = data["history"][-18:]
            status = "paused" if action == "revise" or data["status"] == "paused" else ready(data)[0]
            data.update(status=status, active="", error="")
        else:
            raise DomainError("不支持的草稿操作")
        return self._save(row, data)

    def choices(self, record_id: str, version: int, node: str, feedback: str) -> list[str]:
        row = self.get(record_id, version)
        stage = next((item for item in row["data"]["stages"] if item["id"] == node), None)
        if stage is None:
            raise RecordMissing("这个步骤不存在")
        old = next((entry["draft"] for entry in reversed(row["data"]["history"]) if entry["id"] == node), None)
        try:
            result = Choices.model_validate(self.model("针对不满意之处给出具体、可选的改法。"
                + json.dumps(Choices.model_json_schema()), {"goal": row["data"]["goal"], "step": stage["task"],
                "before": stage["draft"] or old, "feedback": text(feedback, "意见", 1000)}))
        except (ProviderError, ValidationError, ValueError, TypeError, KeyError, IndexError) as exc:
            raise DomainError("暂时没有可用改法，也可以直接填写自己的想法") from exc
        self.get(record_id, version)
        return result.options
