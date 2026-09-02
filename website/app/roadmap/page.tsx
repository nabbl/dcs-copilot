import type { Metadata } from "next";

export const metadata: Metadata = {
  title: "MARA Roadmap",
  description: "What works now and where the open-source DCS copilot is heading next.",
  openGraph: { title: "MARA Roadmap", description: "What works now and where MARA is heading next.", images: [] },
  twitter: { title: "MARA Roadmap", description: "What works now and where MARA is heading next.", images: [] },
};

const roadmap = [
  {
    phase: "NOW",
    label: "Early access",
    title: "A useful Hornet copilot",
    intro: "The first public slice is intentionally focused: one aircraft, a dependable startup journey, and useful airborne context.",
    items: [
      ["Startup guidance", "Guided F/A-18C checklist assistance from cockpit entry through taxi readiness."],
      ["Cockpit-aware answers", "Reads supported switch and aircraft state, then answers questions with that live context."],
      ["General flight status", "Provides useful aircraft and flight information after takeoff."],
    ],
  },
  {
    phase: "NEXT",
    label: "Awareness & coaching",
    title: "See more. Teach better.",
    intro: "The next work turns MARA from a cockpit-aware copilot into a more capable training and situational-awareness partner.",
    items: [
      ["Combat awareness", "Help with radar contacts and analysis of the pilot’s radar picture."],
      ["Spatial Coach", "Finish live formation coaching, carrier approaches, CASE I segmentation, feedback, and debriefs."],
      ["Awareness-gap detection", "Identify specific differences between what the pilot appears to understand and what the available environment data shows."],
      ["Live validation", "Qualify behaviour across real single-player and multiplayer missions, including export restrictions."],
    ],
  },
  {
    phase: "LATER",
    label: "Broader capability",
    title: "More airframes. Deeper help.",
    intro: "Once the Hornet experience is trustworthy, MARA can expand without weakening the deterministic safety boundary.",
    items: [
      ["More fixed-wing aircraft", "Add aircraft through versioned cockpit mappings, curated knowledge, and explicit tests."],
      ["Helicopter support", "Extend flight-state, procedures, and coaching to rotary-wing operations."],
      ["Richer procedures", "Grow sourced startup, navigation, mission-configuration, landing, and aerial-refuelling guidance."],
      ["Better checklist control", "Add pause, repeat, defer, skip, interruption, and resume behaviour."],
      ["Offline resilience", "Provide critical local warning cues and clearer runtime-health reporting during service outages."],
    ],
  },
];

export default function RoadmapPage() {
  return (
    <main className="roadmap-page">
      <header className="docs-header roadmap-header">
        <a className="wordmark" href="../">M.A.R.A <span>/// DCS COPILOT</span></a>
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
