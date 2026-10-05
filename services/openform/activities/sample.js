/* Runs inside the isolated page. Authorization and persistence belong to the host. */
(() => {
  const form = document.getElementById("answers");
  const status = document.getElementById("status");
  let revision = 0, initialized = false, completed = false, busy = false, pending = null;
  const fields = [];
  const notice = (message) => { status.textContent = message; };
  function controls() {
    form.querySelectorAll("button,input,textarea").forEach((control) => { control.disabled = busy || !initialized || completed; });
  }
  function readPath(value, path) { return path.split(".").reduce((item, key) => item && item[key], value); }
  function setPath(value, path, result) {
    const keys = path.split("."); let current = value;
    keys.slice(0, -1).forEach((key) => { current = current[key] ??= {}; });
    current[keys.at(-1)] = result;
  }
  function schemaAt(path) {
    return path.split(".").reduce((schema, key) => schema.properties[key], activityConfig.submissionSchema);
  }
  for (const question of activityConfig.questions) {
    const box = document.createElement("fieldset"), legend = document.createElement("legend");
    legend.textContent = question.title; box.append(legend);
    const schema = schemaAt(question.dataPath);
    const field = { question, box, inputs: [] }; fields.push(field);
    if (question.kind === "choice") {
      for (const option of schema.enum) {
        const label = document.createElement("label"), input = document.createElement("input");
        input.type = "radio"; input.name = question.id; input.value = option; input.required = true;
        label.append(input, document.createTextNode(option)); box.append(label); field.inputs.push(input);
      }
    } else if (question.kind === "observations") {
      const rows = document.createElement("div"), add = document.createElement("button");
      add.type = "button"; add.textContent = "增加测量记录";
      field.add = (data = {}) => {
        if (rows.children.length >= schema.maxItems) { notice("测量记录已达到上限。"); return; }
        const row = document.createElement("div"); row.className = "row";
        for (const [name, rule] of Object.entries(schema.items.properties)) {
          const label = document.createElement("label"), input = document.createElement("input");
          label.textContent = name === "temperature" ? "温度（℃）" : "溶解时间（秒）";
          input.type = "number"; input.step = "any"; input.min = rule.minimum; input.max = rule.maximum;
          input.required = true; input.dataset.field = name; input.value = data[name] ?? ""; label.append(input); row.append(label);
        }
        const remove = document.createElement("button"); remove.type = "button"; remove.textContent = "删除记录";
        remove.addEventListener("click", () => row.remove()); row.append(remove); rows.append(row); controls();
      };
      add.addEventListener("click", () => field.add()); field.rows = rows; box.append(rows, add); field.add();
    } else {
      const input = document.createElement("textarea"); input.rows = 4; input.required = true;
      input.maxLength = schema.maxLength; input.setAttribute("aria-label", question.title); box.append(input); field.inputs.push(input);
    }
    document.getElementById("questions").append(box);
  }
  function collect() {
    const result = {};
    for (const field of fields) {
      let value;
      if (field.rows) value = Array.from(field.rows.children).map((row) => {
        const data = {}; row.querySelectorAll("input").forEach((input) => { if (input.value !== "") data[input.dataset.field] = Number(input.value); }); return data;
      });
      else if (field.question.kind === "choice") value = field.inputs.find((input) => input.checked)?.value;
      else value = field.inputs[0].value;
      if (value !== undefined) setPath(result, field.question.dataPath, value);
    }
    return result;
  }
  function render(data) {
    for (const field of fields) {
      const value = readPath(data, field.question.dataPath);
      if (field.rows) { field.rows.replaceChildren(); for (const row of value ?? [{}]) field.add(row); }
      else if (field.question.kind === "choice") field.inputs.forEach((input) => { input.checked = input.value === value; });
      else field.inputs[0].value = value ?? "";
    }
  }
  async function load() {
    const result = await OpenForm.loadProgress(); revision = result.revision; completed = result.state === "submitted";
    render(result.data); notice(completed ? "已提交。持久化回执：" + result.receipt.receiptId : "已读取服务端进度，版本 " + revision + "。");
    return result;
  }
  async function write(method, data) {
    if (pending && (pending.method !== method || JSON.stringify(pending.params.data) !== JSON.stringify(data))) {
      throw new Error("上一项操作结果待确认，请先读取进度或在活动外恢复回执，再继续修改。");
    }
    pending ??= { method, params: { data, expectedRevision: revision, idempotencyKey: OpenForm.newIdempotencyKey() } };
    try {
      const receipt = await OpenForm[method](pending.params); revision = receipt.revision; pending = null;
      completed = receipt.state === "submitted";
      notice((completed ? "已提交" : "已保存") + "。持久化回执：" + receipt.receiptId); return receipt;
    } catch (error) {
      if (!error.code || !["RESULT_UNKNOWN", "SERVICE_UNAVAILABLE"].includes(error.code)) pending = null;
      throw error;
    }
  }
  async function action(run) {
    if (busy) return; busy = true; controls();
    try { await run(); } catch (error) { notice(error.message || "操作结果未确认，请查看活动外的恢复提示。"); }
    finally { busy = false; controls(); }
  }
  document.getElementById("save").addEventListener("click", () => action(() => write("saveProgress", collect())));
  document.getElementById("read").addEventListener("click", () => action(load));
  document.getElementById("submit").addEventListener("click", () => {
    if (Array.from(form.querySelectorAll("input,textarea")).some((input) => !input.reportValidity())) return;
    const data = collect();
    void action(async () => {
      const saved = await write("saveProgress", data);
      const reread = await load();
      if (reread.revision !== saved.revision) throw new Error("另一设备已更新作答。页面已读取新内容，请核对后再次提交。");
      await write("submit", data);
    });
  });
  controls();
  void action(async () => { await OpenForm.ready({ capabilities: activityConfig.capabilities }); initialized = true; await load(); });
})();
