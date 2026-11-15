const fs = require('node:fs/promises');
const path = require('node:path');
const { randomUUID } = require('node:crypto');

// The main process owns timers: minimizing/closing the renderer cannot throttle delivery.
class ReminderScheduler {
  constructor({ filename, deliver, now = Date.now, changed = () => {} }) {
    this.filename = filename; this.deliver = deliver; this.now = now; this.changed = changed;
    this.items = []; this.delivered = {}; this.operations = Promise.resolve(); this.error = '';
  }
  serial(action) {
    const next = this.operations.catch(() => {}).then(action);
    this.operations = next; return next;
  }
  async load() {
    try {
      const data = JSON.parse(await fs.readFile(this.filename, 'utf8'));
      if (data.version !== 1 || !Array.isArray(data.items) || !data.delivered || typeof data.delivered !== 'object') throw new Error('提醒存储格式无效');
      validReminders(data.items);
      this.items = data.items; this.delivered = data.delivered;
    } catch (e) { if (e.code !== 'ENOENT') throw e; }
  }
  async save() {
    const cutoff = this.now() - 7 * 86400000;
    this.delivered = Object.fromEntries(Object.entries(this.delivered).filter(([, at]) => at >= cutoff).slice(-10000));
    await fs.mkdir(path.dirname(this.filename), { recursive: true });
    const temp = this.filename + '.tmp';
    await fs.writeFile(temp, JSON.stringify({ version: 1, items: this.items, delivered: this.delivered }), 'utf8');
    await fs.rename(temp, this.filename);
    this.error = '';
  }
  replace(rows, sound) {
    validReminders(rows);
    return this.serial(async () => {
      const byKey = new Map(rows.map(r => [r.key, r]));
      const auxiliary = rows.length ? this.items.filter(r => r.auxiliary && (!r.sourceKey || byKey.get(r.sourceKey)?.at === r.sourceAt)) : [];
      this.items = [...rows.map(r => ({ ...r, sound: !!sound })), ...auxiliary];
      await this.save(); this.changed(this.items);
      return { count: this.items.filter(r => Date.parse(r.at) > this.now() && !this.delivered[this.token(r)]).length };
    });
  }
  append(reminder, sound) {
    validReminders([reminder]);
    return this.serial(async () => {
      this.items.push({ ...reminder, sound: !!sound, auxiliary: true }); await this.save();
    });
  }
  snooze(reminder) {
    return this.serial(async () => {
      // Do not resurrect a canceled, changed, or disabled lesson from a stale popup.
      if (!this.items.some(r => r.key === reminder.key && r.at === reminder.at)) return;
      this.items.push({ ...reminder, key: `snooze:${randomUUID()}`, at: new Date(this.now() + 300000).toISOString(), auxiliary: true,
        sourceKey: reminder.sourceKey || reminder.key, sourceAt: reminder.sourceAt || reminder.at });
      await this.save();
    });
  }
  token(r) { return `${r.key}@${r.at}`; }
  tick() {
    return this.serial(async () => {
      const now = this.now(); let dirty = false;
      for (const r of this.items) {
        const due = Date.parse(r.at); const token = this.token(r);
        if (due > now || this.delivered[token]) continue;
        // A short resume grace avoids both lost recent reminders and a flood of yesterday's classes.
        if (now - due <= 600000 && (r.auxiliary || Date.parse(r.lessonAt) >= now)) await this.deliver(r);
        this.delivered[token] = now; dirty = true;
      }
      if (dirty) await this.save();
    });
  }
  start() {
    this.timer = setInterval(() => { this.tick().catch(e => { this.error = e.message; }); }, 500);
  }
  async stop() { clearInterval(this.timer); await this.operations.catch(() => {}); }
}
function validReminders(rows) {
  if (!Array.isArray(rows) || rows.length > 4000) throw new Error('提醒条数超过上限（4000）');
  const keys = new Set();
  for (const r of rows) {
    if (!r || !Number.isSafeInteger(r.id) || r.id < 1 || typeof r.key !== 'string' || !r.key || r.key.length > 1000 || typeof r.title !== 'string' || r.title.length > 1000 || typeof r.body !== 'string' || r.body.length > 5000 || !Number.isFinite(Date.parse(r.at)) || !Number.isFinite(Date.parse(r.lessonAt))) throw new Error('提醒格式无效');
    if (keys.has(r.key)) throw new Error('提醒键重复'); keys.add(r.key);
  }
}
module.exports = { ReminderScheduler, validReminders };
