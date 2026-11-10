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
  missions: [],
  activity: [],
  edges: [],
  liveMessages: [],
  liveKeys: new Set(),
  looking: null,
  history: [],
  pinned: null,
  split: 46,
  progress: { fetching: "", pages_read: 0, leads_queued: 0, lessons_drafted: 0 },
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
      ${lesson.review_note ? `<p class="banner" data-testid="review-note">${escapeHtml(lesson.review_note)}</p>` : ""}
      <p class="meta"><span class="meter" style="--v:${Number(lesson.confidence) || 0}"><span></span></span> confidence ${Number(lesson.confidence || 0).toFixed(2)}</p>
      <ul class="cites">${cites}</ul>
      <div class="actions">
        <button type="button" class="primary" data-testid="file-lesson" data-file="${escapeHtml(lesson.lesson_id)}" ${filed || rejected ? "disabled" : ""}>${filed ? "Filed" : "File into the twin"}</button>
        <button type="button" class="danger" data-testid="reject-lesson" data-reject="${escapeHtml(lesson.lesson_id)}" ${filed || rejected ? "disabled" : ""}>Not this one</button>
      </div>
    </article>`;
}

function lessonsView() {
  const flagged = state.lessons.filter((lesson) => lesson.status === "draft" && lesson.review_note);
  const filed = state.lessons.filter((lesson) => lesson.status === "filed");
  if (!flagged.length && !filed.length) return `<div class="empty"><h2>Nothing filed.</h2><p>A lesson reaches the twin only after you file it. Drafts stay in the study room.</p></div>`;
  const waiting = flagged.map((lesson) => lessonCard(lesson)).join("");
  return waiting + filed.map((lesson) => lessonCard(lesson)).join("");
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
    <p class="meta">phi4, Mistral, and Gemma read. llama3.1:8b moderates when it is on the study instance. Embedding models do not speak. ChatGPT and Gemini join only if you add an API key.</p>
    ${hosts}
    ${providerCards()}`;
}

function providerCards() {
  const rows = state.providers || {};
  const explain = `<p class="meta">A ChatGPT Plus or Gemini app subscription is separate from API access. An OpenAI key is pay-as-you-go from platform.openai.com. A Gemini key from aistudio.google.com has a free tier.</p>`;
  const card = (name, title) => {
    const row = rows[name] || {};
    const choices = row.choices || [];
    const options = choices.map((model) => `<option ${model === row.model ? "selected" : ""}>${escapeHtml(model)}</option>`).join("");
    return `<form class="mission" data-provider="${name}" data-testid="provider-${name}">
      <h3>${title}</h3>
      <label class="meta"><input type="checkbox" name="enabled" ${row.enabled ? "checked" : ""}> Let this model sit on the panel</label>
      <label class="meta"><input type="checkbox" name="moderator" ${row.moderator ? "checked" : ""}> Use it as the moderator</label>
      <input name="key" type="password" autocomplete="off" placeholder="${row.key_set ? escapeHtml(row.key_mask || "Key saved") : "Paste an API key"}" aria-label="${title} API key">
      <select name="model" aria-label="${title} model">${options || `<option>${escapeHtml(row.model || "")}</option>`}</select>
      <input name="cap_hour" type="text" value="${row.cap_hour || 20}" aria-label="Calls an hour">
      <input name="cap_day" type="text" value="${row.cap_day || 100}" aria-label="Calls a day">
      <p class="meta" data-testid="usage-${name}">${row.used_hour || 0} this hour · ${row.used_day || 0} today, of ${row.cap_hour || 20}/hour and ${row.cap_day || 100}/day</p>
      <div class="actions">
        <button class="primary" type="submit">Save</button>
        <button class="quiet" type="button" data-test-provider="${name}">Test connection</button>
      </div>
    </form>`;
  };
  return `<h3>Optional cloud seats</h3>${explain}${card("openai", "ChatGPT")}${card("gemini", "Gemini")}`;
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
    live: ["Live Room", "The panel reads with you. Nothing is filed until you say so."],
    automate: ["Automate", "On until you pause or stop it. Pace only slows the room."],
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
  else if (state.view === "live") viewHtml = liveView();
  else if (state.view === "automate") viewHtml = automateView();
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
  $("stage").querySelectorAll("[data-history]").forEach((button) => {
    button.addEventListener("click", () => {
      state.looking = state.history[Number(button.dataset.history)];
      render();
    });
  });
  const splitter = $("stage").querySelector("[data-testid='splitter']");
  if (splitter) bindSplitter(splitter);
  $("stage").querySelectorAll("[data-mission]").forEach((button) => {
    button.addEventListener("click", () => missionVerb(button.dataset.mission, button.dataset.verb));
  });
  const pace = $("pace-form");
  if (pace) pace.addEventListener("submit", (event) => { event.preventDefault(); savePace(); });
  const login = $("login-toggle");
  if (login) login.addEventListener("change", () => toggleLogin(login.checked));
  $("stage").querySelectorAll("[data-provider]").forEach((form) => {
    form.addEventListener("submit", (event) => { event.preventDefault(); saveProvider(form); });
  });
  $("stage").querySelectorAll("[data-test-provider]").forEach((button) => {
    button.addEventListener("click", () => testProvider(button.dataset.testProvider));
  });
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
    if (view === "automate" || view === "live") {
      state.missions = (await api("/api/missions")).missions;
      state.activity = (await api("/api/activity")).activity;
      state.edges = (await api("/api/graph")).edges;
    }
    if (view === "models" && !state.models) {
      setView("models");
      state.models = await api("/api/models");
      state.providers = (await api("/api/providers")).providers;
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
  const running = (state.missions || []).some((mission) => mission.status === "running");
  setView(running ? "live" : "library");
  say(running ? "The room is running." : "Library open.");
});

$("ask-dock").addEventListener("submit", async (event) => {
  event.preventDefault();
  const input = $("ask-input");
  const text = (input.value || "").trim();
  if (!text) return;
  input.value = "";
  try {
    const result = await api("/api/chat", { method: "POST", body: JSON.stringify({ text }) });
    say(result.reply);
    if (state.view !== "live") setView("live");
    state.missions = (await api("/api/missions")).missions;
  } catch (error) {
    say(error.message);
  }
});

function bubble(message) {
  const initial = (message.name || "?").slice(0, 1).toUpperCase();
  return `<article class="bubble">
    <div class="avatar" style="background:${escapeHtml(message.color || "#d4a373")}">${escapeHtml(initial)}</div>
    <div>
      <div class="who" style="color:${escapeHtml(message.color || "#d4a373")}">${escapeHtml(message.name || "")}</div>
      <p>${escapeHtml(message.text || "")}</p>
    </div>
  </article>`;
}

function rememberChat(message) {
  const key = `${message.at || ""}|${message.name || ""}|${message.text || ""}`;
  if (state.liveKeys.has(key)) return;
  state.liveKeys.add(key);
  state.liveMessages.push(message);
  state.liveMessages = state.liveMessages.slice(-80);
}

function highlighted(text, mark) {
  const body = String(text || "");
  const needle = String(mark || "");
  if (!needle || !body.includes(needle)) return paragraphs(body);
  const index = body.indexOf(needle);
  return paragraphs(body.slice(0, index)) + `<p><mark>${escapeHtml(needle)}</mark></p>` + paragraphs(body.slice(index + needle.length));
}

function liveView() {
  const looking = state.looking;
  const history = state.history.map((item, index) => `<button type="button" data-history="${index}">${escapeHtml(item.title || item.url || "Page")}</button>`).join("");
  const reader = looking ? `
    <p class="why-line" data-testid="live-why">${escapeHtml(looking.why || "")}${looking.from_url ? ` · from ${escapeHtml(looking.from_url)}` : ""}</p>
    <p class="meta">${escapeHtml(looking.url || "No page yet")}</p>
    <h2 style="font-family:var(--serif);font-weight:500;font-size:32px;margin:8px 0">${escapeHtml(looking.title || "Waiting")}</h2>
    <div class="reading">${highlighted(looking.text, looking.highlight)}</div>` : `<div class="empty"><h2>The room is opening.</h2><p>When a page is chosen, it shows up here with the reason it was followed.</p></div>`;
  const pin = state.pinned ? `<div class="pin" data-testid="live-pin"><p class="area">${escapeHtml((state.pinned.tags || []).join(" ") || "Lesson")}</p><p>${escapeHtml(state.pinned.summary || "")}</p><button type="button" class="primary" data-file="${escapeHtml(state.pinned.lesson_id || "")}">File into the twin</button></div>` : "";
  const progress = state.progress || {};
  const progressLine = `Fetching ${progress.fetching || "the next page"} · ${progress.pages_read || 0} pages read · ${progress.leads_queued || 0} leads waiting · ${progress.lessons_drafted || 0} lessons drafted`;
  return `<p class="meta" data-testid="live-progress">${escapeHtml(progressLine)}</p>
    <div class="live" data-testid="live-room" style="--split:${state.split}%">
    <section class="live-chat"><div id="live-log">${state.liveMessages.map(bubble).join("") || `<p class="meta">The readers will speak as pages come in. You can type below.</p>`}</div></section>
    <div class="splitter" data-testid="splitter" role="separator" aria-orientation="vertical" aria-label="Resize the room"></div>
    <section class="live-read" data-testid="live-reader">
      <div class="history-strip">${history}</div>
      ${reader}
      ${pin}
    </section>
  </div>`;
}

function automateView() {
  const missions = state.missions.length ? state.missions : [];
  const cards = missions.map((mission) => `
    <article class="mission${mission.standing ? " standing" : ""}" data-testid="${mission.standing ? "mission-standing" : "mission"}">
      <p class="area">${mission.standing ? "Standing mission" : "Mission"} · ${escapeHtml(mission.status)}</p>
      <h3>${escapeHtml(mission.title)}</h3>
      <p>${escapeHtml(mission.brief || "")}</p>
      <p class="meta">${escapeHtml(mission.tag || "research")} · ${mission.pages_per_hour || 12} pages an hour · depth ${mission.max_depth ?? 2}</p>
      <div class="actions">
        <button type="button" class="quiet" data-mission="${escapeHtml(mission.mission_id)}" data-verb="start">Start</button>
        <button type="button" class="quiet" data-testid="pause-mission" data-mission="${escapeHtml(mission.mission_id)}" data-verb="pause">Pause</button>
        <button type="button" class="danger" data-mission="${escapeHtml(mission.mission_id)}" data-verb="stop">Stop</button>
      </div>
    </article>`).join("");
  const standing = missions.find((mission) => mission.standing) || missions[0];
  const pace = standing ? `
    <form id="pace-form" class="field">
      <input name="pages" type="text" value="${standing.pages_per_hour || 12}" aria-label="Pages an hour">
      <input name="depth" type="text" value="${standing.max_depth ?? 2}" aria-label="Lead depth">
      <button class="quiet" type="submit">Set pace</button>
    </form>
    <p class="meta">Pages an hour and lead depth only slow the room. They do not stop it. When the frontier goes quiet, the mission seeds again.</p>` : "";
  const feed = (state.activity || []).slice().reverse().slice(0, 12).map((item) => `<div class="feed-line" data-testid="activity-feed">${escapeHtml(item.message || "")}</div>`).join("") || `<p class="meta">No pages yet. The standing mission is queued.</p>`;
  const edges = (state.edges || []).slice().reverse().slice(0, 10).map((edge) => `<div class="edge" data-testid="lead-graph">${escapeHtml(edge.from || "seed")} → ${escapeHtml(edge.to || "")}<br><span class="meta">${escapeHtml(edge.why || "")}</span></div>`).join("") || `<p class="meta">Leads show up here as the room follows them.</p>`;
  const communities = (standing && standing.communities || []).map((item) => `<span class="chip">${escapeHtml(item.name || item.url)}</span>`).join("");
  return `${cards}${pace}
    <h3>Communities to watch</h3>
    <div>${communities || `<p class="meta">None yet.</p>`}</div>
    <label class="meta"><input id="login-toggle" type="checkbox" data-testid="login-toggle" ${state.login ? "checked" : ""}> Start hidden when I sign in to Windows</label>
    <h3>Activity</h3>
    ${feed}
    <h3>How leads connected</h3>
    ${edges}`;
}

function bindSplitter(splitter) {
  splitter.addEventListener("pointerdown", (event) => {
    splitter.classList.add("dragging");
    const parent = splitter.parentElement;
    const move = (ev) => {
      const rect = parent.getBoundingClientRect();
      const width = Math.min(70, Math.max(28, ((ev.clientX - rect.left) / rect.width) * 100));
      state.split = width;
      parent.style.setProperty("--split", `${width}%`);
    };
    const up = () => {
      splitter.classList.remove("dragging");
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
    event.preventDefault();
  });
}

async function missionVerb(id, verb) {
  try {
    const result = await api(`/api/missions/${id}/${verb}`, { method: "POST" });
    say(result.note || "Updated.");
    state.missions = (await api("/api/missions")).missions;
    render();
  } catch (error) {
    say(error.message);
  }
}

async function savePace() {
  const standing = (state.missions || []).find((mission) => mission.standing) || state.missions[0];
  if (!standing) return;
  const form = $("pace-form");
  const pages = Number(form.pages.value);
  const depth = Number(form.depth.value);
  const result = await api(`/api/missions/${standing.mission_id}`, { method: "PATCH", body: JSON.stringify({ pages_per_hour: pages, max_depth: depth }) });
  state.missions = state.missions.map((mission) => mission.mission_id === result.mission.mission_id ? result.mission : mission);
  say("Pace saved. The room keeps going.");
}

async function saveProvider(form) {
  const name = form.dataset.provider;
  const body = {
    enabled: form.enabled.checked,
    moderator: form.moderator.checked,
    model: form.model.value,
    cap_hour: Number(form.cap_hour.value),
    cap_day: Number(form.cap_day.value),
  };
  if (form.key.value.trim()) body.key = form.key.value.trim();
  const result = await api(`/api/providers/${name}`, { method: "PUT", body: JSON.stringify(body) });
  state.providers = state.providers || {};
  state.providers[name] = result.provider;
  form.key.value = "";
  say(result.provider.key_set ? "Saved. The key stays on this PC." : "Saved.");
  render();
}

async function testProvider(name) {
  try {
    const result = await api(`/api/providers/${name}/test`, { method: "POST", body: "{}" });
    state.providers = (await api("/api/providers")).providers;
    say(`Connected. ${result.models.length} models available.`);
    render();
  } catch (error) {
    say(error.message);
  }
}

async function toggleLogin(enabled) {
  const result = await api("/api/startup", { method: "POST", body: JSON.stringify({ enabled }) });
  say(result.note || "Saved.");
}

function connectLive() {
  if (state.stream) return;
  const stream = new EventSource("/api/live/stream");
  state.stream = stream;
  const take = (name, handler) => stream.addEventListener(name, (event) => {
    handler(JSON.parse(event.data));
    if (state.view === "live" || state.view === "automate") render();
  });
  take("looking", (data) => {
    state.looking = data;
    state.history = [data, ...state.history.filter((item) => item.url !== data.url)].slice(0, 8);
  });
  take("chat", (data) => rememberChat(data));
  take("lesson", (data) => { state.pinned = data; });
  take("activity", (data) => { state.activity = [...state.activity, data].slice(-80); });
  take("progress", (data) => {
    state.progress = data;
    const line = `Fetching ${data.fetching || "the next page"} · ${data.pages_read || 0} pages read · ${data.leads_queued || 0} leads waiting · ${data.lessons_drafted || 0} lessons drafted`;
    const node = document.querySelector("[data-testid='live-progress']");
    if (node) node.textContent = line;
    if (state.view === "live") $("status").textContent = line;
  });
  stream.onerror = () => {};
}

async function boot() {
  state.setup = await api("/api/setup");
  state.missions = (await api("/api/missions")).missions;
  const running = state.missions.some((mission) => mission.status === "running");
  if (running) state.view = "live";
  if (!state.setup.acked) $("setup").hidden = false;
  await refreshLibrary();
  state.knowledge = await api("/api/knowledge");
  state.providers = (await api("/api/providers")).providers;
  render();
  connectLive();
  api("/api/models").then((models) => {
    state.models = models;
    if (state.view === "models") render();
  }).catch(() => {});
  api("/api/startup").then((startup) => {
    state.login = !!startup.enabled;
    if (state.view === "automate") render();
  }).catch(() => {});
  const filed = (state.knowledge && state.knowledge.lessons || []).length;
  say(filed ? `Ready. ${filed} lesson${filed === 1 ? "" : "s"} filed.` : "Ready. Nothing is filed until you say so.");
}

boot().catch((error) => say(error.message));
