// Start the API before Next so the first sign-in never races an absent backend.
// Existing APIs and remote API_PROXY_URL targets are reused, never terminated.
import { spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import nextEnv from "@next/env";

const dashboard = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const root = resolve(dashboard, "..");
nextEnv.loadEnvConfig(dashboard, true);
const api = new URL(process.env.API_PROXY_URL || "http://127.0.0.1:8000");
const local = ["localhost", "127.0.0.1", "[::1]"].includes(api.hostname);
const children = new Set();
let stopping = false;

function stop(code = 0) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  // Uvicorn reload and Next both have workers; terminate only our process groups.
  for (const child of children) {
    try { process.platform === "win32" ? child.kill("SIGTERM") : process.kill(-child.pid, "SIGTERM"); } catch {}
  }
  const force = setTimeout(() => {
    for (const child of children) {
      try { process.platform === "win32" ? child.kill("SIGKILL") : process.kill(-child.pid, "SIGKILL"); } catch {}
    }
  }, 4000);
  force.unref();
}
process.on("SIGINT", () => stop());
process.on("SIGTERM", () => stop());

function start(command, args, cwd, name) {
  const child = spawn(command, args, { cwd, stdio: "inherit", detached: process.platform !== "win32" });
  children.add(child);
  child.on("error", (error) => {
    console.error(`[dev] Could not start ${name}: ${error.message}`);
    stop(1);
  });
  child.on("exit", (code) => {
    children.delete(child);
    if (!stopping) {
      console.error(`[dev] ${name} stopped. ${name === "API" ? "Check its error above; install Python dependencies with .venv/bin/python -m pip install -r requirements.txt from the project root." : "Stopping the API started by this command."}`);
      stop(code || 1);
    }
  });
  return child;
}

async function ready() {
  try {
    const response = await fetch(new URL("health", `${api.href.replace(/\/$/, "")}/`), { signal: AbortSignal.timeout(3000) });
    if (!response.ok) return false;
    const body = await response.json();
    return body.ok === true && ["sqlite", "supabase"].includes(body.store);
  } catch { return false; }
}

async function main() {
  if (local && !(await ready())) {
    const venvPython = resolve(root, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");
    const python = process.env.PYTHON || (existsSync(venvPython) ? venvPython : "python3");
    console.log(`[dev] Starting the Python API on port ${api.port || 80}…`);
    const child = start(python, ["-m", "uvicorn", "api.main:app", "--reload", "--host", api.hostname === "[::1]" ? "::1" : api.hostname, "--port", api.port || "80"], root, "API");
    const deadline = Date.now() + 30000;
    while (!stopping && child.exitCode === null && Date.now() < deadline) {
      if (await ready()) break;
      await new Promise((done) => setTimeout(done, 300));
    }
    if (stopping) return;
    if (!(await ready())) {
      console.error("[dev] The API did not become ready. Check its startup error above and API_PROXY_URL. The website was not started.");
      stop(1);
      return;
    }
    console.log("[dev] API ready. Starting the website.");
  } else {
    console.log(local ? "[dev] Reusing the running API." : "[dev] Using the configured remote API; starting the website only.");
  }
  if (!stopping) start(process.execPath, [resolve(dashboard, "node_modules/next/dist/bin/next"), "dev", ...process.argv.slice(2)], dashboard, "Website");
}

main().catch((error) => { console.error(`[dev] ${error.message}`); stop(1); });
