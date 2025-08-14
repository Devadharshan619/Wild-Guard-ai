const WS_URLS = [
  "ws://127.0.0.1:8765",
  "ws://localhost:8765",
];

const els = {
  home: document.getElementById("home"),
  detect: document.getElementById("detect"),
  startLive: document.getElementById("startLive"),
  fileInput: document.getElementById("fileInput"),
  back: document.getElementById("back"),
  stop: document.getElementById("stop"),
  frame: document.getElementById("frame"),
  status: document.getElementById("status"),
  flagHuman: document.getElementById("flagHuman"),
  flagAnimals: document.getElementById("flagAnimals"),
  flagVehicle: document.getElementById("flagVehicle"),
  flagOthers: document.getElementById("flagOthers"),
  flagAlert: document.getElementById("flagAlert"),
};

let ws;

function connect() {
  let idx = 0;
  function tryConnect() {
    if (idx >= WS_URLS.length) {
      els.status.textContent = "Status: WebSocket not found";
      setTimeout(() => { idx = 0; tryConnect(); }, 1500);
      return;
    }
    const url = WS_URLS[idx++];
    ws = new WebSocket(url);
    ws.onopen = () => { els.status.textContent = "Status: Connected (" + url + ")"; };
    ws.onclose = () => { els.status.textContent = "Status: Disconnected"; setTimeout(tryConnect, 1000); };
    ws.onerror = () => { try { ws.close(); } catch {} };
    ws.onmessage = (evt) => {
      const data = JSON.parse(evt.data);
      if (data.type === "frame") {
        els.frame.src = "data:image/jpeg;base64," + data.b64;
        const f = data.flags || {};
        els.flagHuman.textContent = "Human: " + (f.human ? "yes" : "no");
        els.flagAnimals.textContent = "Animals: " + ((f.animals && f.animals.length) ? f.animals.join(", ") : "-");
        els.flagVehicle.textContent = "Vehicle: " + (f.vehicle ? "yes" : "no");
        els.flagOthers.textContent = "Others: " + (f.others || 0);
        els.flagAlert.textContent = "Email sent: " + (f.alerted ? "yes" : "no");
      } else if (data.type === "status") {
        els.status.textContent = "Status: " + data.status;
      }
    };
  }
  tryConnect();
}

function gotoDetect() {
  els.home.classList.add("hidden");
  els.detect.classList.remove("hidden");
}
function gotoHome() {
  els.detect.classList.add("hidden");
  els.home.classList.remove("hidden");
}

els.startLive.addEventListener("click", () => {
  gotoDetect();
  ws && ws.send(JSON.stringify({ cmd: "start", source: "webcam" }));
});

els.fileInput.addEventListener("change", (e) => {
  const f = e.target.files?.[0];
  if (!f) return;
  const filePath = f.path || null; // Electron usually provides path
  gotoDetect();
  if (filePath) {
    ws && ws.send(JSON.stringify({ cmd: "start", source: "file", path: filePath }));
  } else {
    ws && ws.send(JSON.stringify({ cmd: "start", source: "webcam" }));
  }
});

els.stop.addEventListener("click", () => { ws && ws.send(JSON.stringify({ cmd: "stop" })); });
els.back.addEventListener("click", () => { ws && ws.send(JSON.stringify({ cmd: "stop" })); gotoHome(); });

connect();
