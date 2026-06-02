======================================== PROMPT GENERATOR — CODE FIXER REQUEST ========================================

Prompt Name: Code Fixer

Target AI Role: [X] 👨‍💻 DEVELOPER

Project/Application Name: Fitness App

Brief Description of Project:
Given code reviews that provide action items at the top of each file, your job is to implement
the code reviewer's suggestions to make the code "better". You need to understand the context
of the code, such as:
- what it is doing
- what it is used for
- how it works
- what the action items mean in scope for the file and how it is being used by other features throughout the app
- are there any action items that might break the code if implemented
- is there anything else that can be added to the code review to make the code better based on the context
  of how and why the code is being used
- etc that will make the code "better" overall

Scope: [X] 🌐 Broad - Full role coverage

Tech Stack:
  Frontend:  Next.js | TailwindCSS | TypeScript/React | React state
  Backend:   FastAPI | Python/SQL | PostgreSQL | SQLAlchemy/SQLModel
  Infra:     GitHub | GitHub CI/CD | Docker | Vercel/GCP

Must Include:
  [X] Task spec with checkboxes    [X] Size framework (S/M/L/XL)   [X] Technical context
  [X] Architecture overview        [X] Coding standards             [X] Constraints
  [X] Behavioral guidelines        [X] Task breakdown               [X] Clarification scenarios

Special Focus:
  [X] Security   [X] Performance   [X] Accessibility  [X] Mobile/responsive
  [X] AI/ML      [X] Cost          [X] Testing        [X] Documentation
  [X] API design [X] Database      [X] UI/UX          [X] i18n

======================================== HOW TO USE ========================================

Submit the above request to an AI prompt engineer (e.g., Claude, GPT-4) along with the
full blank meta-prompt template (prompt-generator-blank.md). The AI will generate a
comprehensive code fixer prompt for the Fitness App frontend following the standard
KriegerDataForge prompt structure.

The generated prompt should enable an AI to:
  1. Read code review action items at the top of a file
  2. Understand the context and purpose of the code
  3. Evaluate each action item for safety and impact
  4. Implement improvements without breaking existing behavior
  5. Suggest additional improvements not in the review

Target output location: prompts/fitness_app/dev/ or prompts/general/dev/
