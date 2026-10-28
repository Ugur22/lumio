export interface Preset {
  id: string;
  label: string;
  baseUrl: string;
  model: string;
  needsKey: boolean;
  // Whether the preset's default model reads images; the user can change it per profile.
  vision: boolean;
  // Default image-generation model, if the provider has one.
  imageModel?: string;
  // Only used to suggest a preset when a key is pasted; the user always confirms.
  keyPrefixes: string[];
}

export const PRESETS: Preset[] = [
  { id: "openai", label: "OpenAI", baseUrl: "https://api.openai.com/v1", model: "gpt-4o-mini", needsKey: true, vision: true, keyPrefixes: ["sk-"] },
  { id: "openrouter", label: "OpenRouter", baseUrl: "https://openrouter.ai/api/v1", model: "openai/gpt-4o-mini", needsKey: true, vision: true, keyPrefixes: ["sk-or-"] },
  { id: "groq", label: "Groq", baseUrl: "https://api.groq.com/openai/v1", model: "llama-3.3-70b-versatile", needsKey: true, vision: false, keyPrefixes: ["gsk_"] },
  { id: "xai", label: "xAI (Grok)", baseUrl: "https://api.x.ai/v1", model: "grok-4", needsKey: true, vision: true, imageModel: "grok-imagine-image-2.0", keyPrefixes: ["xai-"] },
  { id: "together", label: "Together", baseUrl: "https://api.together.xyz/v1", model: "meta-llama/Llama-3.3-70B-Instruct-Turbo", needsKey: true, vision: false, keyPrefixes: [] },
  { id: "anthropic", label: "Anthropic (OpenAI-compatible)", baseUrl: "https://api.anthropic.com/v1", model: "claude-sonnet-5-5", needsKey: true, vision: true, keyPrefixes: ["sk-ant-"] },
  { id: "dolphin", label: "Dolphin", baseUrl: "https://api.dolphinllm.com/v1", model: "uncensored", needsKey: true, vision: false, keyPrefixes: [] },
  { id: "ollama", label: "Ollama (local)", baseUrl: "http://localhost:11434/v1", model: "llama3.2", needsKey: false, vision: false, keyPrefixes: [] },
  { id: "custom", label: "Custom", baseUrl: "", model: "", needsKey: true, vision: false, keyPrefixes: [] },
];

export const presetById = (id: string) => PRESETS.find((p) => p.id === id);

// The longest matching prefix wins, so "sk-or-" beats the generic "sk-".
export function detectPreset(key: string): Preset | undefined {
  const k = key.trim();
  let best: { preset: Preset; len: number } | undefined;
  for (const preset of PRESETS) {
    for (const prefix of preset.keyPrefixes) {
      if (k.startsWith(prefix) && (!best || prefix.length > best.len)) best = { preset, len: prefix.length };
    }
  }
  return best?.preset;
}

export function hostOf(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}
