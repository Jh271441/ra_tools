import { RefObject, useEffect } from "react";

export type ShortcutScope = "global" | "page" | "popover" | "modal";

export interface ShortcutBinding {
  id: string;
  scope: ShortcutScope;
  combo: string;
  handler: (event: KeyboardEvent) => boolean | void;
  allowInInput?: boolean;
  allowRepeat?: boolean;
  description?: string;
}

const SCOPE_PRIORITY: Record<ShortcutScope, number> = {
  global: 1,
  page: 2,
  popover: 3,
  modal: 4,
};

function isEditableTarget(target: EventTarget | null): boolean {
  if (!(target instanceof HTMLElement)) return false;
  if (target.isContentEditable) return true;
  if (target.closest('[role="textbox"]')) return true;
  const tag = target.tagName.toUpperCase();
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT";
}

function normalizeKey(key: string): string {
  const raw = String(key || "");
  if (raw === " ") return "Space";
  if (raw.length === 1) return raw.toLowerCase();
  return raw;
}

export function formatEventCombo(event: KeyboardEvent): string {
  const parts: string[] = [];
  if (event.ctrlKey) parts.push("Ctrl");
  if (event.metaKey) parts.push("Meta");
  if (event.altKey) parts.push("Alt");
  if (event.shiftKey && (event.key.length > 1 || /^[A-Za-z]$/.test(event.key))) parts.push("Shift");
  parts.push(normalizeKey(event.key));
  return parts.join("+");
}

export function normalizeCombo(combo: string): string {
  const tokens = String(combo || "")
    .split("+")
    .map((part) => part.trim())
    .filter(Boolean);
  const modifiers = new Set<string>();
  let mainKey = "";
  for (const token of tokens) {
    const lower = token.toLowerCase();
    if (lower === "ctrl" || lower === "control") modifiers.add("Ctrl");
    else if (lower === "meta" || lower === "cmd" || lower === "command") modifiers.add("Meta");
    else if (lower === "alt" || lower === "option") modifiers.add("Alt");
    else if (lower === "shift") modifiers.add("Shift");
    else mainKey = normalizeKey(token);
  }
  const ordered: string[] = [];
  if (modifiers.has("Ctrl")) ordered.push("Ctrl");
  if (modifiers.has("Meta")) ordered.push("Meta");
  if (modifiers.has("Alt")) ordered.push("Alt");
  if (modifiers.has("Shift")) ordered.push("Shift");
  if (mainKey) ordered.push(mainKey);
  return ordered.join("+");
}

interface ActiveScopeEntry {
  id: string;
  scope: ShortcutScope;
}

/**
 * Centralized keyboard shortcut arbiter with Focus-Trap scope stack & IME guard.
 * Higher-priority active scopes (e.g. `modal`, `popover`) automatically mask
 * lower-priority (`page`, `global`) shortcuts until popped.
 */
export class ShortcutManager {
  private bindings = new Map<string, ShortcutBinding>();
  private scopeStack: ActiveScopeEntry[] = [];
  private seq = 0;
  private attached = false;
  private boundListener: (event: KeyboardEvent) => void;

  constructor() {
    this.boundListener = (event) => this.handleKeyDown(event);
  }

  attach(target: Window | Document = window): void {
    if (this.attached || typeof target === "undefined") return;
    target.addEventListener("keydown", this.boundListener as EventListener);
    this.attached = true;
  }

  detach(target: Window | Document = window): void {
    if (!this.attached || typeof target === "undefined") return;
    target.removeEventListener("keydown", this.boundListener as EventListener);
    this.attached = false;
  }

  pushScope(scope: ShortcutScope): () => void {
    const id = `scope-${++this.seq}`;
    this.scopeStack.push({ id, scope });
    return () => {
      const idx = this.scopeStack.findIndex((item) => item.id === id);
      if (idx >= 0) this.scopeStack.splice(idx, 1);
    };
  }

  activeMinimumScopePriority(): number {
    if (!this.scopeStack.length) return SCOPE_PRIORITY.global;
    let highest = SCOPE_PRIORITY.global;
    for (const entry of this.scopeStack) {
      const prio = SCOPE_PRIORITY[entry.scope];
      if (prio > highest) highest = prio;
    }
    return highest;
  }

  hasActiveModalOrPopover(): boolean {
    return this.activeMinimumScopePriority() >= SCOPE_PRIORITY.popover;
  }

  register(binding: Omit<ShortcutBinding, "id">): () => void {
    this.attach();
    const id = `shortcut-${++this.seq}`;
    this.bindings.set(id, {
      ...binding,
      id,
      combo: normalizeCombo(binding.combo),
    });
    return () => {
      this.bindings.delete(id);
    };
  }

  handleKeyDown(event: KeyboardEvent): boolean {
    // Strictly guard IME composition (Chinese/Japanese/Korean input methods)
    if (event.isComposing || event.keyCode === 229 || event.key === "Process") {
      return false;
    }
    if (event.defaultPrevented) return false;

    const minPriority = this.activeMinimumScopePriority();
    const combo = formatEventCombo(event);
    const inEditable = isEditableTarget(event.target);

    // Evaluate newest bindings of highest priority first
    const candidates = Array.from(this.bindings.values())
      .filter((binding) => {
        if (SCOPE_PRIORITY[binding.scope] < minPriority) return false;
        if (binding.combo !== combo) return false;
        if (event.repeat && !binding.allowRepeat) return false;
        if (inEditable && !binding.allowInInput) return false;
        return true;
      })
      .sort((a, b) => SCOPE_PRIORITY[b.scope] - SCOPE_PRIORITY[a.scope]);

    for (const binding of candidates) {
      const handled = binding.handler(event);
      if (handled !== false) {
        return true;
      }
    }
    return false;
  }

  listBindings(): ShortcutBinding[] {
    return Array.from(this.bindings.values());
  }
}

export const shortcutManager = new ShortcutManager();

if (typeof window !== "undefined") {
  shortcutManager.attach(window);
  (window as unknown as { __RA_SHORTCUT_MANAGER__?: ShortcutManager }).__RA_SHORTCUT_MANAGER__ =
    shortcutManager;
}

export function useShortcut(
  scope: ShortcutScope,
  combo: string,
  handler: (event: KeyboardEvent) => boolean | void,
  options: { enabled?: boolean; allowInInput?: boolean; allowRepeat?: boolean } = {},
): void {
  const { enabled = true, allowInInput = false, allowRepeat = false } = options;
  useEffect(() => {
    if (!enabled) return;
    return shortcutManager.register({
      scope,
      combo,
      handler,
      allowInInput,
      allowRepeat,
    });
  }, [scope, combo, handler, enabled, allowInInput, allowRepeat]);
}

const FOCUSABLE_SELECTOR =
  'a[href], button:not([disabled]), textarea:not([disabled]), input:not([disabled]):not([type="hidden"]), select:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function useFocusTrap(
  active: boolean,
  containerRef: RefObject<HTMLElement | null>,
  scope: ShortcutScope = "modal",
): void {
  useEffect(() => {
    if (!active) return;
    const popScope = shortcutManager.pushScope(scope);
    const handleTab = (event: KeyboardEvent) => {
      if (event.key !== "Tab" || !containerRef.current) return;
      const nodes = Array.from(
        containerRef.current.querySelectorAll<HTMLElement>(FOCUSABLE_SELECTOR),
      ).filter((el) => el.offsetParent !== null || el === document.activeElement);
      if (!nodes.length) return;
      const first = nodes[0];
      const last = nodes[nodes.length - 1];
      if (event.shiftKey) {
        if (document.activeElement === first || !containerRef.current.contains(document.activeElement)) {
          event.preventDefault();
          last.focus();
        }
      } else if (document.activeElement === last || !containerRef.current.contains(document.activeElement)) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener("keydown", handleTab);
    return () => {
      document.removeEventListener("keydown", handleTab);
      popScope();
    };
  }, [active, containerRef, scope]);
}
