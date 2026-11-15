import type { Reminder } from '../domain/types';
export interface LogSyncStatus {
  enabled: boolean;
  time: string;
  repo: string;
  branch: string;
  directory: string;
  tokenConfigured: boolean;
  tokenFile: string;
  logsDir: string;
  files: number;
  todayCount: number;
  nextRunAt: string | null;
  lastCommit: string;
  lastCommitAt: string;
  lastCommitFiles: number;
  lastError: string;
  lastResult: LogSyncResult | null;
}
export interface LogSyncResult {
  ok: boolean;
  reason: string;
  message?: string;
  sha?: string;
  files?: number;
}
export {};
declare global {
  interface Window {
    kexu?: {
      schedule(reminders: Reminder[], sound: boolean): Promise<{ count: number; error?: string }>;
      testNotification(reminder: Reminder, sound: boolean): Promise<void>;
      notificationStatus(): Promise<{ enabled: boolean; error?: string; warning?: string }>;
      setAutoStart(enabled: boolean): Promise<boolean>;
      getAutoStart(): Promise<boolean>;
      logSyncStatus(): Promise<LogSyncStatus>;
      syncLogsNow(): Promise<LogSyncResult>;
      setLogSyncConfig(patch: { enabled?: boolean; time?: string; tokenFile?: string }): Promise<{ enabled: boolean; time: string; tokenFile?: string }>;
      openLogsDir(): Promise<string>;
    };
  }
}
