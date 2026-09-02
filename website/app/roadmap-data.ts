export const roadmap = [
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
] as const;
