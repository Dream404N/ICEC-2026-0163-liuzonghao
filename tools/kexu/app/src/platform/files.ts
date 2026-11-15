import { Capacitor } from '@capacitor/core';
import { Filesystem, Directory } from '@capacitor/filesystem';
import { Share } from '@capacitor/share';
export async function saveFile(name: string, data: Blob | string, mime = 'application/json') {
  const blob = typeof data === 'string' ? new Blob([data], { type: mime }) : data;
  if (Capacitor.isNativePlatform()) {
    const encoded = await new Promise<string>((resolve, reject) => { const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(',')[1]); reader.onerror = reject; reader.readAsDataURL(blob); });
    const file = await Filesystem.writeFile({ path: name, data: encoded, directory: Directory.Cache });
    await Share.share({ title: '保存课表文件', url: file.uri });
  } else {
    const url = URL.createObjectURL(blob); const a = document.createElement('a'); a.href = url; a.download = name; a.click(); setTimeout(() => URL.revokeObjectURL(url), 30000);
  }
}
