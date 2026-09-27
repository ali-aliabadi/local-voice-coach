// The settings form renders itself from what the server declares in settings.SPEC, so
// adding a knob in Python makes it appear here with no change to this file.

const escape = (text) =>
  String(text).replace(/[&<>"]/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);

function field(item) {
  const id = `set-${item.key}`;
  const note = [
    item.help,
    item.restart ? 'Takes effect after a restart.' : '',
    item.isSet ? 'A value is stored. Leave blank to keep it.' : '',
    item.isDefault === false ? 'Customised — clear the box to go back to the default.' : '',
  ].filter(Boolean).join(' ');

  let input;
  if (item.kind === 'textarea') {
    input = `<textarea id="${id}" name="${item.key}"
      placeholder="${escape((item.default || '').slice(0, 120))}…">${escape(item.value)}</textarea>`;
  } else if (item.kind === 'select') {
    const options = (item.choices.length ? item.choices : [item.value]).map(
      (choice) => `<option${choice === item.value ? ' selected' : ''}>${escape(choice)}</option>`);
    input = `<select id="${id}" name="${item.key}">${options.join('')}</select>`;
  } else {
    const step = item.step ? ` step="${item.step}"` : '';
    const placeholder = item.secret && item.isSet ? ' placeholder="•••••••• stored"' : '';
    input = `<input id="${id}" name="${item.key}" type="${item.kind}"${step}${placeholder}
      value="${item.secret ? '' : escape(item.value)}">`;
  }

  return `<label for="${id}"><span>${escape(item.label)}</span>${input}
    ${note ? `<small>${escape(note)}</small>` : ''}</label>`;
}

export async function renderSettings(form) {
  const items = await (await fetch('/api/settings')).json();
  const groups = ['Backends', 'Scoring', 'Model', 'Prompts'];
  form.innerHTML = groups.map((group) => {
    const rows = items.filter((item) => item.group === group);
    if (!rows.length) return '';
    const intro = group === 'Prompts'
      ? '<p class="foot">Aim the interviewer at a specific company, role or seniority. '
        + 'Clear a box to restore the built-in prompt.</p>'
      : '';
    return `<fieldset><legend>${group}</legend>${intro}${rows.map(field).join('')}</fieldset>`;
  }).join('');
}

export async function saveSettings(form) {
  const payload = {};
  new FormData(form).forEach((value, key) => { payload[key] = value; });
  await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  });
}
