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
