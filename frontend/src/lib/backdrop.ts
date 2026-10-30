/**
 * A drag that starts inside the dialog and ends on the backdrop fires `click` on the dialog
 * itself, so the click target alone cannot tell it from a real backdrop click.
 */
export function isBackdropClick(pressTarget: EventTarget | null, clickTarget: EventTarget | null, dialog: EventTarget | null): boolean {
  return dialog !== null && pressTarget === dialog && clickTarget === dialog;
}
