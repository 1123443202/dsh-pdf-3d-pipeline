#!/usr/bin/env node
// pdf3d — a thin CLI over the pipeline, so a human (or an agent without the
// skill loaded) can answer three questions without reading the docs:
//   is this machine able to run it?      pdf3d doctor
//   is dsh able to see the skill?        pdf3d link / pdf3d unlink
//   run one stage                        pdf3d run verify -- -Spec ... -Step ...
//
// Output is deliberately ASCII: Windows consoles default to a legacy code page
// and this file is UTF-8, so Chinese here would arrive as mojibake.
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import {
  PKG,
  PKG_ROOT,
  SKILL_DIRS,
  SKILL_NAME,
  exists,
  ensureLink,
  isLink,
  removeLink,
} from "../lib/paths.mjs";

const R = PKG_ROOT;
const ok = (m) => console.log(`  OK    ${m}`);
const bad = (m) => console.log(`  BLOCK ${m}`);
const warn = (m) => console.log(`  WARN  ${m}`);

function powershell() {
  const ps = path.join(process.env.SystemRoot || "C:\\Windows", "System32", "WindowsPowerShell", "v1.0", "powershell.exe");
  return exists(ps) ? ps : "powershell";
}

function psRun(args, opts = {}) {
  return spawnSync(powershell(), ["-NoProfile", "-ExecutionPolicy", "Bypass", ...args], {
    encoding: "utf8",
    ...opts,
  });
}

function doctor() {
  let blocks = 0;
  let warns = 0;
  const fail = (m) => { blocks++; bad(m); };

  console.log(`pdf3d ${PKG.version}  ${R}`);
  if (process.platform !== "win32") fail(`platform is ${process.platform}, this pipeline needs Windows + COM`);
  else ok(`windows, node ${process.version}`);

  // --- package shape: the skill is only usable if its files are all here.
  const required = [
    "SKILL.md",
    "AGENTS.md",
    "QUICKSTART.md",
    "run.ps1",
    "reference/操作手册.md",
    "reference/验收契约.md",
    "reference/坑与排障.md",
    "reference/流水线接口.md",
    "scripts/drawing_spec.py",
    "scripts/spec_verify.py",
    "scripts/DwgBuild.cs",
    "scripts/diagnostics/gate_selftest.py",
  ];
  const missing = required.filter((f) => !exists(path.join(R, f)));
  if (missing.length) fail(`package incomplete, missing ${missing.length}: ${missing.join(", ")}`);
  else ok(`all ${required.length} key files present`);

  const pyFiles = fs.readdirSync(path.join(R, "scripts")).filter((f) => f.endsWith(".py")).length;
  ok(`scripts/: ${pyFiles} python + ${fs.readdirSync(path.join(R, "scripts")).filter((f) => f.endsWith(".ps1") || f.endsWith(".cs")).length} ps1/cs`);

  // --- where the skill is visible. dsh is the only one that matters, the rest
  // are informational: a missing link there just means that agent never got it.
  for (const [key, dir] of Object.entries(SKILL_DIRS)) {
    const link = path.join(dir, SKILL_NAME);
    if (!exists(dir)) continue;
    if (exists(link)) {
      const state = isLink(link) ? "linked" : "real copy (updates will not reach it)";
      if (!isLink(link)) warns++;
      ok(`${key.padEnd(9)} ${state}`);
    } else if (key === "dsh") {
      fail(`${key.padEnd(9)} missing ${link}  (run: pdf3d link)`);
    } else {
      warn(`${key.padEnd(9)} not installed there (optional)`);
      warns++;
    }
  }

  // --- environment: delegate to the one script that already knows, instead of
  // keeping a second copy of the detection rules in two languages.
  console.log("\n-- run.ps1 preflight --");
  const res = psRun(["-File", path.join(R, "run.ps1"), "preflight"], { stdio: "inherit" });
  const passed = res.status === 0;

  console.log("");
  if (!passed) blocks++;
  if (blocks === 0) console.log(`RESULT: ready${warns ? ` (${warns} warning)` : ""}`);
  else console.log(`RESULT: ${blocks} blocking item(s) — fix them before stage 1`);
  return blocks === 0 ? 0 : 1;
}

function link(copy) {
  let rc = 0;
  for (const [key, dir] of Object.entries(SKILL_DIRS)) {
    if (!exists(dir)) { console.log(`  skip  ${key.padEnd(9)} ${dir} does not exist`); continue; }
    if (copy) {
      console.log(`  skip  ${key.padEnd(9)} -copy is not implemented in the CLI, use install.ps1 -Copy`);
      continue;
    }
    const state = ensureLink(dir);
    console.log(`  ${state.padEnd(8)} ${key.padEnd(9)} ${path.join(dir, SKILL_NAME)}`);
    if (state.startsWith("failed") || state === "occupied") rc = 1;
  }
  return rc;
}

function unlink() {
  let rc = 0;
  for (const [key, dir] of Object.entries(SKILL_DIRS)) {
    const state = removeLink(dir);
    if (state === "absent") continue;
    console.log(`  ${state.padEnd(8)} ${key.padEnd(9)} ${path.join(dir, SKILL_NAME)}`);
    if (state.startsWith("failed")) rc = 1;
  }
  return rc;
}

function run(stage, rest) {
  if (!stage) {
    console.error("usage: pdf3d run <preflight|spec|dwg|part|thickness|build|verify|deliver> [-Pdf ...]");
    return 2;
  }
  const args = ["-File", path.join(R, "run.ps1"), stage, ...rest];
  const res = psRun(args, { stdio: "inherit" });
  return typeof res.status === "number" ? res.status : 2;
}

function help() {
  console.log(`pdf3d ${PKG.version}

  pdf3d doctor                  check package + environment, then run preflight
  pdf3d link                    expose the skill to every agent folder found
  pdf3d unlink                  remove those links (never the package)
  pdf3d run <stage> [args...]   forward to run.ps1, e.g.
                                  pdf3d run verify -Spec drawing_spec.json -Step out\\PART.STEP
  pdf3d path                    print the package root
`);
  return 0;
}

const [cmd, ...rest] = process.argv.slice(2);
let code;
switch (cmd) {
  case "doctor":
  case "check":
    code = doctor();
    break;
  case "link":
    code = link(rest.includes("--copy"));
    break;
  case "unlink":
    code = unlink();
    break;
  case "run":
    code = run(rest[0], rest.slice(1));
    break;
  case "path":
    console.log(R);
    code = 0;
    break;
  case undefined:
  case "-h":
  case "--help":
  case "help":
    code = help();
    break;
  default:
    console.error(`unknown command: ${cmd}`);
    code = 2;
}
process.exit(code);
