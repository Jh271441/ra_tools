import { describe, expect, it, vi } from "vitest";
import { ShortcutManager } from "./shortcutManager";

describe("ShortcutManager", () => {
  it("suppresses lower-priority page shortcuts while a modal scope is active", () => {
    const mgr = new ShortcutManager();
    const pageSpy = vi.fn();
    const modalSpy = vi.fn();

    mgr.register({ scope: "page", combo: "ArrowRight", handler: pageSpy });
    mgr.register({ scope: "modal", combo: "Escape", handler: modalSpy });

    mgr.handleKeyDown(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    expect(pageSpy).toHaveBeenCalledTimes(1);

    const popModal = mgr.pushScope("modal");
    mgr.handleKeyDown(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    expect(pageSpy).toHaveBeenCalledTimes(1); // blocked by modal scope!

    mgr.handleKeyDown(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(modalSpy).toHaveBeenCalledTimes(1);

    popModal();
    mgr.handleKeyDown(new KeyboardEvent("keydown", { key: "ArrowRight" }));
    expect(pageSpy).toHaveBeenCalledTimes(2);
  });

  it("ignores IME composition events and editable inputs by default", () => {
    const mgr = new ShortcutManager();
    const spy = vi.fn();
    mgr.register({ scope: "page", combo: "r", handler: spy });

    // IME composing event must be ignored
    const imeEvent = new KeyboardEvent("keydown", { key: "r", isComposing: true });
    expect(mgr.handleKeyDown(imeEvent)).toBe(false);
    expect(spy).not.toHaveBeenCalled();

    // Typing inside an input must be ignored unless allowInInput=true
    const input = document.createElement("input");
    document.body.appendChild(input);
    const inputEvent = new KeyboardEvent("keydown", { key: "r", bubbles: true });
    Object.defineProperty(inputEvent, "target", { value: input });
    expect(mgr.handleKeyDown(inputEvent)).toBe(false);
    expect(spy).not.toHaveBeenCalled();
    input.remove();
  });
});
