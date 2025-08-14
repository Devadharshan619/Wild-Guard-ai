import { app, BrowserWindow, Menu, shell, dialog } from "electron";
import path from "path";
import fs from "fs";
import { fileURLToPath } from "url";
import { spawn } from "child_process";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

let win = null;
let backendProc = null;

function backendDir() {
  return app.isPackaged
    ? path.join(process.resourcesPath, "backend", "detector")
    : path.join(__dirname, "..", "detector");
}
function backendExe() {
  return app.isPackaged
    ? path.join(backendDir(), "detector.exe")
    : null; // dev: started by npm script
}
function envPath() {
  return path.join(backendDir(), ".env");
}

async function ensureEnvFile() {
  try {
    const dir = backendDir();
    await fs.promises.mkdir(dir, { recursive: true }).catch(() => {});
    try {
      await fs.promises.access(envPath(), fs.constants.F_OK);
    } catch {
      const sample = `# Email/Gmail alert config
YOLO_MODEL=./yolov8n.pt
CAMERA_URL=0
WS_HOST=127.0.0.1
WS_PORT=8765
EMAIL_ON=true
GMAIL_FROM=
GMAIL_TO=
GMAIL_APP_PASSWORD=
EMAIL_NOTIFY_FOR=human,animal,vehicle,weapon
ALERT_COOLDOWN_SEC=30
`;
      await fs.promises.writeFile(envPath(), sample, "utf8");
    }
  } catch (e) {
    console.error("[settings] ensureEnvFile error:", e);
  }
}

function startBackendIfPackaged() {
  if (!app.isPackaged) return;
  const exe = backendExe();
  try {
    backendProc = spawn(exe, [], { cwd: backendDir(), windowsHide: true });
    backendProc.stdout?.on("data", d => process.stdout.write(`[detector] ${d}`));
    backendProc.stderr?.on("data", d => process.stderr.write(`[detector] ${d}`));
    backendProc.on("exit", code => console.log("[detector] exited", code));
    console.log("[backend] starting:", exe);
  } catch (e) {
    console.error("[backend] failed to start:", e);
  }
}

function setMenu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    {
      label: "Settings", submenu: [
        {
          label: "Open Email Config (.env)",
          accelerator: "Ctrl+,",
          click: async () => {
            try {
              await ensureEnvFile();
              const err = await shell.openPath(envPath());
              if (err) {
                console.error("[settings] openPath error:", err);
                shell.showItemInFolder(envPath());
                dialog.showMessageBox({
                  type: "info",
                  message: "Opened folder. If the file didn't open, edit .env and restart the app."
                });
              }
            } catch (e) {
              dialog.showErrorBox("Settings", String(e));
            }
          }
        },
        {
          label: "Reveal Backend Folder",
          click: () => shell.openPath(backendDir())
        }
      ]
    }
  ]));
}

function createWindow() {
  win = new BrowserWindow({
    width: 1100,
    height: 750,
    webPreferences: {
      contextIsolation: true
    }
  });

  const htmlPath = path.join(__dirname, "index.html");
  console.log("[main] loadFile:", htmlPath, "| resourcesPath:", process.resourcesPath);
  win.webContents.on("did-fail-load", (_e, code, desc, url) =>
    console.error("did-fail-load", code, desc, url)
  );

  win.loadFile(htmlPath);
}

app.whenReady().then(async () => {
  await ensureEnvFile();
  startBackendIfPackaged();
  setMenu();
  createWindow();
});

app.on("before-quit", () => {
  try { backendProc?.kill(); } catch {}
});
