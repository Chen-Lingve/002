"use strict";
const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
const h = value => String(value ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const kinds = {source:"原始依据",interface:"接口规范",selection:"企业选型",rule:"检查规则",template:"建模模板",case:"案例记录"};
const caseTypes = {project_case:"项目案例",general_method:"通用方法"};
const ruleModes = {manual:"人工核查",automatic:"自动计算"};
const classificationLabel = record => caseTypes[record.case_type] || ruleModes[record.rule_mode];
const statuses = {draft:"草稿",pending:"待审核",published:"已发布",superseded:"历史版本",retired:"已停用"};
const outcomes = {pass:"通过",fail:"不通过",insufficient_data:"资料不足"};
const state = {view:"library",selected:null,edit:null,catalog:[],artifacts:[],offset:0,filters:{},stats:{},evalProfile:null,review:null};
const icon = name => `<i data-lucide="${name}"></i>`;
const badge = (status, label) => `<span class="badge ${h(status)}">${h(label ?? statuses[status] ?? outcomes[status] ?? status)}</span>`;
const date = value => value ? new Date(value).toLocaleString("zh-CN", {hour12:false}) : "—";
const key = record => `${record.record_id}|${record.version}`;
const refOf = value => {const [record_id,version] = value.split("|"); return {record_id,version:Number(version)};};
const icons = () => window.lucide?.createIcons();
const empty = (title, description = "", name = "folder-open") => `<div class="empty">${icon(name)}<strong>${h(title)}</strong><span>${h(description)}</span></div>`;

async function api(url, options = {}) {
  const opts = {...options};
  if (opts.body && !(opts.body instanceof FormData)) {
    opts.headers = {...opts.headers,"Content-Type":"application/json"};
    opts.body = JSON.stringify(opts.body);
  }
  const response = await fetch("/api" + url, opts);
  if (!response.ok) {
    let detail;
    try { detail = (await response.json()).detail; } catch { detail = response.statusText; }
    throw new Error(Array.isArray(detail) ? detail.map(item => `${item.loc.join(".")}: ${item.msg}`).join("\n") : String(detail));
  }
  return response.json();
}
function error(message, target = "#error") {const el = $(target); el.textContent = message; el.hidden = !message;}
function toast(message) {$("#toast").textContent = message; $("#toast").hidden = false; clearTimeout(state.toast); state.toast = setTimeout(() => $("#toast").hidden = true, 3500);}
function actor(value = $("#actor").value) {const name = value.trim(); if (!name) throw new Error("请填写操作人姓名。"); return name;}
function rememberActor(name) {$("#actor").value = name;try {localStorage.setItem("rfkb-actor",name);} catch {}}
async function task(fn, target = "#error") {error("",target); try {await fn();} catch (exc) {error(exc.message,target);} icons();}
function download(name, value) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value,null,2)], {type:"application/json"}));
  const link = document.createElement("a"); link.href = url; link.download = name; link.click(); setTimeout(() => URL.revokeObjectURL(url),1000);
}
async function allPages(url) {
  const items = [];
  for (let offset = 0; ; offset += 100) {
    const page = await api(`${url}${url.includes("?") ? "&" : "?"}limit=100&offset=${offset}`);
    items.push(...page.items);
    if (items.length >= page.total) return items;
    if (offset >= 9900) throw new Error("候选条目超过 10000 条，请缩小知识库范围。");
  }
}
async function refreshStats() {
  state.stats = await api("/stats");
  const s = state.stats;
  $("#mode").className = `badge ${s.test_mode ? "test" : "published"}`;
  $("#mode").textContent = s.test_mode ? "测试库" : "正式库";
  $("#count-records").textContent = s.records; $("#count-pending").textContent = s.statuses.pending || 0;
  $("#count-runs").textContent = s.runs; $("#count-artifacts").textContent = s.artifacts;
  $("#stats").innerHTML = [[s.records,"知识条目"],[s.statuses.published || 0,"已发布版本"],[s.statuses.pending || 0,"待审核"],[s.artifacts,"原始附件"]].map(([n,label]) => `<div class="stat"><strong>${n}</strong><span>${label}</span></div>`).join("");
}
async function catalog() {state.catalog = await allPages("/records"); state.artifacts = await allPages("/artifacts");}

async function view(name, reset = true) {
  state.view = name; if (reset) state.offset = 0;
  const ticket = (state.viewTicket || 0) + 1;state.viewTicket = ticket;
  $$(".nav").forEach(btn => btn.classList.toggle("active",btn.dataset.view === name));
  $("#page-title").textContent = {library:"知识条目",pending:"待审核",evaluate:"参数检查",runs:"运行记录",artifacts:"资料附件"}[name];
  $("#new-record").hidden = !["library","pending"].includes(name);
  $("#workspace").innerHTML = empty("正在载入","读取本地知识库","loader");
  error("");
  await refreshStats();
  if (state.viewTicket !== ticket) return;
  if (name === "library" || name === "pending") await library();
  if (name === "evaluate") await evaluationView();
  if (name === "runs") await runsView();
  if (name === "artifacts") await artifactsView();
  icons();
}
async function library() {
  const f = state.filters;
  const params = new URLSearchParams({limit:30,offset:state.offset,include_drafts:true});
  for (const field of ["query","kind","family","status"]) if (f[field]) params.set(field,f[field]);
  if (caseTypes[f.classification]) params.set("case_type",f.classification);
  if (ruleModes[f.classification]) params.set("rule_mode",f.classification);
  if (state.view === "pending") params.set("status","pending");
  const data = await api("/records?" + params);
  $("#workspace").innerHTML = `
    <form id="filters" class="filters">
      <input class="search" name="query" aria-label="搜索知识条目" placeholder="搜索标题、料号或内容" value="${h(f.query || "")}">
      <select name="kind" aria-label="条目类型"><option value="">全部类型</option>${Object.entries(kinds).map(([id,label]) => `<option value="${id}" ${id === f.kind ? "selected" : ""}>${label}</option>`).join("")}</select>
      <input name="family" aria-label="系列筛选" placeholder="系列，如 SMA" value="${h(f.family || "")}">
      <select name="classification" aria-label="用途分类">${options(Object.entries({...caseTypes,...ruleModes}),f.classification,"全部用途")}</select>
      ${state.view === "library" ? `<select name="status" aria-label="状态筛选"><option value="">最新版本</option>${Object.entries(statuses).map(([id,label]) => `<option value="${id}" ${id === f.status ? "selected" : ""}>${label}</option>`).join("")}</select>` : ""}
      <button type="submit">检索</button>
    </form>
    <div class="workbench"><div class="record-list"><div class="list-header"><span>${state.view === "pending" ? "审核队列" : "知识目录"}</span><span>共 ${data.total} 项</span></div>
    ${data.items.map(record => `<button class="record-row ${state.selected && key(state.selected) === key(record) ? "selected" : ""}" data-record="${h(key(record))}"><div class="row-title">${h(record.title)}</div><div class="row-meta"><span>${h(classificationLabel(record) || kinds[record.kind])}</span><span>${h(record.family || "未分类")} · v${record.version}</span>${badge(record.status)}${record.test_only ? badge("test","测试") : ""}</div><div class="row-summary">${h(record.summary)}</div></button>`).join("") || empty("暂无条目", state.view === "pending" ? "待提交的审核会显示在此处" : "从原始依据开始建立知识")}
    <div class="pagination"><button id="prev-page" ${state.offset === 0 ? "disabled" : ""}>上一页</button><span>${data.total ? state.offset + 1 : 0}–${Math.min(state.offset + 30,data.total)}</span><button id="next-page" ${state.offset + 30 >= data.total ? "disabled" : ""}>下一页</button></div></div>
    <article id="detail" class="detail">${empty("选择一个条目","查看内容、版本与证据","scan-line")}</article></div>`;
  $("#filters").onsubmit = event => {event.preventDefault();state.filters = Object.fromEntries(new FormData(event.target));state.offset = 0;task(library);};
  $("#prev-page").onclick = () => task(async () => {state.offset -= 30;await library();});
  $("#next-page").onclick = () => task(async () => {state.offset += 30;await library();});
  $$("[data-record]").forEach(btn => btn.onclick = () => task(async () => {
    await selectRecord(refOf(btn.dataset.record));
    if (matchMedia("(max-width: 1100px)").matches) $("#detail").scrollIntoView({block:"start"});
  }));
  if (state.selected) await selectRecord({record_id:state.selected.record_id,version:state.selected.version});
}
function metadata(rows) {return `<dl class="metadata">${rows.map(([label,value]) => `<dt>${h(label)}</dt><dd>${h(value ?? "—")}</dd>`).join("")}</dl>`;}
function table(headers, rows) {return `<div class="table-wrap"><table><thead><tr>${headers.map(v => `<th>${h(v)}</th>`).join("")}</tr></thead><tbody>${rows.join("")}</tbody></table></div>`;}
function intervalText(item) {return `${item.lower ?? "−∞"} ～ ${item.upper ?? "+∞"}`;}
const shownFields = {
  source:["document_code","edition","issuer","source_url","artifact_id"],
  interface:["role","variant","grade","constraints"], rule:["operation","hole","shaft","lower","upper","unit","review_instructions"],
  case:["description","case_type"], selection:["parameters"], template:["dimension_map","artifact_id"]
};
const detailLabels = new Map(Object.entries({
  part_number:"料号",case_code:"案例编号",drawing_number:"图号",drawing_revision:"图纸版次",
  units:"单位",requirement:"工程要求",outcome:"结论",next_evidence:"待补证据",
  production_evidence:"生产工艺证据",hfss:"HFSS 仿真记录",cases:"仿真工况",geometry:"几何条件",
  mode:"求解类型",limits:"适用限制",worst_sample:"最差采样点",
  sample_frequencies_GHz:"采样频率 (GHz)",comparison_planes_x_mm:"比较参考面 X (mm)",
  reference_impedance_ohm:"参考阻抗 (Ω)",vswr_at_26p5:"26.5 GHz 驻波比",vswr:"驻波比",
  s21_dB_at_26p5:"26.5 GHz S21 (dB)",frequency_GHz:"频率 (GHz)",port:"端口",
  historical_evidence:"历史证据",findings:"核查记录",observation:"观察",interpretation:"解读",
  evidence_locator:"证据位置",locator:"证据位置",retrieved_on:"查阅日期",
  source_path:"原件路径",identity_basis:"识别依据",authority_confirmed:"已确认受控版本",
  profile_ref:"接口规范关联"
}));
function detailValue(value, field) {
  if (value == null) return '<span class="muted">未记录</span>';
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) {
    if (!value.length) return '<span class="muted">无</span>';
    if (value.every(v => v === null || typeof v !== "object")) return value.map(v => detailValue(v)).join("、");
    return `<ol class="detail-values">${value.map(v => `<li>${detailValue(v)}</li>`).join("")}</ol>`;
  }
  if (typeof value === "object") return detailFields(Object.entries(value));
  return field === "outcome" ? badge(value) : h(value);
}
function detailFields(entries) {
  return entries.length ? `<dl class="detail-fields">${entries.map(([name,value]) =>
    `<div class="${value && typeof value === "object" && !Array.isArray(value) ? "field-group" : ""}"><dt>${h(detailLabels.get(name) || name)}</dt><dd>${detailValue(value,name)}</dd></div>`
  ).join("")}</dl>` : '<span class="muted">无</span>';
}
const artifactUrl = id => `/api/artifacts/${encodeURIComponent(id)}`;
const previewable = /\.(md|txt|json|csv|tsv|log|s2p|conv|png|jpe?g|pdf)$/i;
function artifactActions(id, name = "") {
  const label = name || "原始附件";
  return `<span class="evidence-file-actions">${!name || previewable.test(name) ?
    `<button type="button" class="quiet" data-preview-id="${h(id)}" data-preview-name="${h(label)}" aria-label="预览 ${h(label)}">${icon("eye")}预览</button>` : ""}
    <a href="${artifactUrl(id)}" download>下载原件</a></span>`;
}
function recordAttachments(record) {
  const b = record.body;
  const files = new Map();
  if (b.artifact_ids_by_file && typeof b.artifact_ids_by_file === "object") {
    for (const [name,id] of Object.entries(b.artifact_ids_by_file)) if (typeof id === "string" && /^[a-f0-9]{64}$/.test(id)) files.set(id,name);
  }
  if (record.kind !== "template" && typeof b.artifact_id === "string" && /^[a-f0-9]{64}$/.test(b.artifact_id) && !files.has(b.artifact_id)) files.set(b.artifact_id,"");
  return files.size ? `<section class="detail-section"><h3>关联附件</h3><ul class="evidence-files">${[...files].map(([id,name]) =>
    `<li><span>${h(name || "原始附件")}</span>${artifactActions(id,name)}</li>`).join("")}</ul></section>` : "";
}
async function openPreview(button) {
  const url = artifactUrl(button.dataset.previewId);
  const dialog = $("#preview"), body = $("#preview-body"), title = $("#preview-title");
  const ticket = state.previewTicket = (state.previewTicket || 0) + 1;
  title.textContent = button.dataset.previewName;
  $("#preview-download").href = url;
  body.textContent = "正在读取附件…";
  dialog.showModal();
  const current = () => dialog.open && state.previewTicket === ticket;
  try {
    const response = await fetch(url + "/preview");
    if (!response.ok) {
      const failure = await response.json().catch(() => ({}));
      throw new Error(failure.detail || "附件预览不可用。");
    }
    const type = response.headers.get("Content-Type")?.split(";")[0];
    const text = type === "text/plain" ? await response.text() : null;
    if (!current()) return;
    const filename = response.headers.get("Content-Disposition")?.split("filename*=UTF-8''")[1];
    if (filename) title.textContent = decodeURIComponent(filename);
    if (type === "image/png" || type === "image/jpeg") {
      const img = document.createElement("img");
      img.alt = title.textContent;
      img.onerror = () => {if (current()) body.textContent = "图片无法显示，请下载原件。";};
      img.src = url + "/preview";
      body.replaceChildren(img);
    } else if (type === "application/pdf") {
      const link = document.createElement("a");
      link.href = url + "/preview"; link.target = "_blank"; link.rel = "noopener";
      link.textContent = "在浏览器中查看 PDF";
      body.replaceChildren(link);
    } else if (text !== null) {
      const pre = document.createElement("pre");
      pre.textContent = text;
      body.replaceChildren(pre);
    } else {
      throw new Error("附件预览不可用。");
    }
  } catch (exc) {
    if (current()) body.textContent = exc.message;
  }
}
function wirePreviews(root) {
  $$("[data-preview-id]",root).forEach(button => button.onclick = () => openPreview(button));
}
const requirementLabels = {
  acceptance_limit:"项目验收要求", diagnostic_reference:"仿真诊断参考",
  simulation_criterion:"仿真数值门限", unconfirmed:"限值待确认"
};
const verificationLabels = {not_verified:"待验证",simulation_only:"已有仿真证据",measured:"已有实测证据"};
function requirementDetail(body) {
  if (body.requirements_schema_version !== 1) return "";
  return `<section class="detail-section"><h3>指标要求与验证状态</h3>${body.acceptance_requirements.map(item => {
    const limit = item.value == null ? "待确认" : `${item.operator} ${item.value}${item.unit === "1" ? "" : ` ${item.unit}`}`;
    const {object, assembly, frequency_GHz, reference_plane} = item.scope;
    return `<div class="evidence"><strong>${h(item.metric)} · ${h(requirementLabels[item.category])}</strong>
      ${metadata([["限值 / 参考值",limit],["适用对象",object],["装配 / 测试状态",assembly],
        ["频段",frequency_GHz?.wording || "待确认"],["参考面",reference_plane || (item.scope.reference_plane_applicable === false ? "不适用" : "待确认")],
        ["验证状态",verificationLabels[item.verification.status]],["验证记录",item.verification.summary]])}
      <button class="quiet ref-link" data-ref="${h(key(item.source))}">查看指标依据 · v${item.source.version}</button>
      <p>${h(item.source.locator)}</p></div>`;
  }).join("")}</section>`;
}
function bodyDetail(record) {
  const b = record.body;
  if (record.kind === "source") return metadata([["文件编号",b.document_code],["版本 / 版次",b.edition],["发布机构",b.issuer],["来源地址",b.source_url]]);
  if (record.kind === "interface") return metadata([["接口角色",b.role],["型式 / 变体",b.variant],["等级 / 类别",b.grade]]) + table(["参数语义 ID","范围","单位","备注"],(b.constraints || []).map(c => `<tr><td>${h(c.id)}</td><td>${h(intervalText(c))}</td><td>${h(c.unit)}</td><td>${h(c.note)}</td></tr>`));
  if (record.kind === "rule" && record.rule_mode === "manual") return `<p class="description">${h(b.review_instructions)}</p>`;
  if (record.kind === "rule") return metadata([["运算",b.operation],["孔参数",b.hole],["轴参数",b.shaft],["允许间隙",`${intervalText(b)} ${b.unit || ""}`]]);
  if (record.kind === "case") return `<p class="description">${h(b.description)}</p>`;
  if (record.kind === "selection") return table(["选定参数","值 / 范围","单位"],Object.entries(b.parameters || {}).map(([id,p]) => `<tr><td>${h(id)}</td><td>${h(p.value ?? intervalText(p))}</td><td>${h(p.unit)}</td></tr>`));
  if (record.kind === "template") return table(["参数语义 ID","原生模型尺寸名"],Object.entries(b.dimension_map || {}).map(([id,native]) => `<tr><td>${h(id)}</td><td>${h(native)}</td></tr>`)) + (b.artifact_id ? `<p><a href="/api/artifacts/${encodeURIComponent(b.artifact_id)}" download>下载模板附件</a></p>` : "");
  return "";
}
async function selectRecord(ref) {
  const r = await api(`/records/${ref.record_id}?version=${ref.version}`);
  state.selected = r;
  const snapshotPath = `/records/${r.record_id}/versions/${r.version}/snapshots`;
  const [versions,audit,snapshots] = await Promise.all([
    api(`/records/${r.record_id}/versions`),api(`/records/${r.record_id}/audit`),api(snapshotPath)
  ]);
  $$("[data-record]").forEach(btn => btn.classList.toggle("selected",btn.dataset.record === key(r)));
  const editable = r.status === "draft", historical = ["published","superseded","retired"].includes(r.status);
  const presented = new Set([...shownFields[r.kind],"artifact_ids_by_file","artifact_id"]);
  if (r.body.requirements_schema_version === 1) presented.add("requirements_schema_version");
  const details = Object.entries(r.body).filter(([name]) => !presented.has(name));
  $("#detail").innerHTML = `
    <div class="detail-top"><div>${badge(r.status)}${r.test_only ? `<span class="scope-label">${badge("test","测试数据")}</span>` : ""}</div><select id="version-select" aria-label="选择历史版本">${versions.items.map(v => `<option value="${v.version}" ${v.version === r.version ? "selected" : ""}>v${v.version} · ${h(statuses[v.status])}</option>`).join("")}</select></div>
    <h2>${h(r.title)}</h2><p class="description">${h(r.summary)}</p>
    <div class="row-meta">${h(classificationLabel(r) || kinds[r.kind])} / ${h(r.family || "未分类")}${r.status === "published" && !r.test_only ? " / 可供 Agent 引用" : ""}</div>
    ${r.test_only ? `<div class="notice warning">测试数据，不能作为工程设计依据。</div>` : ""}
    <div class="actions">
      ${editable ? `<button data-action="edit">${icon("pencil")}编辑草稿</button>` : ""}
      ${editable || r.status === "pending" ? `<button data-action="validate_publish" class="primary">${icon("check")}校验并发布</button>` : ""}
      ${r.status === "pending" ? `<button data-action="publish">人工审核发布</button><button data-action="return">退回草稿</button>` : ""}
      ${historical ? `<button data-action="new-version">${icon("copy-plus")}建立新版本</button><button data-action="context" title="导出固定版本的上下文">导出上下文</button>` : ""}
      ${r.status === "published" ? `<button data-action="retire" class="danger">停用</button>` : ""}
      ${historical && r.kind === "interface" ? `<button data-action="evaluate">检查参数</button>` : ""}
    </div>
    <section class="detail-section"><h3>内容</h3>${bodyDetail(r)}</section>
    ${r.kind === "case" ? requirementDetail(r.body) : ""}
    ${recordAttachments(r)}
    ${details.length ? `<section class="detail-section"><h3>详细记录</h3>${detailFields(details)}</section>` : ""}
    <section class="detail-section"><h3>依据与固定版本</h3>${r.references.map(ref => `<div class="evidence"><button class="quiet ref-link" data-ref="${h(key(ref))}">查看依据 · v${ref.version}</button><div>${h(ref.locator)}</div><div class="hash">${h(ref.record_id)}</div></div>`).join("") || `<p class="muted">未关联依据</p>`}</section>
    <section class="detail-section"><h3>版本信息</h3>${metadata([["版本",`v${r.version}`],["审核人",r.reviewed_by],["审核意见",r.review_note],["更新时间",date(r.updated_at)]])}<p class="hash">ID ${h(r.record_id)}<br>SHA256 ${h(r.content_hash)}</p></section>
    ${snapshots.items.length ? `<section class="detail-section"><h3>内容快照 · v${r.version}</h3><ul>${snapshots.items.map(snapshot => `<li><button class="quiet" data-snapshot="${h(snapshot.content_hash)}">读取 ${h(snapshot.content_hash.slice(0,12))}</button> <time>${h(date(snapshot.captured_at))}</time></li>`).join("")}</ul><div id="snapshot-preview"></div></section>` : ""}
    <section class="detail-section"><h3>变更记录</h3><ol class="audit">${audit.items.map(e => `<li><strong>v${e.version} · ${h({create:"建立",save:"保存",submit:"提交",publish:"人工审核发布",validate_publish:"自动校验发布",return:"退回",retire:"停用",new_version:"新建版本"}[e.action] || e.action)}</strong> · ${h(e.actor)}<p>${h(e.note)}</p><time>${h(date(e.created_at))}</time>${e.content_hash ? `<div class="hash">${h(e.content_hash.slice(0,12))}</div>` : ""}</li>`).join("")}</ol></section>`;
  $("#version-select").onchange = event => task(() => selectRecord({record_id:r.record_id,version:Number(event.target.value)}));
  $$(".ref-link").forEach(btn => btn.onclick = () => task(() => selectRecord(refOf(btn.dataset.ref))));
  $$("[data-action]").forEach(btn => btn.onclick = () => {
    if (btn.disabled) return;
    btn.disabled = true;
    return task(async () => {
      try {await recordAction(btn.dataset.action);} finally {btn.disabled = false;}
    });
  });
  $$("[data-snapshot]",$("#detail")).forEach(button => button.onclick = () => task(async () => {
    const result = await api(`${snapshotPath}/${button.dataset.snapshot}`);
    const preview = $("#snapshot-preview");
    if (!preview || !button.isConnected) return;
    preview.textContent = "";
    const content = document.createElement("pre");
    content.className = "description";
    content.textContent = JSON.stringify(result,null,2);
    preview.append(content);
  }));
  wirePreviews($("#detail"));
  icons();
}
async function recordAction(action) {
  const r = state.selected;
  if (action === "edit") return openEditor(r);
  if (action === "context") return download(`context-${r.record_id}-v${r.version}.json`,await api("/context",{method:"POST",body:{records:[{record_id:r.record_id,version:r.version}]}}));
  if (action === "evaluate") {state.evalProfile = r;return view("evaluate");}
  if (action === "validate_publish") {
    state.selected = await api(`/records/${r.record_id}/transition`,{
      method:"POST",body:{version:r.version,action,edit_token:r.edit_token,actor:actor(),note:""}
    });
    state.filters = {};
    await view("library");
    return toast("已通过校验并发布");
  }
  if (action === "new-version") {
    const draft = await api(`/records/${r.record_id}/versions`,{method:"POST",body:{from_version:r.version,actor:actor()}});
    state.selected = draft; await view("library"); return openEditor(draft);
  }
  state.review = action;
  const labels = {publish:"人工审核发布",return:"退回草稿",retire:"停用版本"};
  $("#review-title").textContent = labels[action]; $("#review-submit").textContent = labels[action];
  $("#review-record").textContent = `${r.title} · v${r.version}`;
  $("#review-form").elements.note.value = ""; error("","#review-error");
  $("#review-form").elements.actor.value = $("#actor").value;
  $("#review").showModal();
}
function input(name,label,value = "",type = "text") {return `<label>${h(label)}<input name="${h(name)}" type="${type}" value="${h(value)}"></label>`;}
function options(items, selected, first = "请选择") {return `<option value="">${first}</option>` + items.map(([value,label]) => `<option value="${h(value)}" ${value === selected ? "selected" : ""}>${h(label)}</option>`).join("");}
function artifactField(value) {return `<label class="wide">原始附件<div class="attachment-line"><select name="artifact_id">${options(state.artifacts.map(a => [a.artifact_id,a.filename]),value,"未选择附件")}</select><button type="button" id="editor-upload" title="上传附件">${icon("upload")}上传</button></div></label><input type="file" id="editor-file" hidden>`;}
function profileField(value) {return `<label class="wide">接口规范 · 固定版本<select name="profile_ref">${options(state.catalog.filter(r => r.kind === "interface").map(r => [key(r),`${r.title} · v${r.version}`]),value && key(value),"请选择接口规范")}</select></label>`;}
function unitSelect(value = "mm", name = "unit") {return `<select name="${name}" aria-label="单位">${["mm","in","deg","1"].map(u => `<option ${u === value ? "selected" : ""}>${u}</option>`).join("")}</select>`;}
function removeButton() {return `<button type="button" class="icon remove-row" title="移除此行" aria-label="移除此行">${icon("minus")}</button>`;}
function constraintRow(c = {}) {return `<div class="constraint">${input("id","参数语义 ID",c.id)}<label>单位${unitSelect(c.unit)}</label>${input("lower","下限",c.lower)}${input("upper","上限",c.upper)}${removeButton()}<label class="wide">备注<input name="note" value="${h(c.note)}"></label></div>`;}
function mapRow(id = "", value = "") {return `<div class="map-row">${input("id","参数语义 ID",id)}${input("native","原生尺寸名",value)}${removeButton()}</div>`;}
function parameterRow(id = "", p = {}, removable = false) {
  const interval = !("value" in p) && ("lower" in p || "upper" in p);
  return `<div class="parameter">${input("id","参数语义 ID",id)}<label>输入形式<select name="mode"><option value="scalar" ${!interval ? "selected" : ""}>单值</option><option value="interval" ${interval ? "selected" : ""}>公差区间</option></select></label>${input("lower","值 / 下限",interval ? p.lower : p.value)}${input("upper","上限",p.upper)}<label>单位${unitSelect(p.unit)}</label>${removable ? removeButton() : ""}</div>`;
}
function referenceRow(ref = {}) {return `<div class="reference-row"><label>发布条目 · 固定版本<select name="ref">${options(state.catalog.map(r => [key(r),`${kinds[r.kind]} / ${r.title} · v${r.version}`]),ref.record_id && key(ref))}</select></label>${input("locator","页码 / 表号 / 条款 / 证据位置",ref.locator)}${removeButton()}</div>`;}
function wireRows(root) {
  $$(".remove-row",root).forEach(btn => btn.onclick = () => btn.parentElement.remove());
  $$(".parameter",root).forEach(row => {
    const mode = $('[name="mode"]',row), upper = $('[name="upper"]',row);
    const toggle = () => {upper.disabled = mode.value === "scalar";};
    mode.onchange = toggle;toggle();
  });
  icons();
}

function renderKindFields(body = {}) {
  const kind = $("#edit-kind").value;
  let content = "";
  if (kind === "source") content = input("document_code","文件编号",body.document_code) + input("edition","版本 / 版次",body.edition) + input("issuer","发布机构",body.issuer) + input("source_url","来源地址（可选）",body.source_url) + artifactField(body.artifact_id);
  if (kind === "interface") content = input("role","接口角色",body.role) + input("variant","型式 / 变体",body.variant) + input("grade","等级 / 类别",body.grade) + `<div class="wide form-section"><div class="section-head"><h3>接口尺寸约束</h3><button type="button" id="add-constraint" class="quiet">${icon("plus")}添加参数</button></div><div id="constraint-rows">${(body.constraints || [{}]).map(constraintRow).join("")}</div></div>`;
  if (kind === "rule") content = `<label>检查方式<select name="operation"><option value="clearance" ${body.operation === "manual" ? "" : "selected"}>自动计算 · 孔轴间隙</option><option value="manual" ${body.operation === "manual" ? "selected" : ""}>人工核查</option></select></label>` +
    `<div id="automatic-fields" class="wide form-grid">${input("hole","孔参数语义 ID",body.hole)}${input("shaft","轴参数语义 ID",body.shaft)}<label>单位${unitSelect(body.unit)}</label>${input("lower","允许间隙下限",body.lower)}${input("upper","允许间隙上限",body.upper)}</div>` +
    `<label id="manual-fields" class="wide">核查步骤<textarea name="review_instructions" rows="5">${h(body.review_instructions)}</textarea></label>`;
  if (kind === "case") content = `<label>用途<select name="case_type">${options(Object.entries(caseTypes),body.case_type,"待分类")}</select></label><label class="wide">现象、条件与验证记录<textarea name="description" rows="6">${h(body.description)}</textarea></label>`;
  if (kind === "template") content = profileField(body.profile_ref) + artifactField(body.artifact_id) + `<div class="wide"><div class="section-head"><h3>原生模型尺寸映射</h3><button id="add-map" type="button" class="quiet">${icon("plus")}添加映射</button></div><div id="map-rows">${Object.entries(body.dimension_map || {}).map(([id,v]) => mapRow(id,v)).join("") || mapRow()}</div></div>`;
  if (kind === "selection") content = profileField(body.profile_ref) + `<div class="wide"><div class="section-head"><h3>选定参数</h3><button id="add-parameter" type="button" class="quiet">${icon("plus")}添加参数</button></div><div id="selection-rows">${Object.entries(body.parameters || {}).map(([id,p]) => parameterRow(id,p,true)).join("") || parameterRow("",{},true)}</div></div>`;
  $("#kind-fields").innerHTML = `<section class="form-section form-grid">${content}</section>`;
  const append = (button, target, html) => {if ($(button)) $(button).onclick = () => {$(target).insertAdjacentHTML("beforeend",html());wireRows($(target));};};
  append("#add-constraint","#constraint-rows",constraintRow); append("#add-map","#map-rows",mapRow); append("#add-parameter","#selection-rows",() => parameterRow("",{},true));
  if ($("#editor-upload")) {
    $("#editor-upload").onclick = () => $("#editor-file").click();
    $("#editor-file").onchange = () => task(async () => {
      const file = $("#editor-file").files[0]; if (!file) return;
      const data = new FormData(); data.append("file",file);
      const a = await api("/artifacts",{method:"POST",body:data}); state.artifacts.unshift(a);
      const select = $('[name="artifact_id"]');
      select.insertAdjacentHTML("afterbegin",`<option value="${h(a.artifact_id)}">${h(a.filename)}</option>`);select.value = a.artifact_id;
      toast("原始附件已保存"); await refreshStats();
    },"#form-error");
  }
  const operation = $('[name="operation"]',$("#kind-fields"));
  if (operation) {
    const toggle = () => {
      const manual = operation.value === "manual";
      $("#automatic-fields").style.display = manual ? "none" : "";
      $("#manual-fields").style.display = manual ? "" : "none";
    };
    operation.onchange = toggle;
    toggle();
  }
  wireRows($("#kind-fields"));
}
async function openEditor(record = null) {
  await catalog();
  if (record) for (const ref of record.references) if (!state.catalog.some(r => key(r) === key(ref))) {
    state.catalog.push(await api(`/records/${ref.record_id}?version=${ref.version}`));
  }
  state.edit = record;
  const form = $("#record-form");form.reset();error("","#form-error");
  $("#editor-title").textContent = record ? `编辑草稿 · v${record.version}` : "新建条目";
  $("#edit-kind").innerHTML = Object.entries(kinds).map(([id,label]) => `<option value="${id}">${label}</option>`).join("");
  form.elements.kind.value = record?.kind || "source";form.elements.kind.disabled = !!record;
  form.elements.actor.value = $("#actor").value;
  for (const name of ["family","title","summary"]) form.elements[name].value = record?.[name] || "";
  form.elements.test_only.checked = record ? record.test_only : !!state.stats.test_mode;
  form.elements.test_only.disabled = !!record || !!state.stats.test_mode;
  renderKindFields(record?.case_type ? {...record.body,case_type:record.case_type} : record?.body || {});
  $("#reference-rows").innerHTML = (record?.references || []).map(referenceRow).join("");
  $("#add-reference").onclick = () => {$("#reference-rows").insertAdjacentHTML("beforeend",referenceRow());wireRows($("#reference-rows"));};
  $("#edit-kind").onchange = () => renderKindFields();
  wireRows($("#reference-rows"));$("#editor").showModal();$("#editor .dialog-body").scrollTop = 0;
}
function rowValues(row) {return Object.fromEntries($$("input,select",row).map(el => [el.name,el.value.trim()]));}
function parametersFrom(rows) {
  const result = Object.create(null);
  for (const row of rows) {
    const v = rowValues(row);
    if (!v.id) throw new Error("参数语义 ID 不能为空。");
    if (Object.hasOwn(result,v.id)) throw new Error(`重复参数：${v.id}`);
    result[v.id] = v.mode === "scalar" ? {value:v.lower,unit:v.unit} : {lower:v.lower,upper:v.upper,unit:v.unit};
  }
  return result;
}
function readPayload() {
  const form = $("#record-form"), get = name => form.elements[name]?.value.trim() || "";
  const kind = get("kind"), body = {...(state.edit?.body || {})};
  const fields = {source:["document_code","edition","issuer","source_url","artifact_id"],interface:["role","variant","grade"],rule:["operation","hole","shaft","unit","lower","upper"],case:["description"],template:["artifact_id"],selection:[]}[kind];
  for (const field of fields) body[field] = get(field);
  if (kind === "interface") body.constraints = $$(".constraint",form).map(row => {const c = rowValues(row);return {...c,quantity:({deg:"angle","1":"dimensionless"}[c.unit] || "length"),lower:c.lower || null,upper:c.upper || null};});
  if (kind === "case" && get("case_type")) body.case_type = get("case_type");
  if (kind === "rule" && body.operation === "manual") {
    for (const field of ["hole","shaft","unit","lower","upper"]) delete body[field];
    body.review_instructions = get("review_instructions");
  } else if (kind === "rule") {
    body.lower ||= null;
    body.upper ||= null;
    delete body.review_instructions;
  }
  if (kind === "selection") body.parameters = parametersFrom($$("#selection-rows .parameter"));
  if (kind === "template") {
    body.dimension_map = Object.create(null);
    for (const row of $$(".map-row",form)) {const v = rowValues(row); if (!v.id || !v.native || Object.hasOwn(body.dimension_map,v.id)) throw new Error("尺寸映射需要唯一的语义 ID 和原生尺寸名。");body.dimension_map[v.id] = v.native;}
  }
  const references = $$(".reference-row",form).map(row => {const v = rowValues(row);if (!v.ref) throw new Error("请选择依据条目及其版本。");return {...refOf(v.ref),locator:v.locator};});
  if (kind === "selection" || kind === "template") {
    if (get("profile_ref")) {
      body.profile_ref = refOf(get("profile_ref"));
      if (!references.some(r => key(r) === key(body.profile_ref))) references.push({...body.profile_ref,locator:"接口规范版本"});
    } else delete body.profile_ref;
  }
  return {kind,title:get("title"),summary:get("summary"),family:get("family"),test_only:form.elements.test_only.checked,body,references};
}
$("#record-form").onsubmit = event => {
  event.preventDefault();
  const publish = event.submitter?.id === "publish-record";
  const buttons = [$("#save-record"), $("#publish-record")];
  if (buttons.some(button => button.disabled)) return;
  task(async () => {
    const record = readPayload(), name = actor($("#record-form").elements.actor.value), r = state.edit;
    rememberActor(name);
    buttons.forEach(button => button.disabled = true);
    try {
      const body = {record,actor:name,publish};
      state.selected = r ? await api(`/records/${r.record_id}/versions/${r.version}`,{method:"PUT",body:{...body,edit_token:r.edit_token}}) : await api("/records",{method:"POST",body});
      $("#editor").close();state.filters = {};await view("library");toast(publish ? "已通过校验并发布" : "草稿已保存");
    } finally {buttons.forEach(button => button.disabled = false);}
  },"#form-error");
};
$("#review-form").onsubmit = event => {
  event.preventDefault();
  task(async () => {
    const r = state.selected;$("#review-submit").disabled = true;
    try {
      const name = actor(event.target.elements.actor.value);rememberActor(name);
      state.selected = await api(`/records/${r.record_id}/transition`,{method:"POST",body:{version:r.version,action:state.review,edit_token:r.edit_token,actor:name,note:event.target.elements.note.value}});
      $("#review").close();await view(state.view);toast("版本状态已更新");
    } finally {$("#review-submit").disabled = false;}
  },"#review-error");
};
async function evaluationView() {
  await catalog();
  const profiles = state.catalog.filter(r => r.kind === "interface");
  if (state.evalProfile && !profiles.some(r => key(r) === key(state.evalProfile))) profiles.push(state.evalProfile);
  $("#workspace").innerHTML = `<div class="evaluation-form"><h2>固定版本参数检查</h2><label>接口规范<select id="eval-profile">${options(profiles.map(r => [key(r),`${r.title} · v${r.version}`]),state.evalProfile && key(state.evalProfile))}</select></label><form id="eval-form"><div id="eval-fields"></div></form><div id="eval-result"></div></div>`;
  $("#eval-profile").onchange = () => {state.evalProfile = profiles.find(r => key(r) === $("#eval-profile").value) || null;renderEvaluation();};
  $("#eval-form").onsubmit = event => {event.preventDefault();task(async () => {
    const profile = state.evalProfile;
    if (!profile) throw new Error("请选择已发布的接口规范。");
    const parameters = parametersFrom($$("#eval-fields .parameter"));
    const rules = $$('[name="eval-rule"]:checked').map(el => refOf(el.value));
    const result = await api("/evaluate",{method:"POST",body:{profile:{record_id:profile.record_id,version:profile.version},parameters,rules}});
    $("#eval-result").innerHTML = resultDetail(result);await refreshStats();icons();
  });};
  renderEvaluation();
}
function renderEvaluation() {
  const r = state.evalProfile;
  if (!r) {$("#eval-fields").innerHTML = empty("尚未选择接口规范","只读取已审核发布的尺寸约束","ruler");return;}
  const rules = state.catalog.filter(rule => rule.rule_mode === "automatic" && rule.family === r.family && rule.test_only === r.test_only);
  $("#eval-result").innerHTML = "";
  $("#eval-fields").innerHTML = `${r.test_only ? `<div class="notice warning">测试数据，检查结果不能用于工程设计。</div>` : ""}<section class="form-section"><h3>输入参数</h3>${(r.body.constraints || []).map(c => parameterRow(c.id,{value:"",unit:c.unit})).join("")}</section><section class="form-section"><h3>附加间隙规则</h3>${rules.map(rule => `<label class="check rule-choice"><input name="eval-rule" type="checkbox" value="${h(key(rule))}">${h(rule.title)} · v${rule.version}</label>`).join("") || `<p class="muted">无匹配系列的已发布规则</p>`}</section><div class="actions"><button type="submit" class="primary">${icon("play")}执行检查</button></div>`;
  $$(".parameter",$("#eval-fields")).forEach(row => row.querySelector('[name="id"]').readOnly = true);
  wireRows($("#eval-fields"));
}
function resultDetail(result) {
  return `<section class="result">${badge(result.outcome)} ${result.test_only ? badge("test","测试结果") : ""}${table(["检查项","结果","归一化范围 / 原因"],result.checks.map(c => `<tr><td>${h(c.id)}</td><td>${badge(c.outcome)}</td><td>${h(c.reason || `${intervalText(c.measured)} ${c.normalized_unit}；限值 ${intervalText(c.limits)}`)}</td></tr>`))}<p class="hash">上下文 SHA256 ${h(result.context_hash)}</p><p class="muted">${h(result.limitations)}</p>${(result.evidence_warnings || []).map(w => `<div class="notice warning">${h(w)}</div>`).join("")}</section>`;
}
async function runsView() {
  const result = await api(`/runs?limit=30&offset=${state.offset}`);
  $("#workspace").innerHTML = result.items.length ? table(["运行时间","结果","范围","运行编号"],result.items.map(r => `<tr class="run-row" data-run="${h(r.run_id)}"><td><button class="quiet">${h(date(r.created_at))}</button></td><td>${badge(r.outcome)}</td><td>${r.test_only ? badge("test","测试") : "正式"}</td><td class="hash">${h(r.run_id)}</td></tr>`)) + `<div class="pagination"><button id="runs-prev" ${!state.offset ? "disabled" : ""}>上一页</button><span>共 ${result.total} 次</span><button id="runs-next" ${state.offset + 30 >= result.total ? "disabled" : ""}>下一页</button></div><div id="run-detail"></div>` : empty("尚无运行记录","已保存的参数检查会保留输入与依据快照","history");
  if ($("#runs-prev")) $("#runs-prev").onclick = () => task(async () => {state.offset -= 30;await runsView();});
  if ($("#runs-next")) $("#runs-next").onclick = () => task(async () => {state.offset += 30;await runsView();});
  $$("[data-run]").forEach(row => row.onclick = () => task(async () => {
    const run = await api("/runs/" + row.dataset.run);
    $("#run-detail").innerHTML = `<section class="detail-section"><div class="section-head"><h2>运行快照</h2><button id="download-run">${icon("download")}导出快照</button></div>${resultDetail(run.result)}</section>`;
    $("#download-run").onclick = () => download(`run-${run.run_id}.json`,run);icons();
  }));
}
async function artifactsView() {
  const result = await api(`/artifacts?limit=30&offset=${state.offset}`);
  $("#workspace").innerHTML = `<form id="upload-form" class="artifact-upload"><input type="file" id="upload-file" aria-label="选择原始资料文件" required><button type="submit" class="primary">${icon("upload")}上传原始资料</button></form>${result.items.length ? table(["文件","大小","SHA256","保存时间"],result.items.map(a => `<tr><td><a href="/api/artifacts/${encodeURIComponent(a.artifact_id)}" download>${h(a.filename)}</a></td><td>${Math.ceil(a.byte_count / 1024)} KB</td><td class="hash">${h(a.sha256)}</td><td>${h(date(a.created_at))}</td></tr>`)) + `<div class="pagination"><button id="artifacts-prev" ${!state.offset ? "disabled" : ""}>上一页</button><span>共 ${result.total} 项</span><button id="artifacts-next" ${state.offset + 30 >= result.total ? "disabled" : ""}>下一页</button></div>` : empty("尚无原始附件","原文、图纸和模板保留原始文件与校验值","files")}`;
  if ($("#artifacts-prev")) $("#artifacts-prev").onclick = () => task(async () => {state.offset -= 30;await artifactsView();});
  if ($("#artifacts-next")) $("#artifacts-next").onclick = () => task(async () => {state.offset += 30;await artifactsView();});
  $("#upload-form").onsubmit = event => {event.preventDefault();task(async () => {
    const data = new FormData(); data.append("file",$("#upload-file").files[0]);
    await api("/artifacts",{method:"POST",body:data});await view("artifacts");toast("原始附件已保存");
  });};
}
$$(".nav").forEach(btn => btn.onclick = () => task(() => view(btn.dataset.view)));
$$("[data-close]").forEach(btn => btn.onclick = () => btn.closest("dialog").close());
$("#new-record").onclick = () => task(() => openEditor());
$("#refresh").onclick = () => task(() => view(state.view,false));
$("#backup").onclick = () => task(async () => {
  $("#backup").disabled = true;
  try {const result = await api("/backup",{method:"POST"});const link = document.createElement("a");link.href = "/api/backups/" + result.name;link.download = result.name;link.click();toast("备份已生成");} finally {$("#backup").disabled = false;}
});
$("#backup-mobile").onclick = () => $("#backup").click();
try {$("#actor").value = localStorage.getItem("rfkb-actor") || "";} catch {}
$("#actor").onchange = () => {try {localStorage.setItem("rfkb-actor",$("#actor").value);} catch {}};
task(() => view("library"));
