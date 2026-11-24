import { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Button } from './button';
import { Select } from './select';

export const PAGE_SIZES = [10, 20, 50, 100];

/** Shared list footer, using the same buttons and selector as the release views. */
export function Pagination({
  total,
  page,
  pageSize,
  loading = false,
  onPageChange,
  onPageSizeChange,
}: {
  total: number;
  page: number;
  pageSize: number;
  loading?: boolean;
  onPageChange: (page: number) => void;
  onPageSizeChange: (size: number) => void;
}) {
  const { t } = useTranslation();
  const pages = Math.ceil(total / pageSize);
  const [jump, setJump] = useState(String(page));
  useEffect(() => setJump(String(page)), [page]);
  const go = () => {
    if (loading || !pages || !/^\d+$/.test(jump)) return;
    onPageChange(Math.min(pages, Math.max(1, Number(jump))));
  };
  return (
    <nav
      aria-label={t('pagination.label')}
      className="flex min-w-0 flex-wrap items-center gap-2 border-t pt-3 text-sm"
    >
      <span className="mr-auto text-muted-foreground">
        {t('pagination.total', { count: total })}
      </span>
      <Select
        label={t('pagination.pageSize')}
        value={String(pageSize)}
        disabled={loading}
        options={PAGE_SIZES.map((size) => ({
          value: String(size),
          label: t('pagination.perPage', { count: size }),
        }))}
        onChange={(value) => onPageSizeChange(Number(value))}
      />
      <Button
        type="button"
        className="min-h-11"
        variant="outline"
        disabled={loading || !pages || page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        {t('pagination.previous')}
      </Button>
      <span aria-live="polite">{t('pagination.page', { page: pages ? page : 0, pages })}</span>
      <Button
        type="button"
        className="min-h-11"
        variant="outline"
        disabled={loading || !pages || page >= pages}
        onClick={() => onPageChange(page + 1)}
      >
        {t('pagination.next')}
      </Button>
      <label className="flex items-center gap-2 text-muted-foreground">
        <span>{t('pagination.jump')}</span>
        <input
          type="text"
          inputMode="numeric"
          pattern="[0-9]*"
          value={jump}
          disabled={loading || !pages}
          aria-label={t('pagination.jumpTo')}
          className="min-h-11 w-16 rounded-md border bg-background px-2 text-center text-foreground"
          onChange={(event) => setJump(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.nativeEvent.isComposing) go();
          }}
        />
      </label>
      <Button
        type="button"
        className="min-h-11"
        variant="outline"
        disabled={loading || !pages || !/^\d+$/.test(jump)}
        onClick={go}
      >
        {t('pagination.go')}
      </Button>
    </nav>
  );
}
