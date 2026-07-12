const state = {
  meetingId: "",
  activeTab: "transcript",
  report: null,
  pollTimer: null,
  mediaRecorder: null,
  mediaStream: null,
  streamSocket: null,
  apiKey: window.localStorage.getItem("meetingAssistantApiKey") || "",
};

const $ = (id) => document.getElementById(id);

function showToast(message) {
  const toast = $("toast");
  toast.textContent = message;
  toast.hidden = false;
  window.clearTimeout(showToast.timer);
  showToast.timer = window.setTimeout(() => {
    toast.hidden = true;
  }, 3600);
}

async function requestJson(url, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.apiKey) {
    headers.set("X-API-Key", state.apiKey);
  }
  const response = await fetch(url, { ...options, headers });
  const text = await response.text();
  const data = text ? JSON.parse(text) : {};
  if (!response.ok) {
    throw new Error(data.detail || data.message || `Request failed: ${response.status}`);
  }
  return data;
}

function websocketUrl(path) {
  const socketProtocol = window.location.protocol === "https:" ? "wss" : "ws";
  const url = new URL(`${socketProtocol}://${window.location.host}${path}`);
  if (state.apiKey) {
    url.searchParams.set("api_key", state.apiKey);
  }
  return url.toString();
}

function setMeetingId(meetingId) {
  state.meetingId = meetingId;
  $("currentMeetingId").textContent = meetingId || "尚未创建";
}

function setProgress(status) {
  const progress = Number(status.progress || 0);
  $("progressBar").style.width = `${Math.max(0, Math.min(100, progress))}%`;
  $("progressText").textContent = `${progress}%`;
  $("stageText").textContent = `${status.stage || status.status || "空闲"} - ${status.message || ""}`;
}

function participantList() {
  return $("participants")
    .value.split(",")
    .map((value) => value.trim())
    .filter(Boolean);
}

async function checkHealth() {
  try {
    await requestJson("/health");
    $("healthDot").className = "status-dot ok";
    $("healthText").textContent = "服务在线";
    $("healthHint").textContent = "FastAPI 后端正常";
  } catch (error) {
    $("healthDot").className = "status-dot bad";
    $("healthText").textContent = "服务离线";
    $("healthHint").textContent = error.message;
  }
}

async function refreshSystemStatus() {
  const data = await requestJson("/api/v1/system/status");
  const asr = data.asr || {};
  const metrics = data.metrics || {};
  const stages = Object.entries(metrics.stages || {})
    .map(([name, item]) => `<li>${escapeHtml(stageLabel(name))}：${item.count} 次，平均 ${item.avg_ms} ms，最大 ${item.max_ms} ms</li>`)
    .join("");
  $("systemStatus").innerHTML = `
    <div class="result-item">
      <strong>鉴权</strong>
      <div>${data.auth_enabled ? "需要 API Key" : "本地开发模式未启用"}</div>
    </div>
    <div class="result-item">
      <strong>语音识别</strong>
      <div>Provider：${escapeHtml(asr.provider)} | 可用：${asr.ready ? "是" : "否"}</div>
      <div><small>WhisperX：${asr.whisperx_available ? "已安装" : "未安装"} | pyannote：${asr.pyannote_available ? "已安装" : "未安装"} | HF token：${asr.hf_token_configured ? "已配置" : "未配置"}</small></div>
      <div><small>模型：${escapeHtml(asr.model)} | 设备：${escapeHtml(asr.device)} | 说话人识别：${asr.diarization_enabled ? "启用" : "关闭"}</small></div>
    </div>
    <div class="result-item">
      <strong>Agent 运行指标</strong>
      <ul>${stages || "<li>暂无 Pipeline 指标。</li>"}</ul>
    </div>`;
}

async function refreshMeetings() {
  const data = await requestJson("/api/v1/meetings?limit=20");
  const items = data.items || [];
  if (!items.length) {
    $("meetingList").textContent = "暂无会议。";
    return;
  }
  $("meetingList").innerHTML = items
    .map((item) => {
      const status = item.status?.status || "created";
      const progress = item.status?.progress ?? 0;
      const title = item.title || item.meeting_id;
      return `
        <div class="result-item meeting-row">
          <div>
            <strong>${escapeHtml(title)}</strong>
            <div><small>${escapeHtml(item.meeting_id)} | ${escapeHtml(status)} | ${progress}%</small></div>
            <div><small>${escapeHtml(item.audio_file_name || "无音频文件")}</small></div>
          </div>
          <div class="row-actions">
            <button type="button" class="secondary" data-load-meeting="${escapeHtml(item.meeting_id)}">加载</button>
            <button type="button" class="secondary" data-retry-meeting="${escapeHtml(item.meeting_id)}" ${item.audio_file_name ? "" : "disabled"}>重试</button>
          </div>
        </div>`;
    })
    .join("");

  document.querySelectorAll("[data-load-meeting]").forEach((button) => {
    button.addEventListener("click", async () => {
      setMeetingId(button.dataset.loadMeeting);
      await loadReport();
      startPolling();
    });
  });

  document.querySelectorAll("[data-retry-meeting]").forEach((button) => {
    button.addEventListener("click", async () => {
      const meetingId = button.dataset.retryMeeting;
      const data = await requestJson(`/api/v1/meeting/${encodeURIComponent(meetingId)}/retry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ force: false }),
      });
      setMeetingId(data.meeting_id);
      setProgress({ status: data.status, stage: data.stage, progress: 0, message: `已重新入队，第 ${data.retry_count} 次尝试` });
      showToast("会议已重新入队");
      startPolling();
      await refreshMeetings();
    });
  });
}

async function refreshActionItems() {
  const params = new URLSearchParams();
  const status = $("actionStatusFilter").value;
  const assignee = $("actionAssigneeFilter").value.trim();
  if (status && status !== "all") {
    params.set("status", status);
  }
  if (assignee) {
    params.set("assignee", assignee);
  }
  params.set("limit", "100");

  const data = await requestJson(`/api/v1/action-items?${params.toString()}`);
  const items = data.items || [];
  if (!items.length) {
    $("actionList").textContent = "暂无待办事项。";
    return;
  }

  $("actionList").innerHTML = items
    .map(
      (item) => `
        <div class="result-item action-row" data-action-id="${escapeHtml(item.item_id)}">
          <div class="action-fields">
            <label>
              负责人
              <input data-action-field="assignee" value="${escapeHtml(item.assignee || "")}" />
            </label>
            <label>
              任务
              <textarea data-action-field="task">${escapeHtml(item.task)}</textarea>
            </label>
            <label>
              截止时间
              <input data-action-field="deadline" value="${escapeHtml(item.deadline || "")}" />
            </label>
            <label>
              上下文
              <input data-action-field="context" value="${escapeHtml(item.context || "")}" />
            </label>
            <div><small>${escapeHtml(item.meeting_id)} | ${escapeHtml(item.item_id)}</small></div>
          </div>
          <div class="action-controls">
            <select data-action-field="priority">
              <option value="low" ${item.priority === "low" ? "selected" : ""}>低</option>
              <option value="medium" ${item.priority === "medium" ? "selected" : ""}>中</option>
              <option value="high" ${item.priority === "high" ? "selected" : ""}>高</option>
              <option value="urgent" ${item.priority === "urgent" ? "selected" : ""}>紧急</option>
            </select>
            <select data-action-field="status">
              <option value="pending" ${item.status === "pending" ? "selected" : ""}>待处理</option>
              <option value="in_progress" ${item.status === "in_progress" ? "selected" : ""}>进行中</option>
              <option value="completed" ${item.status === "completed" ? "selected" : ""}>已完成</option>
              <option value="cancelled" ${item.status === "cancelled" ? "selected" : ""}>已取消</option>
            </select>
            <button type="button" class="secondary" data-save-action="${escapeHtml(item.item_id)}">保存</button>
          </div>
        </div>`
    )
    .join("");

  document.querySelectorAll("[data-save-action]").forEach((button) => {
    button.addEventListener("click", async () => {
      const row = button.closest("[data-action-id]");
      const payload = {};
      row.querySelectorAll("[data-action-field]").forEach((field) => {
        payload[field.dataset.actionField] = field.value.trim();
      });
      await requestJson(`/api/v1/action-items/${encodeURIComponent(button.dataset.saveAction)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      showToast("待办事项已更新");
      await refreshActionItems();
    });
  });
}

async function createMeeting() {
  const payload = {
    title: $("meetingTitle").value.trim(),
    participants: participantList(),
    language: $("language").value,
  };
  const data = await requestJson("/api/v1/meeting/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  setMeetingId(data.meeting_id);
  setProgress({ status: "created", stage: "created", progress: 0, message: "会议已创建" });
  showToast("会议已创建");
}

async function ensureMeeting() {
  if (!state.meetingId) {
    await createMeeting();
  }
  return state.meetingId;
}

async function uploadAudio() {
  const file = $("audioFile").files[0];
  if (!file) {
    showToast("请先选择音频文件");
    return;
  }
  const meetingId = await ensureMeeting();
  const form = new FormData();
  form.append("file", file);
  const language = encodeURIComponent($("language").value);
  await requestJson(`/api/v1/meeting/${encodeURIComponent(meetingId)}/upload?language=${language}`, {
    method: "POST",
    body: form,
  });
  showToast("音频已上传，开始后台处理");
  startPolling();
}

async function runSample() {
  const meetingId = await ensureMeeting();
  setProgress({ status: "processing", stage: "sample", progress: 1, message: "正在运行示例 Pipeline" });
  const data = await requestJson(`/api/v1/meeting/${encodeURIComponent(meetingId)}/demo`, {
    method: "POST",
  });
  state.report = data;
  setProgress({ status: "completed", stage: "completed", progress: 100, message: "示例运行完成" });
  renderActiveTab();
  showToast("示例 Pipeline 已完成");
}

function startPolling() {
  window.clearInterval(state.pollTimer);
  state.pollTimer = window.setInterval(pollStatus, 1800);
  pollStatus();
}

async function pollStatus() {
  if (!state.meetingId) {
    return;
  }
  try {
    const status = await requestJson(`/api/v1/meeting/${encodeURIComponent(state.meetingId)}/status`);
    setProgress(status);
    if (status.status === "completed") {
      window.clearInterval(state.pollTimer);
      await loadReport();
      await refreshActionItems();
    }
    if (status.status === "failed") {
      window.clearInterval(state.pollTimer);
      showToast(`处理失败：${(status.errors || []).join("; ")}`);
    }
  } catch (error) {
    showToast(error.message);
  }
}

async function loadReport() {
  if (!state.meetingId) {
    showToast("请先创建或选择会议");
    return;
  }
  state.report = await requestJson(`/api/v1/meeting/${encodeURIComponent(state.meetingId)}/report`);
  renderActiveTab();
}

function exportMarkdown() {
  if (!state.meetingId) {
    showToast("请先创建或加载会议");
    return;
  }
  window.open(`/api/v1/meeting/${encodeURIComponent(state.meetingId)}/export.md`, "_blank");
}

function renderActiveTab() {
  if (!state.report) {
    $("resultBody").textContent = "暂无会议报告。";
    return;
  }
  const value = state.report[state.activeTab];
  const renderers = {
    transcript: renderTranscript,
    summary: renderSummary,
    actions: renderActions,
    insights: renderInsights,
    followup: renderFollowup,
  };
  $("resultBody").innerHTML = renderers[state.activeTab](value);
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

function stageLabel(value) {
  return {
    transcription: "语音转写",
    summary: "会议纪要",
    action: "待办提取",
    insight: "会议洞察",
    followup: "跟进处理",
    http: "HTTP 请求",
    pipeline: "Pipeline",
  }[value] || value;
}

function priorityLabel(value) {
  return {
    low: "低",
    medium: "中",
    high: "高",
    urgent: "紧急",
  }[value] || value || "中";
}

function renderTranscript(transcript) {
  const segments = transcript?.segments || [];
  if (!segments.length) {
    return "暂无转写片段。";
  }
  return segments
    .map(
      (segment) => `
        <div class="result-item">
          <strong>${escapeHtml(segment.speaker)}</strong>
          <span>${Number(segment.start || 0).toFixed(1)}s - ${Number(segment.end || 0).toFixed(1)}s</span>
          <div>${escapeHtml(segment.text)}</div>
        </div>`
    )
    .join("");
}

function renderSummary(summary) {
  if (!summary) {
    return "暂无会议纪要。";
  }
  const topics = (summary.topics || [])
    .map((topic) => {
      const points = (topic.discussion_points || []).map((point) => `<li>${escapeHtml(point)}</li>`).join("");
      return `<div class="result-item"><strong>${escapeHtml(topic.title)}</strong><ul>${points}</ul><p>${escapeHtml(topic.conclusion || "")}</p></div>`;
    })
    .join("");
  const decisions = (summary.decisions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const nextSteps = (summary.next_steps || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `
    <strong>${escapeHtml(summary.title)}</strong>
    <p>参会人：${escapeHtml((summary.participants || []).join(", "))}</p>
    ${topics}
    <h4>决策</h4><ul>${decisions}</ul>
    <h4>下一步</h4><ul>${nextSteps}</ul>`;
}

function renderActions(actions) {
  const items = actions?.action_items || [];
  if (!items.length) {
    return "暂无待办事项。";
  }
  return items
    .map(
      (item) => `
        <div class="result-item">
          <strong>${escapeHtml(item.assignee)}</strong>
          <div>${escapeHtml(item.task)}</div>
          <small>截止时间：${escapeHtml(item.deadline || "无")} | 优先级：${escapeHtml(priorityLabel(item.priority))}</small>
          <div><small>Jira：${escapeHtml(item.jira_issue_key || "-")} | 飞书：${escapeHtml(item.feishu_task_id || "-")}</small></div>
        </div>`
    )
    .join("");
}

function renderInsights(insights) {
  if (!insights) {
    return "暂无会议洞察。";
  }
  const speakers = (insights.speaker_stats || [])
    .map((stat) => `<li>${escapeHtml(stat.speaker)}：${Number(stat.percentage || 0).toFixed(1)}%</li>`)
    .join("");
  const highlights = (insights.highlights || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  const suggestions = (insights.suggestions || []).map((item) => `<li>${escapeHtml(item)}</li>`).join("");
  return `
    <p>情绪：<strong>${escapeHtml(insights.overall_sentiment)}</strong> (${Number(insights.sentiment_score || 0).toFixed(2)})</p>
    <p>效率评分：<strong>${Number(insights.efficiency_score || 0).toFixed(1)}</strong>/10</p>
    <p>关键词：${escapeHtml((insights.keywords || []).join(", "))}</p>
    <h4>发言统计</h4><ul>${speakers}</ul>
    <h4>亮点</h4><ul>${highlights}</ul>
    <h4>建议</h4><ul>${suggestions}</ul>`;
}

function renderFollowup(followup) {
  if (!followup) {
    return "暂无跟进结果。";
  }
  return `
    <p>报告地址：${escapeHtml(followup.report_url || "-")}</p>
    <p>纪要已发送：${followup.summary_sent ? "是" : "否"}</p>
    <p>已写入向量库：${followup.stored_in_vector_db ? "是" : "否"}</p>
    <p>Jira 事项：${escapeHtml((followup.jira_issues_created || []).join(", ") || "-")}</p>
    <p>飞书任务：${escapeHtml((followup.feishu_tasks_created || []).join(", ") || "-")}</p>`;
}

async function searchMemory() {
  const query = $("searchQuery").value.trim();
  if (!query) {
    return;
  }
  const data = await requestJson(`/api/v1/meeting/search?query=${encodeURIComponent(query)}&limit=5`);
  const results = data.results || [];
  if (!results.length) {
    $("memoryResults").textContent = "没有匹配的会议记忆。";
    return;
  }
  $("memoryResults").innerHTML = results
    .map(
      (item) => `
        <div class="result-item">
          <strong>${escapeHtml(item.meeting_id || item.id || "会议")}</strong>
          <div>${escapeHtml(item.document || item.text || JSON.stringify(item))}</div>
        </div>`
    )
    .join("");
}

async function startStream() {
  const meetingId = await ensureMeeting();
  const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
  const socket = new WebSocket(websocketUrl(`/ws/transcription/${encodeURIComponent(meetingId)}`));

  state.mediaStream = mediaStream;
  state.streamSocket = socket;

  socket.addEventListener("open", () => {
    socket.send(JSON.stringify({
      type: "config",
      language: $("language").value,
      audio_file_name: "browser-recording.webm",
      min_flush_bytes: 320000,
      flush_interval_s: 10,
    }));
    const recorder = new MediaRecorder(mediaStream, { mimeType: "audio/webm" });
    state.mediaRecorder = recorder;
    recorder.addEventListener("dataavailable", (event) => {
      if (event.data.size > 0 && socket.readyState === WebSocket.OPEN) {
        socket.send(event.data);
      }
    });
    recorder.start(2500);
    $("streamStatus").textContent = "正在通过 WebSocket 录音。";
    $("startStreamBtn").disabled = true;
    $("flushStreamBtn").disabled = false;
    $("stopStreamBtn").disabled = false;
  });

  socket.addEventListener("message", (event) => {
    const data = JSON.parse(event.data);
    handleStreamMessage(data);
  });

  socket.addEventListener("close", () => {
    stopLocalMedia();
    $("startStreamBtn").disabled = false;
    $("flushStreamBtn").disabled = true;
    $("stopStreamBtn").disabled = true;
  });
}

function handleStreamMessage(data) {
  if (data.type === "buffered") {
    $("streamStatus").textContent = `已缓存 ${data.buffer_size} 字节。`;
  }
  if (data.type === "partial_transcript" || data.type === "final_transcript") {
    const text = data.transcript?.full_text || "暂未识别到文本。";
    $("liveTranscript").textContent = text;
  }
  if (["transcript", "summary", "actions", "insights", "followup"].includes(data.type)) {
    state.report = state.report || { meeting_id: state.meetingId };
    state.report[data.type] = data.data;
    renderActiveTab();
  }
  if (data.type === "completed") {
    $("streamStatus").textContent = "实时音频分析完成。";
    loadReport().catch(() => {});
  }
  if (data.type === "error") {
    showToast(data.message || "实时录音出错");
  }
}

function flushStream() {
  if (state.streamSocket?.readyState === WebSocket.OPEN) {
    state.streamSocket.send(JSON.stringify({ type: "flush" }));
  }
}

function stopStream() {
  if (state.mediaRecorder?.state === "recording") {
    state.mediaRecorder.stop();
  }
  if (state.streamSocket?.readyState === WebSocket.OPEN) {
    state.streamSocket.send(JSON.stringify({ type: "stop" }));
  }
  stopLocalMedia();
}

function stopLocalMedia() {
  state.mediaStream?.getTracks().forEach((track) => track.stop());
  state.mediaStream = null;
  state.mediaRecorder = null;
}

function bindEvents() {
  $("createMeetingBtn").addEventListener("click", () => createMeeting().catch((error) => showToast(error.message)));
  $("uploadBtn").addEventListener("click", () => uploadAudio().catch((error) => showToast(error.message)));
  $("sampleBtn").addEventListener("click", () => runSample().catch((error) => showToast(error.message)));
  $("refreshReportBtn").addEventListener("click", () => loadReport().catch((error) => showToast(error.message)));
  $("exportReportBtn").addEventListener("click", exportMarkdown);
  $("refreshMeetingsBtn").addEventListener("click", () => refreshMeetings().catch((error) => showToast(error.message)));
  $("refreshActionsBtn").addEventListener("click", () => refreshActionItems().catch((error) => showToast(error.message)));
  $("actionStatusFilter").addEventListener("change", () => refreshActionItems().catch((error) => showToast(error.message)));
  $("actionAssigneeFilter").addEventListener("input", () => {
    window.clearTimeout(refreshActionItems.timer);
    refreshActionItems.timer = window.setTimeout(() => {
      refreshActionItems().catch((error) => showToast(error.message));
    }, 250);
  });
  $("searchBtn").addEventListener("click", () => searchMemory().catch((error) => showToast(error.message)));
  $("saveApiKeyBtn").addEventListener("click", () => {
    state.apiKey = $("apiKeyInput").value.trim();
    window.localStorage.setItem("meetingAssistantApiKey", state.apiKey);
    showToast("API Key 已保存到本地浏览器");
    refreshSystemStatus().catch((error) => showToast(error.message));
  });
  $("refreshSystemBtn").addEventListener("click", () => refreshSystemStatus().catch((error) => showToast(error.message)));
  $("startStreamBtn").addEventListener("click", () => startStream().catch((error) => showToast(error.message)));
  $("flushStreamBtn").addEventListener("click", flushStream);
  $("stopStreamBtn").addEventListener("click", stopStream);

  document.querySelectorAll(".tab").forEach((tab) => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".tab").forEach((item) => item.classList.remove("active"));
      tab.classList.add("active");
      state.activeTab = tab.dataset.tab;
      renderActiveTab();
    });
  });
}

bindEvents();
$("apiKeyInput").value = state.apiKey;
checkHealth();
refreshMeetings().catch(() => {});
refreshActionItems().catch(() => {});
refreshSystemStatus().catch(() => {});
