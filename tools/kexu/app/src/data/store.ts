import { openDB } from 'idb';
import { useSyncExternalStore } from 'react';
import type { AppState } from '../domain/types';
import { initialState } from '../domain/seed';
import { validateState } from './validation';

let state: AppState;
let storageError = '';
const listeners = new Set<() => void>();
let saving = Promise.resolve();
const database = openDB('kexu-v1', 2, { upgrade(db) { if (!db.objectStoreNames.contains('app')) db.createObjectStore('app'); if (!db.objectStoreNames.contains('backups')) db.createObjectStore('backups'); } });
export async function loadStore() {
  const db = await database;
  const saved: unknown = await db.get('app', 'state');
  if (saved !== undefined) { validateState(saved); state = saved; }
  else { state = initialState(); await db.put('app', state, 'state'); }
}
export const getState = () => state;
export const getStorageError = () => storageError;
export function updateStore(update: (current: AppState) => AppState) {
  state = update(state);
  const snapshot = structuredClone(state);
  saving = saving.catch(() => {}).then(async () => {
    try { const db = await database; await db.put('app', snapshot, 'state'); storageError = ''; }
    catch (error) { storageError = `本地保存失败，请立即导出备份：${String(error)}`; state = { ...state }; }
    for (const fn of listeners) fn();
  });
  for (const fn of listeners) fn();
}
export const flushStore = () => saving;
export interface SafetyBackup { id: string; label: string; createdAt: string; state: AppState }
export async function saveSafetyBackup(label: string) {
  await flushStore();
  const backup: SafetyBackup = { id: crypto.randomUUID(), label, createdAt: new Date().toISOString(), state: structuredClone(state) };
  const db = await database; await db.put('backups', backup, backup.id);
  return backup;
}
export async function safetyBackups(): Promise<SafetyBackup[]> {
  const db = await database;
  return (await db.getAll('backups') as SafetyBackup[]).sort((a, b) => b.createdAt.localeCompare(a.createdAt));
}
export function useStore() { return useSyncExternalStore(fn => { listeners.add(fn); return () => { listeners.delete(fn); }; }, getState); }
export function subscribe(fn: () => void) { listeners.add(fn); return () => { listeners.delete(fn); }; }
