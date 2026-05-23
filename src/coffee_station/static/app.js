const state = {
  activeSessionId: null,
  activeCameraId: null,
  streamUrl: null,
  pollTimer: null
};

const els = {
  statusDot: document.getElementById("statusDot"),
  robotStatus: document.getElementById("robotStatus"),
  cameraSelect: document.getElementById("cameraSelect"),
  autoInclude: document.getElementById("autoInclude"),
  frequency: document.getElementById("frequency"),
  displayFps: document.getElementById("displayFps"),
  applyCamera: document.getElementById("applyCamera"),
  scanCameras: document.getElementById("scanCameras"),
  stopRobot: document.getElementById("stopRobot"),
  cameraFeed: document.getElementById("cameraFeed"),
  noFrame: document.getElementById("noFrame"),
  newSession: document.getElementById("newSession"),
  sessionToggle: document.getElementById("sessionToggle"),
  sessionSelect: document.getElementById("sessionSelect"),
  toolSelect: document.getElementById("toolSelect"),
  toolArgs: document.getElementById("toolArgs"),
  runTool: document.getElementById("runTool"),
  skillList: document.getElementById("skillList"),
  queueList: document.getElementById("queueList"),
  queueChips: document.getElementById("queueChips"),
  messages: document.getElementById("messages"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput"),
  settingsBtn: document.getElementById("settingsBtn"),
  drawer: document.getElementById("drawer"),
  drawerScrim: document.getElementById("drawerScrim"),
  drawerClose: document.getElementById("drawerClose")
};

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options
  });
  if (!response.ok) {
    throw new Error(await response.text());
  }
  return response.json();
}

async function boot() {
  await refreshSessions();
  await refreshCameras();
  await refreshSkills();
  startPolling();
}

async function refreshSessions() {
  const data = await api("/api/sessions");
  state.activeSessionId = data.active_session_id || data.sessions[0]?.id || null;
  els.sessionSelect.innerHTML = "";
  for (const session of data.sessions) {
    const option = document.createElement("option");
    option.value = session.id;
    option.textContent = session.title;
    option.selected = session.id === state.activeSessionId;
    els.sessionSelect.appendChild(option);
  }
  if (state.activeSessionId) {
    await refreshSession(state.activeSessionId);
  }
}

function setStatus(robotState, sessionStatus) {
  const backend = robotState?.backend || "?";
  const connected = !!robotState?.connected;
  let label;
  let cls = "dot";
  if (!connected) {
    label = `${backend} · offline`;
    cls = "dot offline";
  } else if (sessionStatus === "paused") {
    label = `${backend} · paused`;
    cls = "dot warn";
  } else {
    label = `${backend} · live`;
    cls = "dot online";
  }
  els.robotStatus.textContent = label;
  els.statusDot.className = cls;

  const paused = sessionStatus === "paused";
  els.sessionToggle.textContent = paused ? "Resume" : "Pause";
  els.sessionToggle.title = paused ? "Resume session" : "Pause session";
  els.sessionToggle.dataset.paused = paused ? "1" : "0";
  els.stopRobot.hidden = !connected;
}

async function refreshSession(sessionId) {
  const snapshot = await api(`/api/sessions/${sessionId}`);
  state.activeSessionId = sessionId;
  setStatus(snapshot.robot_state, snapshot.session.status);
  renderMessages(snapshot.messages);
  renderQueue(snapshot.queued_actions || []);
}

function renderMessages(messages) {
  const atBottom = els.messages.scrollTop + els.messages.clientHeight >= els.messages.scrollHeight - 30;
  els.messages.innerHTML = "";
  for (const message of messages) {
    if (message.role === "system") continue;
    const row = document.createElement("div");
    row.className = `message ${message.role}`;
    const meta = document.createElement("div");
    meta.className = "meta";
    const label = message.role === "model" ? "assistant" : message.role;
    meta.innerHTML = `<span>${label}</span><span>${new Date(message.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>`;
    const content = document.createElement("div");
    content.className = "content";
    content.textContent = message.content;
    row.append(meta, content);
    els.messages.appendChild(row);
  }
  if (atBottom) {
    els.messages.scrollTop = els.messages.scrollHeight;
  }
}

function renderQueue(actions) {
  // Drawer list
  els.queueList.innerHTML = "";
  if (actions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "queue-item";
    empty.innerHTML = '<span class="queue-empty">No queued actions</span><span></span>';
    els.queueList.appendChild(empty);
  } else {
    for (const action of actions) {
      const row = document.createElement("div");
      row.className = "queue-item";
      const due = new Date(action.due_at * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
      const label = document.createElement("div");
      label.innerHTML = `<strong>${action.tool_name}</strong><span>${action.status} · ${due}</span>`;
      const cancel = document.createElement("button");
      cancel.type = "button";
      cancel.textContent = "Cancel";
      cancel.addEventListener("click", async () => {
        await api(`/api/sessions/${state.activeSessionId}/actions/${action.id}/cancel`, { method: "POST", body: "{}" });
        await refreshSession(state.activeSessionId);
      });
      row.append(label, cancel);
      els.queueList.appendChild(row);
    }
  }

  // Bottom chips: just show active queue summary
  els.queueChips.innerHTML = "";
  const active = actions.filter((a) => a.status === "scheduled" || a.status === "running");
  for (const action of active.slice(0, 4)) {
    const chip = document.createElement("div");
    chip.className = "chip";
    chip.innerHTML = `<span class="chip-dot"></span><span>${action.tool_name}</span>`;
    const x = document.createElement("button");
    x.type = "button";
    x.textContent = "×";
    x.title = "Cancel";
    x.addEventListener("click", async () => {
      await api(`/api/sessions/${state.activeSessionId}/actions/${action.id}/cancel`, { method: "POST", body: "{}" });
      await refreshSession(state.activeSessionId);
    });
    chip.appendChild(x);
    els.queueChips.appendChild(chip);
  }
  if (active.length > 4) {
    const more = document.createElement("div");
    more.className = "chip";
    more.textContent = `+${active.length - 4} more`;
    els.queueChips.appendChild(more);
  }
}

async function refreshSkills() {
  const data = await api("/api/skills");
  els.skillList.innerHTML = "";
  if (!data.skills || data.skills.length === 0) {
    const empty = document.createElement("div");
    empty.className = "skill-item";
    empty.textContent = "No skills loaded";
    els.skillList.appendChild(empty);
    return;
  }
  for (const skill of data.skills) {
    const row = document.createElement("div");
    row.className = "skill-item";
    row.innerHTML = `<strong>${skill.name}</strong><span>${skill.description || ""}</span>`;
    els.skillList.appendChild(row);
  }
}

async function refreshCameras() {
  const data = await api("/api/cameras");
  els.cameraSelect.innerHTML = "";
  for (const status of data.cameras) {
    const camera = status.camera;
    const option = document.createElement("option");
    option.value = camera.camera_id;
    option.textContent = camera.label || `Camera ${camera.camera_id}`;
    els.cameraSelect.appendChild(option);
  }
  if (data.cameras.length > 0) {
    const camera = data.cameras[0].camera;
    state.activeCameraId = camera.camera_id;
    els.cameraSelect.value = String(camera.camera_id);
    els.autoInclude.checked = camera.auto_include;
    els.frequency.value = camera.frequency_hz;
    setCameraStream();
  }
}

function setCameraStream() {
  if (state.activeCameraId === null || state.activeCameraId === undefined) return;
  const fps = Math.max(1, Math.min(60, Number(els.displayFps.value) || 30));
  const url = `/api/cameras/${state.activeCameraId}/stream?fps=${encodeURIComponent(fps)}`;
  if (state.streamUrl === url && els.cameraFeed.src.endsWith(url)) return;
  state.streamUrl = url;
  els.cameraFeed.onload = () => {
    els.cameraFeed.style.display = "block";
    els.noFrame.style.display = "none";
  };
  els.cameraFeed.onerror = () => {
    els.cameraFeed.style.display = "none";
    els.noFrame.style.display = "grid";
  };
  els.cameraFeed.src = url;
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    if (state.activeSessionId) {
      try {
        await refreshSession(state.activeSessionId);
        await refreshSessions();
      } catch (err) { /* ignore transient */ }
    }
  }, 1500);
}

/* ============ Drawer ============ */

function openDrawer() {
  els.drawer.hidden = false;
  els.drawerScrim.hidden = false;
}

function closeDrawer() {
  els.drawer.hidden = true;
  els.drawerScrim.hidden = true;
}

els.settingsBtn.addEventListener("click", openDrawer);
els.drawerClose.addEventListener("click", closeDrawer);
els.drawerScrim.addEventListener("click", closeDrawer);
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && !els.drawer.hidden) closeDrawer();
});

/* ============ Camera ============ */

els.cameraSelect.addEventListener("change", () => {
  state.activeCameraId = Number(els.cameraSelect.value);
  state.streamUrl = null;
  setCameraStream();
});

els.displayFps.addEventListener("change", () => {
  state.streamUrl = null;
  setCameraStream();
});

els.scanCameras.addEventListener("click", async () => {
  await api("/api/cameras/discover", { method: "POST", body: "{}" });
  await refreshCameras();
});

els.applyCamera.addEventListener("click", async () => {
  await api("/api/cameras/configure", {
    method: "POST",
    body: JSON.stringify({
      camera_id: Number(els.cameraSelect.value),
      enabled: true,
      auto_include: els.autoInclude.checked,
      frequency_hz: Number(els.frequency.value)
    })
  });
  await refreshCameras();
  state.streamUrl = null;
  setCameraStream();
});

/* ============ Robot + sessions ============ */

els.stopRobot.addEventListener("click", async () => {
  if (!state.activeSessionId) return;
  await api(`/api/robot/stop/${state.activeSessionId}`, { method: "POST", body: "{}" });
  await refreshSession(state.activeSessionId);
});

els.newSession.addEventListener("click", async () => {
  const name = `Session ${new Date().toLocaleString()}`;
  const data = await api("/api/sessions", { method: "POST", body: JSON.stringify({ title: name }) });
  state.activeSessionId = data.session.id;
  await refreshSessions();
});

els.sessionToggle.addEventListener("click", async () => {
  if (!state.activeSessionId) return;
  const nextStatus = els.sessionToggle.dataset.paused === "1" ? "running" : "paused";
  await api(`/api/sessions/${state.activeSessionId}/status`, {
    method: "POST",
    body: JSON.stringify({ status: nextStatus })
  });
  await refreshSession(state.activeSessionId);
});

els.sessionSelect.addEventListener("change", async () => {
  const sessionId = els.sessionSelect.value;
  await api(`/api/sessions/${sessionId}/activate`, { method: "POST", body: "{}" });
  await refreshSession(sessionId);
});

/* ============ Chat ============ */

function autoResizeChat() {
  els.chatInput.style.height = "auto";
  els.chatInput.style.height = Math.min(els.chatInput.scrollHeight, 120) + "px";
}

els.chatInput.addEventListener("input", autoResizeChat);

els.chatInput.addEventListener("keydown", (e) => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    els.chatForm.requestSubmit();
  }
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = els.chatInput.value.trim();
  if (!content || !state.activeSessionId) return;
  els.chatInput.value = "";
  autoResizeChat();
  await api(`/api/sessions/${state.activeSessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content })
  });
  await refreshSession(state.activeSessionId);
});

/* ============ Tools ============ */

els.toolSelect.addEventListener("change", () => {
  const examples = {
    get_robot_state: {},
    diagnose_hardware: {},
    scan_feetech_motors: { port: "/dev/cu.usbmodem5B415328371" },
    set_joint_pose: { joints: [0, -25, 35, -10, 0, 0], duration_s: 0.5 },
    set_world_pose: { x: 0.18, y: 0, z: 0.14, pitch: -25, duration_s: 0.5 },
    offset_world_pose: { dx: 0.01, dy: 0, dz: 0, duration_s: 0.25 },
    request_latest_frame: { camera_id: state.activeCameraId || 0, refresh: true },
    list_agent_skills: {},
    activate_agent_skill: { name: "pour-coffee-cup-to-cup" },
    record_calibration_point: {
      believed_x: 0.18, believed_y: 0, believed_z: 0.14,
      actual_x: 0.18, actual_y: 0, actual_z: 0.14,
      note: "measured from camera or operator"
    },
    get_calibration: {},
    clear_calibration: {},
    bundle_tool_calls: {
      calls: [
        { tool_name: "offset_world_pose", args: { dz: 0.02, duration_s: 0.25 }, offset_s: 0 },
        { tool_name: "offset_world_pose", args: { dz: -0.02, duration_s: 0.25 }, offset_s: 1 }
      ]
    },
    cancel_queued_actions: {}
  };
  els.toolArgs.value = JSON.stringify(examples[els.toolSelect.value] || {}, null, 2);
});

els.runTool.addEventListener("click", async () => {
  if (!state.activeSessionId) return;
  let args = {};
  try {
    args = JSON.parse(els.toolArgs.value || "{}");
  } catch (error) {
    alert(`Invalid JSON: ${error.message}`);
    return;
  }
  await api("/api/tools/call", {
    method: "POST",
    body: JSON.stringify({
      session_id: state.activeSessionId,
      tool_name: els.toolSelect.value,
      args
    })
  });
  await refreshSession(state.activeSessionId);
});

boot().catch((error) => {
  els.robotStatus.textContent = error.message;
  els.statusDot.className = "dot offline";
});
