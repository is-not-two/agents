# 交互参考 · 已委托选定

记录日期：2026-10-13。用户要求查找、记录并回传参考网址，采用哪些交互由用户确认。后续用户已授权 agent 选择并实施：采用 B 分段选择、D 分类折叠、E 详情抽屉，结合 A 的按钮层级和 F 的真实变化提示；C 仅借鉴短空间过渡。以下保留调研时的候选说明。

建议先看 B（横向选择）、C（卡片展开）、E（详情面板）。每个页面看中间的演示区即可，下面的代码部分无需阅读。最终可以组合不同站点的细节。

| 编号 | 直接链接 | 点哪里 | 我认为值得借鉴的细节 | 本项目可用位置 | 选择 |
| --- | --- | --- | --- | --- | --- |
| A | [Ant Design 按钮](https://ant.design/components/button-cn/) | 代码演示的 Primary Button；“加载中状态”的 Icon Start | 主次按钮容易辨认；点击反馈短而明确；操作中有加载状态 | 保存、检索、导出 | 已评估，采用范围见页首 |
| B | [Mantine 分段选择](https://mantine.dev/core/segmented-control/) | Usage 区的 React / Angular / Vue；右侧可调整 Size 和 Radius | 白色选中块平滑移动；控件等高、紧凑；支持适当色彩重点 | P0–P4、入口/侧栏模式、局部视图 | 已评估，采用范围见页首 |
| C | [Motion · iOS App Store 展开示例](https://examples.motion.dev/react/app-store) | 点击任意大卡片，再点击卡片外侧关闭 | 卡片向详情连续展开，背景变暗，关闭回到原位置，空间关系清楚 | 工作区入口、知识卡片详情 | 已评估，采用范围见页首 |
| D | [Radix 分类折叠](https://www.radix-ui.com/primitives/docs/components/accordion) | Is it accessible? / Is it unstyled? / Can it be animated? | 标题保持可见；箭头与内容展开同步；收起后分类结构仍清楚 | 规划阶段、知识分组、阶段记录明细 | 已评估，采用范围见页首 |
| E | [Mantine 详情抽屉](https://mantine.dev/core/drawer/) | Usage 区 Open Drawer；Position 区 Right；Esc 关闭 | 从边缘进入详情，原列表位置保留；遮罩帮助聚焦 | 知识原文、任务详情、流程节点设置 | 已评估，采用范围见页首 |
| F | [Radix 完成提示](https://www.radix-ui.com/primitives/docs/components/toast) | Add to calendar | 轻提示及时确认结果，Undo 提供撤销入口；不遮住整个工作区 | 保存完成、可撤销的归档/删除 | 已评估，采用范围见页首 |

## 我的推荐组合

1. B 用于 P0–P4 和模式选择：让当前选择的位置变化看得见。
2. A 用于保存、查询等动作：保留短点击反馈与清楚的忙碌状态。
3. E 用于内容详情：阅读/修改时仍知道自己从哪个列表进入。
4. C 用于少量重要入口或内容卡片：展开更有空间连续感。
5. D 用于阶段/分类分组，F 用于操作结果。这两类以功能需要决定是否采用。

这些是 agent 的主观建议，尚未拍板。用户可以回复“B 的切换 + C 的展开 + A 的按钮”或指出喜欢的具体细节，再进入相应实施阶段。

## 实际核验与限制

- A–F 官方页面均返回正常页面，无需登录即可体验上述演示。
- A 实际点击 Primary Button；Icon Start 点击后捕获 loading 状态。
- B 点击 Angular 对应标签，单选状态改变为选中；已查看选中块移动后的截图。
- C 实际点击卡片，进入 open/overlay 状态；已查看图片与正文完整展开后的截图。
- D 实际展开/收起，aria-expanded 为 false→true→false。
- E 实际打开抽屉并 Esc 关闭；Right 选项直接打开右侧面板，实测宽 440px（1440px 页面）。
- F 实际点击演示按钮，显示提示与 Undo。此为站点演示，不产生真实日历事件。
- Google 搜索页触发验证码，未绕过；继续通过公开搜索工具定位并直接访问官方页面。六项候选的交互已在真实浏览器中核验。
- Google [Material Ripple](https://material-web.dev/components/ripple/) 与 [Material Tabs](https://material-web.dev/components/tabs/) 作为补充原理参考。官方独立演示依赖外部预览服务，在本机未稳定加载，不列为优先体验候选。
- 未检查这些站点所有设备/浏览器与全部功能；本轮不下载整站、不移植第三方素材、不安装新 UI 依赖。

截图与原始核验：output/playwright/reference-A-button-loading.png、reference-B-segments.png、reference-C-card-expand.png、reference-D-accordion.png、reference-E-drawer.png、reference-F-toast.png；汇总为 output/web/interaction-reference-verification.json。

P0–P4 的既有设计稿独立保留：[本地优先级预览](http://127.0.0.1:8770/?v=4#module/planning/tasks/p0)。它仍为示例内容，真实优先级保存尚未接入生产接口。
