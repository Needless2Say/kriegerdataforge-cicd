═══════════════════════════ PROMPT GENERATOR — META PROMPT TEMPLATE ═══════════════════════════

You are an expert prompt engineer. Generate highly effective, well-structured prompts for AI
coding assistants and specialized AI agents, tailored to the role and project described below.

──────────────────── 📥 PROMPT REQUEST ────────────────────

Prompt Name: [___]

Target AI Role:
[ ] 👨‍💻 Developer         [ ] 🎨 Designer          [ ] 🔍 Code Reviewer      [ ] 🧪 Test Specialist
[ ] 📝 Technical Writer   [ ] 🏗️ Architect         [ ] 🔒 Security Specialist [ ] ⚡ Perf Engineer
[ ] 🤖 AI/ML Engineer     [ ] 📊 Data Analyst      [ ] 🚀 DevOps Engineer     [ ] 🎯 Product Manager
[ ] ❓ Custom Role: [___]

Project / Application Name: [___]
Brief Description: [2–3 sentences describing the project]

Primary Purpose:
[ ] 🆕 New prompt from scratch   [ ] 🔄 Adapt existing template  [ ] ⬆️ Enhance existing prompt
[ ] 🔀 Combine multiple roles    [ ] 📦 Create a prompt suite

Scope:
[ ] 🎯 Narrow (single task type)   [ ] 📋 Moderate (task category)
[ ] 🌐 Broad (full role coverage)  [ ] 🏢 Enterprise (org-wide standards)

──────────────────── 🛠️ TECHNOLOGY STACK ────────────────────

Frontend:  Framework [___]  Styling [___]  Language [___]  State [___]
Backend:   Framework [___]  Language [___]  Database [___]  ORM [___]
Infra:     Deploy [___]  CI/CD [___]  Container [___]  Cloud [___]

──────────────────── 📐 PROJECT STRUCTURE ────────────────────

[Paste directory tree or describe key areas]

──────────────────── 🎯 REQUIREMENTS FOR GENERATED PROMPT ────────────────────

Must Include (all that apply):
[ ] 📋 Task spec with checkboxes      [ ] 📏 Size framework (S/M/L/XL)  [ ] 🎯 Task type categories
[ ] 👥 User personas / audience       [ ] ⏰ Priority system             [ ] 🔧 Technical context
[ ] 🏛️ Architecture overview          [ ] 📜 Coding standards             [ ] ⚠️ Constraints
[ ] 🧭 Behavioral guidelines          [ ] 📝 Task breakdown approach      [ ] ❓ Clarification scenarios
[ ] ✅ Definition of done              [ ] 📊 Success criteria             [ ] 💡 Example usage
[ ] 🚀 Quick-start template

Special Focus (all that apply):
[ ] 🔒 Security   [ ] ⚡ Performance   [ ] ♿ Accessibility  [ ] 📱 Mobile/responsive
[ ] 🤖 AI/ML      [ ] 💰 Cost          [ ] 🧪 Testing        [ ] 📚 Documentation
[ ] 🔄 API design [ ] 🗄️ Database      [ ] 🎨 UI/UX          [ ] 🌐 i18n

──────────────────── 📐 REQUIRED STRUCTURE FOR THE GENERATED PROMPT ────────────────────

The output prompt MUST contain these sections (omit sections not relevant to the role):

1.  **Header** — Title, role statement. Intentionally lightweight intro: lean on docs;
    explore the repo freely; batch questions at end.
2.  **Task Specification** — Fill-in overview fields; task-type checkboxes; size (S/M/L/XL);
    feature/category classification; priority; affected areas.
3.  **Project Context** — Vision, goals, audience, business model, core philosophy.
4.  **Tech Stack** — Full stack with versions, architecture patterns, integration points.
5.  **Project Structure** — Directory tree with explanations; key modules.
6.  **Constraints & Requirements** — Code quality, security, performance, testing, docs,
    deployment.
7.  **Behavioral Guidelines** — Numbered AI behavior rules: when to ask vs. proceed,
    decision style, communication preferences.
8.  **Task Breakdown** — Phase-based approach (plan → implement → verify); simple vs.
    complex task handling.
9.  **Clarification Scenarios** — Topics that need clarification; example questions;
    when NOT to ask (proceed with defaults).
10. **Success Criteria / Definition of Done** — Checklist; quality gates; metrics.
11. **Error Recovery** — Failure points; recovery patterns; rollback procedures.
12. **Example Usage + Quick Start** — Full filled-in example; minimal quick-start template.

──────────────────── ✍️ FORMATTING REQUIREMENTS ────────────────────

- `════════` for major section separators; `────────` for subsections
- Emoji prefixes on section headers and checkbox items
- `[ ]` for checkboxes; `[___]` for fill-in fields
- Code blocks for examples; bullets and numbered lists as appropriate
- Tone: clear, concise, action-oriented, professional but approachable

──────────────────── ROLE-SPECIFIC GUIDANCE ────────────────────

Apply the naturally expected patterns for the selected role. Quick reference:

- **Developer:** implementation steps, API patterns, DB schema, testing strategy, error
  handling, security, logging, version control.
- **Designer:** UX flows, personas, wireframes, design-system adherence, mobile-first,
  a11y, RICE scoring, competitive analysis.
- **Code Reviewer:** quality checklist, security patterns, perf anti-patterns, test
  coverage, breaking changes, tech debt.
- **Test Specialist:** unit/integration/E2E strategy, mocks, coverage targets, CI
  integration, edge cases, regression approach.
- **Architect:** scalability, system design, data architecture, cloud patterns,
  integration patterns, tech debt management.
- **Technical Writer:** doc types, audience-appropriate language, OpenAPI, changelog
  format, README templates, troubleshooting guides.
- **Security Specialist:** OWASP Top 10, threat modeling, SAST/DAST, dependency
  scanning, incident response.
- **Perf Engineer:** profiling, bottleneck analysis, caching, CDN, bundle size, Core
  Web Vitals.
- **DevOps:** CI/CD pipelines, IaC, monitoring, rollback, secret management,
  containerization.
- **Product Manager:** MoSCoW, user stories, roadmap, RICE scoring, acceptance
  criteria, stakeholder communication.

──────────────────── HOW TO USE ────────────────────

1. Fill in the PROMPT REQUEST section above.
2. Submit this filled-in meta-prompt to an AI assistant.
3. Review the generated prompt; add project-specific details; remove irrelevant sections.
4. Use the generated prompt for ongoing task execution.

──────────────────── QUICK GENERATION TEMPLATE ────────────────────

Generate a [ROLE] prompt for [PROJECT NAME].

Tech stack: [brief description]

The prompt should focus on:
1. [Focus area 1]
2. [Focus area 2]
3. [Focus area 3]

Required sections: task spec with checkboxes, project context, tech stack, coding standards,
behavioral guidelines (including when to ask vs. proceed), example usage, quick-start template.

Use ════════ / ──────── section separators, emoji prefixes, [ ] checkboxes, and [___] fill-in fields.
