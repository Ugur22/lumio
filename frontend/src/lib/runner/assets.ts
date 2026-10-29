// Vite turns these into build assets (the wasm and the standard library land in dist/assets) and
// the text files into strings of this chunk, so the runtime ships with the app and works
// offline. This module is only imported on the first Python run.
import loaderSource from "pyodide/pyodide.mjs?raw";
import asmSource from "pyodide/pyodide.asm.mjs?raw";
import lockSource from "pyodide/pyodide-lock.json?raw";
import wasmUrl from "pyodide/pyodide.asm.wasm?url";
import stdlibUrl from "pyodide/python_stdlib.zip?url";

export type PythonAssets = {
  loaderSource: string;
  asmSource: string;
  lockSource: string;
  wasm: ArrayBuffer;
  stdlib: ArrayBuffer;
};

async function bytes(url: string): Promise<ArrayBuffer> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`${url}: ${res.status}`);
  return res.arrayBuffer();
}

let cached: Promise<PythonAssets> | undefined;

export function loadPythonAssets(): Promise<PythonAssets> {
  cached ??= Promise.all([bytes(wasmUrl), bytes(stdlibUrl)])
    .then(([wasm, stdlib]) => ({ loaderSource, asmSource, lockSource, wasm, stdlib }))
    .catch((e: unknown) => {
      cached = undefined;
      throw e;
    });
  return cached;
}
