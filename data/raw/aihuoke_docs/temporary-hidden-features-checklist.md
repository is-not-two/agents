# 临时隐藏功能检查与恢复清单

## 目标与边界

本次仅移除管理端和 PC 端入口；不删除数据、不下线接口，也不阻止已知 URL 直接访问。
所有前端改动均以 `Temporarily hidden` 注释标记，恢复时只需撤销对应注释附近的筛选、`v-if="false"` 或菜单项改动。

## 发布前检查

- [ ] 已部署 `admin` 与 `pc` 前端构建产物。
- [ ] 管理员重新登录，使菜单数据重新加载。
- [ ] 已确认保留接口和已有配置数据，不执行删除操作。

## 隐藏项核对

| 范围 | 应隐藏的入口 | 实现位置 | 恢复方式 |
| --- | --- | --- | --- |
| 后台菜单 | 系统激活 | `admin/src/stores/modules/user.ts` 前端菜单筛选 | 移除前端菜单名称筛选 |
| 后台菜单 | 营销管理整组（含 OEM、代理相关子项） | `admin/src/stores/modules/user.ts` 前端菜单筛选 | 移除前端菜单名称筛选 |
| 后台菜单 | AI 助理、AI 思维导图、美工设计、AI 面试、AI 直播 | `admin/src/stores/modules/user.ts` 前端菜单筛选 | 移除前端菜单名称筛选 |
| 管理端工作台 | 版本信息卡片；美工设计、思维导图、AI 面试的算力配置标签 | `admin/src/views/workbench/index.vue` | 移除相邻的临时隐藏注释与 `v-if="false"`，恢复三栏布局 |
| 管理端支付 | 微信公众号、H5 支付场景；余额支付、支付宝支付配置 | `admin/src/views/setting/pay/method/index.vue`、`admin/src/views/setting/pay/config/index.vue` | 删除展示筛选；原始接口数据未被修改 |
| 管理端存储 | 七牛云、腾讯云 COS | `admin/src/views/setting/storage/index.vue` | 删除 `qiniu` / `qcloud` 展示筛选；已有配置未被修改 |
| PC 侧栏与首页 | AI 销售 | `pc/src/layouts/components/aside/sidebar/menu-container.vue`、`pc/src/pages/index/index.vue` | 恢复对应菜单对象和首页卡片 |
| PC AI 工具 | 思维导图、无人直播 | `pc/src/pages/app/internal/index.vue`、`pc/src/pages/staff/index.vue` | 恢复侧栏项、组件导入、分组映射和功能卡片 |

## 验收清单

- [ ] `admin`：看不到系统激活、营销管理整组、AI 助理、AI 思维导图、美工设计、AI 面试、AI 直播。
- [ ] `admin`：工作台不显示版本信息以及上述三个算力配置标签。
- [ ] `admin`：支付页仅保留 PC 支付；支付配置仅显示微信支付；存储页仅显示本地存储和阿里云 OSS。
- [ ] `pc`：侧栏和首页不显示 AI 销售；AI 工具不显示思维导图与无人直播；功能卡片没有上述入口。
- [ ] 已知直链仍可访问，符合本次“仅隐藏入口”的范围。

## 恢复步骤

1. 恢复 `admin` 和 `pc` 中所有 `Temporarily hidden` 标记附近的改动，重新构建并发布两端前端。
2. 管理员重新登录，按“验收清单”反向核对所有入口均已恢复。

## 构建记录

- `admin`：`npm run build:test` 通过。
- `pc`：`npm run build` 通过。
- `admin`、`pc` 的类型检查受现有依赖问题影响，未作为本次变更的失败判定。
