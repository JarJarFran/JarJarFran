"use strict";

const state = {
  options: null,
  profile: null,
  result: null,
  history: [],
  exercises: new Map(),
};

const $ = (id) => document.getElementById(id);

// ---------------------------------------------------------------------------
// Utilidades
// ---------------------------------------------------------------------------

let toastTimer = null;
function toast(message, isError = false) {
  const node = $("toast");
  node.textContent = message;
  node.classList.toggle("error", isError);
  node.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { node.hidden = true; }, isError ? 7000 : 3500);
}

async function api(path, body) {
  const response = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    let detail = `Error ${response.status}`;
    try {
      const payload = await response.json();
      if (payload.detail) {
        detail = typeof payload.detail === "string"
          ? payload.detail
          : JSON.stringify(payload.detail);
      }
    } catch { /* respuesta sin JSON: nos quedamos con el código */ }
    throw new Error(detail);
  }
  return response;
}

function chip(name, value, label, checked = false) {
  const wrapper = document.createElement("label");
  wrapper.className = "chip";
  const input = document.createElement("input");
  input.type = "checkbox";
  input.name = name;
  input.value = value;
  input.checked = checked;
  const span = document.createElement("span");
  span.textContent = label;
  wrapper.append(input, span);
  return wrapper;
}

function checkedValues(containerId) {
  return [...document.querySelectorAll(`#${containerId} input:checked`)].map((i) => i.value);
}

// ---------------------------------------------------------------------------
// Arranque
// ---------------------------------------------------------------------------

async function boot() {
  const response = await fetch("/api/options");
  const options = await response.json();
  state.options = options;

  for (const goal of options.goals) {
    $("goal").append(new Option(goal.label, goal.value));
  }
  for (const level of options.experience) {
    $("experience").append(new Option(level, level));
  }

  // Material: los más habituales vienen premarcados para que la primera
  // generación funcione sin tocar nada.
  const preselected = new Set(["body weight", "dumbbell", "barbell"]);
  const equipment = $("equipment");
  for (const item of options.equipment) {
    equipment.append(chip("equipment", item.value, item.label, preselected.has(item.value)));
  }

  const injuries = $("injuries");
  for (const joint of options.injuries) {
    injuries.append(chip("injuries", joint, joint));
  }

  $("engine-badge").textContent = options.ai_available
    ? `IA activa · ${options.model}`
    : "Sin clave de API · planificador determinista";
  $("catalog-note").textContent = `${options.exercise_count} ejercicios en catálogo.`;

  const quick = [
    "Tengo menos tiempo: recorta las sesiones a 45 minutos.",
    "Cambia el ejercicio principal del primer día por otro patrón.",
    "Sube el volumen de espalda y baja el de pecho.",
    "Añade más trabajo de core al final de cada sesión.",
    "Quiero centrarme en mejorar la sentadilla.",
  ];
  for (const text of quick) {
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = text;
    button.addEventListener("click", () => { $("adapt-text").value = text; });
    $("quick-adapts").append(button);
  }
}

function readProfile() {
  const equipment = checkedValues("equipment");
  if (equipment.length === 0) {
    throw new Error("Selecciona al menos un tipo de material disponible.");
  }
  const age = $("age").value;
  const weight = $("weight").value;
  return {
    goal: $("goal").value,
    experience: $("experience").value,
    days_per_week: Number($("days").value),
    session_minutes: Number($("minutes").value),
    equipment,
    injuries: checkedValues("injuries"),
    age: age ? Number(age) : null,
    bodyweight_kg: weight ? Number(weight) : null,
    notes: $("notes").value.trim(),
  };
}

// ---------------------------------------------------------------------------
// Render
// ---------------------------------------------------------------------------

async function loadExercise(id) {
  if (state.exercises.has(id)) return state.exercises.get(id);
  const response = await fetch(`/api/exercises/${id}`);
  if (!response.ok) return null;
  const exercise = await response.json();
  state.exercises.set(id, exercise);
  return exercise;
}

function renderIssues(issues) {
  const container = $("issues");
  container.innerHTML = "";
  if (!issues.length) return;
  for (const issue of issues) {
    const node = document.createElement("div");
    node.className = `notice ${issue.severity}`;
    const code = document.createElement("code");
    code.textContent = issue.code;
    node.append(code, document.createTextNode(` — ${issue.message}`));
    container.append(node);
  }
}

async function renderRoutine(result) {
  const routine = result.routine;
  $("routine-title").textContent = routine.title;
  $("routine-summary").textContent = routine.summary;
  renderIssues(result.issues);

  const container = $("day-list");
  container.innerHTML = "";

  for (const day of routine.days) {
    const section = document.createElement("section");
    section.className = "day";

    const head = document.createElement("div");
    head.className = "day-head";
    const title = document.createElement("h3");
    title.textContent = day.name;
    const meta = document.createElement("span");
    meta.className = "meta";
    meta.textContent = day.focus;
    head.append(title, meta);
    section.append(head);

    for (const block of day.blocks) {
      const exercise = await loadExercise(block.exercise_id);
      const row = document.createElement("div");
      row.className = "block";

      const img = document.createElement("img");
      img.loading = "lazy";
      img.width = 84;
      img.height = 84;
      img.alt = exercise ? `Ejecución de ${exercise.name}` : "";
      if (exercise) img.src = exercise.gif_url;
      row.append(img);

      const info = document.createElement("div");
      const name = document.createElement("div");
      name.className = "name";
      const role = document.createElement("span");
      role.className = "role";
      role.textContent = block.role;
      name.append(role, document.createTextNode(exercise ? exercise.name : block.exercise_id));
      const sub = document.createElement("div");
      sub.className = "sub";
      sub.textContent = exercise
        ? `${exercise.body_part} · ${exercise.target} · ${exercise.equipment}`
        : "";
      info.append(name, sub);
      if (block.notes) {
        const cue = document.createElement("div");
        cue.className = "cue";
        cue.textContent = block.notes;
        info.append(cue);
      }
      row.append(info);

      const presc = document.createElement("div");
      presc.className = "presc";
      const main = document.createElement("b");
      main.textContent = `${block.sets} × ${block.reps}`;
      presc.append(main, document.createTextNode(
        `RIR ${block.rir} · ${block.rest_seconds}s`,
      ));
      row.append(presc);

      section.append(row);
    }
    container.append(section);
  }

  const history = $("history");
  history.innerHTML = "";
  for (const entry of state.history) {
    const item = document.createElement("li");
    item.textContent = entry;
    history.append(item);
  }

  $("empty-state").hidden = true;
  $("routine").hidden = false;
}

// ---------------------------------------------------------------------------
// Acciones
// ---------------------------------------------------------------------------

async function generate(event) {
  event.preventDefault();
  const button = $("generate-btn");
  const original = button.textContent;
  try {
    state.profile = readProfile();
  } catch (error) {
    toast(error.message, true);
    return;
  }
  button.disabled = true;
  button.textContent = "Generando…";
  try {
    const response = await api("/api/routines", {
      profile: state.profile,
      engine: "auto",
    });
    state.result = await response.json();
    state.history = [];
    await renderRoutine(state.result);
    const errors = state.result.issues.filter((i) => i.severity === "error").length;
    toast(errors
      ? `Rutina generada con ${errors} incumplimiento(s) sin resolver.`
      : "Rutina generada y validada.", errors > 0);
    $("result-panel").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function adapt(event) {
  event.preventDefault();
  const text = $("adapt-text").value.trim();
  if (!text) {
    toast("Escribe qué quieres cambiar.", true);
    return;
  }
  const button = $("adapt-btn");
  const original = button.textContent;
  button.disabled = true;
  button.textContent = "Aplicando…";
  try {
    const response = await api("/api/routines/adapt", {
      profile: state.profile,
      routine: state.result.routine,
      request: text,
    });
    state.result = await response.json();
    state.history.push(text);
    $("adapt-text").value = "";
    await renderRoutine(state.result);
    toast("Rutina actualizada.");
  } catch (error) {
    toast(error.message, true);
  } finally {
    button.disabled = false;
    button.textContent = original;
  }
}

async function openDocument() {
  try {
    // Con copia local de los GIF el documento se genera autocontenido, así
    // se puede guardar y consultar sin conexión.
    const embed = state.options?.local_media ? "?embed=1" : "";
    const response = await api(`/api/document.html${embed}`, {
      profile: state.profile,
      result: state.result,
    });
    const html = await response.text();
    const url = URL.createObjectURL(new Blob([html], { type: "text/html" }));
    window.open(url, "_blank", "noopener");
    setTimeout(() => URL.revokeObjectURL(url), 60000);
  } catch (error) {
    toast(error.message, true);
  }
}

async function downloadMarkdown() {
  try {
    const response = await api("/api/document.md", {
      profile: state.profile,
      result: state.result,
    });
    const text = await response.text();
    const url = URL.createObjectURL(new Blob([text], { type: "text/markdown" }));
    const link = document.createElement("a");
    link.href = url;
    link.download = "rutina.md";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    toast(error.message, true);
  }
}

$("profile-form").addEventListener("submit", generate);
$("adapt-form").addEventListener("submit", adapt);
$("doc-btn").addEventListener("click", openDocument);
$("md-btn").addEventListener("click", downloadMarkdown);

boot().catch((error) => toast(`No se pudo cargar la app: ${error.message}`, true));
