// Paste into mcp__claude-in-chrome__javascript_tool on a LinkedIn /jobs/search-results/ page.
// Scrolls the results list and returns one compact object per job card.
// Card root: [componentkey="job-card-component-ref-<jobId>"] (LinkedIn AI-search UI, Oct 2026).
const seen = new Map();
const clean = s => s.replace(/^Selected,\s*/, '').replace(/\s*\(Verified job\)$/, '').trim();
const grab = () => {
  for (const el of document.querySelectorAll('[componentkey^="job-card-component-ref-"]')) {
    const id = el.getAttribute('componentkey').replace('job-card-component-ref-', '');
    if (seen.has(id)) continue;
    let l = el.innerText.split('\n').map(s => s.trim()).filter(Boolean)
      .filter(s => !/^(Verified job|Promoted|Viewed|Saved|·|•)$/.test(s));
    if (!l.length) continue;
    const title = clean(l[0]);
    if (l[1] && clean(l[1]) === title) l.splice(1, 1);
    const rest = l.slice(1);
    const company = rest[0] || '';
    const location = rest.find(s => /\((Remote|Hybrid|On-site)\)|United States|, [A-Z]{2}\b/.test(s) && s !== company) || '';
    const salary = (rest.find(s => /\$[\d.,]+K?\/(yr|hr)/.test(s)) || '').trim();
    const posted = ((rest.find(s => /^Posted /.test(s)) || '').replace('Posted ', ''));
    const applicants = (rest.find(s => /applicants?/i.test(s) && !/early applicant|reviewing/i.test(s)) || '');
    const flags = rest.filter(s => /top applicant|Be an early applicant|Actively reviewing|connection|alumni/i.test(s)).join('; ');
    const applied = rest.some(s => /^Applied/.test(s));
    seen.set(id, { id, title, company, location, salary, posted, applicants, flags, applied,
                   url: `https://www.linkedin.com/jobs/view/${id}/` });
  }
};
const first = document.querySelector('[componentkey^="job-card-component-ref-"]');
let sc = first;
while (sc && !(sc.scrollHeight > sc.clientHeight + 50 && /auto|scroll/.test(getComputedStyle(sc).overflowY))) sc = sc.parentElement;
for (let i = 0; i < 12; i++) { grab(); (sc || window).scrollBy(0, 600); await new Promise(r => setTimeout(r, 500)); }
grab();
({ count: seen.size, jobs: [...seen.values()] })
