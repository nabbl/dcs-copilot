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
        <div className="docs-main-links"><a href="../">Overview</a><a href="../docs/">Flight manual</a></div>
        <a className="kofi-link" href="https://ko-fi.com/nabblsawesome" target="_blank" rel="noreferrer">Support on Ko-fi ↗</a>
      </header>

      <section className="roadmap-intro">
        <div>
          <p className="eyebrow">Development vector</p>
          <h1>The MARA<br /><em>roadmap.</em></h1>
        </div>
        <div className="roadmap-summary">
          <p>MARA starts narrow and earns her way outward: first the F/A-18C, then better awareness and coaching, then more aircraft.</p>
          <span>Direction, not a promise of dates.</span>
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
        <div><span>OPEN SOURCE</span><h2>The code will be public.</h2></div>
        <p>Once the early-access release is ready, the repository will be public. Contributions, testing, and support for more aircraft will be welcome.</p>
        <a className="button" href="https://ko-fi.com/nabblsawesome" target="_blank" rel="noreferrer">Support development <span>↗</span></a>
      </section>
    </main>
  );
}
