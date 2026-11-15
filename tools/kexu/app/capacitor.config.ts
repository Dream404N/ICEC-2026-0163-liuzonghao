import type { CapacitorConfig } from '@capacitor/cli';
const config: CapacitorConfig = {
  appId: 'cn.kexu.schedule', appName: '课序', webDir: 'dist',
  android: { allowMixedContent: false },
  plugins: { LocalNotifications: { smallIcon: 'ic_stat_school', iconColor: '#16786c' } },
};
export default config;
