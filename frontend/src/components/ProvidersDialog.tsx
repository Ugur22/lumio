import { useEffect, useRef, useState, type FormEvent } from "react";
import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { useWebKeyActions, useWebStatus } from "../hooks/useWebSearch";
import { formatTokens } from "../lib/context";
import { detectPreset, hostOf, PRESETS, presetById } from "../lib/providers";
import type { Profile } from "../types";
import { PressButton } from "./PressButton";

interface Props {
  open: boolean;
  onClose: () => void;
}

type View = { kind: "list" } | { kind: "form"; profile: Profile | null };
type Notice = { kind: "ok" | "error"; text: string } | null;

const MIN_WINDOW = 1000;

const focus = "focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent";
const field = `rounded-xl border border-border bg-bg px-3 py-2 ${focus}`;
const secondary = `rounded-xl border border-border bg-surface px-3.5 py-2 text-muted shadow-soft hover:text-text disabled:opacity-50 ${focus}`;
const primary = `rounded-xl bg-accent px-3.5 py-2 font-semibold text-on-accent shadow-soft disabled:opacity-50 ${focus} focus-visible:outline-offset-2`;

function keyLabel(p: Profile): string {
  if (!p.needs_key) return "No key needed";
  if (!p.configured) return "No key";
  const tail = p.last4 ? ` ending in ${p.last4}` : "";
  return p.source === "env" ? `Key from .env${tail}` : `Key in keychain${tail}`;
}

export function ProvidersDialog({ open, onClose }: Props) {
  const ref = useRef<HTMLDialogElement>(null);
  const [view, setView] = useState<View>({ kind: "list" });

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
  }, [open]);

  function close() {
    setView({ kind: "list" });
    onClose();
  }

  return (
    <dialog
      ref={ref}
      aria-labelledby="providers-title"
      onClose={close}
      onClick={(e) => e.target === ref.current && close()}
      className="m-auto w-[min(92vw,30rem)] rounded-2xl border border-border bg-surface p-0 text-text shadow-lift backdrop:bg-black/40"
    >
      {view.kind === "list" ? (
        <ProfileListView onAdd={() => setView({ kind: "form", profile: null })} onEdit={(p) => setView({ kind: "form", profile: p })} onClose={close} />
      ) : (
        // Keyed so switching between profiles never carries a typed key over.
        <ProfileForm key={view.profile?.id ?? "new"} profile={view.profile} onDone={() => setView({ kind: "list" })} />
      )}
    </dialog>
  );
}

interface ListProps {
  onAdd: () => void;
  onEdit: (p: Profile) => void;
  onClose: () => void;
}

function ProfileListView({ onAdd, onEdit, onClose }: ListProps) {
  const { data, isPending, error } = useProfiles();
  const actions = useProfileActions();
  const [failure, setFailure] = useState<string | null>(null);

  async function activate(id: string) {
    setFailure(null);
    try {
      await actions.activate(id);
    } catch (err) {
      setFailure((err as Error).message);
    }
  }

  return (
    <div className="flex flex-col gap-4 p-5">
      <h2 id="providers-title" className="font-display text-lg font-semibold">
        Providers
      </h2>
      {isPending && <p className="text-muted">Loading…</p>}
      {error && <p role="alert" className="text-warn-bar">{error.message}</p>}
      {data && data.profiles.length === 0 && (
        <p className="text-muted">No provider yet. Add one to start chatting.</p>
      )}
      <ul className="flex flex-col gap-2">
        {data?.profiles.map((p) => (
          <li key={p.id} className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-2.5">
            <input
              type="radio"
              name="active-provider"
              aria-label={`Use ${p.name}`}
              checked={data.active === p.id}
              onChange={() => activate(p.id)}
              className={`accent-[var(--accent)] ${focus}`}
            />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{p.name}</div>
              <div className="truncate text-[12px] text-muted">
                {hostOf(p.base_url)} · {p.model} · {keyLabel(p)}
                {p.context_window ? ` · ${formatTokens(p.context_window)} context` : ""}
              </div>
            </div>
            <button type="button" onClick={() => onEdit(p)} className={`rounded px-2 py-1 text-muted hover:text-text ${focus}`}>
              Edit
            </button>
          </li>
        ))}
      </ul>
      {failure && <p role="alert" className="text-warn-bar">{failure}</p>}
      <WebSearchSection />
      <div className="flex items-center gap-2">
        <PressButton type="button" onClick={onAdd} hover={1.02} press={0.97} className={primary}>
          Add provider
        </PressButton>
        <button type="button" onClick={onClose} className={`ml-auto rounded px-2 py-1 text-muted hover:text-text ${focus}`}>
          Close
        </button>
      </div>
    </div>
  );
}

function WebSearchSection() {
  const { data } = useWebStatus();
  const actions = useWebKeyActions();
  const [key, setKey] = useState("");
  const [replacing, setReplacing] = useState(false);
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setFailure(null);
    try {
      await action();
    } catch (err) {
      setFailure((err as Error).message);
    } finally {
      setBusy(false);
    }
  }

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const typed = key.trim();
    if (!typed) return;
    // Cleared before the request settles so the secret never lingers in the DOM or state.
    setKey("");
    return run(async () => {
      await actions.save(typed);
      setReplacing(false);
    });
  }

  const showForm = data !== undefined && (!data.configured || replacing);

  return (
    <div className="flex flex-col gap-2 border-t border-border pt-4">
      <h3 className="text-[13px] font-medium">Web search</h3>
      {data?.configured && (
        <div className="flex items-center gap-3 rounded-xl border border-border bg-bg px-3 py-2.5">
          <span aria-hidden="true" className="size-2.5 flex-none rounded-full bg-note-bar" />
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">Tavily</div>
            <div className="truncate text-[12px] text-muted">
              Key in keychain{data.last4 ? ` ending in ${data.last4}` : ""}
            </div>
          </div>
          <button
            type="button"
            onClick={() => setReplacing((on) => !on)}
            className={`rounded px-2 py-1 text-muted hover:text-text ${focus}`}
          >
            {replacing ? "Cancel" : "Replace"}
          </button>
          <button
            type="button"
            disabled={busy}
            onClick={() => run(actions.remove)}
            className={`rounded px-2 py-1 text-warn-bar disabled:opacity-50 ${focus}`}
          >
            Remove
          </button>
        </div>
      )}
      {data && !data.configured && (
        <p className="text-[12px] text-muted">No Tavily key. The Web toggle needs one; pasted links work without it.</p>
      )}
      {showForm && (
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <input
            type="password"
            aria-label="Tavily API key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="Paste your Tavily API key"
            className={`${field} min-w-0 flex-1`}
          />
          <PressButton type="submit" disabled={busy || !key.trim()} hover={1.02} press={0.97} className={secondary}>
            Save
          </PressButton>
        </form>
      )}
      {failure && <p role="alert" className="text-warn-bar">{failure}</p>}
    </div>
  );
}

function ProfileForm({ profile, onDone }: { profile: Profile | null; onDone: () => void }) {
  const actions = useProfileActions();
  const editing = profile !== null;

  const [preset, setPreset] = useState(editing ? "" : "custom");
  const [name, setName] = useState(profile?.name ?? "");
  const [baseUrl, setBaseUrl] = useState(profile?.base_url ?? "");
  const [model, setModel] = useState(profile?.model ?? "");
  const [needsKey, setNeedsKey] = useState(profile?.needs_key ?? true);
  const [vision, setVision] = useState(profile?.vision ?? false);
  const [imageModel, setImageModel] = useState(profile?.image_model ?? "");
  const [key, setKey] = useState("");
  const [models, setModels] = useState<string[]>([]);
  const [contextWindow, setContextWindow] = useState(profile?.context_window?.toString() ?? "");
  // Sizes the provider reported per model; they only prefill, the typed value always wins.
  const [windows, setWindows] = useState<Record<string, number>>({});
  const [windowTouched, setWindowTouched] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice>(null);

  const hint = !editing && preset === "custom" ? detectPreset(key) : undefined;

  function applyPreset(id: string) {
    setPreset(id);
    const p = presetById(id);
    if (!p) return;
    // Keep a name the user typed themselves; only replace blank or preset-derived ones.
    if (!name || PRESETS.some((x) => x.label === name)) setName(p.id === "custom" ? "" : p.label);
    setBaseUrl(p.baseUrl);
    setModel(p.model);
    setNeedsKey(p.needsKey);
    setVision(p.vision);
    setImageModel(p.imageModel ?? "");
    setModels([]);
    setWindows({});
    setContextWindow("");
    setWindowTouched(false);
  }

  function chooseModel(value: string, reported = windows) {
    setModel(value);
    const known = reported[value.trim()];
    if (known && !windowTouched) setContextWindow(String(known));
  }

  async function run(action: () => Promise<void>) {
    setBusy(true);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
    }
  }

  const fetchModels = () =>
    run(async () => {
      const res = await actions.models({
        profile_id: profile?.id,
        base_url: baseUrl.trim() || undefined,
        key: key.trim() || undefined,
        needs_key: needsKey,
      });
      setModels(res.models);
      const reported = res.context_windows ?? {};
      setWindows(reported);
      chooseModel(model, reported);
      setNotice({ kind: "ok", text: `Connected. ${res.models.length} models found.` });
    });

  function onSubmit(e: FormEvent) {
    e.preventDefault();
    const typedKey = key.trim();
    // Cleared before the request settles so the secret never lingers in the DOM or state.
    setKey("");
    return run(async () => {
      const body = { name: name.trim(), base_url: baseUrl.trim(), model: model.trim(), vision, image_model: imageModel.trim() || null };
      // Editing sends null to clear a size; creating just leaves it out.
      if (profile) await actions.edit(profile.id, { ...body, context_window: windowValue, ...(typedKey && { key: typedKey }) });
      else await actions.create({ ...body, needs_key: needsKey, ...(windowValue !== null && { context_window: windowValue }), ...(typedKey && { key: typedKey }) });
      onDone();
    });
  }

  function onDelete() {
    if (!profile || !window.confirm(`Remove "${profile.name}" and its saved key?`)) return;
    return run(async () => {
      await actions.remove(profile.id);
      onDone();
    });
  }

  const windowText = contextWindow.trim();
  const windowValue = windowText === "" ? null : Number(windowText);
  const windowValid = windowValue === null || (Number.isInteger(windowValue) && windowValue >= MIN_WINDOW);

  const canSave = !busy && windowValid && name.trim() && baseUrl.trim() && model.trim() && (editing || !needsKey || key.trim());

  return (
    <form onSubmit={onSubmit} className="flex flex-col gap-3.5 p-5">
      <h2 id="providers-title" className="font-display text-lg font-semibold">
        {editing ? `Edit ${profile.name}` : "Add provider"}
      </h2>

      {!editing && (
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">Provider</span>
          <select value={preset} onChange={(e) => applyPreset(e.target.value)} className={field}>
            {PRESETS.map((p) => (
              <option key={p.id} value={p.id}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
      )}

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium">Name</span>
        <input value={name} onChange={(e) => setName(e.target.value)} className={field} />
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium">Base URL</span>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.example.com/v1"
          inputMode="url"
          spellCheck={false}
          className={field}
        />
        {baseUrl.trim() && (
          <span className="text-[12px] text-muted">Your key is sent to {hostOf(baseUrl.trim())}.</span>
        )}
      </label>

      {needsKey && (
        <label className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">API key</span>
          <input
            type="password"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder={editing ? "Leave blank to keep the saved key" : "Paste your API key"}
            className={field}
          />
          {hint && (
            <button
              type="button"
              onClick={() => applyPreset(hint.id)}
              className={`self-start rounded text-[12px] text-accent underline ${focus}`}
            >
              Looks like a {hint.label} key — use that preset
            </button>
          )}
          <span className="text-[12px] text-muted">
            Stored by the server in your system keychain. It is never sent back to the browser.
          </span>
        </label>
      )}

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium">Model</span>
        <input
          value={model}
          onChange={(e) => chooseModel(e.target.value)}
          list="model-options"
          spellCheck={false}
          className={field}
        />
        <datalist id="model-options">
          {models.map((m) => (
            <option key={m} value={m} />
          ))}
        </datalist>
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium">Context window (tokens, optional)</span>
        <input
          type="number"
          inputMode="numeric"
          min={MIN_WINDOW}
          step={1}
          value={contextWindow}
          onChange={(e) => {
            setContextWindow(e.target.value);
            setWindowTouched(true);
          }}
          placeholder="e.g. 128000"
          aria-invalid={!windowValid}
          className={field}
        />
        <span className={`text-[12px] ${windowValid ? "text-muted" : "text-warn-bar"}`}>
          {windowValid
            ? "How much text the model can read at once. Lets Lumio show how full the context is. Some providers report it when you fetch models."
            : `Use a whole number of at least ${MIN_WINDOW.toLocaleString()}, or leave it blank.`}
        </span>
      </label>

      <label className="flex flex-col gap-1.5">
        <span className="text-[13px] font-medium">Image model (optional)</span>
        <input
          value={imageModel}
          onChange={(e) => setImageModel(e.target.value)}
          placeholder="e.g. grok-imagine-image-2.0"
          spellCheck={false}
          className={field}
        />
        <span className="text-[12px] text-muted">
          Lets the model illustrate its replies. Leave blank if this provider has no image generation; the Illustrate
          button then stays hidden.
        </span>
      </label>

      <label className="flex items-start gap-2.5">
        <input
          type="checkbox"
          checked={vision}
          onChange={(e) => setVision(e.target.checked)}
          className="mt-1 size-4 accent-accent"
        />
        <span className="flex flex-col">
          <span className="text-[13px] font-medium">Can read images</span>
          <span className="text-[12px] text-muted">
            Turn on only if this model accepts image input (such as Grok, GPT-4o or LLaVA). Otherwise attaching images
            stays off.
          </span>
        </span>
      </label>

      {notice && (
        <p role={notice.kind === "error" ? "alert" : "status"} className={notice.kind === "error" ? "text-warn-bar" : "text-note-bar"}>
          {notice.text}
        </p>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <PressButton type="submit" disabled={!canSave} hover={1.02} press={0.97} className={primary}>
          Save
        </PressButton>
        <PressButton
          type="button"
          disabled={busy || !baseUrl.trim()}
          onClick={fetchModels}
          hover={1.02}
          press={0.97}
          className={secondary}
        >
          Test &amp; fetch models
        </PressButton>
        {editing && (
          <button type="button" disabled={busy} onClick={onDelete} className={`rounded px-2 py-1 text-warn-bar disabled:opacity-50 ${focus}`}>
            Remove
          </button>
        )}
        <button type="button" onClick={onDone} className={`ml-auto rounded px-2 py-1 text-muted hover:text-text ${focus}`}>
          Back
        </button>
      </div>
    </form>
  );
}
