const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs/promises');
const os = require('node:os');
const path = require('node:path');
const { ReminderScheduler, validReminders } = require('../electron/reminder-scheduler.cjs');

async function setup(t) {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), 'kexu-scheduler-'));
  t.after(() => fs.rm(dir, { recursive: true, force: true }));
  let now = Date.parse('2026-11-15T00:00:00Z'); const shown = [];
  const options = { filename: path.join(dir, 'plan.json'), now: () => now, deliver: r => shown.push(r) };
  const scheduler = new ReminderScheduler(options); await scheduler.load();
  const row = (key = 'lesson:15', delta = 1000) => ({ id: 1, key, title: '<测试>', body: '教室 301', at: new Date(now + delta).toISOString(), lessonAt: new Date(now + 3600000).toISOString() });
  return { scheduler, options, shown, row, advance: ms => { now += ms; } };
}
test('到点实际投递一次，重复刷新及重启后不重复投递', async t => {
  const x = await setup(t), r = x.row();
  await x.scheduler.replace([r], false); await x.scheduler.tick(); assert.equal(x.shown.length, 0);
  x.advance(1001); await Promise.all([x.scheduler.tick(), x.scheduler.tick()]); assert.equal(x.shown.length, 1);
  await x.scheduler.replace([r], true); await x.scheduler.tick(); assert.equal(x.shown.length, 1);
  const restart = new ReminderScheduler(x.options); await restart.load(); await restart.tick(); assert.equal(x.shown.length, 1);
});
test('持久计划在重启后触发，取消旧课和修改时间不留下旧提醒', async t => {
  const x = await setup(t); await x.scheduler.replace([x.row()], false);
  const restart = new ReminderScheduler(x.options); await restart.load(); x.advance(1001); await restart.tick(); assert.equal(x.shown.length, 1);
  const r = x.row('changed'); await restart.replace([r], false); await restart.replace([{ ...r, at: new Date(Date.parse(r.at) + 10000).toISOString() }], false);
  x.advance(1001); await restart.tick(); assert.equal(x.shown.length, 1);
  await restart.replace([], false); x.advance(20000); await restart.tick(); assert.equal(x.shown.length, 1);
});
test('5 分钟稍后提醒跨重启保留，关闭或移除源课程后取消', async t => {
  const x = await setup(t), r = x.row();
  await x.scheduler.replace([r], false); x.advance(1001); await x.scheduler.tick(); await x.scheduler.snooze(r);
  await x.scheduler.replace([r], true);
  const restart = new ReminderScheduler(x.options); await restart.load(); x.advance(300000); await restart.tick(); assert.equal(x.shown.length, 2);
  await restart.snooze(x.shown[1]); await restart.replace([], false); x.advance(300000); await restart.tick(); assert.equal(x.shown.length, 2);
  await restart.snooze(r); assert.equal(restart.items.length, 0);
});
test('恢复运行只补发最近十分钟的有效课程，过时课程不刷屏', async t => {
  const x = await setup(t), recent = x.row('recent', -60000), stale = x.row('stale', -700000), started = { ...x.row('started', -1000), lessonAt: new Date(x.options.now() - 1).toISOString() };
  await x.scheduler.replace([recent, stale, started], false); await x.scheduler.tick(); assert.deepEqual(x.shown.map(r => r.key), ['recent']);
});
test('原生边界拒绝非法时间与重复提醒，损坏文件不被静默覆盖', async t => {
  const x = await setup(t); assert.throws(() => validReminders([{ ...x.row(), at: 'invalid' }]));
  assert.throws(() => validReminders([x.row(), x.row()]));
  await fs.writeFile(x.options.filename, '{broken');
  await assert.rejects(new ReminderScheduler(x.options).load());
  assert.equal(await fs.readFile(x.options.filename, 'utf8'), '{broken');
});
