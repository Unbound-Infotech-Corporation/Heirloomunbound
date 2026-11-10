const state = {
  view: "library",
  setup: null,
  library: [],
  source: null,
  study: null,
  lessons: [],
  proposals: [],
  models: null,
  knowledge: null,
  topicHits: null,
  receipt: null,
  busy: "",
};

const $ = (id) => document.getElementById(id);

async function api(path, options = {}) {
  const res = await fetch(path, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
  });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const error = new Error(body.detail || "Something went wrong.");
    error.status = res.status;
    throw error;
  }
  return body;
}

function say(text) {
  $("status").textContent = text;
}

function escapeHtml(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function hostOf(url) {
  if (!url) return "";
  if (String(url).startsWith("sample://")) return "Included sample";
  if (String(url).startsWith("file://")) return "On this PC";
  try { return new URL(url).host; } catch { return url; }
}

function citeLabel(citation) {
  if (!citation) return "";
  if (String(citation.url || "").startsWith("sample://")) return "Included sample";
  if (String(citation.url || "").startsWith("file://")) return citation.title || "Local file";
  return citation.url || citation.title || "";
}

function bodyText(source) {
  let text = String(source.text || "");
  const title = String(source.title || "");
  if (title && text.startsWith(title)) text = text.slice(title.length).trim();
  return text;
}

function paragraphs(text) {
  const clean = String(text || "").replace(/\s+/g, " ").trim();
  if (!clean) return "";
  const parts = clean.split(/(?<=\.)\s+(?=[A-Z“"])/g);
  const chunks = [];
  let current = "";
  parts.forEach((part) => {
    if ((current + " " + part).length > 320 && current) {
      chunks.push(current.trim());
      current = part;
    } else {
      current = `${current} ${part}`.trim();
    }
  });
  if (current) chunks.push(current.trim());
  return chunks.map((chunk) => `<p>${escapeHtml(chunk)}</p>`).join("");
}

function closeMenus() {
  document.querySelectorAll(".dropdown").forEach((node) => { node.hidden = true; });
  document.querySelectorAll(".menu > button").forEach((node) => node.setAttribute("aria-expanded", "false"));
}

function setView(view) {
  state.view = view;
  closeMenus();
  render();
}

async function refreshLibrary() {
  const body = await api("/api/library");
  state.library = body.sources || [];
}

async function openSource(sourceId) {
  const body = await api(`/api/library/${sourceId}`);
  state.source = body.source;
  state.view = "library";
  render();
}

async function addUrl() {
  const input = $("url-input");
  const url = (input?.value || "").trim();
  if (!url) { say("Paste a link first."); return; }
  say("Reading…");
  try {
    const result = await api("/api/library/url", { method: "POST", body: JSON.stringify({ url }) });
    if (result.status === "paywall") {
      say(result.message);
      state.receipt = null;
      renderInspectorCitation(result.citation, result.message);
      return;
    }
    if (result.status === "duplicate") {
      say(result.message);
      await refreshLibrary();
      await openSource(result.source.source_id);
      return;
    }
    say("Added to the library.");
    await refreshLibrary();
    await openSource(result.source.source_id);
  } catch (error) {
    say(error.message);
  }
}

async function addTopic() {
  const input = $("topic-input");
  const topic = (input?.value || "").trim();
  if (!topic) { say("Type a topic first."); return; }
  say("Looking for open readings…");
  try {
    state.topicHits = await api("/api/library/topic", { method: "POST", body: JSON.stringify({ topic }) });
    const count = (state.topicHits.candidates || []).length;
    say(count ? `Found ${count} open readings.` : "No open readings came back.");
    render();
  } catch (error) {
    say(error.message);
  }
}

async function readCandidate(candidate) {
  say("Reading…");
  try {
    const result = await api("/api/library/read", {
      method: "POST",
      body: JSON.stringify({ url: candidate.url, title: candidate.title, date: candidate.date || "", origin: candidate.origin || "topic" }),
    });
    if (!result.stored && result.status === "duplicate") {
      say(result.message);
      await refreshLibrary();
      await openSource(result.source.source_id);
      return;
    }
    say("Added to the library.");
    state.topicHits = null;
    await refreshLibrary();
    await openSource(result.source.source_id);
  } catch (error) {
    say(error.message);
  }
}

async function readSample() {
  say("Opening the sample…");
  try {
    await api("/api/setup/ack", { method: "POST" });
    $("setup").hidden = true;
    const result = await api("/api/library/sample", { method: "POST" });
    await refreshLibrary();
    const source = result.source;
    if (source) await openSource(source.source_id);
    say(result.status === "duplicate" ? "The sample is already in the library." : "Sample ready.");
  } catch (error) {
    say(error.message);
  }
}

async function runStudy(engine) {
  if (!state.source || state.source.kind === "feed") {
    say("Open an article, paper, or PDF first.");
    setView("library");
    return;
  }
  state.busy = engine;
  state.view = "study";
  render();
  say(engine === "practice" ? "Running the practice panel…" : "The panel is reading…");
  try {
    state.study = await api("/api/study", {
      method: "POST",
      body: JSON.stringify({ source_id: state.source.source_id, engine }),
    });
    state.proposals = await api("/api/queue").then((body) => body.proposals);
    say(engine === "practice" ? "Practice panel pinned a lesson. Nothing is filed yet." : "The panel pinned a lesson. Nothing is filed yet.");
  } catch (error) {
    state.study = null;
    say(error.message);
  } finally {
    state.busy = "";
    render();
  }
}

async function fileLesson(lessonId) {
  say("Filing…");
  try {
    const result = await api(`/api/lessons/${lessonId}/file`, { method: "POST" });
    state.receipt = result.receipt;
    if (state.study && state.study.lesson.lesson_id === lessonId) state.study.lesson = result.lesson;
    state.knowledge = await api("/api/knowledge");
    state.lessons = (await api("/api/lessons")).lessons;
    say("Filed. The twin can cite this. Its code was not changed.");
    render();
  } catch (error) {
    say(error.message);
  }
}

async function rejectLesson(lessonId) {
  try {
    const result = await api(`/api/lessons/${lessonId}/reject`, { method: "POST" });
    state.receipt = result.receipt;
    if (state.study && state.study.lesson.lesson_id === lessonId) state.study.lesson = result.lesson;
    say("Set aside. Nothing was written into the twin.");
    render();
  } catch (error) {
    say(error.message);
  }
}

async function decideIdea(proposalId, accept) {
  const path = accept ? "accept" : "decline";
  try {
    const result = await api(`/api/queue/${proposalId}/${path}`, { method: "POST" });
    state.receipt = result.receipt;
    state.proposals = (await api("/api/queue")).proposals;
    say(accept ? "Decision recorded. The twin’s code was not changed." : "Idea declined.");
    render();
  } catch (error) {
    say(error.message);
  }
}

function renderInspectorCitation(citation, message) {
  $("inspector").innerHTML = `
    <p class="area">Citation</p>
    <h2 style="font-family:var(--serif);font-weight:500;font-size:28px;margin:6px 0">${escapeHtml(citation?.title || "Untitled")}</h2>
    <p class="meta">${escapeHtml(citeLabel(citation))}</p>
    <p>${escapeHtml(message || "")}</p>`;
}

function toolbar() {
  if (state.view === "library" || state.view === "study") {
    return `
      <form class="field" id="url-form">
        <input id="url-input" data-testid="url-input" type="url" placeholder="Paste an article, paper, feed, or PDF link" autocomplete="off">
        <button class="primary" type="submit" data-testid="add-url">Add</button>
      </form>
      <form class="field" id="topic-form">
        <input id="topic-input" data-testid="topic-input" type="text" placeholder="Topic, such as voice cloning" autocomplete="off">
        <button class="quiet" type="submit" data-testid="add-topic">Find</button>
      </form>`;
  }
  if (state.view === "models") {
    return `<button class="quiet" type="button" id="refresh-models">Look again</button>`;
  }
  return "";
}

function libraryView() {
  const hits = state.topicHits;
  const hitBlock = hits ? `
    <section>
      <p class="area">Open readings for “${escapeHtml(hits.topic)}”</p>
      ${(hits.notes || []).map((note) => `<p class="meta">${escapeHtml(note)}</p>`).join("")}
      <div class="list">
        ${(hits.candidates || []).map((item, index) => `
          <button type="button" class="row" data-hit="${index}">
            <span><strong>${escapeHtml(item.title)}</strong><span class="meta">${escapeHtml(item.origin || "")} · ${escapeHtml(hostOf(item.url))}</span></span>
          </button>`).join("") || `<p>Nothing open came back. Paste a link instead.</p>`}
      </div>
    </section>` : "";
  if (state.source && state.source.text) {
    return `
      ${hitBlock}
      <article class="reading" data-testid="reading">
        <h2>${escapeHtml(state.source.title)}</h2>
        <p class="byline meta">${escapeHtml(state.source.date || "No date")} · ${escapeHtml(hostOf(state.source.url))}</p>
        ${paragraphs(bodyText(state.source))}
      </article>`;
  }
  if (state.source && state.source.kind === "feed") {
    return `
      <p class="area">Feed</p>
      <div class="list">
        ${(state.source.items || []).map((item, index) => `
          <button type="button" class="row" data-feed="${index}">
            <span><strong>${escapeHtml(item.title)}</strong><span class="meta">${escapeHtml(item.date || "")}</span></span>
          </button>`).join("")}
      </div>`;
  }
  const rows = state.library.map((item) => `
    <button type="button" class="row" data-source="${escapeHtml(item.source_id)}" ${state.source && state.source.source_id === item.source_id ? 'aria-current="true"' : ""}>
      <span><strong>${escapeHtml(item.title || "Untitled")}</strong>
        <span class="meta">${escapeHtml(item.date || "No date")} · ${escapeHtml(hostOf(item.url))} · ${item.kind === "feed" ? "feed" : `${item.words || 0} words`}</span>
      </span>
    </button>`).join("");
  return `
    ${hitBlock}
    ${rows || `<div class="empty"><h2>The library is empty.</h2><p>Paste a link, or read the included sample. Study Hall will ask robots.txt first, and it will not step around a paywall.</p></div>`}
    <div class="list">${rows ? "" : ""}</div>`;
}

function noteText(note) {
  const parsed = note.parsed || {};
  if (note.round === "critique") return parsed.keep || parsed.agree || note.text;
  return parsed.useful || parsed.summary || note.text;
}

function studyView() {
  if (state.busy) {
    return `<div class="empty"><h2>${state.busy === "practice" ? "Practice panel" : "The room is reading."}</h2><p>Readers go first, then they critique each other. The moderator pins one card.</p></div>`;
  }
  if (!state.study) {
    return `<div class="empty"><h2>No lesson yet.</h2><p>Open a reading, then run the panel. If Ollama is quiet, the practice panel shows the same room with scripted readers.</p>
      <div class="actions">
        <button type="button" class="primary" data-testid="run-panel" id="run-panel">Run the panel</button>
        <button type="button" class="quiet" data-testid="run-practice" id="run-practice">Practice panel</button>
      </div></div>`;
  }
  const lesson = state.study.lesson;
  const byModel = {};
  (state.study.notes || []).filter((note) => note.round !== "pin").forEach((note) => {
    byModel[note.model] = byModel[note.model] || [];
    byModel[note.model].push(note);
  });
  const seats = Object.entries(byModel).map(([model, notes]) => `
    <article class="seat">
      <h3>${escapeHtml(model)}</h3>
      ${notes.map((note) => `<p><span class="round">${escapeHtml(note.round)}</span><br>${escapeHtml(noteText(note))}</p>`).join("")}
    </article>`).join("");
  const banner = state.study.engine === "practice"
    ? `<div class="banner" data-testid="practice-banner">Practice panel. These readers are scripted so you can see the room with no model running. Filing still requires you.</div>`
    : "";
  return `${banner}<div class="room">${seats}</div>${lessonCard(lesson)}`;
}

function lessonCard(lesson) {
  const filed = lesson.status === "filed";
  const rejected = lesson.status === "rejected";
  const cites = (lesson.citations || []).map((item) => {
    const label = citeLabel(item);
    const external = item.url && /^https?:/i.test(item.url);
    const inner = external ? `<a href="${escapeHtml(item.url)}" target="_blank" rel="noreferrer">${escapeHtml(item.title || label)}</a>` : escapeHtml(item.title || label);
    return `<li class="meta">${inner}</li>`;
  }).join("");
  return `
    <article class="lesson" data-testid="lesson-card">
      <p class="area">Lesson card · ${escapeHtml(lesson.moderator || "moderator")}</p>
      <h2>${escapeHtml(lesson.summary)}</h2>
      <p class="why">${escapeHtml(lesson.why_it_matters || "")}</p>
      <p class="meta"><span class="meter" style="--v:${Number(lesson.confidence) || 0}"><span></span></span> confidence ${Number(lesson.confidence || 0).toFixed(2)}</p>
      <ul class="cites">${cites}</ul>
      <div class="actions">
        <button type="button" class="primary" data-testid="file-lesson" data-file="${escapeHtml(lesson.lesson_id)}" ${filed || rejected ? "disabled" : ""}>${filed ? "Filed" : "File into the twin"}</button>
        <button type="button" class="danger" data-testid="reject-lesson" data-reject="${escapeHtml(lesson.lesson_id)}" ${filed || rejected ? "disabled" : ""}>Not this one</button>
      </div>
    </article>`;
}

function lessonsView() {
  const rows = state.lessons.filter((lesson) => lesson.status === "filed");
  if (!rows.length) return `<div class="empty"><h2>Nothing filed.</h2><p>A lesson reaches the twin only after you file it. Drafts stay in the study room.</p></div>`;
  return rows.map((lesson) => lessonCard(lesson)).join("");
}

function queueView() {
  if (!state.proposals.length) return `<div class="empty"><h2>No ideas yet.</h2><p>When a lesson suggests a change to memory, voice, prompts, safety, or the screen, it waits here. Accepting an idea records your decision. It does not change the twin.</p></div>`;
  return state.proposals.map((item) => `
    <article class="card" data-testid="queue-item">
      <p class="area">${escapeHtml(item.area)}</p>
      <h3>${escapeHtml(item.title)}</h3>
      <p>${escapeHtml(item.idea)}</p>
      <p class="meta">${escapeHtml(item.status)}</p>
      ${item.status === "pending" ? `<div class="actions">
        <button type="button" class="primary" data-testid="accept-idea" data-accept="${escapeHtml(item.proposal_id)}">Record this decision</button>
        <button type="button" class="quiet" data-decline="${escapeHtml(item.proposal_id)}">Decline</button>
      </div>` : ""}
    </article>`).join("");
}

function modelsView() {
  const report = state.models;
  if (!report) return `<div class="empty"><h2>Looking for models…</h2><p>Study Hall checks 127.0.0.1:11435 first, then the main Ollama on 11434.</p></div>`;
  const wanted = new Set([
    ...(report.configured_readers || []).map((item) => item.model),
    report.configured_moderator && report.configured_moderator.model,
  ].filter(Boolean));
  const hosts = (report.hosts || []).map((host) => `
    <section class="host">
      <h3>${escapeHtml(host.name)}</h3>
      <p class="meta">${escapeHtml(host.url)} · ${host.ok ? "answering" : "not answering"}</p>
      <div>${(host.models || []).map((model) => {
        const embed = /embed/i.test(model);
        const on = wanted.has(model);
        return `<span class="chip${on ? " on" : ""}${embed ? " embed" : ""}">${escapeHtml(model)}${embed ? " · embed" : ""}${on ? " · panel" : ""}</span>`;
      }).join("") || `<span class="meta">${host.ok ? "No models reported." : "Not answering right now."}</span>`}</div>
    </section>`).join("");
  const liveReaders = new Set((report.readers || []).map((seat) => seat.model));
  const wantedReaders = (report.configured_readers || []).map((item) => item.model);
  const readers = wantedReaders.map((model) => liveReaders.has(model) ? model : `${model} (not running)`).join(", ") || "none configured";
  const wantedModerator = (report.configured_moderator && report.configured_moderator.model) || "llama3.1:8b";
  const moderator = report.moderator ? report.moderator.model : `${wantedModerator} (not running)`;
  const embedder = report.embedder ? `${report.embedder.model} on ${report.embedder.host}` : "mxbai-embed-large (not running)";
  return `
    <p>Default readers: ${escapeHtml(readers)}. Moderator: ${escapeHtml(moderator)}. Embeddings: ${escapeHtml(embedder)}.</p>
    <p class="meta">phi4, Mistral, and Gemma read. llama3.1:8b moderates when it is on the study instance. Embedding models do not speak. Cloud APIs stay off unless you add one to config.json.</p>
    ${hosts}`;
}

function renderInspector() {
  const lesson = state.study && state.study.lesson;
  const knowledge = state.knowledge;
  const count = knowledge ? (knowledge.lessons || []).length : null;
  const receipt = state.receipt;
  let body = "";
  if (state.source) {
    body += `<p class="area">Source</p><h2 style="font-family:var(--serif);font-weight:500;font-size:26px;margin:4px 0 6px">${escapeHtml(state.source.title || "Untitled")}</h2><p class="meta">${escapeHtml(state.source.date || "No date")}<br>${escapeHtml(hostOf(state.source.url))}</p>`;
  } else {
    body += `<p>Choose a reading. The inspector keeps its source, date, and link.</p>`;
  }
  if (count !== null) {
    body += `<p class="meta" data-testid="knowledge-count" style="margin-top:12px">${count} filed ${count === 1 ? "lesson" : "lessons"} in twin knowledge</p>`;
  }
  if (lesson) {
    body += `<p style="margin-top:14px">Confidence ${Number(lesson.confidence || 0).toFixed(2)}. ${lesson.status === "filed" ? "Filed." : "Not filed."}</p>`;
  }
  if (receipt) {
    body += `<div class="receipt"><strong>Receipt ${escapeHtml(receipt.receipt_id)}</strong><p>${escapeHtml(receipt.note)}</p><p class="meta">${escapeHtml((receipt.wrote || []).join(", "))}${receipt.code_changed ? "" : " · code unchanged"}</p></div>`;
  }
  $("inspector").innerHTML = body;
}

function receiptHtml() {
  const receipt = state.receipt;
  if (!receipt) return "";
  return `<div class="receipt" data-testid="receipt"><strong>Receipt ${escapeHtml(receipt.receipt_id)}</strong><p>${escapeHtml(receipt.note)}</p><p class="meta">${escapeHtml((receipt.wrote || []).join(", "))}${receipt.code_changed ? "" : " · code unchanged"}</p></div>`;
}

function render() {
  const titles = {
    library: ["Library", "Readings stay on this PC."],
    study: ["Study", "Several models, one pinned card."],
    lessons: ["Lessons", "What the twin is allowed to cite."],
    queue: ["Ideas", "Decisions only. The twin’s code stays put."],
    models: ["Models", "Local first. The study Ollama is port 11435."],
  };
  const [title, sub] = titles[state.view] || titles.library;
  $("doc-title").textContent = state.view === "library" && state.source ? state.source.title : title;
  $("doc-sub").textContent = sub;
  $("toolbar").innerHTML = toolbar();
  const stage = $("stage");
  let viewHtml = modelsView();
  if (state.view === "library") viewHtml = libraryView();
  else if (state.view === "study") viewHtml = studyView();
  else if (state.view === "lessons") viewHtml = lessonsView();
  else if (state.view === "queue") viewHtml = queueView();
  stage.innerHTML = viewHtml + (state.view === "models" ? "" : receiptHtml());
  document.querySelectorAll(".rail button").forEach((button) => {
    button.setAttribute("aria-current", button.dataset.goto === state.view ? "page" : "false");
  });
  renderInspector();
  bindStage();
}

function bindStage() {
  const urlForm = $("url-form");
  if (urlForm) urlForm.addEventListener("submit", (event) => { event.preventDefault(); addUrl(); });
  const topicForm = $("topic-form");
  if (topicForm) topicForm.addEventListener("submit", (event) => { event.preventDefault(); addTopic(); });
  $("stage").querySelectorAll("[data-source]").forEach((button) => {
    button.addEventListener("click", () => openSource(button.dataset.source));
  });
  $("stage").querySelectorAll("[data-hit]").forEach((button) => {
    button.addEventListener("click", () => readCandidate(state.topicHits.candidates[Number(button.dataset.hit)]));
  });
  $("stage").querySelectorAll("[data-feed]").forEach((button) => {
    button.addEventListener("click", () => readCandidate(state.source.items[Number(button.dataset.feed)]));
  });
  $("stage").querySelectorAll("[data-file]").forEach((button) => {
    button.addEventListener("click", () => fileLesson(button.dataset.file));
  });
  $("stage").querySelectorAll("[data-reject]").forEach((button) => {
    button.addEventListener("click", () => rejectLesson(button.dataset.reject));
  });
  $("stage").querySelectorAll("[data-accept]").forEach((button) => {
    button.addEventListener("click", () => decideIdea(button.dataset.accept, true));
  });
  $("stage").querySelectorAll("[data-decline]").forEach((button) => {
    button.addEventListener("click", () => decideIdea(button.dataset.decline, false));
  });
  const run = $("run-panel");
  if (run) run.addEventListener("click", () => runStudy("auto"));
  const practice = $("run-practice");
  if (practice) practice.addEventListener("click", () => runStudy("practice"));
  const refresh = $("refresh-models");
  if (refresh) refresh.addEventListener("click", async () => {
    say("Looking for models…");
    state.models = null;
    render();
    state.models = await api("/api/models");
    say("Model list updated.");
    render();
  });
}

document.querySelectorAll(".rail button, [data-goto]").forEach((button) => {
  button.addEventListener("click", async () => {
    const view = button.dataset.goto;
    if (view === "library" && state.view === "library" && state.source) state.source = null;
    if (view === "lessons") state.lessons = (await api("/api/lessons")).lessons;
    if (view === "queue") state.proposals = (await api("/api/queue")).proposals;
    if (view === "models" && !state.models) {
      setView("models");
      state.models = await api("/api/models");
    }
    if (view === "study" && state.source) state.view = "study";
    setView(view);
  });
});

document.querySelectorAll(".menu > button").forEach((button) => {
  button.addEventListener("click", (event) => {
    event.stopPropagation();
    const open = button.getAttribute("aria-expanded") === "true";
    closeMenus();
    if (!open) {
      button.setAttribute("aria-expanded", "true");
      $(`menu-${button.dataset.menu}`).hidden = false;
    }
  });
});

document.addEventListener("click", () => closeMenus());
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape") closeMenus();
});

document.querySelectorAll("[data-action]").forEach((button) => {
  button.addEventListener("click", async () => {
    closeMenus();
    const action = button.dataset.action;
    if (action === "focus-url") { setView("library"); $("url-input")?.focus(); }
    if (action === "focus-topic") { setView("library"); $("topic-input")?.focus(); }
    if (action === "sample") await readSample();
    if (action === "upload") $("file-input").click();
    if (action === "run-local") await runStudy("auto");
    if (action === "run-practice") await runStudy("practice");
  });
});

$("file-input").addEventListener("change", async () => {
  const file = $("file-input").files && $("file-input").files[0];
  $("file-input").value = "";
  if (!file) return;
  say("Reading the file…");
  const body = new FormData();
  body.append("file", file);
  const res = await fetch("/api/library/file", { method: "POST", body });
  const payload = await res.json().catch(() => ({}));
  if (!res.ok) { say(payload.detail || "That file was not read."); return; }
  await refreshLibrary();
  if (payload.source) await openSource(payload.source.source_id);
  say(payload.status === "duplicate" ? "That file is already in the library." : "Added to the library.");
});

$("setup-sample").addEventListener("click", () => readSample());
$("setup-open").addEventListener("click", async () => {
  await api("/api/setup/ack", { method: "POST" });
  $("setup").hidden = true;
  say("Library open.");
});

async function boot() {
  state.setup = await api("/api/setup");
  if (!state.setup.acked) $("setup").hidden = false;
  await refreshLibrary();
  state.knowledge = await api("/api/knowledge");
  render();
  api("/api/models").then((models) => {
    state.models = models;
    if (state.view === "models") render();
  }).catch(() => {});
  const filed = (state.knowledge && state.knowledge.lessons || []).length;
  say(filed ? `Ready. ${filed} lesson${filed === 1 ? "" : "s"} filed.` : "Ready. Nothing is filed until you say so.");
}

boot().catch((error) => say(error.message));
