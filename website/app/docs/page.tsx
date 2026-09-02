import type { Metadata } from "next";
import type { ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import manual from "../../content/manual.md?raw";

export const metadata: Metadata = {
  title: "MARA Flight Manual",
  description: "Requirements, setup, OpenAI API costs, controls, privacy, and troubleshooting for free MARA early access.",
  openGraph: { title: "MARA Flight Manual", description: "The early-access flight manual for MARA.", images: [] },
  twitter: { title: "MARA Flight Manual", description: "The early-access flight manual for MARA.", images: [] },
};

const chapters = [
  ["before-you-install", "Prerequisites"],
  ["choose-your-setup", "Choose your setup"],
  ["start-here", "Start here"],
  ["your-first-sortie", "Your first sortie"],
  ["what-mara-can-do", "What MARA can do"],
  ["voice-and-controls", "Voice and controls"],
  ["privacy-boundary", "Privacy boundary"],
  ["troubleshooting", "Troubleshooting"],
  ["early-access-expectations", "Early access"],
];

function textOf(children: ReactNode): string {
  if (typeof children === "string" || typeof children === "number") return String(children);
  if (Array.isArray(children)) return children.map(textOf).join("");
  if (children && typeof children === "object" && "props" in children) {
    return textOf((children as { props: { children?: ReactNode } }).props.children);
  }
  return "";
}

function slug(children: ReactNode) {
  return textOf(children).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/(^-|-$)/g, "");
}

export default function DocsPage() {
  return (
    <main className="docs-shell" id="top">
      <header className="docs-header">
        <a className="wordmark" href="../">M.A.R.A <span>{"///"} DCS COPILOT</span></a>
        <div className="docs-main-links"><a href="../">Overview</a><a href="../#roadmap">Roadmap</a><a href="https://github.com/nabbl/dcs-copilot" target="_blank" rel="noreferrer">GitHub ↗</a></div>
        <span className="status-pill"><i /> Early build</span>
      </header>

      <aside className="docs-sidebar">
        <p>On this page</p>
        <nav aria-label="Documentation chapters">
          {chapters.map(([id, label], index) => (
            <a href={`#${id}`} key={id}><span>{String(index + 1).padStart(2, "0")}</span>{label}</a>
          ))}
        </nav>
        <div className="sidebar-note">
          <b>EARLY ACCESS</b>
          <p>Windows · F/A-18C focus</p>
        </div>
      </aside>

      <article className="manual">
        <div className="manual-kicker">DOCUMENT // USER GUIDE</div>
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            h2: ({ children }) => <h2 id={slug(children)}>{children}<a href={`#${slug(children)}`} aria-label={`Link to ${textOf(children)}`}>#</a></h2>,
            h3: ({ children }) => <h3 id={slug(children)}>{children}</h3>,
          }}
        >
          {manual}
        </ReactMarkdown>
        <div className="manual-end">
          <span>END OF DOCUMENT</span>
          <a href="#top">Return to top ↑</a>
        </div>
      </article>
    </main>
  );
}
