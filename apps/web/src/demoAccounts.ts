// SYNTHETIC demo accounts created by `make seed` (scripts/seed_demo.py). Local-only
// credentials: never shown in a production build unless explicitly flagged as a demo.

export const DEMO_PASSWORD = "cairn-demo-only";

export interface DemoAccount {
  email: string;
  name: string;
  role: string;
  description: string;
}

export const DEMO_ACCOUNTS: DemoAccount[] = [
  {
    email: "participant.health@smarttech.example",
    name: "Synthetic Participant A",
    role: "Participant",
    description: "Health journey: chat, upload evidence, manage consent",
  },
  {
    email: "participant.mentorship@smarttech.example",
    name: "Synthetic Participant B",
    role: "Participant",
    description: "Mentorship journey: chat, upload evidence, manage consent",
  },
  {
    email: "mentor.demo@smarttech.example",
    name: "Demo Mentor",
    role: "Facilitator",
    description: "Read-only view of the mentorship journey they mentor",
  },
  {
    email: "admin.demo@smarttech.example",
    name: "Demo Tenant Admin",
    role: "Administrator",
    description: "Every journey in the demo organisation",
  },
];

/** Dev server, or a build made with VITE_DEMO_ACCOUNTS=true (the local Compose stack). */
export const showDemoAccounts =
  import.meta.env.DEV || import.meta.env.VITE_DEMO_ACCOUNTS === "true";
