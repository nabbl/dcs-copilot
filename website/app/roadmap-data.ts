export const roadmap = [
  {
    phase: "NOW",
    label: "Getting the basics right",
    title: "A useful Hornet copilot",
    intro: "The first public version focuses on one aircraft and making the things MARA already does reliable and useful.",
    items: [
      ["Startup guidance", "Guided F/A-18C checklist assistance from cockpit entry through taxi readiness."],
      ["Cockpit-aware answers", "Reads supported switch and aircraft state, then answers questions with that live context."],
      ["General flight status", "Provides useful aircraft and flight information after takeoff."],
    ],
  },
  {
    phase: "NEXT",
    label: "After the basics",
    title: "Better awareness and coaching",
    intro: "Once the basics are solid, the focus shifts toward helping pilots notice more and improve how they fly.",
    items: [
      ["Radar assistance", "Help interpret your radar picture using only information already available in your cockpit."],
      ["Missed cues", "Point out important cockpit or flight-state cues that are easy to overlook."],
      ["Formation & carrier coaching", "Evaluate formation position, carrier approaches and CASE I patterns when the server allows the required telemetry."],
      ["Real-world testing", "Test behaviour across single-player and multiplayer missions, including servers with export restrictions."],
    ],
  },
  {
    phase: "LATER",
    label: "If it proves useful",
    title: "More aircraft and deeper support",
    intro: "If people find MARA useful, expand support without making the existing aircraft worse.",
    items: [
      ["More fixed-wing aircraft", "Add more aircraft one at a time, with proper cockpit mappings, procedures and testing."],
      ["Helicopter support", "Extend flight-state, procedures, and coaching to rotary-wing operations."],
      ["Richer procedures", "Grow sourced startup, navigation, mission-configuration, landing, and aerial-refuelling guidance."],
      ["Better checklist control", "Add pause, repeat, defer, skip, interruption, and resume behaviour."],
      ["Offline resilience", "Keep important local warnings working even if the AI service is temporarily unavailable."],
    ],
  },
] as const;
