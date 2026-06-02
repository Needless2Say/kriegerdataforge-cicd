======================================== PROMPT GENERATOR — DOCUMENTATION PROMPT REQUEST ========================================

Prompt Name: Documentation Prompt Generator

Target AI Role: [X] 📝 TECHNICAL WRITER

Project/Application Name: Tiffany's Space (and KriegerDataForge Backend)

Brief Description of Project:
Create a documentation prompt that is specialized to document a specific aspect of the project
where this is located in.

For example:
- In Tiffany's Space repo or the kriegerdataforge backend repo, this prompt should be able to
  write clear documentation about the coding standards of the repo, such as:
    - how the code is structured
    - how the code is organized
    - how the code flows from page rendering code organization, feature code organization, and
      core common code organization
    - how there are comments and doc strings for every file from file level, to function level,
      to line level comments

This documentation creator prompt should also be able to document aspects of the repo for
another AI agent to get a better understanding of the repo to better:
- structure code
- design and implement features
- brainstorm ideas to better enhance the project
- and more

Scope: [X] 🎯 Narrow - Single specific task type (documentation)

Tech Stack:
  Frontend:  Next.js/React | TailwindCSS | TypeScript
  Backend:   FastAPI | Python | PostgreSQL | SQLAlchemy/SQLModel
  Infra:     GitHub | GitHub CI/CD | Docker | Vercel/GCP

Must Include:
  [X] Task spec with checkboxes    [X] Size framework (S/M/L/XL)   [X] Task type categorization
  [X] User personas/audience       [X] Task breakdown               [X] Clarification scenarios

Special Focus:
  [X] Documentation requirements

======================================== HOW TO USE ========================================

Submit the above request to an AI prompt engineer (e.g., Claude, GPT-4) along with the
full blank meta-prompt template (prompt-generator-blank.md). The AI will generate a
specialized documentation prompt for Tiffany's Space frontend or KriegerDataForge backend.

The generated prompt should be placed in: prompts/tiffanys_space/docs/ or prompts/kriegerdataforge/docs/
