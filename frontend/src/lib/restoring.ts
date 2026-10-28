interface State {
  chosen: string | null | undefined;
  listPending: boolean;
  currentId: string | null;
  chatPending: boolean;
}

// Before the list and the newest chat have loaded there is no answer yet to "which chat is this?",
// and showing the blank New chat screen for that moment is a flicker that then jumps to the real chat.
export function isRestoring({ chosen, listPending, currentId, chatPending }: State): boolean {
  if (chosen !== undefined) return false;
  return listPending || (currentId !== null && chatPending);
}
