import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { Check, ChevronDown } from 'lucide-react';
import { Button } from './button';

interface Option { value: string; label: string; disabled?: boolean }

/** Shared single select, using the project's Button and theme tokens. */
export function Select({ value, options, onChange, label, disabled }: {
  value: string; options: Option[]; onChange: (value: string) => void; label: string; disabled?: boolean;
}) {
  const id = useId();
  const trigger = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const [position, setPosition] = useState({left:0,top:0,width:0,maxHeight:0});
  const selected = options.find(option => option.value === value);
  const close = (focus = false) => { setOpen(false); if (focus) trigger.current?.focus({preventScroll:true}); };
  const move = (direction: number | 'first' | 'last') => {
    const buttons = Array.from(panel.current?.querySelectorAll<HTMLButtonElement>('button:not(:disabled)') || []);
    const current = buttons.indexOf(document.activeElement as HTMLButtonElement);
    buttons[direction === 'first' ? 0 : direction === 'last' ? buttons.length - 1 : (current + direction + buttons.length) % buttons.length]?.focus();
  };
  useLayoutEffect(() => {
    if (!open || disabled) return;
    const place = () => {
      const rect = trigger.current!.getBoundingClientRect();
      const view = window.visualViewport;
      const left = view?.offsetLeft || 0, top = view?.offsetTop || 0;
      const right = left + (view?.width || innerWidth), bottom = top + (view?.height || innerHeight);
      const width = Math.min(Math.max(rect.width, 180), right - left - 16);
      const below = bottom - rect.bottom - 12, above = rect.top - top - 12;
      const height = Math.min(320, below >= Math.min(180, above) ? below : above);
      setPosition({left:Math.max(left + 8, Math.min(rect.left, right - width - 8)),top:below >= Math.min(180, above) ? rect.bottom + 4 : Math.max(top + 8, rect.top - 4 - Math.min(height, options.length * 44 + 8)),width,maxHeight:Math.max(44,height)});
    };
    place();
    (panel.current?.querySelector<HTMLButtonElement>('[aria-selected="true"]:not(:disabled)') || panel.current?.querySelector<HTMLButtonElement>('button:not(:disabled)'))?.focus({preventScroll:true});
    window.addEventListener('resize',place);window.addEventListener('scroll',place,true);
    window.visualViewport?.addEventListener('resize',place);window.visualViewport?.addEventListener('scroll',place);
    return () => {window.removeEventListener('resize',place);window.removeEventListener('scroll',place,true);window.visualViewport?.removeEventListener('resize',place);window.visualViewport?.removeEventListener('scroll',place);};
  }, [open, disabled, options.length]);
  useEffect(() => {
    if (!open) return;
    const outside = (event: Event) => { if (!panel.current?.contains(event.target as Node) && !trigger.current?.contains(event.target as Node)) close(); };
    document.addEventListener('pointerdown',outside);document.addEventListener('focusin',outside);
    return () => {document.removeEventListener('pointerdown',outside);document.removeEventListener('focusin',outside);};
  }, [open]);
  useEffect(() => { if (disabled) setOpen(false); }, [disabled]);
  return <div className="ui-select min-w-0">
    <Button ref={trigger} type="button" variant="outline" className="ui-select-trigger min-h-11 max-w-full" disabled={disabled} aria-label={label} aria-haspopup="listbox" aria-expanded={open} aria-controls={`${id}-options`} onClick={() => setOpen(!open)} onKeyDown={event => {
      if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {event.preventDefault();setOpen(true);}
    }}><span className="truncate">{selected?.label || value}</span><ChevronDown className="h-4 w-4 shrink-0" aria-hidden="true"/></Button>
    {open && !disabled && createPortal(<div ref={panel} id={`${id}-options`} role="listbox" aria-label={label} style={position} className="ui-select-panel fixed z-50 overflow-y-auto overscroll-contain rounded-md border bg-card p-1 text-foreground shadow-lg" onKeyDown={event => {
      if (event.key === 'Escape') {event.preventDefault();event.stopPropagation();close(true);}
      else if (event.key === 'Tab') close(true);
      else if (['ArrowDown','ArrowUp','Home','End'].includes(event.key)) {event.preventDefault();move(event.key === 'Home' ? 'first' : event.key === 'End' ? 'last' : event.key === 'ArrowDown' ? 1 : -1);}
    }}>{options.map(option => <button key={option.value} type="button" role="option" aria-selected={option.value === value} disabled={option.disabled} className="ui-select-option flex min-h-11 w-full items-center gap-2 rounded px-2 text-left text-sm hover:bg-muted focus:bg-muted focus:outline-none disabled:pointer-events-none disabled:opacity-50" onClick={() => {onChange(option.value);close(true);}}><Check className={`h-4 w-4 shrink-0${option.value === value ? '' : ' invisible'}`} aria-hidden="true"/><span className="min-w-0 break-words">{option.label}</span></button>)}</div>,document.body)}
  </div>;
}
