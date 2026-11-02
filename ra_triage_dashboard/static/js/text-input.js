/* Shared IME guards. Linux/X11 can report an IME key with isComposing=false. */
function isImeComposing(event) {
  return Boolean(
    event?.isComposing || event?.keyCode === 229 || event?.which === 229
    || event?.target?.dataset?.imeComposing === "1"
  );
}

function hasFocusedTextInput(root) {
  const active = document.activeElement;
  return Boolean(root?.contains?.(active) && active?.matches?.(
    "textarea, input:not([type='checkbox']):not([type='radio']):not([type='button']):not([type='submit']), [contenteditable='true'], [role='textbox']"
  ));
}

function mediaShortcutHasEditableTarget(target) {
  // Review checkboxes use the displayed number shortcuts. They must not take
  // keyboard ownership away from the video while a tag group is open.
  if (target?.matches?.('input[type="checkbox"]') && target.closest?.(
    "#reviewPane .review-dropdown[open], #caseLabelingEditor .review-dropdown[open]"
  )) return false;
  return Boolean(target?.closest?.(
    "input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox'], .ui-select, .review-status-picker, .detail-media-picker"
  ));
}
