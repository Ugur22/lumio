import { createContext, useContext } from "react";

export type CodeActions = {
  askAboutRun: (text: string) => void;
  // True while a reply is streaming, when a new message cannot be sent.
  busy: boolean;
};

export const CodeActionsContext = createContext<CodeActions | undefined>(undefined);

export const useCodeActions = () => useContext(CodeActionsContext);
