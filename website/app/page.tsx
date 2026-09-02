import { roadmap } from "./roadmap-data";

const capabilities = [
  ["01", "Startup guidance", "Walk through an F/A-18C cold start step by step. MARA checks supported cockpit state and can tell when you’re ready to continue."],
  ["02", "Cockpit questions", "Ask what a switch does, why a warning is on, or whether the aircraft is configured for the next step."],
  ["03", "In-flight help", "Get concise aircraft and flight information without digging through menus or taking your hands off the controls."],
  ["04", "Hands on the HOTAS", "Bind PTT and mute to a key or HOTAS button and talk to MARA when you need her."],
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
          <a href="https://github.com/nabbl/dcs-copilot" target="_blank" rel="noreferrer">GitHub ↗</a>
        </nav>
        <span className="status-pill"><i /> Early build</span>
      </header>

      <section className="hero" id="top">
        <div className="hero-copy">
          <p className="eyebrow">Experimental voice copilot for DCS</p>
          <h1>Your copilot <em>for DCS</em></h1>
          <p className="lede">
            MARA is a voice copilot for DCS. She can follow supported cockpit
            and flight state, help with procedures, answer questions, and point
            out things you may have missed.
          </p>
          <div className="hero-actions">
            <a className="button button-primary" href="./docs/">Get started <span>→</span></a>
            <a className="text-link" href="#capabilities">See what works today ↓</a>
          </div>
          <p className="hero-cost"><strong>Free to use.</strong> Bring your own OpenAI API key; usage is billed directly to your OpenAI account.</p>
        </div>

        <div className="portrait" aria-label="Reserved area for MARA character artwork">
          <img src="./mara-portrait.jpg" alt="MARA, the DCS voice copilot, against a formation of fighter aircraft" />
          <p className="portrait-caption"><b>CALLSIGN</b> MARA // MISSION-AWARE REALTIME ASSISTANT</p>
        </div>
      </section>

      <section className="capabilities" id="capabilities">
        <div className="section-heading">
          <p className="eyebrow">F/A-18C support</p>
          <h2>What MARA can<br />do today</h2>
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

      <section className="why-section">
        <div>
          <p className="eyebrow">Why I built this</p>
          <h2>It started with<br />a cold start.</h2>
        </div>
        <div className="why-copy">
          <p>I started MARA because I wanted something beside me in DCS that could actually understand what was happening in the aircraft—not just respond to voice commands. It started as a cold-start copilot and has slowly grown into an experiment in what a useful virtual crew member could be.</p>
          <p>I don’t know yet what MARA should become. That’s part of why I’m putting it out there early.</p>
        </div>
      </section>

      <section className="home-roadmap" id="roadmap">
        <div className="home-roadmap-heading">
          <div>
            <p className="eyebrow">What I’m working on</p>
            <h2>Where MARA<br /><em>goes next</em></h2>
          </div>
          <div className="roadmap-summary">
            <p>This is a working roadmap, not a release schedule. Priorities will change based on what people actually use and ask for.</p>
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
        <div>
          <p className="eyebrow">Community project</p>
          <h2>Built for<br /><em>DCS pilots.</em></h2>
        </div>
        <div className="community-copy">
          <p>MARA is a hobby project built for DCS pilots. The code is open source, and contributions are welcome—whether that’s a bug report, an aircraft mapping, a procedure, or an idea for something that would actually help in the cockpit.</p>
          <a className="button" href="https://github.com/nabbl/dcs-copilot" target="_blank" rel="noreferrer">View on GitHub <span>↗</span></a>
          <p className="community-note">Especially welcome: tell me what you actually want MARA to do.</p>
        </div>
      </section>

      <section className="support-callout">
        <div>
          <p className="eyebrow">Support the project</p>
          <h2>Like MARA?</h2>
        </div>
        <p>MARA is free and open source. If you want to help cover development costs, you can buy me a coffee.</p>
        <a className="button" href="https://ko-fi.com/nabblsawesome" target="_blank" rel="noreferrer">Support on Ko-fi <span>↗</span></a>
      </section>

      <footer>
        <div className="footer-mark">M.A.R.A</div>
        <p>Mission-Aware Realtime Assistant</p>
        <div className="footer-links"><a href="#roadmap">Roadmap</a><a href="./docs/">Flight manual</a><a href="https://github.com/nabbl/dcs-copilot" target="_blank" rel="noreferrer">GitHub ↗</a></div>
      </footer>
    </main>
  );
}
