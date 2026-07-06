import { Languages, Moon, RefreshCw, Sun } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { Button } from './ui/button';

interface TopControlsProps {
  dark: boolean;
  onToggleDark: () => void;
  onRefresh: () => void;
  refreshing: boolean;
}

export function TopControls({ dark, onToggleDark, onRefresh, refreshing }: TopControlsProps) {
  const { t, i18n } = useTranslation();
  const nextLang = i18n.language === 'zh' ? 'en' : 'zh';

  return (
    <div className="flex flex-wrap items-center gap-2">
      <Button
        variant="outline"
        size="sm"
        onClick={() => {
          localStorage.setItem('lang', nextLang);
          void i18n.changeLanguage(nextLang);
        }}
      >
        <Languages className="h-4 w-4" />
        {t('language')}
      </Button>
      <Button variant="outline" size="sm" onClick={onToggleDark}>
        {dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        {t('theme')}
      </Button>
      <Button size="sm" onClick={onRefresh} disabled={refreshing}>
        <RefreshCw className={`h-4 w-4 ${refreshing ? 'animate-spin' : ''}`} />
        {refreshing ? t('refreshing') : t('refresh')}
      </Button>
    </div>
  );
}
