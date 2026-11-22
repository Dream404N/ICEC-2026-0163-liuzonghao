'use strict';

/**
 * 课序 · 运行日志每天自动提交到 GitHub
 *
 * 原则（与项目其余部分一致，别为了「日志好看」破坏它）：
 *  - 只记录真实发生的事件：启动、退出、提醒弹出、测试通知、设置变更、提交结果。
 *    关机 / 没打开应用 / 断网的那天就是没有日志，不补写、不造心跳。
 *  - 每天只用一个 setTimeout 睡到提交时刻，不轮询、不扫表、不联网探测。
 *  - 凭据只从环境变量或本机 tokenFile 读，不写进配置、不写进日志、不进仓库。
 *  - 只往自己的目录写文件，基于远端最新 commit 建 tree，绝不删别人的文件。
 *
 * 纯 Node 标准库，Electron 打包后无需额外依赖。
 */
const fs = require('node:fs/promises');
const fsSync = require('node:fs');
const path = require('node:path');
const os = require('node:os');
const https = require('node:https');
const http = require('node:http');
const tls = require('node:tls');
const crypto = require('node:crypto');

const DEFAULT_CONFIG = Object.freeze({
  enabled: true,
  time: '23:50',                                  // 本机时间，HH:mm
  repo: 'Dream404N/ICEC-2026-0163-liuzonghao',
  branch: '',                                     // 空 = 使用仓库默认分支
  directory: 'tools/kexu/usage_logs',            // 远端目录，只碰这里
  tokenFile: '',                                  // 本机 token 文件绝对路径（可选）
  proxy: '',                                      // 可选 http://host:port，不配置则直连
});

const SECRET_RE = /(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|SCT[0-9A-Za-z]{5,}|Bearer\s+[A-Za-z0-9_.-]{20,})/g;
const LOG_NAME_RE = /^\d{4}-\d{2}-\d{2}\.jsonl$/;

function beijingDate(ms) { return new Date(ms + 8 * 3600000).toISOString().slice(0, 10); }
function beijingClock(ms) { return new Date(ms + 8 * 3600000).toISOString().slice(11, 19); }

/** 距离下一个本机 HH:mm 的毫秒数；已过则算明天。 */
function msUntil(hhmm, now) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm));
  if (!m) throw new Error('提交时间格式应为 HH:mm');
  const h = Number(m[1]), minute = Number(m[2]);
  if (h > 23 || minute > 59) throw new Error('提交时间超出范围');
  const d = new Date(now);
  const target = new Date(d.getFullYear(), d.getMonth(), d.getDate(), h, minute, 0, 0).getTime();
  const delta = target - now;
  return delta > 0 ? delta : delta + 86400000;
}

function pastTodayTime(hhmm, now) {
  const m = /^(\d{1,2}):(\d{2})$/.exec(String(hhmm));
  if (!m) return false;
  const d = new Date(now);
  return d.getHours() * 60 + d.getMinutes() >= Number(m[1]) * 60 + Number(m[2]);
}

function blobSha(buf) {
  const b = Buffer.isBuffer(buf) ? buf : Buffer.from(buf);
  return crypto.createHash('sha1').update(Buffer.from('blob ' + b.length + '\0', 'binary')).update(b).digest('hex');
}

function scrub(text) {
  return String(text == null ? '' : text).replace(SECRET_RE, '[已脱敏]');
}

function readToken(cfg, env) {
  const e = env || process.env;
  const inline = String(e.KEXU_GH_TOKEN || e.ICEC_GH_TOKEN || '').trim();
  if (inline) return inline;
  const candidates = [cfg.tokenFile, path.join(os.homedir(), '.workbuddy', '.gh_token')];
  for (const f of candidates) {
    if (!f) continue;
    try {
      const t = fsSync.readFileSync(f, 'utf8').trim();
      if (t) return t;
    } catch { /* 文件不存在就没这一路凭据，继续找 */ }
  }
  return '';
}

function validateConfig(patch) {
  const out = {};
  if ('enabled' in patch) {
    if (typeof patch.enabled !== 'boolean') throw new Error('enabled 必须是布尔值');
    out.enabled = patch.enabled;
  }
  if ('time' in patch) {
    if (!/^\d{1,2}:\d{2}$/.test(String(patch.time)) || Number(String(patch.time).split(':')[0]) > 23 || Number(String(patch.time).split(':')[1]) > 59) throw new Error('提交时间格式应为 HH:mm');
    out.time = String(patch.time);
  }
  if ('repo' in patch) {
    if (!/^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(String(patch.repo))) throw new Error('仓库格式应为 owner/name');
    out.repo = String(patch.repo);
  }
  if ('branch' in patch) out.branch = String(patch.branch || '').replace(/[^A-Za-z0-9_./-]/g, '');
  if ('directory' in patch) {
    const d = String(patch.directory || '').replace(/\\/g, '/').replace(/^\/+|\/+$/g, '');
    if (!d || d.includes('..') || d.startsWith('.')) throw new Error('远端目录不合法');
    out.directory = d;
  }
  if ('tokenFile' in patch) out.tokenFile = String(patch.tokenFile || '');
  if ('proxy' in patch) out.proxy = String(patch.proxy || '');
  return out;
}

/** 直连 api.github.com；配置了 proxy 时走 HTTP CONNECT 隧道。 */
function realRequest({ token, method, path: apiPath, body, proxy: proxyOpt }) {
  const data = body === undefined ? null : Buffer.from(JSON.stringify(body), 'utf8');
  const headers = {
    'User-Agent': 'kexu-log-sync',
    'Accept': 'application/vnd.github+json',
    'Authorization': 'Bearer ' + token,
  };
  if (data) {
    headers['Content-Type'] = 'application/json';
    headers['Content-Length'] = String(data.length);
  }
  // 默认直连。只有使用者显式配置 proxy / KEXU_HTTPS_PROXY 才走隧道，
  // 避免终端里临时设的代理变量把已验证可直连的请求带偏。
  const proxy = String(proxyOpt || process.env.KEXU_HTTPS_PROXY || '').trim();
  return new Promise((resolve, reject) => {
    const finish = (socket, closeSocket) => {
      const req = https.request({
        host: 'api.github.com', port: 443, path: apiPath, method, headers,
        agent: false, timeout: 25000,
        createConnection: socket ? () => socket : undefined,
      }, res => {
        let raw = '';
        res.setEncoding('utf8');
        res.on('data', d => { raw += d; });
        res.on('end', () => {
          if (closeSocket) { try { socket.end(); } catch { /* ignore */ } }
          let json = {};
          try { json = raw ? JSON.parse(raw) : {}; } catch { json = { message: raw.slice(0, 200) }; }
          resolve({ status: res.statusCode, json });
        });
      });
      req.on('timeout', () => { req.destroy(new Error('请求 GitHub 超时')); });
      req.on('error', reject);
      if (data) req.write(data);
      req.end();
    };
    if (!proxy) return finish(null, false);
    let u;
    try { u = new URL(proxy); } catch { return reject(new Error('代理地址不合法')); }
    const connect = http.request({
      host: u.hostname, port: Number(u.port) || 80, method: 'CONNECT',
      path: 'api.github.com:443', headers: { Host: 'api.github.com:443' }, timeout: 15000,
    });
    connect.on('connect', (res, socket) => {
      if (res.statusCode !== 200) { socket.destroy(); return reject(new Error('代理 CONNECT 返回 ' + res.statusCode)); }
      const secured = tls.connect({ socket, servername: 'api.github.com' }, () => finish(secured, true));
      secured.on('error', reject);
    });
    connect.on('timeout', () => connect.destroy(new Error('连接代理超时')));
    connect.on('error', reject);
    connect.end();
  });
}

class LogSync {
  constructor({ userDataDir, logsDir, now = Date.now, request = realRequest, env = process.env, version = '', platform = process.platform } = {}) {
    const base = userDataDir || path.join(process.env.APPDATA || path.join(os.homedir(), 'AppData', 'Roaming'), '课序');
    this.baseDir = base;
    this.logsDir = logsDir || path.join(base, 'usage_logs');
    this.configFile = path.join(base, 'log-sync.json');
    this.stateFile = path.join(base, 'log-sync-state.json');
    this.now = now;
    this.request = request;
    this.env = env;
    this.version = version;
    this.platform = platform;
    this.timer = null;
    this.lastError = '';
    this.lastResult = null;
    this.writeChain = Promise.resolve();
    this.syncChain = Promise.resolve();
  }

  async config() {
    let saved = {};
    try { saved = JSON.parse(await fs.readFile(this.configFile, 'utf8')); } catch { /* 首次运行用默认值 */ }
    const cfg = { ...DEFAULT_CONFIG, ...saved };
    if (!this._created) {
      this._created = true;
      try { await fs.access(this.configFile); } catch { await this.writeConfig(cfg); }
    }
    return cfg;
  }

  async writeConfig(cfg) {
    await fs.mkdir(this.baseDir, { recursive: true });
    const tmp = this.configFile + '.tmp';
    await fs.writeFile(tmp, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
    await fs.rename(tmp, this.configFile);
  }

  async configure(patch) {
    const clean = validateConfig(patch || {});
    const cfg = { ...await this.config(), ...clean };
    await this.writeConfig(cfg);
    this.scheduleNext(cfg);
    return this.publicConfig(cfg);
  }

  publicConfig(cfg) {
    return {
      enabled: cfg.enabled, time: cfg.time, repo: cfg.repo,
      branch: cfg.branch || '（仓库默认）', directory: cfg.directory,
      tokenConfigured: !!readToken(cfg, this.env),
      tokenFile: cfg.tokenFile ? path.basename(cfg.tokenFile) : '（环境变量 / 默认位置）',
    };
  }

  async readState() {
    try { return JSON.parse(await fs.readFile(this.stateFile, 'utf8')); } catch { return {}; }
  }

  async writeState(state) {
    await fs.mkdir(this.baseDir, { recursive: true });
    await fs.writeFile(this.stateFile, JSON.stringify(state, null, 2) + '\n', 'utf8');
  }

  /** 追加一条真实事件；写操作串行，避免并发 append 交错。 */
  log(event, detail = '', ok = true) {
    const job = this.writeChain.catch(() => {}).then(async () => {
      const ms = this.now();
      const rec = {
        ts: new Date(ms).toISOString(),
        date: beijingDate(ms), local: beijingClock(ms),
        event: scrub(event).slice(0, 80),
        detail: scrub(detail).slice(0, 500),
        ok: !!ok, source: 'kexu-desktop',
        app: this.version, platform: this.platform,
      };
      await fs.mkdir(this.logsDir, { recursive: true });
      await fs.appendFile(path.join(this.logsDir, rec.date + '.jsonl'), JSON.stringify(rec) + '\n', 'utf8');
      return rec;
    });
    this.writeChain = job;
    return job;
  }

  /** 退出时用：同步落盘，保证 app_exit 不因进程立即结束而丢。 */
  logNow(event, detail = '', ok = true) {
    const ms = this.now();
    const rec = {
      ts: new Date(ms).toISOString(), date: beijingDate(ms), local: beijingClock(ms),
      event: scrub(event).slice(0, 80), detail: scrub(detail).slice(0, 500),
      ok: !!ok, source: 'kexu-desktop', app: this.version, platform: this.platform,
    };
    try {
      fsSync.mkdirSync(this.logsDir, { recursive: true });
      fsSync.appendFileSync(path.join(this.logsDir, rec.date + '.jsonl'), JSON.stringify(rec) + '\n', 'utf8');
    } catch { /* 磁盘不可写也不能阻止退出 */ }
    return rec;
  }

  async localLogs() {
    let names = [];
    try { names = await fs.readdir(this.logsDir); } catch { return []; }
    const out = [];
    for (const name of names.filter(n => LOG_NAME_RE.test(n)).sort()) {
      const content = await fs.readFile(path.join(this.logsDir, name));
      out.push({ name, content, sha: blobSha(content) });
    }
    return out;
  }

  /** 单次定时：算好下一次提交时刻，睡到那一刻；触发后再排下一天。 */
  scheduleNext(cfg) {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
    if (!cfg || !cfg.enabled) return;
    const delay = msUntil(cfg.time, this.now());
    this.nextRunAt = new Date(this.now() + delay).toISOString();
    this.timer = setTimeout(() => {
      this.timer = null;
      this.sync('scheduled').catch(e => { this.lastError = String(e.message || e); })
        .finally(() => { this.config().then(c => this.scheduleNext(c)).catch(() => {}); });
    }, delay);
    if (this.timer.unref) this.timer.unref();
  }

  /** 启动：写一条真实启动记录、排定时；若已过今天的提交点且今天还没提交过，补传真实存在的日志。 */
  async start() {
    const cfg = await this.config();
    await this.log('app_start', '课序启动 | v' + (this.version || '?') + ' | ' + this.platform);
    this.scheduleNext(cfg);
    if (!cfg.enabled || !readToken(cfg, this.env)) return;
    const state = await this.readState();
    const today = beijingDate(this.now());
    // writeState 存的是 ISO 字符串，而 beijingDate 只接受毫秒数；直接传字符串会
    // 拼成非法日期并抛 RangeError，使「今天已提交就不补传」的判断失效。
    const lastCommitMs = state.lastCommitAt ? Date.parse(state.lastCommitAt) : NaN;
    const committedToday = Number.isFinite(lastCommitMs) && beijingDate(lastCommitMs) === today;
    if (!committedToday && pastTodayTime(cfg.time, this.now())) {
      this.sync('catch-up').catch(e => { this.lastError = String(e.message || e); });
    }
  }

  stop() {
    if (this.timer) { clearTimeout(this.timer); this.timer = null; }
  }

  async status() {
    const cfg = await this.config();
    const state = await this.readState();
    const files = await this.localLogs();
    const today = beijingDate(this.now());
    let todayCount = 0;
    for (const f of files) {
      if (f.name.slice(0, 10) !== today) continue;
      todayCount += f.content.toString('utf8').split('\n').filter(Boolean).length;
    }
    return {
      ...this.publicConfig(cfg),
      logsDir: this.logsDir,
      files: files.length,
      todayCount,
      nextRunAt: cfg.enabled ? (this.nextRunAt || null) : null,
      lastCommit: state.lastCommitSha || '',
      lastCommitAt: state.lastCommitAt || '',
      lastCommitFiles: state.files || 0,
      lastError: this.lastError,
      lastResult: this.lastResult,
    };
  }

  /** 提交日志到 GitHub。只增改自己目录，不删除任何远端文件。 */
  sync(reason = 'scheduled') {
    const job = this.syncChain.catch(() => {}).then(() => this._sync(reason, true));
    this.syncChain = job;
    return job;
  }

  async _sync(reason, allowRetry) {
    const cfg = await this.config();
    if (!cfg.enabled) return { ok: false, reason: 'disabled', message: '日志同步已关闭' };
    const token = readToken(cfg, this.env);
    if (!token) {
      this.lastError = '未配置 GitHub 凭据';
      this.lastResult = { ok: false, reason: 'token_missing' };
      // 定时跑但没配凭据时别每天刷一条同样的记录；手动触发才如实记一次。
      if (reason === 'manual') await this.log('log_sync_skipped', '未配置 GitHub 凭据，日志仅保存在本机', false);
      return { ...this.lastResult, message: this.lastError };
    }
    if (reason === 'manual') await this.log('manual_sync', '使用者手动触发日志同步');
    const files = await this.localLogs();
    if (!files.length) return { ok: true, reason: 'no_logs', message: '本机暂无运行日志，未产生空提交' };
    for (const f of files) {
      SECRET_RE.lastIndex = 0;
      if (SECRET_RE.test(f.content.toString('utf8'))) {
        const msg = '日志中出现疑似密钥串，已中止提交：' + f.name;
        this.lastError = msg;
        await this.log('log_sync_failed', msg, false);
        return { ok: false, reason: 'secret_detected', message: msg };
      }
    }
    const R = '/repos/' + cfg.repo;
    const call = (method, apiPath, body) => this.request({ token, method, path: apiPath, body, proxy: cfg.proxy });
    try {
      const repo = await call('GET', R);
      if (repo.status !== 200) throw new Error('读取仓库失败 HTTP ' + repo.status + ' ' + (repo.json.message || ''));
      const branch = cfg.branch || repo.json.default_branch || 'main';
      const br = await call('GET', R + '/branches/' + encodeURIComponent(branch));
      if (br.status !== 200 || !br.json.commit) throw new Error('读取分支失败 HTTP ' + br.status);
      const head = br.json.commit.sha;
      const tree = await call('GET', R + '/git/trees/' + head + '?recursive=1');
      if (tree.status !== 200 || !tree.json.tree) throw new Error('读取文件树失败 HTTP ' + tree.status);
      const remote = new Map(tree.json.tree
        .filter(x => x.type === 'blob' && x.path.startsWith(cfg.directory + '/'))
        .map(x => [x.path, x.sha]));

      const entries = [];
      for (const f of files) {
        const rel = cfg.directory + '/' + f.name;
        if (remote.get(rel) === f.sha) continue;
        const blob = await call('POST', R + '/git/blobs', { content: f.content.toString('base64'), encoding: 'base64' });
        if (blob.status !== 200 && blob.status !== 201) throw new Error('上传日志失败 HTTP ' + blob.status);
        entries.push({ path: rel, mode: '100644', type: 'blob', sha: blob.json.sha });
      }
      let result;
      if (!entries.length) {
        result = { ok: true, reason: 'no_changes', sha: head, files: 0, message: '日志已全部在远端，未产生重复提交' };
      } else {
        const tr = await call('POST', R + '/git/trees', { base_tree: tree.json.sha, tree: entries });
        if (tr.status !== 200 && tr.status !== 201) throw new Error('创建文件树失败 HTTP ' + tr.status);
        let total = 0;
        for (const f of files) total += f.content.toString('utf8').split('\n').filter(Boolean).length;
        const message = '课序运行日志 ' + beijingDate(this.now()) + '（真实事件 ' + total + ' 条，' + reason + '）';
        const cm = await call('POST', R + '/git/commits', { message, tree: tr.json.sha, parents: [head] });
        if (cm.status !== 200 && cm.status !== 201) throw new Error('创建提交失败 HTTP ' + cm.status);
        const ref = await call('PATCH', R + '/git/refs/heads/' + encodeURIComponent(branch), { sha: cm.json.sha });
        if ((ref.status === 422 || ref.status === 409) && allowRetry) {
          // 云端同时有别的提交：取最新 head 重来一次，不强行覆盖。
          return this._sync(reason, false);
        }
        if (ref.status !== 200 && ref.status !== 201) throw new Error('更新分支失败 HTTP ' + ref.status + ' ' + (ref.json.message || ''));
        result = { ok: true, reason: 'committed', sha: cm.json.sha, files: entries.length, message: '已提交 ' + cm.json.sha.slice(0, 7) + '（' + entries.length + ' 个日志文件）' };
        await this.writeState({ lastCommitSha: cm.json.sha, lastCommitAt: new Date(this.now()).toISOString(), files: entries.length, reason });
      }
      this.lastError = '';
      this.lastResult = result;
      return result;
    } catch (e) {
      const msg = String(e.message || e);
      this.lastError = msg;
      this.lastResult = { ok: false, reason: 'error', message: msg };
      await this.log('log_sync_failed', scrub(msg).slice(0, 300), false);
      return this.lastResult;
    }
  }
}

module.exports = { LogSync, DEFAULT_CONFIG, beijingDate, beijingClock, msUntil, pastTodayTime, blobSha, scrub, readToken, validateConfig };
