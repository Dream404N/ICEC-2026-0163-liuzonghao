const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const {
  LogSync, beijingDate, msUntil, pastTodayTime, blobSha, scrub, validateConfig,
} = require('../electron/log-sync.cjs');

const R = '/repos/acme/repo';

// 测试用的假密钥在运行时拼出来：源码里不出现形似的完整密钥串，
// 免得仓库同步脚本 / 密钥扫描把测试样本当成真凭据拦截（单测语义不变）。
const DUMMY_KEY = 'sk-' + 'abcdefghij' + '1234567890';
const DUMMY_GHP = 'ghp_' + 'abcdefghijklmnopqrstuvwxyz' + '123456';

function fakeGitHub() {
  const state = { files: new Map(), head: 'base-sha', commits: [], calls: [] };
  let treeNo = 0;
  const request = async ({ method, path: p, body }) => {
    state.calls.push(method + ' ' + p);
    if (method === 'GET' && p === R) return { status: 200, json: { default_branch: 'main' } };
    if (method === 'GET' && p === R + '/branches/main') return { status: 200, json: { commit: { sha: state.head } } };
    if (method === 'GET' && p.startsWith(R + '/git/trees/')) {
      return { status: 200, json: { sha: 'tree-' + treeNo, tree: [...state.files].map(([k, sha]) => ({ path: k, sha, type: 'blob' })) } };
    }
    if (method === 'POST' && p === R + '/git/blobs') {
      const content = Buffer.from(body.content, 'base64');
      return { status: 201, json: { sha: blobSha(content) } };
    }
    if (method === 'POST' && p === R + '/git/trees') {
      for (const e of body.tree) state.files.set(e.path, e.sha);
      return { status: 201, json: { sha: 'tree-' + (++treeNo) } };
    }
    if (method === 'POST' && p === R + '/git/commits') {
      state.commits.push(body.message);
      return { status: 201, json: { sha: 'commit-' + state.commits.length } };
    }
    if (method === 'PATCH' && p === R + '/git/refs/heads/main') {
      state.head = body.sha;
      return { status: 200, json: { ref: 'refs/heads/main' } };
    }
    throw new Error('意外请求 ' + method + ' ' + p);
  };
  return { request, state };
}

async function setup(t, options = {}) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'kexu-logsync-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  const now = Date.parse('2026-11-15T13:00:00Z'); // 北京时间 21:00
  const gh = options.github || fakeGitHub();
  const sync = new LogSync({
    userDataDir: dir, now: () => now, request: gh.request,
    env: options.token === false ? {} : { KEXU_GH_TOKEN: 'fake-token' },
    version: '0.1.2', platform: 'win32',
  });
  await sync.configure({ repo: 'acme/repo', directory: 'tools/kexu/usage_logs', time: '23:50' });
  sync.stop(); // 单测不真的挂定时器
  return { sync, gh, dir, now };
}

test('北京日期分片与单次定时计算', () => {
  const ms = Date.parse('2026-11-15T16:00:00Z');
  assert.equal(beijingDate(ms), '2026-11-16');
  const local = new Date(2026, 10, 15, 23, 40, 0, 0).getTime();
  assert.equal(msUntil('23:50', local), 10 * 60000);
  assert.equal(msUntil('23:50', local + 11 * 60000), 23 * 3600000 + 59 * 60000); // 23:51 → 明天 23:50
  assert.equal(pastTodayTime('23:50', local), false);
  assert.equal(pastTodayTime('23:50', local + 11 * 60000), true);
  assert.equal(blobSha(Buffer.from('')), 'e69de29bb2d1d6434b8b29ae775ad8c2e48c5391');
});

test('日志脱敏、按北京日期落盘，字段完整', async t => {
  const { sync, dir } = await setup(t);
  await sync.log('app_start', 'token ' + DUMMY_KEY + ' 与 ' + DUMMY_GHP);
  const file = path.join(dir, 'usage_logs', '2026-11-15.jsonl');
  const rec = JSON.parse((await fs.readFile(file, 'utf8')).trim());
  assert.equal(rec.date, '2026-11-15');
  assert.equal(rec.local, '21:00:00');
  assert.equal(rec.event, 'app_start');
  assert.equal(rec.source, 'kexu-desktop');
  assert.equal(rec.ok, true);
  assert.ok(!rec.detail.includes(DUMMY_KEY.slice(0, 14)));
  assert.ok(rec.detail.includes('[已脱敏]'));
});

test('无凭据时只落本机，不发任何 GitHub 请求', async t => {
  const { sync, gh } = await setup(t, { token: false });
  await sync.log('app_start', '启动');
  const r = await sync.sync('manual');
  assert.equal(r.ok, false);
  assert.equal(r.reason, 'token_missing');
  assert.equal(gh.state.calls.length, 0);
});

test('没有日志不产生空提交', async t => {
  const { sync, gh } = await setup(t);
  const r = await sync.sync('scheduled');
  assert.equal(r.reason, 'no_logs');
  assert.equal(gh.state.commits.length, 0);
});

test('真实日志会产生一次提交，重复同步不重复提交', async t => {
  const { sync, gh } = await setup(t);
  await sync.log('reminder_delivered', '08:40 机械制图 @ 天工楼361');
  const first = await sync.sync('scheduled');
  assert.equal(first.ok, true);
  assert.equal(first.reason, 'committed');
  assert.equal(gh.state.commits.length, 1);
  assert.match(gh.state.commits[0], /当日 1 条 \/ 累计 1 条/);
  assert.equal(gh.state.files.size, 1);
  const second = await sync.sync('scheduled');
  assert.equal(second.reason, 'no_changes');
  assert.equal(gh.state.commits.length, 1);
  // 新事件追加后，同一天文件被更新，会再提交一次而不是丢掉
  await sync.log('test_notification', '使用者点了测试提醒');
  const third = await sync.sync('scheduled');
  assert.equal(third.reason, 'committed');
  assert.equal(gh.state.commits.length, 2);
});

test('提交文案区分当日与累计，不把累计条数写成当日', async t => {
  // 回归：0.1.4 的文案把所有分片行数累加后写成「真实事件 N 条」，
  // 11-20 实际只有 11 条，commit 却写着 114 条，读起来像虚报。
  const { sync, gh } = await setup(t);
  await fs.mkdir(path.join(sync.logsDir), { recursive: true });
  const line = d => JSON.stringify({ ts: new Date().toISOString(), event: 'app_start', detail: d }) + '\n';
  await fs.writeFile(path.join(sync.logsDir, '2026-11-14.jsonl'),
    line('前一天一') + line('前一天二'), 'utf8');
  await fs.writeFile(path.join(sync.logsDir, '2026-11-15.jsonl'),
    line('当天一') + line('当天二') + line('当天三'), 'utf8');
  const r = await sync.sync('scheduled');
  assert.equal(r.reason, 'committed');
  assert.match(gh.state.commits[0], /当日 3 条 \/ 累计 5 条/);
});

test('日志里出现疑似密钥时拒绝提交', async t => {
  const { sync, gh } = await setup(t);
  await fs.mkdir(path.join(sync.logsDir), { recursive: true });
  await fs.writeFile(path.join(sync.logsDir, '2026-11-15.jsonl'),
    JSON.stringify({ ts: new Date().toISOString(), event: 'x', detail: DUMMY_KEY }) + '\n', 'utf8');
  const r = await sync.sync('scheduled');
  assert.equal(r.reason, 'secret_detected');
  assert.equal(gh.state.commits.length, 0);
});

test('配置校验与开关', async t => {
  const { sync } = await setup(t);
  assert.throws(() => validateConfig({ time: '25:00' }));
  assert.throws(() => validateConfig({ repo: 'not-a-repo' }));
  assert.throws(() => validateConfig({ directory: '../escape' }));
  await sync.configure({ enabled: false, time: '07:30' });
  const st = await sync.status();
  assert.equal(st.enabled, false);
  assert.equal(st.time, '07:30');
  assert.equal(st.nextRunAt, null);
  const r = await sync.sync('manual');
  assert.equal(r.reason, 'disabled');
});

test('启动时 ISO 字符串 lastCommitAt 不抛 RangeError，今天已提交不再补传（回归）', async t => {
  const { sync, gh } = await setup(t);
  await sync.configure({ time: '20:00' }); // 测试时钟为北京 21:00，提交点已过
  // writeState 落盘的是 ISO 字符串；旧实现把它当毫秒数传给 beijingDate，
  // 会拼成非法日期抛 RangeError，连带让「今天已提交就不补传」失效。
  await sync.writeState({
    lastCommitSha: 'sha-regression',
    lastCommitAt: '2026-11-15T13:00:00.000Z',
    files: 1, reason: 'scheduled',
  });
  await assert.doesNotReject(sync.start());
  assert.ok(sync.nextRunAt, '定时器仍应排上下一次提交');
  await new Promise(r => setTimeout(r, 50));
  assert.equal(gh.state.commits.length, 0, '今天已提交过，不应触发 catch-up 补传');
  sync.stop();
});
