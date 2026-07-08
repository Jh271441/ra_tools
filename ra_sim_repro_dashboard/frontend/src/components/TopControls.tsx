import { Languages, Moon, RefreshCw, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { cn } from '../lib/utils';
import { Button } from './ui/button';

interface TopControlsProps {
  dark: boolean;
  onToggleDark: () => void;
  onRefresh: () => void;
  refreshing: boolean;
  compact?: boolean;
  className?: string;
}

export function TopControls({ dark, onToggleDark, onRefresh, refreshing, compact = false, className }: TopControlsProps) {
  const { t, i18n } = useTranslation();
  const nextLang = i18n.language === 'zh' ? 'en' : 'zh';

  return (
    <div className={cn('flex flex-wrap items-center gap-2', compact && 'grid grid-cols-1', className)}>
      <Button
        variant={compact ? 'ghost' : 'outline'}
        size={compact ? 'icon' : 'sm'}
        className={cn(compact ? 'sidebar-icon-button' : 'flex-1 whitespace-nowrap')}
        onClick={() => {
          localStorage.setItem('lang', nextLang);
          void i18n.changeLanguage(nextLang);
        }}
        title={t('language')}
        aria-label={t('language')}
      >
        <Languages className="h-4 w-4" />
        {!compact ? t('language') : null}
      </Button>
      <Button
        variant={compact ? 'ghost' : 'outline'}
        size={compact ? 'icon' : 'sm'}
        className={cn(compact ? 'sidebar-icon-button' : 'flex-1 whitespace-nowrap')}
        onClick={onToggleDark}
        title={t('theme')}
        aria-label={t('theme')}
      >
        {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        {!compact ? t('theme') : null}
      </Button>
      <Button
        variant={compact ? 'ghost' : 'default'}
        size={compact ? 'icon' : 'sm'}
        className={cn(compact ? 'sidebar-icon-button text-primary' : 'flex-[1.4] whitespace-nowrap')}
        onClick={onRefresh}
        disabled={refreshing}
        title={refreshing ? t('refreshing') : t('refresh')}
        aria-label={refreshing ? t('refreshing') : t('refresh')}
      >
        <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        {!compact ? (refreshing ? t('refreshing') : t('refresh')) : null}
      </Button>
    </div>
  );
}
