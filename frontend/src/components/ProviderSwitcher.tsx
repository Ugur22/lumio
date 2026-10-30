import { useChat } from "../hooks/useChats";
import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { useSwitchChatProfile } from "../hooks/useStory";
import { effectiveProfile } from "../lib/providers";
import { Button, Select } from "./ui";

interface Props {
  // The open chat; null means a blank chat, where the picker sets the default for new chats.
  chatId: string | null;
  onManage: () => void;
}

export function ProviderSwitcher({ chatId, onManage }: Props) {
  const { data } = useProfiles();
  const chat = useChat(chatId).data;
  const actions = useProfileActions();
  const chatSwitch = useSwitchChatProfile(chat);
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
    else void actions.activate(id);
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
      <Button
        variant="bare"
        onClick={onManage}
        title="Change model or provider settings"
        className="min-w-0 max-w-[11rem] truncate rounded-lg px-2 py-1 hover:bg-bubble hover:text-text max-[520px]:hidden"
      >
        {active.model}
      </Button>
    </div>
  );
}
