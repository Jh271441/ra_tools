export function showWorkbenchToast(message: string, isError = false): void {
  if (typeof window === "undefined") return;
  const win = window as unknown as {
    showToast?: (msg: string, err?: boolean) => void;
  };
  win.showToast?.(message, isError);
}
