// Every path this bundle needs, resolved from its own location plus ~/.dsh.
// Nothing is hardcoded to a user name: the package can live in a profile's
// node_modules, in a repo, or as a junction, and all three resolve the same.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const PKG_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const PKG = JSON.parse(fs.readFileSync(path.join(PKG_ROOT, "package.json"), "utf8"));

// Must equal the `name` in SKILL.md frontmatter, and it is also the folder name
// dsh scans for. Changing one without the other makes the skill invisible.
export const SKILL_NAME = "pdf-to-3d-pipeline";

export const DSH_HOME = process.env.DSH_HOME || path.join(os.homedir(), ".dsh");
export const BOOT_LOG = path.join(DSH_HOME, "pdf3d-boot.log");

export const SKILL_DIRS = {
  dsh: path.join(DSH_HOME, "skills"),
  workbuddy: path.join(os.homedir(), ".workbuddy", "skills"),
  claude: path.join(os.homedir(), ".claude", "skills"),
  codex: path.join(os.homedir(), ".codex", "skills"),
  cursor: path.join(os.homedir(), ".cursor", "skills"),
  agents: path.join(os.homedir(), ".agents", "skills"),
};

export function exists(p) {
  try {
    return fs.existsSync(p);
  } catch {
    return false;
  }
}

// True when p itself is a link/junction (not merely inside one).
export function isLink(p) {
  try {
    return fs.lstatSync(p).isSymbolicLink();
  } catch {
    return false;
  }
}

export function bootLog(msg) {
  const line = `${new Date().toISOString()} ${msg}\n`;
  try {
    fs.mkdirSync(path.dirname(BOOT_LOG), { recursive: true });
    fs.appendFileSync(BOOT_LOG, line, "utf8");
  } catch {}
  try {
    process.stderr.write(`[pdf3d] ${msg}\n`);
  } catch {}
}

// Create <dir>/<SKILL_NAME> -> package root. Never touches an existing real
// directory: a copy someone made on purpose is theirs, not ours to replace.
// Returns a short word describing what happened, for the log.
export function ensureLink(dir) {
  const link = path.join(dir, SKILL_NAME);
  if (exists(link)) {
    if (isLink(link)) return "linked";
    if (exists(path.join(link, "SKILL.md"))) return "real-copy";
    return "occupied";
  }
  if (!exists(dir)) return "no-parent";
  try {
    fs.symlinkSync(PKG_ROOT, link, "junction");
    return "created";
  } catch (err) {
    return `failed:${err.code || err.message}`;
  }
}

export function removeLink(dir) {
  const link = path.join(dir, SKILL_NAME);
  if (!exists(link)) return "absent";
  if (!isLink(link)) return "real-copy";
  try {
    fs.unlinkSync(link); // unlink on a junction removes the link, not the target
    return "removed";
  } catch (err) {
    return `failed:${err.code || err.message}`;
  }
}

export function pythonCandidates() {
  const out = [];
  if (process.env.PDF3D_PYTHON) out.push(process.env.PDF3D_PYTHON);
  const local = path.join(os.homedir(), "cad-agents", "venv-solidworks", "Scripts", "python.exe");
  out.push(local, "python", "py");
  return out;
}
