(() => {
  if ("serviceWorker" in navigator) {
    // Ask any older registration to check immediately, then register a
    // versioned script so a cached v1/v2 shell cannot keep the old generic
    // “Failed to fetch” message after the backend has been fixed.
    navigator.serviceWorker.getRegistrations().then((registrations) => {
      registrations.forEach((registration) => registration.update().catch(() => {}));
    }).catch(() => {});
    navigator.serviceWorker.register("/static/sw.js?v=20260829-3", { updateViaCache: "none" }).catch(() => {});
  }
  const MAX_BYTES = 10 * 1024 * 1024;
  const state = { courses: [], reminders: [] };
  const $ = (selector) => document.querySelector(selector);
  const fileInput = $("#fileInput");
  const dropzone = $("#dropzone");
  const workspace = $("#workspace");

  const escapeHtml = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({"&":"&amp;","<":"&lt;",">":"&gt;","\"":"&quot;","'":"&#39;"}[char]));
  const setStatus = (element, message, kind = "") => { element.textContent = message || ""; element.className = `status ${kind}`; };
  const weekdays = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"];
  const periods = Array.from({ length: 15 }, (_, index) => index + 1);
  const periodRanges = periods.flatMap((start) => periods.slice(start - 1).map((end) => `${start}-${end}`));
  const periodRangeLabels = periodRanges.map((range) => `${range.replace("-", "–")}节`);

  async function readJson(response) {
    const text = await response.text();
    try { return JSON.parse(text); }
    catch (_) { throw new Error(`解析服务返回了无效响应（HTTP ${response.status}）。请确认后端服务使用的是本项目的完整版本。`); }
  }

  async function checkBackend() {
    const banner = $("#connectionBanner");
    try {
      const response = await fetch("/healthz", { cache: "no-store" });
      if (!response.ok) throw new Error("health check failed");
      banner.classList.add("hidden");
    } catch (_) {
      banner.classList.remove("hidden");
      $("#connectionMessage").textContent = window.location.protocol === "file:"
        ? "请不要直接双击 index.html；请运行“启动课表转换工具.cmd”，再打开 http://127.0.0.1:8787。"
        : "请确认后端服务仍在运行，或联系网站管理员。当前页面无法访问 /api/parse。";
      window.setTimeout(checkBackend, 2500);
    }
  }
  checkBackend();

  function selectOptions(values, selected, labels = values) {
    return values.map((value, index) => `<option value="${escapeHtml(value)}" ${String(value) === String(selected) ? "selected" : ""}>${escapeHtml(labels[index] ?? value)}</option>`).join("");
  }

  function renderCourses() {
    const tbody = $("#courseTable tbody");
    $("#emptyCourses").classList.toggle("hidden", state.courses.length > 0);
    tbody.innerHTML = state.courses.map((course, index) => `<tr data-index="${index}">
      <td><input class="cell-input name-input" data-field="name" value="${escapeHtml(course.name)}" aria-label="课程名称"></td>
      <td><select class="cell-input" data-field="weekday" aria-label="星期">${selectOptions(weekdays.map((_, i) => i), course.weekday, weekdays)}</select></td>
      <td><select class="cell-input" data-field="periods" aria-label="节次">${selectOptions(periodRanges, `${course.start_period}-${course.end_period}`, periodRangeLabels)}</select></td>
      <td><input class="cell-input weeks-input" data-field="weeks" value="${escapeHtml(course.weeks)}" aria-label="周次"></td>
      <td><input class="cell-input" data-field="location" value="${escapeHtml(course.location)}" aria-label="地点"></td>
      <td><input class="cell-input" data-field="teacher" value="${escapeHtml(course.teacher)}" aria-label="教师"></td>
      <td><select class="cell-input" data-field="course_type" aria-label="课程类型">${selectOptions(["理论", "实验", "实践"], course.course_type)}</select></td>
      <td><button class="remove-btn" data-remove="${index}" title="删除此行" aria-label="删除此行">×</button></td>
    </tr>`).join("");
  }

  function renderReminders() {
    const container = $("#reminders");
    if (!state.reminders.length) { container.innerHTML = `<div class="reminder-card"><span>未识别到无具体时段的课程。</span></div>`; return; }
    container.innerHTML = state.reminders.map((item, index) => `<div class="reminder-card" data-index="${index}">
      <input class="reminder-input reminder-name" data-field="name" value="${escapeHtml(item.name)}" aria-label="提醒名称">
      <div class="reminder-fields"><label>第 <input class="reminder-input" data-field="start_week" type="number" min="1" max="53" value="${escapeHtml(item.start_week)}" aria-label="开始周">–<input class="reminder-input" data-field="end_week" type="number" min="1" max="53" value="${escapeHtml(item.end_week)}" aria-label="结束周"> 周</label></div>
      <input class="reminder-input" data-field="teacher" value="${escapeHtml(item.teacher || "")}" placeholder="教师（可选）" aria-label="教师">
      <input class="reminder-input" data-field="note" value="${escapeHtml(item.note || "")}" placeholder="备注（可选）" aria-label="备注">
      <span class="reminder-caption">整周日历事项 · 未指定具体时间</span>
    </div>`).join("");
  }

  function showWarnings(warnings) {
    const box = $("#warnings");
    if (!warnings || !warnings.length) { box.classList.add("hidden"); box.innerHTML = ""; return; }
    box.classList.remove("hidden");
    box.innerHTML = warnings.map((warning) => `<div>⚠ ${escapeHtml(warning)}</div>`).join("");
  }

  function handleParsed(result, file) {
    state.courses = result.courses || [];
    state.reminders = result.reminders || [];
    $("#fileMeta").classList.remove("hidden");
    $("#fileMeta").innerHTML = `已选择 <strong>${escapeHtml(file.name)}</strong><span>${(file.size / 1024).toFixed(1)} KB · ${result.pages} 页${result.used_ocr ? " · OCR" : ""}</span>`;
    $("#parseSummary").textContent = `${state.courses.length} 门固定课程 · ${state.reminders.length} 项全天提醒`;
    renderCourses(); renderReminders(); showWarnings(result.warnings); workspace.classList.remove("hidden");
    workspace.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  async function uploadFile(file) {
    if (!file || !file.name.toLowerCase().endsWith(".pdf")) { setStatus($("#uploadStatus"), "请选择 .pdf 文件。", "error"); return; }
    if (file.size > MAX_BYTES) { setStatus($("#uploadStatus"), "文件超过 10 MB 限制。", "error"); return; }
    const form = new FormData(); form.append("file", file, file.name);
    setStatus($("#uploadStatus"), "正在解析课表，请稍候…", "loading");
    dropzone.classList.add("busy");
    try {
      const response = await fetch("/api/parse", { method: "POST", body: form });
      const result = await readJson(response);
      if (!response.ok) throw new Error([result.error, ...(result.details || [])].filter(Boolean).join("；"));
      handleParsed(result, file); setStatus($("#uploadStatus"), "解析完成，请核对下方表格。", "success");
    } catch (error) {
      const message = error instanceof TypeError
        ? "无法连接解析服务，请稍后重试；使用公开网址时请联系网站管理员，本地使用时请确认服务已启动。"
        : (error.message || "解析失败，请重试。");
      $("#connectionBanner").classList.toggle("hidden", !(error instanceof TypeError));
      setStatus($("#uploadStatus"), message, "error");
    }
    finally { dropzone.classList.remove("busy"); }
  }

  dropzone.addEventListener("click", () => fileInput.click());
  dropzone.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); fileInput.click(); } });
  fileInput.addEventListener("change", () => uploadFile(fileInput.files[0]));
  ["dragenter", "dragover"].forEach((type) => dropzone.addEventListener(type, (event) => { event.preventDefault(); dropzone.classList.add("dragover"); }));
  ["dragleave", "drop"].forEach((type) => dropzone.addEventListener(type, (event) => { event.preventDefault(); dropzone.classList.remove("dragover"); }));
  dropzone.addEventListener("drop", (event) => uploadFile(event.dataTransfer.files[0]));

  $("#courseTable").addEventListener("input", (event) => {
    const field = event.target.dataset.field; const row = event.target.closest("tr");
    if (!field || !row) return; const course = state.courses[Number(row.dataset.index)];
    if (field === "periods") { const [start, end] = event.target.value.split("-").map(Number); course.start_period = start; course.end_period = end; }
    else if (field === "weekday") course.weekday = Number(event.target.value);
    else course[field] = event.target.value;
  });
  $("#courseTable").addEventListener("change", (event) => event.target.dispatchEvent(new Event("input", { bubbles: true })));
  $("#courseTable").addEventListener("click", (event) => { const button = event.target.closest("[data-remove]"); if (button) { state.courses.splice(Number(button.dataset.remove), 1); renderCourses(); } });
  $("#addCourseButton").addEventListener("click", () => {
    state.courses.push({ name: "新课程", weekday: 0, start_period: 1, end_period: 2, weeks: "1-17周", location: "", teacher: "", course_type: "理论", source: "手动" });
    renderCourses();
    const last = $("#courseTable tbody tr:last-child .name-input"); if (last) { last.focus(); last.select(); }
  });
  $("#reminders").addEventListener("input", (event) => {
    const field = event.target.dataset.field; const card = event.target.closest(".reminder-card");
    if (!field || !card) return; const reminder = state.reminders[Number(card.dataset.index)];
    reminder[field] = ["start_week", "end_week"].includes(field) ? Number(event.target.value) : event.target.value;
  });
  ["#week1Start", "#timezone"].forEach((selector) => $(selector).addEventListener("change", () => { $("#confirmSettings").checked = false; }));

  $("#generateButton").addEventListener("click", async () => {
    const week1Start = $("#week1Start").value;
    if (!week1Start) { setStatus($("#generateStatus"), "请先选择第 1 周周一日期。", "error"); $("#week1Start").focus(); return; }
    if (new Date(`${week1Start}T00:00:00Z`).getUTCDay() !== 1) { setStatus($("#generateStatus"), "第 1 周日期必须是星期一。", "error"); return; }
    if (!$("#confirmSettings").checked) { setStatus($("#generateStatus"), "请勾选确认框，确认第 1 周日期和时区。", "error"); $("#confirmSettings").focus(); return; }
    if (!state.courses.length) { setStatus($("#generateStatus"), "没有可导出的固定时段课程。", "error"); return; }
    const button = $("#generateButton"); button.disabled = true; setStatus($("#generateStatus"), "正在生成并检查 ICS…", "loading");
    try {
      const response = await fetch("/api/generate", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ courses: state.courses, reminders: state.reminders, week1_start: week1Start, timezone: $("#timezone").value }) });
      const result = await readJson(response);
      if (!response.ok) throw new Error([result.error, ...(result.details || [])].filter(Boolean).join("；"));
      const blob = new Blob([result.ics], { type: "text/calendar;charset=utf-8" }); const url = URL.createObjectURL(blob); const link = document.createElement("a");
      link.href = url; link.download = result.filename || "course-calendar.ics"; document.body.appendChild(link); link.click(); link.remove(); URL.revokeObjectURL(url);
      const summary = result.summary; setStatus($("#generateStatus"), `已生成 ${summary.event_count} 个事件（${summary.date_start} 至 ${summary.date_end}），文件已开始下载。`, "success");
    } catch (error) { setStatus($("#generateStatus"), error.message || "生成失败，请检查课程信息。", "error"); }
    finally { button.disabled = false; }
  });
})();
