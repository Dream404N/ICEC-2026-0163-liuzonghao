# 工具采用记录

依赖版本由 package-lock.json 锁定；安装使用 npm ci。下表来自本机已安装包的 package.json，未以注册表版本号推断实际使用版本。

| 包 | 实际版本 | 许可证 | 上游 |
|---|---|---|---|
| react | 19.3.1 | MIT | https://github.com/react/react |
| vite | 7.3.8 | MIT | https://github.com/vitejs/vite |
| electron | 45.3.2 | MIT | https://github.com/electron/electron |
| @capacitor/core | 8.6.2 | MIT | https://github.com/ionic-team/capacitor |
| @capacitor/local-notifications | 8.3.1 | MIT | https://github.com/ionic-team/capacitor-local-notifications |
| @supabase/supabase-js | 2.119.0 | MIT | https://github.com/supabase/supabase-js |
| exceljs | 4.4.0 | MIT | https://github.com/exceljs/exceljs |
| idb | 8.0.4 | ISC | git://github.com/jakearchibald/idb |
| vitest | 4.1.12 | MIT | https://github.com/vitest-dev/vitest |
| @playwright/test | 1.65.1 | Apache-2.0 | https://github.com/microsoft/playwright |
| @electric-sql/pglite | 0.5.16 | Apache-2.0 | https://github.com/electric-sql/pglite |

采用理由：React / Capacitor / Electron 共享界面并保留原生通知入口；ExcelJS 负责 XLSX 读写，避免自实现 ZIP/XML；Supabase 负责认证与 RLS；idb 提供持久存储事务；Vitest / PGlite / Playwright 分别交叉验证业务、真实 PostgreSQL 语义与页面交互。

边界：使用成熟插件不代表已通过真机测试。安卓开机恢复已检查插件源码和合并清单；实际投递仍需设备验收。ExcelJS 的 uuid 覆盖版本通过 XLSX 读写测试交叉检查。镜像下载仅为解决本机网络超时，不变更依赖版本或目标平台。
