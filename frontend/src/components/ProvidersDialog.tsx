import { useEffect, useRef, useState, type FormEvent } from "react";
import { DialogTitle, Field, Label } from "@headlessui/react";
import { shouldAutoFetch } from "../lib/modelOptions";
import { useProfileActions, useProfiles } from "../hooks/useProfiles";
import { useWebKeyActions, useWebStatus } from "../hooks/useWebSearch";
import { formatTokens } from "../lib/context";
import { detectPreset, hostOf, PRESETS, presetById } from "../lib/providers";
import type { KeyStore, Profile } from "../types";
import { ModelCombobox } from "./ModelCombobox";
import { Button, CheckboxField, ConfirmDialog, Modal, PressButton, Select, TextField, TextInput, fieldClass, focusRing } from "./ui";

interface Props {
  open: boolean;
  onClose: () => void;
}

type View = { kind: "list" } | { kind: "form"; profile: Profile | null };
type Notice = { kind: "ok" | "error"; text: string } | null;

const MIN_WINDOW = 1000;

function keyHome(store: KeyStore): string {
  return store === "file" ? "saved on the server" : "in keychain";
}

function keyLabel(p: Profile): string {
  if (!p.needs_key) return "No key needed";
  if (!p.configured) return "No key";
  const tail = p.last4 ? ` ending in ${p.last4}` : "";
  return p.source === "env" ? `Key from .env${tail}` : `Key ${keyHome(p.key_store)}${tail}`;
}

export function ProvidersDialog({ open, onClose }: Props) {
  const [view, setView] = useState<View>({ kind: "list" });

  function close() {
    setView({ kind: "list" });
    onClose();
  }

  return (
    <Modal open={open} onClose={close} className="w-[min(92vw,30rem)]">
      {view.kind === "list" ? (
        <ProfileListView onAdd={() => setView({ kind: "form", profile: null })} onEdit={(p) => setView({ kind: "form", profile: p })} onClose={close} />
      ) : (
        // Keyed so switching between profiles never carries a typed key over.
        <ProfileForm key={view.profile?.id ?? "new"} profile={view.profile} onDone={() => setView({ kind: "list" })} />
      )}
    </Modal>
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
      <DialogTitle as="h2" className="font-display text-lg font-semibold">
        Providers
      </DialogTitle>
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
              name="default-provider"
              aria-label={`Use ${p.name} as default for new chats`}
              checked={data.active === p.id}
              onChange={() => activate(p.id)}
              className={`accent-[var(--accent)] ${focusRing}`}
            />
            <div className="min-w-0 flex-1">
              <div className="truncate font-medium">{p.name}</div>
              <div className="truncate text-[12px] text-muted">
                {hostOf(p.base_url)} · {p.model} · {keyLabel(p)}
                {p.context_window ? ` · ${formatTokens(p.context_window)} context` : ""}
              </div>
            </div>
            <Button onClick={() => onEdit(p)}>Edit</Button>
          </li>
        ))}
      </ul>
      {failure && <p role="alert" className="text-warn-bar">{failure}</p>}
      <WebSearchSection />
      <div className="flex items-center gap-2">
        <PressButton type="button" onClick={onAdd} hover={1.02} press={0.97} variant="primary">
          Add provider
        </PressButton>
        <Button onClick={onClose} className="ml-auto">
          Close
        </Button>
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
              Key {keyHome(data.key_store)}{data.last4 ? ` ending in ${data.last4}` : ""}
            </div>
          </div>
          <Button onClick={() => setReplacing((on) => !on)}>{replacing ? "Cancel" : "Replace"}</Button>
          <Button variant="danger" disabled={busy} onClick={() => run(actions.remove)}>
            Remove
          </Button>
        </div>
      )}
      {data && !data.configured && (
        <p className="text-[12px] text-muted">No Tavily key. The Web toggle needs one; pasted links work without it.</p>
      )}
      {showForm && (
        <form onSubmit={onSubmit} className="flex items-center gap-2">
          <TextInput
            type="password"
            aria-label="Tavily API key"
            value={key}
            onChange={(e) => setKey(e.target.value)}
            autoComplete="off"
            spellCheck={false}
            placeholder="Paste your Tavily API key"
            className="min-w-0 flex-1"
          />
          <PressButton type="submit" disabled={busy || !key.trim()} hover={1.02} press={0.97} variant="secondary">
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
  const [keyCommitted, setKeyCommitted] = useState(false);
  const latestFetch = useRef<() => Promise<void>>(async () => undefined);
  const fetched = useRef("");
  const request = useRef(0);

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

  const [confirmRemove, setConfirmRemove] = useState(false);

  // Which button's request is in flight, so only that one shows the spinner.
  const [pending, setPending] = useState<"save" | "fetch" | null>(null);

  async function run(action: () => Promise<void>, kind: "save" | "fetch" | null = null) {
    setBusy(true);
    setPending(kind);
    setNotice(null);
    try {
      await action();
    } catch (err) {
      setNotice({ kind: "error", text: (err as Error).message });
    } finally {
      setBusy(false);
      setPending(null);
    }
  }

  const fetchModels = () => {
    const mine = ++request.current;
    return run(async () => {
      const res = await actions.models({
        profile_id: profile?.id,
        base_url: baseUrl.trim() || undefined,
        key: key.trim() || undefined,
        needs_key: needsKey,
      });
      if (mine !== request.current) return;
      setModels(res.models);
      const reported = res.context_windows ?? {};
      setWindows(reported);
      chooseModel(model, reported);
      setNotice({ kind: "ok", text: `Connected. ${res.models.length} models found.` });
    }, "fetch");
  };
  latestFetch.current = fetchModels;

  // Debounced, and keyed on what the request depends on so typing elsewhere never refires it.
  // The key only counts once its field was left, and a saved key is only used for the saved URL.
  const savedUrl = profile?.base_url;
  useEffect(() => {
    if (!shouldAutoFetch({ baseUrl, needsKey, keyCommitted, saved: savedUrl === undefined ? null : { baseUrl: savedUrl } })) return;
    const signature = `${baseUrl.trim()}|${needsKey}|${keyCommitted}`;
    if (fetched.current === signature) return;
    const timer = setTimeout(() => {
      fetched.current = signature;
      void latestFetch.current();
    }, 700);
    return () => clearTimeout(timer);
  }, [baseUrl, needsKey, keyCommitted, savedUrl]);

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
    }, "save");
  }

  function onDelete() {
    setConfirmRemove(false);
    if (!profile) return;
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
    <>
      <form onSubmit={onSubmit} className="flex flex-col gap-3.5 p-5">
        <DialogTitle as="h2" className="font-display text-lg font-semibold">
          {editing ? `Edit ${profile.name}` : "Add provider"}
        </DialogTitle>

        {!editing && (
          <Field className="flex flex-col gap-1.5">
            <Label className="text-[13px] font-medium">Provider</Label>
            <Select
              value={preset}
              onChange={applyPreset}
              options={PRESETS.map((p) => ({ value: p.id, label: p.label }))}
            />
          </Field>
        )}

        <TextField label="Name" value={name} onChange={(e) => setName(e.target.value)} />

        <TextField
          label="Base URL"
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          placeholder="https://api.example.com/v1"
          inputMode="url"
          spellCheck={false}
          description={baseUrl.trim() && `Your key is sent to ${hostOf(baseUrl.trim())}.`}
        />

        {needsKey && (
          <TextField
            label="API key"
            type="password"
            value={key}
            onChange={(e) => {
              setKey(e.target.value);
              setKeyCommitted(false);
            }}
            onBlur={() => setKeyCommitted(key.trim() !== "")}
            autoComplete="off"
            spellCheck={false}
            placeholder={editing ? "Leave blank to keep the saved key" : "Paste your API key"}
            description="Stored by the server. It is never sent back to the browser."
          >
            {hint && (
              <Button variant="link" onClick={() => applyPreset(hint.id)} className="self-start">
                Looks like a {hint.label} key — use that preset
              </Button>
            )}
          </TextField>
        )}

        <div className="flex flex-col gap-1.5">
          <span className="text-[13px] font-medium">Model</span>
          <ModelCombobox value={model} models={models} onChange={chooseModel} className={fieldClass} />
        </div>

        <TextField
          label="Context window (tokens, optional)"
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
          description="How much text the model can read at once. Lets Lumio show how full the context is. Some providers report it when you fetch models."
          error={!windowValid && `Use a whole number of at least ${MIN_WINDOW.toLocaleString()}, or leave it blank.`}
        />

        <TextField
          label="Image model (optional)"
          value={imageModel}
          onChange={(e) => setImageModel(e.target.value)}
          placeholder="e.g. grok-imagine-image-2.0"
          spellCheck={false}
          description="Lets the model illustrate its replies. Leave blank if this provider has no image generation; the Illustrate button then stays hidden."
        />

        <CheckboxField
          label="Can read images"
          description="Turn on only if this model accepts image input (such as Grok, GPT-4o or LLaVA). Otherwise attaching images stays off."
          checked={vision}
          onChange={setVision}
        />

        {/* Always rendered, one line tall, so the result of Test & fetch models doesn't push the buttons down. */}
        <p
          role={notice?.kind === "error" ? "alert" : "status"}
          className={`min-h-[1.5em] ${notice?.kind === "error" ? "text-warn-bar" : "text-note-bar"}`}
        >
          {notice?.text}
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <PressButton type="submit" disabled={!canSave && pending !== "save"} loading={pending === "save"} hover={1.02} press={0.97} variant="primary">
            Save
          </PressButton>
          <PressButton
            type="button"
            disabled={(busy && pending !== "fetch") || !baseUrl.trim()}
            loading={pending === "fetch"}
            onClick={fetchModels}
            hover={1.02}
            press={0.97}
            variant="secondary"
          >
            Test &amp; fetch models
          </PressButton>
          {editing && (
            <Button variant="danger" disabled={busy} onClick={() => setConfirmRemove(true)}>
              Remove
            </Button>
          )}
          <Button onClick={onDone} className="ml-auto">
            Back
          </Button>
        </div>
      </form>
      <ConfirmDialog
        open={confirmRemove}
        title={`Remove ${profile?.name ?? "provider"}?`}
        description={`This also deletes its saved API key from ${profile?.key_store === "file" ? "the server" : "your keychain"}.`}
        confirmLabel="Remove"
        danger
        onConfirm={onDelete}
        onCancel={() => setConfirmRemove(false)}
      />
    </>
  );
}
