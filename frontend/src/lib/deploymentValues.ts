/** Empty or out-of-range deployment values must not create invalid maps or tight polling loops. */
export function boundedEnvNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  if (!value?.trim()) return fallback
  const parsed = Number(value)
  return Number.isFinite(parsed) && parsed >= min && parsed <= max ? parsed : fallback
}
