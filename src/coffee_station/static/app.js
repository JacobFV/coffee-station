const state = {
  activeSessionId: null,
  activeCameraId: 0,
  streamUrl: null,
  pollTimer: null
};

const els = {
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
  pauseSession: document.getElementById("pauseSession"),
  resumeSession: document.getElementById("resumeSession"),
  sessionSelect: document.getElementById("sessionSelect"),
  toolSelect: document.getElementById("toolSelect"),
  toolArgs: document.getElementById("toolArgs"),
  runTool: document.getElementById("runTool"),
  skillList: document.getElementById("skillList"),
  queueList: document.getElementById("queueList"),
  messages: document.getElementById("messages"),
  chatForm: document.getElementById("chatForm"),
  chatInput: document.getElementById("chatInput")
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
    option.textContent = `${session.title} - ${session.status}`;
    option.selected = session.id === state.activeSessionId;
    els.sessionSelect.appendChild(option);
  }
  if (state.activeSessionId) {
    await refreshSession(state.activeSessionId);
  }
}

async function refreshSession(sessionId) {
  const snapshot = await api(`/api/sessions/${sessionId}`);
  state.activeSessionId = sessionId;
  els.robotStatus.textContent = `${snapshot.robot_state.backend} ${snapshot.robot_state.connected ? "connected" : "offline"} - ${snapshot.session.status}`;
  renderMessages(snapshot.messages);
  renderQueue(snapshot.queued_actions || []);
}

function renderMessages(messages) {
  const atBottom = els.messages.scrollTop + els.messages.clientHeight >= els.messages.scrollHeight - 20;
  els.messages.innerHTML = "";
  for (const message of messages) {
    const row = document.createElement("div");
    row.className = `message ${message.role}`;
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.innerHTML = `<span>${message.role}</span><span>${new Date(message.created_at).toLocaleTimeString()}</span>`;
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
  els.queueList.innerHTML = "";
  if (actions.length === 0) {
    const empty = document.createElement("div");
    empty.className = "queue-item";
    empty.textContent = "No queued actions";
    els.queueList.appendChild(empty);
    return;
  }
  for (const action of actions) {
    const row = document.createElement("div");
    row.className = "queue-item";
    const due = new Date(action.due_at * 1000).toLocaleTimeString();
    const label = document.createElement("div");
    label.innerHTML = `<strong>${action.tool_name}</strong><span>${action.status} at ${due}</span>`;
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

async function refreshSkills() {
  const data = await api("/api/skills");
  els.skillList.innerHTML = "";
  for (const skill of data.skills) {
    const row = document.createElement("div");
    row.className = "skill-item";
    row.innerHTML = `<strong>${skill.name}</strong><span>${skill.description}</span>`;
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
  if (state.activeCameraId === null || state.activeCameraId === undefined) {
    return;
  }
  const fps = Math.max(1, Math.min(60, Number(els.displayFps.value) || 30));
  const url = `/api/cameras/${state.activeCameraId}/stream?fps=${encodeURIComponent(fps)}`;
  if (state.streamUrl === url && els.cameraFeed.src.endsWith(url)) {
    return;
  }
  state.streamUrl = url;
  els.cameraFeed.onload = () => {
    els.cameraFeed.style.display = "block";
    els.noFrame.style.display = "none";
  };
  els.cameraFeed.onerror = () => {
    els.cameraFeed.style.display = "none";
    els.noFrame.style.display = "block";
  };
  els.cameraFeed.src = url;
}

function startPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = setInterval(async () => {
    if (state.activeSessionId) {
      await refreshSession(state.activeSessionId);
      await refreshSessions();
    }
  }, 1500);
}

els.cameraSelect.addEventListener("change", async () => {
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

els.stopRobot.addEventListener("click", async () => {
  if (!state.activeSessionId) return;
  await api(`/api/robot/stop/${state.activeSessionId}`, { method: "POST", body: "{}" });
  await refreshSession(state.activeSessionId);
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

els.newSession.addEventListener("click", async () => {
  const name = `Session ${new Date().toLocaleString()}`;
  const data = await api("/api/sessions", { method: "POST", body: JSON.stringify({ title: name }) });
  state.activeSessionId = data.session.id;
  await refreshSessions();
});

els.pauseSession.addEventListener("click", async () => {
  if (!state.activeSessionId) return;
  await api(`/api/sessions/${state.activeSessionId}/status`, {
    method: "POST",
    body: JSON.stringify({ status: "paused" })
  });
  await refreshSession(state.activeSessionId);
});

els.resumeSession.addEventListener("click", async () => {
  if (!state.activeSessionId) return;
  await api(`/api/sessions/${state.activeSessionId}/status`, {
    method: "POST",
    body: JSON.stringify({ status: "running" })
  });
  await refreshSession(state.activeSessionId);
});

els.sessionSelect.addEventListener("change", async () => {
  const sessionId = els.sessionSelect.value;
  await api(`/api/sessions/${sessionId}/activate`, { method: "POST", body: "{}" });
  await refreshSession(sessionId);
});

els.chatForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  const content = els.chatInput.value.trim();
  if (!content || !state.activeSessionId) return;
  els.chatInput.value = "";
  await api(`/api/sessions/${state.activeSessionId}/messages`, {
    method: "POST",
    body: JSON.stringify({ content })
  });
  await refreshSession(state.activeSessionId);
});

els.toolSelect.addEventListener("change", () => {
  const examples = {
    get_robot_state: {},
    diagnose_hardware: {},
    set_joint_pose: { joints: [0, -25, 35, -10, 0, 0], duration_s: 0.5 },
    set_world_pose: { x: 0.18, y: 0, z: 0.14, pitch: -25, duration_s: 0.5 },
    offset_world_pose: { dx: 0.01, dy: 0, dz: 0, duration_s: 0.25 },
    request_latest_frame: { camera_id: state.activeCameraId || 0, refresh: true },
    list_agent_skills: {},
    activate_agent_skill: { name: "pour-coffee-cup-to-cup" },
    record_calibration_point: {
      believed_x: 0.18,
      believed_y: 0,
      believed_z: 0.14,
      actual_x: 0.18,
      actual_y: 0,
      actual_z: 0.14,
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
});
