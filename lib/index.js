// dsh bundle entry point.
//
// The interesting part of this package is its SKILL.md and the gate scripts next
// to it — dsh discovers skills on the filesystem, so "installing the plugin" and
// "making the skill visible" are two different things. This module closes that
// gap: on load it makes sure the skill folder in this package is reachable at
// ~/.dsh/skills/<name>, which is the path dsh actually scans.
//
// It does nothing else, and it never throws. A bundle that throws in apply()
// takes the harness down with it, and a broken link is not worth that.
import { DSH_HOME, PKG, PKG_ROOT, SKILL_DIRS, SKILL_NAME, bootLog, ensureLink } from "./paths.mjs";

export const name = "pdf-3d-pipeline";

// "none" to mount nothing, "all" to expose the skill to every agent folder that
// already exists (claude/codex/cursor...), anything else means dsh only.
function targets() {
  const mode = (process.env.PDF3D_MOUNT || "dsh").trim().toLowerCase();
  if (mode === "none") return [];
  if (mode === "all") return Object.keys(SKILL_DIRS);
  return ["dsh"];
}

export function apply(ctx) {
  try {
    bootLog(`apply: v${PKG.version} root=${PKG_ROOT}`);
  } catch {}

  for (const key of targets()) {
    const dir = SKILL_DIRS[key];
    if (!dir) continue;
    let state;
    try {
      state = ensureLink(dir);
    } catch (err) {
      state = `failed:${err.message}`;
      continue;
    }
    // "created" first run, "linked" every run after that. The rest are worth a
    // line in the log because they all mean the same thing: dsh will not see the
    // skill until someone looks.
    if (state !== "linked") bootLog(`mount ${key}: ${state} (${dir}\\${SKILL_NAME})`);
    if (state === "real-copy") {
      bootLog(`mount ${key}: a real copy shadows the package — delete it to follow updates`);
    }
  }

  bootLog(`ready: skill "${SKILL_NAME}" under ${DSH_HOME}\\skills`);
}
