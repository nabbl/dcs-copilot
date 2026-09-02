import type { Metadata } from "next";
import { roadmap } from "../roadmap-data";

export const metadata: Metadata = {
  title: "MARA Roadmap",
  description: "What works now and where the open-source DCS copilot is heading next.",
  openGraph: { title: "MARA Roadmap", description: "What works now and where MARA is heading next.", images: [] },
  twitter: { title: "MARA Roadmap", description: "What works now and where MARA is heading next.", images: [] },
};

export default function RoadmapPage() {
  return (
    <main className="roadmap-page">
      <header className="docs-header roadmap-header">
        <a className="wordmark" href="../">M.A.R.A <span>{"///"} DCS COPILOT</span></a>
        <div className="docs-main-links"><a href="../">Overview</a><a href="../docs/">Flight manual</a><a href="https://github.com/nabbl/dcs-copilot" target="_blank" rel="noreferrer">GitHub ↗</a></div>
        <span className="status-pill"><i /> Early build</span>
      </header>

      <section className="roadmap-intro">
        <div>
          <p className="eyebrow">What I’m working on</p>
          <h1>Where MARA<br /><em>goes next</em></h1>
        </div>
        <div className="roadmap-summary">
          <p>This is a working roadmap, not a release schedule. Priorities will change based on what people actually use and ask for.</p>
        </div>
      </section>

      <section className="roadmap-grid" aria-label="MARA product roadmap">
        {roadmap.map((column) => (
          <article className="roadmap-column" key={column.phase}>
            <div className="phase-tag"><span>{column.phase}</span>{column.label}</div>
            <h2>{column.title}</h2>
            <p className="phase-intro">{column.intro}</p>
            <ol>
              {column.items.map(([title, body]) => (
                <li key={title}><h3>{title}</h3><p>{body}</p></li>
              ))}
            </ol>
          </article>
        ))}
      </section>

      <section className="open-source-roadmap">
        <div><span>COMMUNITY PROJECT</span><h2>The code is public.</h2></div>
        <p>MARA is open source. Bug reports, testing, aircraft mappings, procedures, and ideas for useful cockpit help are all welcome.</p>
        <a className="button" href="https://github.com/nabbl/dcs-copilot" target="_blank" rel="noreferrer">View on GitHub <span>↗</span></a>
      </section>
    </main>
  );
}
