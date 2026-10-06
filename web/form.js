// Form fields rendered from what the server declares, so adding a field in Python makes
// it appear here with no change to this file. Shared by the profile and settings pages.

export const escape = (text) =>
  String(text ?? "").replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

export function field(item) {
  const id = `f-${item.key}`;
  const note = [
    item.help,
    item.restart ? "Takes effect after a restart." : "",
    item.isSet ? "A value is stored. Leave blank to keep it." : "",
    item.isDefault === false ? "Customised — clear the box for the built-in one." : "",
  ].filter(Boolean).join(" ");

  let input;
  if (item.kind === "document") {
    // A file is read into the box by the server (documents.py), to check before saving.
    return `<label for="${id}"><span>${escape(item.label)}</span>
      <textarea id="${id}" name="${item.key}" rows="10">${escape(item.value)}</textarea>
      <small id="${id}-note">${escape(note)}</small></label>
      <input type="file" class="upload" accept=".pdf,.docx,.odt,.txt,.md" data-into="${id}"
        aria-label="Upload a file for: ${escape(item.label)}">`;
  }
  if (item.kind === "textarea") {
    const hint = item.placeholder || (item.default || "").slice(0, 110);
    input = `<textarea id="${id}" name="${item.key}" rows="4"
      placeholder="${escape(hint)}">${escape(item.value)}</textarea>`;
  } else if (item.kind === "select") {
    const options = (item.choices?.length ? item.choices : [item.value]).map((choice) =>
      `<option${choice === item.value ? " selected" : ""}>${escape(choice)}</option>`);
    input = `<select id="${id}" name="${item.key}">${options.join("")}</select>`;
  } else {
    const step = item.step ? ` step="${item.step}"` : "";
    const placeholder = item.secret && item.isSet
      ? ' placeholder="•••••••• stored"'
      : item.placeholder ? ` placeholder="${escape(item.placeholder)}"` : "";
    input = `<input id="${id}" name="${item.key}" type="${item.kind}"${step}${placeholder}
      value="${item.secret ? "" : escape(item.value)}">`;
  }

  return `<label for="${id}"><span>${escape(item.label)}</span>${input}
    ${note ? `<small>${escape(note)}</small>` : ""}</label>`;
}

export function values(form) {
  const out = {};
  new FormData(form).forEach((value, key) => { out[key] = value; });
  return out;
}

export async function post(url, payload) {
  await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export const get = async (url) => (await fetch(url)).json();
