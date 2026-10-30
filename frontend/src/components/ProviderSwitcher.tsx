import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { Button, Select } from "./ui";

interface Props {
  onManage: () => void;
}


export function ProviderSwitcher({ onManage }: Props) {
  const { data } = useProfiles();
  const actions = useProfileActions();
  if (!data) return null;

  const active = data.profiles.find((p) => p.id === data.active);

  if (!active) {
    return (
      <Button variant="bare" onClick={onManage} className="rounded-lg px-2.5 py-1 text-accent">
        Add a provider
      </Button>
    );
  }

  return (
    <div className="flex min-w-0 pl-2 items-center gap-2 text-[13px] text-muted">
      <Select
        variant="compact"
        aria-label="Provider"
        value={active.id}
        onChange={(id) => void actions.activate(id)}
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
