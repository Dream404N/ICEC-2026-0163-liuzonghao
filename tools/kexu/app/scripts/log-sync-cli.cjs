'use strict';
/**
 * 课序 · 运行日志命令行入口（排查 / 手动验证用，不依赖 Electron 窗口）
 *
 *   node scripts/log-sync-cli.cjs status          看状态
 *   node scripts/log-sync-cli.cjs sync            立即提交一次（真实日志）
 *   node scripts/log-sync-cli.cjs log <事件> <说明>  手动补记一条真实事件
 *   node scripts/log-sync-cli.cjs enable|disable  开关每天自动提交
 *   node scripts/log-sync-cli.cjs time 23:50      改每天提交时间
 *   node scripts/log-sync-cli.cjs token <绝对路径>  指定本机 token 文件
 *
 * 目录必须与 Electron 主进程一致：安装版用 app.getPath('userData')，
 * 目录名取自 package.json 的 name，即 %APPDATA%\classmate-reminder；
 * 只有早期开发版才落在 %APPDATA%\课序。两个都存在时以安装版为准，
 * 否则命令行看的是另一份日志，会误判「装了却没日志」。
 * 若手动改过位置，用 KEXU_USER_DATA 覆盖。
 */
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { LogSync } = require('../electron/log-sync.cjs');

function userData() {
  if (process.env.KEXU_USER_DATA) return process.env.KEXU_USER_DATA;
  const appdata = process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming');
  // 安装版优先；只有不存在时才回落到早期开发版目录。
  for (const name of ['classmate-reminder', '课序']) {
    const p = path.join(appdata, name);
    if (fs.existsSync(p)) return p;
  }
  return path.join(appdata, 'classmate-reminder');
}

const sync = new LogSync({ userDataDir: userData(), version: 'cli', platform: process.platform });
const [cmd, ...args] = process.argv.slice(2);

(async () => {
  switch (cmd || 'status') {
    case 'status': {
      const s = await sync.status();
      console.log('运行日志目录 :', s.logsDir);
      console.log('自动提交     :', s.enabled ? '开启' : '关闭', '| 每天', s.time, '（本机时间）');
      console.log('目标仓库     :', s.repo, '| 分支', s.branch, '| 目录', s.directory);
      console.log('凭据         :', s.tokenConfigured ? '已配置（' + s.tokenFile + '）' : '未配置，日志只留本机');
      console.log('本地日志     :', s.files, '个文件 | 今日', s.todayCount, '条事件');
      console.log('下次提交     :', s.nextRunAt || '（未运行中的定时器；由应用窗口负责）');
      console.log('最近提交     :', s.lastCommit ? s.lastCommit.slice(0, 7) + ' @ ' + s.lastCommitAt : '尚无');
      if (s.lastError) console.log('最近错误     :', s.lastError);
      break;
    }
    case 'sync': {
      const r = await sync.sync('manual');
      console.log(r.ok ? '✓ ' : '✗ ', r.message || r.reason, r.sha ? '| commit ' + r.sha : '');
      if (!r.ok) process.exitCode = 1;
      break;
    }
    case 'log': {
      if (!args[0]) throw new Error('用法: log <事件> <说明>');
      const rec = await sync.log(args[0], args.slice(1).join(' '));
      console.log('已记录真实事件:', rec.ts, rec.event, '|', rec.detail);
      break;
    }
    case 'enable':
    case 'disable': {
      const c = await sync.configure({ enabled: cmd === 'enable' });
      console.log('自动提交已' + (c.enabled ? '开启' : '关闭'), '| 每天', c.time);
      break;
    }
    case 'time': {
      if (!args[0]) throw new Error('用法: time HH:mm');
      const c = await sync.configure({ time: args[0] });
      console.log('每天提交时间已改为', c.time);
      break;
    }
    case 'token': {
      if (!args[0]) throw new Error('用法: token <本机 token 文件绝对路径>；传 off 可清空');
      const value = args[0] === 'off' ? '' : args[0];
      const c = await sync.configure({ tokenFile: value });
      console.log('凭据文件已设置：', value || '（清空，改用环境变量 / 默认位置）');
      console.log('配置只保存文件路径，不含 token 本身；当前状态：', c.tokenConfigured ? '已配置' : '未配置');
      break;
    }
    default:
      throw new Error('未知命令: ' + cmd + '（可用 status / sync / log / enable / disable / time / token）');
  }
})().catch(e => { console.error('失败:', e.message || e); process.exitCode = 1; });
