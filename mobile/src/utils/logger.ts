type LogValue = string | number | boolean | null | undefined | Error | Record<string, unknown>;

const isDev = __DEV__;

function write(prefix: string, color: string, values: LogValue[]) {
  if (!isDev) return;
  console.log(`%c${prefix}`, `color:${color};font-weight:bold`, ...values);
}

export const logger = {
  api: (...values: LogValue[]) => write('[API]', '#3B82F6', values),
  db: (...values: LogValue[]) => write('[DB]', '#00FF88', values),
  gps: (...values: LogValue[]) => write('[GPS]', '#FF8C00', values),
  error: (...values: LogValue[]) => write('[ERROR]', '#FF3B5C', values),
};
