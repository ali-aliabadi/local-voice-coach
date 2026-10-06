// Real job postings, from Himalayas, to practise the interview for. Choosing one makes it
// the job posting the interview modes read: the interviewer works there and asks against
// it. Himalayas' terms ask for a visible link back and its name as the source.

import { escape, get, post } from "../form.js";
import { go } from "../router.js";

const LEVELS = ["", "Entry-level", "Mid-level", "Senior", "Manager", "Director", "Executive"];

const posting = (job, n) => `<article class="job">
  <h2>${escape(job.title)}</h2>
  <p class="foot">${[job.company, job.location, job.salary, job.type,
    job.posted && `posted ${job.posted}`].filter(Boolean).map(escape).join(" · ")}</p>
  <p>${escape(job.excerpt)}</p>
  <div class="row">
    <button class="primary" data-job="${n}">Practise for this job</button>
    <a href="${escape(job.url)}" target="_blank" rel="noopener">Read it and apply on
      Himalayas ↗</a>
    <span class="saved" hidden>saved as your job posting</span>
  </div>
</article>`;

export async function render(root, _params, query) {
  root.innerHTML = `<h1>Jobs to practise for</h1><p class="foot loading">Looking…</p>`;
  const found = await get(`/api/jobs?${query}`);
  const page = Number(query.get("page")) || 1;
  const next = new URLSearchParams(query);
  next.set("page", page + 1);

  root.innerHTML = `
    <h1>Jobs to practise for</h1>
    <p class="foot lead">Real remote postings. Pick one and it becomes the job posting your
      interviewer reads: they work there, and ask against what it needs.</p>
    <form id="search">
      <label><span>Role or keywords</span>
        <input name="q" value="${escape(found.q ?? query.get("q"))}"></label>
      <label><span>Level</span><select name="seniority">${LEVELS.map((level) =>
        `<option value="${level}"${level === found.seniority ? " selected" : ""}>
          ${level || "any level"}</option>`).join("")}</select></label>
      <label><span>A country you can work from</span>
        <input name="country" placeholder="any — or e.g. Germany, DE"
          value="${escape(query.get("country"))}"></label>
      <label class="check"><input type="checkbox" name="worldwide" value="1"
        ${query.get("worldwide") === "1" ? "checked" : ""}> Open worldwide only</label>
      <button class="primary">Search</button>
    </form>
    ${found.error ? `<p class="notice">${escape(found.error)}</p>`
      : found.jobs.length ? found.jobs.map(posting).join("")
      : `<p class="foot">Nothing found. Try fewer words, or any level.</p>`}
    ${found.total > page * 20 ? `<p><a href="/jobs?${escape(next)}">More postings</a></p>` : ""}
    <p class="foot">Jobs from <a href="https://himalayas.app" target="_blank"
      rel="noopener">Himalayas</a>, a remote job board. Only your search leaves this
      machine, and only when you search.</p>`;

  root.querySelector("#search").addEventListener("submit", (event) => {
    event.preventDefault();
    const ask = new URLSearchParams(new FormData(event.target));
    go(`/jobs?${ask}`);
  });
  root.querySelectorAll("[data-job]").forEach((button) =>
    button.addEventListener("click", async () => {
      const job = found.jobs[Number(button.dataset.job)];
      await post("/api/profile", { job: `${job.title} at ${job.company}\n\n${job.description}` });
      button.parentElement.querySelector(".saved").hidden = false;
      setTimeout(() => go("/modes"), 900);
    }));
}
