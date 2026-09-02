import { roadmap } from "./roadmap-data";

const capabilities = [
  ["01", "Startup help", "Follow the Hornet checklist and know when you are ready to taxi."],
  ["02", "Cockpit awareness", "Ask about switches, aircraft state, and general F/A-18C information."],
  ["03", "Flight information", "Get useful aircraft and flight status once you are airborne."],
  ["04", "Your controls", "Choose your microphone and speakers, then bind PTT and mute to a key, modifier combination, or HOTAS button."],
];

export default function Home() {
  return (
    <main>
      <header className="site-header">
        <a className="wordmark" href="#top" aria-label="MARA home">
          M.A.R.A <span>{"///"} DCS COPILOT</span>
        </a>
        <nav aria-label="Primary navigation">
          <a href="#capabilities">Capabilities</a>
          <a href="#roadmap">Roadmap</a>
          <a href="./docs/">Flight manual</a>
        </nav>
        <div className="header-actions">
          <span className="status-pill"><i /> Early access</span>
          <a className="kofi-link" href="https://ko-fi.com/nabblsawesome" target="_blank" rel="noreferrer">Support on Ko-fi ↗</a>
        </div>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Mission-aware realtime assistant</p>
          <h1>Your second seat.<br /><em>Always watching.</em></h1>
          <p className="lede">
            MARA is a voice copilot for DCS—aware of your aircraft, your phase
            of flight, and what needs your attention next.
          </p>
          <div className="hero-actions">
            <a className="button button-primary" href="./docs/">Read the flight manual <span>→</span></a>
            <a className="text-link" href="#capabilities">See what she can do ↓</a>
          </div>
        </div>

        <div className="portrait" aria-label="Reserved area for MARA character artwork">
          <img src="./mara-portrait.jpg" alt="MARA, the DCS voice copilot, against a formation of fighter aircraft" />
          <p className="portrait-caption"><b>CALLSIGN</b> MARA // MISSION-AWARE REALTIME ASSISTANT</p>
        </div>
      </section>

      <section className="capabilities" id="capabilities">
        <div className="section-heading">
          <p className="eyebrow">Built for the sortie</p>
          <h2>Not a chatbot.<br />A crew member.</h2>
        </div>
        <div className="capability-list">
          {capabilities.map(([number, title, body]) => (
            <article key={number}>
              <span>{number}</span>
              <h3>{title}</h3>
              <p>{body}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="home-roadmap" id="roadmap">
        <div className="home-roadmap-heading">
          <div>
            <p className="eyebrow">Development vector</p>
            <h2>The MARA<br /><em>roadmap.</em></h2>
          </div>
          <div className="roadmap-summary">
            <p>MARA starts narrow and earns her way outward: first the F/A-18C, then better awareness and coaching, then more aircraft.</p>
            <span>Direction, not a promise of dates.</span>
          </div>
        </div>
        <div className="roadmap-grid" aria-label="MARA product roadmap">
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
        </div>
      </section>

      <section className="open-source-callout">
        <p className="eyebrow">Open source</p>
        <h2>MARA will be<br /><em>open source.</em></h2>
        <div>
          <p>You’ll be able to read the code, report problems, contribute fixes, and help add support for other aircraft.</p>
          <a className="button" href="#roadmap">See the roadmap <span>↑</span></a>
        </div>
      </section>

      <footer>
        <div className="footer-mark">M.A.R.A</div>
        <p>Mission-Aware Realtime Assistant</p>
        <div className="footer-links"><a href="#roadmap">Roadmap</a><a href="./docs/">Flight manual →</a></div>
      </footer>
    </main>
  );
}
