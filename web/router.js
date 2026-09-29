// Real paths, not hashes: /profile and /history/3 survive a reload and can be pasted to
// someone. The server serves index.html for anything it does not claim itself.

const routes = [];
let current = null;

export function route(pattern, view) {
  const names = [];
  const regex = new RegExp(
    "^" + pattern.replace(/:(\w+)/g, (_, name) => {
      names.push(name);
      return "([^/]+)";
    }) + "$",
  );
  routes.push({ regex, names, view });
}

export function go(path, replace = false) {
  if (path !== location.pathname) {
    history[replace ? "replaceState" : "pushState"]({}, "", path);
  }
  render();
}

export async function render() {
  const path = location.pathname;
  const root = document.getElementById("app");

  // Let the view being left tear down: the practice view has a socket and a microphone.
  if (current?.leave) await current.leave();
  current = null;

  for (const { regex, names, view } of routes) {
    const match = path.match(regex);
    if (!match) continue;
    const params = Object.fromEntries(names.map((n, i) => [n, match[i + 1]]));
    current = view;
    root.innerHTML = "";
    await view.render(root, params, new URLSearchParams(location.search));
    document.querySelectorAll("header a").forEach((a) =>
      a.classList.toggle("on", a.getAttribute("href") === path));
    return;
  }
  root.innerHTML = `<h1>Not found</h1><p class="foot">
    <a href="/">Back to practice</a></p>`;
}

// One listener for every internal link, so no view has to wire up navigation.
document.addEventListener("click", (event) => {
  const link = event.target.closest("a[href^='/']");
  if (!link || link.target || event.metaKey || event.ctrlKey) return;
  event.preventDefault();
  go(link.getAttribute("href"));
});

addEventListener("popstate", render);
