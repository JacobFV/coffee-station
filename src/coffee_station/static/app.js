const state = {
  activeSessionId: null,
  activeCameraId: 0,
  frameTimer: null,
  pollTimer: null
};

const els = {
  robotStatus: document.getElementById("robotStatus"),
  cameraSelect: document.getElementById("cameraSelect"),
  autoInclude: document.getElementById("autoInclude"),
  frequency: document.getElementById("frequency"),
  applyCamera: document.getElementById("applyCamera"),
  cameraFeed: document.getElementById("cameraFeed"),
  noFrame: document.getElementById("noFrame"),
  newSession: document.getElementById("newSession"),
  pauseSession: document.getElementById("pauseSession"),
  resumeSession: document.getElementById("resumeSession"),
  sessionSelect: document.getElementById("sessionSelect"),
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

async function refreshCameras() {
  const data = await api("/api/cameras");
  els.cameraSelect.innerHTML = "";
  for (const camera of data.cameras) {
    const option = document.createElement("option");
    option.value = camera.camera_id;
    option.textContent = camera.label || `Camera ${camera.camera_id}`;
    els.cameraSelect.appendChild(option);
  }
  if (data.cameras.length > 0) {
    const camera = data.cameras[0];
    state.activeCameraId = camera.camera_id;
    els.cameraSelect.value = String(camera.camera_id);
    els.autoInclude.checked = camera.auto_include;
    els.frequency.value = camera.frequency_hz;
    refreshFrame();
  }
}

function refreshFrame() {
  if (state.activeCameraId === null || state.activeCameraId === undefined) {
    return;
  }
  const url = `/api/cameras/${state.activeCameraId}/frame?t=${Date.now()}`;
  const image = new Image();
  image.onload = () => {
    els.cameraFeed.src = url;
    els.cameraFeed.style.display = "block";
    els.noFrame.style.display = "none";
  };
  image.onerror = () => {
    els.cameraFeed.style.display = "none";
    els.noFrame.style.display = "block";
  };
  image.src = url;
}

function startPolling() {
  clearInterval(state.frameTimer);
  clearInterval(state.pollTimer);
  state.frameTimer = setInterval(refreshFrame, 500);
  state.pollTimer = setInterval(async () => {
    if (state.activeSessionId) {
      await refreshSession(state.activeSessionId);
      await refreshSessions();
    }
  }, 1500);
}

els.cameraSelect.addEventListener("change", async () => {
  state.activeCameraId = Number(els.cameraSelect.value);
  refreshFrame();
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

boot().catch((error) => {
  els.robotStatus.textContent = error.message;
});
