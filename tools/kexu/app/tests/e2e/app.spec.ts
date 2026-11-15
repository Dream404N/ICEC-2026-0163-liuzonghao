import { test, expect } from '@playwright/test';

test('设置学期、管理课程、单次调课、备份与刷新恢复', async ({ page }) => {
  const errors: string[] = []; page.on('pageerror', error => errors.push(error.message));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: /每一节课，都从容以赴/ })).toBeVisible();
  await expect(page.getByText('先告诉课序，第一周从哪一天开始')).toBeVisible();
  await page.getByRole('button', { name: '偏好设置', exact: true }).click();
  await page.getByLabel('第一周的周一', { exact: true }).fill('2026-08-31');
  await page.getByRole('button', { name: '保存学期设置', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('学期和作息时间已保存');
  await page.getByRole('button', { name: '课程管理', exact: true }).click();
  await expect(page.locator('.course-tile')).toHaveCount(9);
  await page.getByRole('button', { name: '添加课程', exact: true }).click();
  const dialog = page.getByRole('dialog');
  await dialog.getByLabel('课程名称', { exact: true }).fill('自动化测试课');
  await dialog.getByLabel('默认教室', { exact: true }).fill('实验楼 301');
  await dialog.getByLabel('规则 1 星期', { exact: true }).selectOption('6');
  await dialog.getByLabel('规则 1 上课周次', { exact: true }).fill('3-13,16-18');
  await dialog.getByRole('button', { name: '保存课程', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.locator('.course-tile')).toHaveCount(10);
  await page.reload(); await page.getByRole('button', { name: '课程管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '自动化测试课', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '周课表', exact: true }).click();
  await page.getByLabel('选择教学周').selectOption('3');
  await page.locator('.week-course').filter({ hasText: '自动化测试课' }).click();
  await page.getByRole('button', { name: '只修改这一次', exact: true }).click();
  await page.getByLabel('教室', { exact: true }).fill('临时教室 202');
  await page.getByRole('button', { name: '保存本次安排', exact: true }).click();
  await expect(page.locator('.week-course').filter({ hasText: '自动化测试课' })).toContainText('临时教室 202');
  await page.getByLabel('选择教学周').selectOption('4');
  await expect(page.locator('.week-course').filter({ hasText: '自动化测试课' })).toContainText('实验楼 301');
  await page.getByRole('button', { name: '导入与备份', exact: true }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出完整备份', exact: true }).click();
  expect((await downloadPromise).suggestedFilename()).toMatch(/课序完整备份.*\.json/);
  await page.screenshot({ path: 'test-results/desktop-transfer.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('手机布局、表格导入错误与追加导入', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 }); await page.goto('/');
  await expect(page.getByRole('heading', { name: /每一节课，都从容以赴/ })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: 'test-results/mobile-home.png', fullPage: true });
  await page.getByRole('button', { name: '导入与备份', exact: true }).click();
  await page.locator('input[type=file][accept=".csv,.xlsx"]').setInputFiles({ name: '课表.csv', mimeType: 'text/csv', buffer: Buffer.from('课程名称,星期,开始时间,结束时间,上课周次,教室,教师,备注\r\n周末练习,6,10:20,11:40,3-13,图书馆,,') });
  await expect(page.getByRole('dialog', { name: '导入预览' })).toBeVisible();
  await page.getByRole('button', { name: '确认追加导入', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: '课程管理', exact: true }).click();
  await expect(page.getByRole('heading', { name: '周末练习', exact: true })).toBeVisible();
  await page.getByLabel('搜索课程').fill('周末练习'); await expect(page.locator('.course-tile')).toHaveCount(1);
  await page.getByRole('button', { name: '删除周末练习', exact: true }).click(); await page.getByRole('button', { name: '确认删除', exact: true }).click();
  await expect(page.locator('.course-tile')).toHaveCount(0);
});

test('图片数据保持待校对，周末及表单冲突提示可用', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: '课程管理', exact: true }).click();
  const tile = page.locator('.course-tile').filter({ has: page.getByRole('heading', { name: '工程数学', exact: true }) });
  await expect(tile.getByText('待校对', { exact: true })).toBeVisible(); await tile.getByRole('button', { name: '编辑', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: /待校对/ })).toBeChecked();
  await page.getByRole('button', { name: '关闭弹窗' }).click();
  await page.getByRole('button', { name: '添加课程', exact: true }).click();
  await page.getByLabel('课程名称', { exact: true }).fill('冲突测试');
  await page.getByLabel('规则 1 上课周次', { exact: true }).fill('3');
  await page.getByRole('button', { name: '保存课程', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('重叠');
});

test('替换课表自动保留本机安全副本，并可恢复全部旧课程', async ({ page }) => {
  await page.goto('/'); await page.getByRole('button', { name: '导入与备份', exact: true }).click();
  await page.locator('input[type=file][accept=".csv,.xlsx"]').setInputFiles({ name: '替换.csv', mimeType: 'text/csv', buffer: Buffer.from('课程名称,星期,开始时间,结束时间,上课周次,教室,教师,备注\r\n替换后的课程,6,10:20,11:40,3-13,图书馆,,') });
  await page.getByRole('checkbox', { name: /替换当前学期/ }).check();
  await page.getByRole('button', { name: '备份并替换', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await expect(page.getByText('替换学期前', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '课程管理', exact: true }).click(); await expect(page.locator('.course-tile')).toHaveCount(1);
  await page.getByRole('button', { name: '导入与备份', exact: true }).click();
  await page.getByRole('button', { name: '选择恢复', exact: true }).click();
  await page.getByRole('button', { name: '先备份，再恢复', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.reload(); await page.getByRole('button', { name: '课程管理', exact: true }).click();
  await expect(page.locator('.course-tile')).toHaveCount(9);
});
