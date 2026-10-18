"""V0 评测题集生成脚本：10 道基础评测题 + must_retrieve 客观判定锚点。

设计规则（对齐 V0 验收标准「评测题可客观判定」）:
1. 每道题必须绑定 ``must_retrieve``：一个或多个「答案所在 chunk_id」；V1 基线按
   top-5 命中判定——命中任一锚点即视为该题召回成功（不依赖主观判断）。
2. 锚点强校验：必须真实存在于 ``data/processed/corpus.jsonl``；校验失败直接报错退出，
   不产出半成品文件（防止人工改题时写出不存在的 chunk_id）。
3. 题型分布：事实查询 / 状态判断 / 通道机制 / 实现细节 / 易混淆 / 决策记录 / 排障根因 /
   字段口径 / 环境事实 / 行为误解；其中状态判断与易混淆题覆盖真实业务坑（"文档有条目但
   实际未落地"），既是 V1 基线的一部分，也是 V2-b 状态感知的前置对照。
4. 题目与答案均出自真实文档（逐条人工核验），``reference_answer`` 为标准答案要点。

运行（必须使用项目虚拟环境解释器）:
    .venv/Scripts/python.exe scripts/v0_generate_eval.py

输出:
    data/processed/eval_questions.json   评测题集（meta + questions[]）
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CORPUS_PATH = PROJECT_ROOT / "data" / "processed" / "corpus.jsonl"
OUTPUT_PATH = PROJECT_ROOT / "data" / "processed" / "eval_questions.json"


class EvalQuestionError(Exception):
    """评测题与语料不一致时抛出（生成前的强校验失败）。"""


#: 10 道评测题（qid / 题型 / 问题 / 必须命中的锚点 chunk / 标准答案要点）
QUESTIONS: List[Dict[str, object]] = [
    {
        "qid": "Q01",
        "type": "事实查询",
        "question": "微信 RPA 协议里主动加好友命令 wechat.add_friend 的命令号和回执号分别是多少？它的幂等键怎么计算？",
        "must_retrieve": ["RPA微信命令与事件协议v0::011"],
        "reference_answer": "命令 739（TYPE_WECHAT_ADD_FRIEND）、回执 842（TYPE_WECHAT_ADD_FRIEND_RESULT）；"
        "幂等键为 sha256(deviceId+wechatId+targetWechat+source)。",
    },
    {
        "qid": "Q02",
        "type": "状态判断",
        "question": "自动通过好友（wechat.accept_friend=740）目前可以通过 RPA 命令下发吗？现在实际由谁承接？",
        "must_retrieve": ["RPA微信命令与事件协议v0::012"],
        "reference_answer": "不能：740/843 仅保留号段，不创建、不 dispatch、不接入业务副作用；当前由 WeChatPadPro 网关"
        "（Cron + 服务链路）承接，待确认迁往 RPA 时再启用。",
    },
    {
        "qid": "Q03",
        "type": "通道机制",
        "question": "设备端上报 type=55（收到好友消息/私信）时，后端会登记独立的 RPA 事件吗？个微 AI 实时回复走哪条通道？",
        "must_retrieve": ["RPA微信命令与事件协议v0::021"],
        "reference_answer": "不登记独立 RPA 事件；AI 实时回复继续走既有 socket.{deviceId}.message protobuf 通道"
        "（TalkToFriendTask），本节字段仅作客户端上报的参照基准。",
    },
    {
        "qid": "Q04",
        "type": "实现细节",
        "question": "设备端收到 wechat.add_friend 下发命令时，命令号放在信封的哪个字段？业务参数（如 targetWechat）在哪个字段里、怎么取出来？",
        "must_retrieve": ["RPA微信命令与事件协议v0::037"],
        "reference_answer": "type 字段即为命令号（739）；业务参数在 content 字段中，它是 JSON 字符串，需先反序列化再取"
        "wechatId / targetWechat / remark / source。",
    },
    {
        "qid": "Q05",
        "type": "易混淆",
        "question": "WeChatPadPro 的 POST /User/FriendVerification 是「通过好友申请」的接口吗？它实际是做什么的？",
        "must_retrieve": ["微信设备指令通道划分与现状::018"],
        "reference_answer": "不是。它是「加我为朋友时需要验证」的开关接口，与自动通过好友无关，不能拿它当自动通过的实现。",
    },
    {
        "qid": "Q06",
        "type": "决策记录",
        "question": "视频号图文下发张数上限（R2 问题）目前最终的决策是什么？是否已经把上限从 12 改成 9？",
        "must_retrieve": ["视频号发布_后端侧答复::011"],
        "reference_answer": "决策（2026-10-08）：暂不动——不把 12 改成 9；其他平台目前无问题，视频号「实发 9 / 记账 12」"
        "的留痕失真作为已知风险接受。",
    },
    {
        "qid": "Q07",
        "type": "排障根因",
        "question": "个微「AI 接管」为什么会对所有提问固定回复同一句「转接」兜底文案？",
        "must_retrieve": ["微信接管AI回复兜底排查::002", "微信接管AI回复兜底排查::004"],
        "reference_answer": "两处叠加：兜底文案是函数硬编码初值（AI 分支未成功赋值就原样发出）；且无知识库分支调用的是"
        "永远失败（code 恒为 0）的桩函数，AI 调用链本身是断的，提示词从未真正发给大模型。",
    },
    {
        "qid": "Q08",
        "type": "字段口径",
        "question": "AI 员工详情完善度接口（setupProgress）里 keyword_count 的统计口径是什么？",
        "must_retrieve": ["api-ai员工-P1-P3接口契约::032"],
        "reference_answer": "该员工获客词与截流词数组中的非空词条数之和；不统计评论/私信话术。",
    },
    {
        "qid": "Q09",
        "type": "环境事实",
        "question": "服务器环境对齐要求中，composer.lock 锁定的 topthink/framework 版本是多少？",
        "must_retrieve": ["SERVER_CHECKLIST::010"],
        "reference_answer": "^8.0.2（由 composer.lock 锁定）。",
    },
    {
        "qid": "Q10",
        "type": "行为误解",
        "question": "智能会话发送附件时，附件内容会通过 SSE 帧重复回传吗？客户端怎么拿到附件服务端确认后的数据？",
        "must_retrieve": ["智能会话-小程序附件联调协议::004"],
        "reference_answer": "不会在 SSE 帧重复回传；客户端在本次发送期间保留已上传附件，结束后通过历史接口取得服务端确认的数据。",
    },
]


def load_corpus_index(corpus_path: Path) -> Dict[str, str]:
    """读取语料库，返回 {chunk_id: heading_path} 索引。"""
    if not corpus_path.is_file():
        raise EvalQuestionError(f"语料文件不存在：{corpus_path}（请先运行 scripts/ingest_md.py）")
    index: Dict[str, str] = {}
    with corpus_path.open(encoding="utf-8") as fp:
        for line in fp:
            record = json.loads(line)
            index[record["chunk_id"]] = record["heading_path"]
    return index


def validate_questions(questions: List[Dict[str, object]], corpus_index: Dict[str, str]) -> None:
    """强校验：qid 唯一、题目/答案非空、must_retrieve 锚点必须存在于语料库。"""
    seen: set[str] = set()
    for item in questions:
        qid = str(item["qid"])
        if qid in seen:
            raise EvalQuestionError(f"qid 重复：{qid}")
        seen.add(qid)
        if not str(item.get("question", "")).strip():
            raise EvalQuestionError(f"{qid} 缺少 question")
        if not str(item.get("reference_answer", "")).strip():
            raise EvalQuestionError(f"{qid} 缺少 reference_answer")
        anchors = item.get("must_retrieve")
        if not isinstance(anchors, list) or not anchors:
            raise EvalQuestionError(f"{qid} 的 must_retrieve 不能为空")
        for chunk_id in anchors:
            if chunk_id not in corpus_index:
                raise EvalQuestionError(f"{qid} 的锚点不存在于语料库：{chunk_id}")


def build_payload(questions: List[Dict[str, object]], corpus_chunks: int) -> Dict[str, object]:
    """组装评测题集输出结构。"""
    type_counter = Counter(str(item["type"]) for item in questions)
    return {
        "meta": {
            "generated_at": datetime.now().isoformat(timespec="seconds"),
            "source_corpus": CORPUS_PATH.relative_to(PROJECT_ROOT).as_posix(),
            "corpus_chunks": corpus_chunks,
            "total_questions": len(questions),
            "type_distribution": dict(type_counter),
            "judge_rule": "top-5 命中任一 must_retrieve 锚点即视为该题召回成功",
        },
        "questions": questions,
    }


def print_report(questions: List[Dict[str, object]], corpus_index: Dict[str, str]) -> None:
    """打印校验结果与题目清单，便于人工核对可客观判定性。"""
    print("=" * 72)
    print("V0 评测题集生成完成")
    print("=" * 72)

    anchor_total = sum(len(item["must_retrieve"]) for item in questions)  # type: ignore[arg-type]
    print(f"\n=== 1. 校验 ===\n{len(questions)} 道题 / {anchor_total} 个锚点，全部存在于语料库（{len(corpus_index)} 条 chunk）")

    print("\n=== 2. 题目清单（含锚点定位）===")
    for item in questions:
        anchors = item["must_retrieve"]  # type: ignore[assignment]
        print(f"\n[{item['qid']}] {item['type']}：{item['question']}")
        print(f"  标准答案要点：{item['reference_answer']}")
        for chunk_id in anchors:  # type: ignore[union-attr]
            heading = corpus_index[chunk_id]
            print(f"  must_retrieve: {chunk_id}")
            print(f"    锚点标题：{heading[:90]}")

    print("\n=== 3. 题型分布 ===")
    for name, count in Counter(str(item["type"]) for item in questions).items():
        print(f"  {name}：{count} 道")

    print(f"\n  输出：{OUTPUT_PATH}")


def main() -> None:
    """脚本入口：加载语料 → 强校验 → 写出 JSON → 打印报告。"""
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
        except (AttributeError, OSError):
            pass

    corpus_index = load_corpus_index(CORPUS_PATH)
    validate_questions(QUESTIONS, corpus_index)

    payload = build_payload(QUESTIONS, len(corpus_index))
    OUTPUT_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    print_report(QUESTIONS, corpus_index)


if __name__ == "__main__":
    main()