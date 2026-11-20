/** Display-only names. Original keys remain authoritative for API requests and links. */
export function releaseDate(key: string): string | null {
  const match = key.match(/^(?:1\.)?gen4-release-(\d{4})(\d{2})(\d{2})(?:\.\d+)?$/)
    || key.match(/^release(\d{4})(\d{2})(\d{2})$/)
    || key.match(/^(\d{4})[_-](\d{2})[_-](\d{2})(?:_v\d+)?$/);
  if (!match) return null;
  const date = `${match[1]}-${match[2]}-${match[3]}`;
  const parsed = new Date(`${date}T00:00:00Z`);
  return !Number.isNaN(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === date ? date : null;
}

export function releaseName(key?: string | null, withYear = false): string {
  if (!key) return '—';
  const date = releaseDate(key);
  if (!date) return key;
  const year = new Intl.DateTimeFormat('en', { year: 'numeric', timeZone: 'Asia/Shanghai' }).format(new Date());
  return withYear || date.slice(0, 4) !== year ? date : date.slice(5);
}
