export function parseWeeks(input: string, total = 30): number[] {
  const raw = input.trim().replace(/[，、；;]/g, ',').replace(/[～~—–至]/g, '-').replace(/第|周|\s/g, '');
  if (!raw) throw new Error('请填写上课周次');
  const parity = /单/.test(raw) ? 1 : /双/.test(raw) ? 0 : null;
  if (/单/.test(raw) && /双/.test(raw)) throw new Error('同一条周次不能同时限定单双周');
  const normalized = raw.replace(/[()（）单双]/g, '');
  const source = normalized === '' || normalized === '每' || normalized === '全部' ? `1-${total}` : normalized;
  const result = new Set<number>();
  for (const part of source.split(',')) {
    if (!/^\d+(-\d+)?$/.test(part)) throw new Error(`无法识别周次：${part || input}`);
    const [a, b = a] = part.split('-').map(Number);
    if (a < 1 || b > total || a > b) throw new Error(`周次必须在 1-${total} 周内，且起始周不大于结束周`);
    for (let n = a; n <= b; n++) if (parity === null || n % 2 === parity) result.add(n);
  }
  if (!result.size) throw new Error('该规则没有有效的上课周次');
  return [...result].sort((a, b) => a - b);
}
export function formatWeeks(weeks: number[]): string {
  const sorted = [...new Set(weeks)].sort((a, b) => a - b);
  const chunks: string[] = [];
  for (let i = 0; i < sorted.length; i++) {
    const start = sorted[i]; let end = start;
    while (sorted[i + 1] === end + 1) end = sorted[++i];
    chunks.push(end === start ? `${start}` : `${start}-${end}`);
  }
  return chunks.join(',');
}
