# 量化成果清单（简历 / 汇报用）

> 由 scripts/record_metric.py 导出；数据源 output/metrics_ledger.jsonl，改动账本后请重新导出，勿手改本文件。
> 口径说明：括号内先给绝对差（百分数指标为 pp 百分点），再给相对提升百分比。


## tech_doc · V0

- 【语料切片基线】主语料切片数：237条；样本：14 份真实文档。结论：基于 14 份真实业务协议文档自建 237 条评测语料库（标题层级切片 + 1500 字符兜底）（来源：output/v0/v0_ingest_stats.json）
- 【V0 评测题集】评测题数：10道；样本：11 个 must_retrieve 锚点。结论：自建 10 道客观评测题（11 个 must_retrieve 锚点，判定不依赖主观）（来源：data/processed/eval_questions.json）

## tech_doc · V1

- 【query instruction 前缀对照】top-5 召回率：90% → 80%（-10pp，相对 -11.11%）；变量：query 是否加 instruction 前缀（向量库与评测集不变）；样本：10 道评测题（237 条语料）。结论：加前缀后 top-5 召回率 -10.0pp；与 bge v1.5「指令无关训练」口径一致（原「必须加前缀」说法针对 v1/英文模型）；n=10 小样本，待扩展复核（来源：output/v1/v1_baseline_report.md）
- 【纯向量检索干净基线】top-5 召回率：90%；变量：query 采用「直接编码」（V1 基线口径）；样本：10 道评测题（237 条语料）。结论：V1 干净基线，作为 V1.5 单变量优化的对比起点（来源：output/v1/v1_baseline_report.md）

## tech_doc · V1.5

- 【重排优化（bge-reranker）】top-5 召回率：90% → 100%（+10pp，相对 +11.11%）；变量：向量候选池 top-20 后接入 bge-reranker-base CrossEncoder 重排（其余与 V1 基线完全一致）；样本：10 道评测题（237 条语料）。结论：重排后 top-5 召回率 90.0%→100.0%（+10.0pp），救回 Q08；n=10 小样本，待扩展复核（来源：output/v1.5/v15_optimize_report.md）
