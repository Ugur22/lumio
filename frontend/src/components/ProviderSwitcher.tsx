import { useProfileActions, useProfiles } from "../hooks/useProfiles";

interface Props {
  onManage: () => void;
}

const focus = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";

export function ProviderSwitcher({ onManage }: Props) {
  const { data } = useProfiles();
  const actions = useProfileActions();
  if (!data) return null;

  const active = data.profiles.find((p) => p.id === data.active);

  if (!active) {
    return (
      <button type="button" onClick={onManage} className={`ml-auto rounded-lg px-2.5 py-1 text-accent ${focus}`}>
        Add a provider
      </button>
    );
  }

  return (
    <div className="ml-auto flex min-w-0 items-center gap-2 text-[13px] text-muted">
      <select
        aria-label="Provider"
        value={active.id}
        onChange={(e) => void actions.activate(e.target.value)}
        className={`max-w-[9rem] truncate rounded-lg border border-border bg-surface px-2 py-1 text-text ${focus}`}
      >
        {data.profiles.map((p) => (
          <option key={p.id} value={p.id}>
            {p.name}
          </option>
        ))}
      </select>
      <button
        type="button"
        onClick={onManage}
        title="Change model or provider settings"
        className={`max-w-[11rem] truncate rounded-lg px-2 py-1 hover:bg-bubble hover:text-text ${focus}`}
      >
        {active.model}
      </button>
    </div>
  );
}
