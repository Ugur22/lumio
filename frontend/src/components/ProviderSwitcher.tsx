import { useEffect, useState } from "react";
import { useMediaQuery } from "../hooks/useMediaQuery";
import { useChat, useSetChatModel } from "../hooks/useChats";
import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { useSwitchChatProfile } from "../hooks/useStory";
import { modelBody, overrideModel, shownModel, showDefaultItem } from "../lib/chatModel";
import { effectiveProfile } from "../lib/providers";
import type { ChatModelBody } from "../types";
import { InlineModelPicker, ModelPicker } from "./ModelPicker";
import { ChevronDownIcon } from "./icons";
import { BottomSheet } from "./ui/BottomSheet";
import { Button, Select } from "./ui";
import { focusRing } from "./ui/styles";

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
  const phone = useMediaQuery("(max-width: 720px)");
  const [sheetOpen, setSheetOpen] = useState(false);
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

  const modelProps = {
    heading: blank ? "Model for the next chat" : "Model for this chat",
    current: shownModel({ chatModel: chat?.model, pending: pendingModel, profileModel: active.model, blank }),
    defaultModel: active.model,
    showDefault: showDefaultItem(override),
    profileId: active.id,
    saveError: setModel.error?.message ?? null,
    onPickWithWindows: pick,
    onManage,
  };
  const providerSelect = (
    <Select
      variant="compact"
      aria-label={chatId ? "Provider for this chat" : "Provider for new chats"}
      value={active.id}
      onChange={change}
      options={data.profiles.map((p) => ({ value: p.id, label: p.name }))}
      className="max-w-[10rem] max-[720px]:max-w-none"
    />
  );

  // One chip on phones keeps the header to a single row; the two controls move into a sheet.
  if (phone) {
    return (
      <>
        <button
          type="button"
          disabled={chatId !== null && !chat}
          aria-label={`Provider and model: ${active.name}, ${modelProps.current}`}
          onClick={() => setSheetOpen(true)}
          // The pill is visually small, so the pseudo-element extends the tap area to 44px.
          className={`relative inline-flex max-w-full items-center gap-1 rounded-full border border-border bg-surface px-2 py-0.5 text-xs text-muted after:absolute after:-inset-x-1 after:-inset-y-2.5 after:content-[''] hover:text-text disabled:opacity-60 ${focusRing}`}
        >
          <span className="truncate">
            {active.name} · {modelProps.current}
          </span>
          <ChevronDownIcon width={12} height={12} aria-hidden="true" className="flex-none" />
        </button>
        <BottomSheet open={sheetOpen} onClose={() => setSheetOpen(false)} title="Provider and model">
          <div className="flex flex-col gap-3 text-muted">
            {fellBack && <p className="text-[13px]">This chat&apos;s provider was removed. Using the default provider.</p>}
            {chatSwitch.error && (
              <p role="alert" className="text-[13px] text-warn-bar">
                {chatSwitch.error.message}
              </p>
            )}
            {providerSelect}
            <InlineModelPicker
              {...modelProps}
              onManage={() => {
                setSheetOpen(false);
                onManage();
              }}
              onDone={() => setSheetOpen(false)}
            />
          </div>
        </BottomSheet>
      </>
    );
  }

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
      {providerSelect}
      <ModelPicker
        disabled={chatId !== null && !chat}
        {...modelProps}
      />
    </div>
  );
}
