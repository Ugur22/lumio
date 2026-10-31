import { useEffect } from "react";
import { useChat, useSetChatModel } from "../hooks/useChats";
import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { useSwitchChatProfile } from "../hooks/useStory";
import { modelBody, overrideModel, shownModel, showDefaultItem } from "../lib/chatModel";
import { effectiveProfile } from "../lib/providers";
import type { ChatModelBody } from "../types";
import { ModelPicker } from "./ModelPicker";
import { Button, Select } from "./ui";

interface Props {
  // The open chat; null means a blank chat, where the picker sets the default for new chats.
  chatId: string | null;
  // A blank chat's unsent model pick, held by the parent and sent with the first message.
  pendingModel: ChatModelBody | null;
  onPendingModel: (pick: ChatModelBody | null) => void;
  onManage: () => void;
}

export function ProviderSwitcher({ chatId, pendingModel, onPendingModel, onManage }: Props) {
  const { data } = useProfiles();
  const chat = useChat(chatId).data;
  const actions = useProfileActions();
  const chatSwitch = useSwitchChatProfile(chat);
  const setModel = useSetChatModel();
  // One mutation serves every chat, so a failed pick must not follow you to the next one.
  const resetModelError = setModel.reset;
  useEffect(() => resetModelError(), [chatId, resetModelError]);
  if (!data) return null;

  const { profile: active, fellBack } = effectiveProfile(data, chatId ? chat?.profile_id : null);

  if (!active) {
    return (
      <Button variant="bare" onClick={onManage} className="rounded-lg px-2.5 py-1 text-accent">
        Add a provider
      </Button>
    );
  }

  const change = (id: string) => {
    if (chatId) chatSwitch.switchTo(id);
    else {
      // The pick was made against the old provider's model list.
      onPendingModel(null);
      void actions.activate(id);
    }
  };

  const blank = chatId === null;
  const override = overrideModel(chat?.model, pendingModel, blank);
  const pick = (model: string | null, windows: Readonly<Record<string, number>>) => {
    const body = modelBody(model, windows);
    if (chatId === null) return onPendingModel(model === null ? null : body);
    return setModel.mutateAsync({ id: chatId, body });
  };

  return (
    <div className="flex min-w-0 pl-2 items-center gap-2 text-[13px] text-muted">
      {fellBack && (
        <span className="flex-none max-[520px]:hidden" title="This chat's provider was removed">
          Using default provider
        </span>
      )}
      {chatSwitch.error && (
        <span role="alert" className="flex-none text-warn-bar">
          {chatSwitch.error.message}
        </span>
      )}
      <Select
        variant="compact"
        aria-label={chatId ? "Provider for this chat" : "Provider for new chats"}
        value={active.id}
        onChange={change}
        options={data.profiles.map((p) => ({ value: p.id, label: p.name }))}
        className="max-w-[10rem]"
      />
      <ModelPicker
        disabled={chatId !== null && !chat}
        heading={blank ? "Model for the next chat" : "Model for this chat"}
        current={shownModel({ chatModel: chat?.model, pending: pendingModel, profileModel: active.model, blank })}
        defaultModel={active.model}
        showDefault={showDefaultItem(override)}
        profileId={active.id}
        saveError={setModel.error?.message ?? null}
        onPickWithWindows={pick}
        onManage={onManage}
      />
    </div>
  );
}
