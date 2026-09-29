// Appearance. Defaults to following the system, but "very dark" is a real complaint and
// the system setting is not always what someone wants while practising.

const KEY = "coach.theme";
export const CHOICES = ["auto", "light", "dark"];

export function current() {
  try { return localStorage.getItem(KEY) || "auto"; } catch { return "auto"; }
}

export function apply(choice = current()) {
  const root = document.documentElement;
  if (choice === "auto") root.removeAttribute("data-theme");
  else root.setAttribute("data-theme", choice);
}

export function set(choice) {
  try { localStorage.setItem(KEY, choice); } catch { /* private mode: this session only */ }
  apply(choice);
}
