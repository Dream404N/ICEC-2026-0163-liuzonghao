import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import path from 'node:path';
const java = process.env.JAVA_HOME || path.resolve('.tools/jdk');
const sdk = process.env.ANDROID_HOME || process.env.ANDROID_SDK_ROOT || path.resolve('.tools/android-sdk');
if (!existsSync(java) || !existsSync(sdk)) { console.error('需要 JDK 21 和 Android SDK 36。运行 scripts/bootstrap-android.ps1 或配置 JAVA_HOME、ANDROID_HOME。'); process.exit(1); }
const executable = process.platform === 'win32' ? 'gradlew.bat' : './gradlew';
const result = spawnSync(executable, ['assembleDebug', '--no-daemon'], { cwd: 'android', stdio: 'inherit', shell: process.platform === 'win32', env: { ...process.env, JAVA_HOME: java, ANDROID_HOME: sdk, ANDROID_SDK_ROOT: sdk } });
process.exit(result.status ?? 1);
