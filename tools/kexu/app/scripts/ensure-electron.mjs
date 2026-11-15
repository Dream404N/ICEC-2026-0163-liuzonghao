import { existsSync } from 'node:fs';
import { spawnSync } from 'node:child_process';
try {
  const { default: binary } = await import('electron');
  if (existsSync(binary)) process.exit(0);
} catch { /* 安装时禁用生命周期脚本的环境中，还没有 Electron 二进制。 */ }
const result = spawnSync(process.execPath, ['node_modules/electron/install.js'], { stdio: 'inherit', env: process.env });
process.exit(result.status ?? 1);
