======================================== KRIEGERDATAFORGE FRONT END TEMPLATE SKELETON — ARCHITECT TEMPLATE ========================================

Subject or Topic: KriegerDataForge Ecosystem — Create a Reusable Next.js Front End Template Skeleton

You are an expert software architect specializing in Next.js, React, TypeScript, and TailwindCSS application scaffolding. Your mission is to create a production-ready front-end template skeleton that any developer can clone and immediately begin building a new application within the KriegerDataForge ecosystem.

The template is based on the proven architecture of the Fitness App Frontend — the first application built in this ecosystem. You will extract, generalize, and templatize its authentication system, project structure, coding standards, configuration, and documentation into a reusable skeleton.

======================================== 📚 REFERENCE APPLICATION ========================================

⚠️ IMPORTANT: The Fitness App Frontend (fitness-app-frontend/) is the reference implementation.
Before scaffolding the template, study these files and docs to understand the patterns being extracted:

────────────────────────────────────────
📂 Reference Documentation (fitness-app-frontend/docs/)
────────────────────────────────────────

MUST READ (architecture & standards to generalize):
  • ARCHITECTURE.md               — Layered architecture, dependency rules, auth model, rendering strategy
  • CODING_STANDARDS.md           — TypeScript strict mode, naming conventions, JSDoc standards, anti-patterns
  • CONVENTIONS_AND_BEST_PRACTICES.md — Import ordering, barrel exports, section headers, type patterns
  • COMPONENT_PATTERN_GUIDE.md    — Server/client component patterns, props interfaces, memoization

READ FOR CONTEXT (patterns to carry over):
  • API_AND_DATA_FLOW_GUIDE.md    — Server actions, API proxy, OpenAPI client, error handling
  • SETUP_AND_ONBOARDING.md       — Docker setup, env vars, local dev workflow
  • TESTING_GUIDE.md              — Jest config, test patterns, coverage expectations
  • DEBUGGING_AND_ERROR_PATHS.md  — Error boundaries, logging, the error-tracking service integration

────────────────────────────────────────
📂 Reference Source Code (fitness-app-frontend/src/)
────────────────────────────────────────

AUTHENTICATION (carry over as-is with generalization):
  • src/proxy.ts                  — Edge middleware for JWT verification
  • src/features/auth/            — Login action, LoginForm, LogoutButton, LoginSchema
  • src/app/(private)/layout.tsx  — Defense-in-depth auth guard layout
  • src/app/(public)/layout.tsx   — Public route group layout
  • src/core/constants/routes.ts  — Route definitions (private/public)
  • src/core/constants/storage-keys.ts — Auth cookie key constants

CORE INFRASTRUCTURE (carry over and generalize):
  • src/core/api/config.ts        — OpenAPI client configuration (server/client resolution)
  • src/core/utils/logger.ts      — Centralized development logger
  • src/core/utils/api-error-handler.ts — API error handling utilities
  • src/core/utils/retry.ts       — Retry logic for transient failures
  • src/core/components/          — Shared UI components (buttons, inputs, modals, skeletons)
  • src/core/hooks/               — Shared hooks (debounce, focus trap, escape key, etc.)
  • src/core/providers/           — ErrorContextProvider

CONFIGURATION (carry over and generalize):
  • next.config.ts                — Security headers, API proxy, the error-tracking service, Docker support
  • tsconfig.json                 — Strict TypeScript with path aliases
  • Dockerfile                    — Multi-stage Docker build (dev + production)
  • .env.example                  — Environment variable template
  • eslint.config.mjs             — ESLint flat config
  • jest.config.ts                — Jest testing configuration
  • docker-compose.yml            — Docker Compose dev environment (at repo root)

MAKEFILE REFERENCE (backend Makefile for style/conventions):
  • kriegerdataforge-backend/Makefile — Reference for Makefile style, colored output, help target

======================================== TASK SPECIFICATION ========================================

────────────────────────────────────────
📋 TASK OVERVIEW
────────────────────────────────────────

Task Name: Create Front End Template Skeleton

One-Sentence Summary:
Create a fully functional, generalized Next.js front-end template skeleton in templates/front-end-application-template/ that any developer can clone to bootstrap a new KriegerDataForge ecosystem application with authentication, project structure, coding standards, and documentation pre-configured.

────────────────────────────────────────
📏 TASK SIZE
────────────────────────────────────────

[X] 🔴 EXTRA LARGE - Cross-cutting, 1000+ lines, full day+

This task involves:
  - Extracting and generalizing ~30+ files from the fitness app
  - Creating example feature module files
  - Writing/adapting documentation
  - Setting up configuration files
  - Ensuring the template builds and runs out of the box

────────────────────────────────────────
🏗️ TASK TYPE
────────────────────────────────────────

[X] 🏛️ Architecture — Template/scaffold creation for ecosystem reuse

────────────────────────────────────────
🎯 SCOPE
────────────────────────────────────────

[X] 🏢 Enterprise — Organization-wide template for all future front-end applications

======================================== KRIEGERDATAFORGE ECOSYSTEM CONTEXT ========================================

────────────────────────────────────────
🌐 ECOSYSTEM OVERVIEW
────────────────────────────────────────

KriegerDataForge is a personal ecosystem of web applications that share a common backend authentication system. Every application in the ecosystem:

  1. Connects to the **same FastAPI backend** for authentication (JWT-based, OAuth2 token endpoint)
  2. Uses the **same tech stack**: Next.js, React, TypeScript, TailwindCSS
  3. Follows the **same architectural patterns**: feature-based isolation, server-first rendering, defense-in-depth auth
  4. Adheres to the **same coding standards**: strict TypeScript, discriminated unions, Zod schemas, comprehensive JSDoc
  5. Deploys via **Docker** (development) and **Vercel** (production)

The first application built on this ecosystem is the **Fitness App** — a nutrition tracking application. This template extracts the reusable foundation from that application.

────────────────────────────────────────
🔐 SHARED AUTHENTICATION SYSTEM
────────────────────────────────────────

All KriegerDataForge applications authenticate against a centralized FastAPI backend:

  • **Auth Endpoint:** POST /auth/token (OAuth2 password grant, returns JWT)
  • **Token Type:** JWT (HS256), stored as httpOnly cookie
  • **Token Verification:** jose library at Edge Runtime (proxy.ts middleware)
  • **Defense-in-Depth:** 3 layers of auth enforcement:
    1. Edge Middleware (proxy.ts) — JWT verification before any page loads
    2. Private Layout Guard — server-side cookie check as fallback
    3. Server Action Auth Check — per-action cookie verification

  • **Auth Flow:**
    1. User submits credentials → LoginForm component
    2. Server action calls backend /auth/token endpoint
    3. Backend returns JWT → server action sets httpOnly cookie
    4. Subsequent requests include cookie → proxy.ts verifies JWT
    5. Logout clears the cookie

────────────────────────────────────────
🎯 CORE PHILOSOPHY (10 Architectural Commandments)
────────────────────────────────────────

These principles govern ALL applications in the ecosystem:

  1. **Feature Isolation** — Features never import from each other. Shared code lives in core/.
  2. **Server-First** — Pages are React Server Components. Client interactivity only where needed.
  3. **Explicit Over Implicit** — Named exports, explicit return types, comprehensive JSDoc.
  4. **Discriminated Unions** — All error/status handling uses { ok: true; data } | { ok: false; error }.
  5. **Zod Everywhere** — Runtime + compile-time validation at every boundary.
  6. **Constants Over Magic** — All magic numbers/strings extracted to core/constants/.
  7. **Code Review Culture** — Every file has a Code Review Summary block.
  8. **Accessibility First** — ARIA, semantic HTML, keyboard nav, focus management.
  9. **Performance Conscious** — React.memo, useCallback, useMemo, useWatch where warranted.
  10. **Defense in Depth** — Auth at 3 layers: proxy, layout, server action.

======================================== TECHNOLOGY STACK ========================================

────────────────────────────────────────
📦 CORE STACK (Template Defaults)
────────────────────────────────────────

| Layer            | Technology                    | Version  | Purpose                                    |
|------------------|-------------------------------|----------|--------------------------------------------|
| **Framework**    | Next.js                       | 16+      | App Router, RSC, Edge middleware            |
| **UI Library**   | React                         | 19+      | Component model, hooks, server components   |
| **Language**     | TypeScript                    | 5.9+     | Strict mode, ES2020 target                  |
| **Styling**      | TailwindCSS                   | v4+      | Utility-first, CSS-first config             |
| **Forms**        | react-hook-form               | 7+       | Form state, field-level subscriptions       |
| **Validation**   | Zod                           | 4+       | Runtime + compile-time schemas              |
| **HTTP Client**  | Axios                         | 1.10+    | Via OpenAPI-generated client                |
| **Auth**         | jose                          | 6+       | JWT verification at Edge Runtime            |
| **Error Tracking** | the error-tracking service                      | 10+      | Client, server, and edge monitoring         |
| **Analytics**    | Vercel Analytics              | 1.6+     | Page-level analytics                        |
| **Build**        | Turbopack                     | (bundled)| Dev server default                          |
| **Container**    | Docker                        | Alpine   | Multi-stage dev + production builds         |
| **API Generation** | openapi-typescript-codegen  | 0.29+    | TypeScript client from backend OpenAPI spec |

────────────────────────────────────────
🔗 BACKEND INTEGRATION
────────────────────────────────────────

| Component      | Technology     | Purpose                               |
|----------------|----------------|---------------------------------------|
| Backend        | FastAPI        | REST API, authentication, data        |
| Database       | PostgreSQL     | Persistent data storage               |
| ORM            | SQLAlchemy     | Database access layer                 |
| Auth           | OAuth2 + JWT   | Password grant, JWT token issuance    |

────────────────────────────────────────
🚀 DEPLOYMENT
────────────────────────────────────────

| Environment | Platform       | Notes                                    |
|-------------|----------------|------------------------------------------|
| Development | Docker Compose | Hot reload, volume mounts, polling        |
| Production  | Vercel         | Standalone output, edge functions         |
| Repository  | GitHub         | CI/CD, PR workflow                        |

======================================== TEMPLATE PROJECT STRUCTURE ========================================

────────────────────────────────────────
📁 TARGET OUTPUT LOCATION
────────────────────────────────────────

templates/front-end-application-template/

────────────────────────────────────────
📁 COMPLETE TEMPLATE DIRECTORY STRUCTURE
────────────────────────────────────────

The template skeleton MUST produce the following structure. Files marked with
[EXAMPLE] are illustrative placeholders showing developers how to use the pattern.
Files marked with [TEMPLATE] are generalized from the fitness app. Files marked
with [AUTH] are the baked-in authentication system carried over directly.

```
templates/front-end-application-template/
│
├── .env.example                          # [TEMPLATE] Environment variable template
├── .env.development                      # [TEMPLATE] Local dev defaults (safe values only)
├── .gitignore                            # [TEMPLATE] Standard Next.js gitignore
├── .dockerignore                         # [TEMPLATE] Docker build exclusions
├── Dockerfile                            # [TEMPLATE] Multi-stage Docker build (dev + prod)
├── docker-compose.yml                    # [TEMPLATE] Standalone dev environment compose
├── eslint.config.mjs                     # [TEMPLATE] ESLint flat config
├── jest.config.ts                        # [TEMPLATE] Jest testing configuration
├── jest.setup.ts                         # [TEMPLATE] Jest setup file
├── babel.config.jest.js                  # [TEMPLATE] Babel config for Jest
├── Makefile                              # [TEMPLATE] Setup & dev commands (install, dev, build, test, lint, etc.)
├── next.config.ts                        # [TEMPLATE] Security headers, proxy, the error-tracking service, Docker
├── next-env.d.ts                         # [TEMPLATE] Next.js type declarations
├── package.json                          # [TEMPLATE] Scripts and metadata ONLY (no dependencies listed)
├── postcss.config.mjs                    # [TEMPLATE] PostCSS for Tailwind
├── tsconfig.json                         # [TEMPLATE] Strict TypeScript config
├── tsconfig.jest.json                    # [TEMPLATE] Jest-specific TypeScript config
├── README.md                             # [TEMPLATE] Quick start guide for new projects
│
├── .github/
│   ├── copilot-instructions.md           # [TEMPLATE] GitHub Copilot workspace instructions
│   └── PULL_REQUEST_TEMPLATE.md          # [TEMPLATE] PR template
│
├── public/                               # Static assets directory
│   └── (empty — developer adds their own assets)
│
├── docs/
│   ├── ARCHITECTURE.md                   # [TEMPLATE] Generalized architecture standards
│   ├── CODING_STANDARDS.md               # [TEMPLATE] Generalized coding standards
│   ├── CONVENTIONS_AND_BEST_PRACTICES.md # [TEMPLATE] Generalized conventions guide
│   ├── SETUP_AND_ONBOARDING.md           # [TEMPLATE] Setup guide for new projects
│   ├── TESTING_GUIDE.md                  # [TEMPLATE] Testing patterns and requirements
│   └── AI_AGENT_CONTEXT.md              # [TEMPLATE] AI agent quick-start guide
│
└── src/
    ├── instrumentation.ts                # [TEMPLATE] the error-tracking service server instrumentation
    ├── instrumentation-client.ts         # [TEMPLATE] the error-tracking service client instrumentation
    ├── proxy.ts                          # [AUTH] Edge middleware — JWT verification
    │
    ├── types/
    │   └── global.d.ts                   # [TEMPLATE] Global type declarations
    │
    ├── app/
    │   ├── layout.tsx                    # [TEMPLATE] Root layout (fonts, metadata, providers)
    │   ├── page.tsx                      # [TEMPLATE] Landing page (redirect to dashboard or login)
    │   ├── error.tsx                     # [TEMPLATE] Global error boundary
    │   ├── global-error.tsx              # [TEMPLATE] Last-resort error boundary
    │   ├── not-found.tsx                 # [TEMPLATE] Custom 404 page
    │   ├── globals.css                   # [TEMPLATE] CSS custom properties, Tailwind v4 import
    │   ├── favicon.ico                   # [TEMPLATE] Default favicon
    │   │
    │   ├── (private)/                    # [AUTH] Auth-protected route group
    │   │   ├── layout.tsx                # [AUTH] Defense-in-depth auth guard
    │   │   ├── error.tsx                 # [TEMPLATE] Error boundary for private routes
    │   │   │
    │   │   ├── dashboard/               # [EXAMPLE] Example private page
    │   │   │   └── page.tsx             # [EXAMPLE] Dashboard page (shows auth user info)
    │   │   │
    │   │   └── example-feature/         # [EXAMPLE] Example feature route
    │   │       └── page.tsx             # [EXAMPLE] Shows how pages delegate to feature components
    │   │
    │   ├── (public)/                     # [AUTH] No-auth route group
    │   │   ├── layout.tsx                # [AUTH] Transparent pass-through layout
    │   │   └── login/
    │   │       └── page.tsx              # [AUTH] Login page
    │   │
    │   └── api/
    │       └── [...path]/
    │           └── route.ts              # [AUTH] API proxy → backend (cookie forwarding)
    │
    ├── core/
    │   ├── api/
    │   │   ├── config.ts                 # [AUTH] OpenAPI client configuration
    │   │   └── generated/                # [TEMPLATE] (empty — generated via openapi codegen)
    │   │       └── .gitkeep
    │   │
    │   ├── components/
    │   │   ├── index.ts                  # [TEMPLATE] Barrel export for shared components
    │   │   ├── ClientInitializer.tsx      # [TEMPLATE] Client-side initialization component
    │   │   │
    │   │   ├── buttons/                  # [TEMPLATE] Shared button components
    │   │   │   └── LoadingButton.tsx     # [EXAMPLE] Example shared button with loading state
    │   │   │
    │   │   ├── inputs/                   # [TEMPLATE] Shared input components
    │   │   │   └── TextInput.tsx         # [EXAMPLE] Example shared text input
    │   │   │
    │   │   ├── modals/                   # [TEMPLATE] Shared modal components
    │   │   │   └── ConfirmModal.tsx      # [EXAMPLE] Example confirm/cancel modal
    │   │   │
    │   │   ├── skeletons/               # [TEMPLATE] Loading skeleton components
    │   │   │   └── CardSkeleton.tsx      # [EXAMPLE] Example skeleton loader
    │   │   │
    │   │   ├── templates/               # [TEMPLATE] Page layout templates
    │   │   │   └── PageTemplate.tsx      # [EXAMPLE] Standard page layout wrapper
    │   │   │
    │   │   └── ui/                       # [TEMPLATE] Base UI primitives
    │   │       └── LoadingSpinner.tsx    # [EXAMPLE] Spinner component
    │   │
    │   ├── config/
    │   │   └── env/                      # [TEMPLATE] Environment config validation
    │   │       └── index.ts              # [TEMPLATE] Env var validation with Zod
    │   │
    │   ├── constants/
    │   │   ├── routes.ts                 # [AUTH] Private/public route definitions
    │   │   ├── storage-keys.ts           # [AUTH] Cookie/storage key constants
    │   │   ├── button-styles.ts          # [EXAMPLE] Example style constants
    │   │   ├── modal-styles.ts           # [EXAMPLE] Example modal style constants
    │   │   └── timing.ts                # [EXAMPLE] Example timing constants (debounce, etc.)
    │   │
    │   ├── data/                         # [TEMPLATE] Static data files
    │   │   └── .gitkeep
    │   │
    │   ├── hooks/
    │   │   ├── index.ts                  # [TEMPLATE] Barrel export for shared hooks
    │   │   ├── useDebouncedValue.ts      # [EXAMPLE] Example debounce hook
    │   │   ├── useEscapeKey.ts           # [EXAMPLE] Example keyboard hook
    │   │   └── __tests__/               # [TEMPLATE] Hook test directory
    │   │       └── useDebouncedValue.test.ts  # [EXAMPLE] Example hook test
    │   │
    │   ├── providers/
    │   │   └── ErrorContextProvider.tsx  # [TEMPLATE] Global error context provider
    │   │
    │   ├── types/
    │   │   └── entities.ts               # [TEMPLATE] Shared entity types
    │   │
    │   └── utils/
    │       ├── api-error-handler.ts      # [AUTH] API error handling utility
    │       ├── api-helpers.ts            # [TEMPLATE] API helper functions
    │       ├── logger.ts                 # [TEMPLATE] Centralized development logger
    │       ├── retry.ts                  # [TEMPLATE] Retry logic for transient failures
    │       ├── server-action-helpers.ts  # [TEMPLATE] Server action utility functions
    │       ├── input-validation.ts       # [EXAMPLE] Example input validation utils
    │       ├── string-manipulation.ts    # [EXAMPLE] Example string utility
    │       └── __tests__/               # [TEMPLATE] Utility test directory
    │           └── string-manipulation.test.ts  # [EXAMPLE] Example utility test
    │
    └── features/
        ├── auth/                         # [AUTH] Complete authentication feature
        │   ├── index.ts                  # Barrel export
        │   ├── actions/
        │   │   └── loginAction.ts        # Server action: authenticate + set cookie
        │   ├── components/
        │   │   ├── LoginForm.tsx          # Login form component
        │   │   └── LogoutButton.tsx       # Logout button component
        │   └── schemas/
        │       └── LoginSchema.ts         # Zod schema for login form validation
        │
        └── example-feature/              # [EXAMPLE] Example feature module
            ├── index.ts                  # Barrel export pattern
            ├── actions/
            │   └── exampleAction.ts      # [EXAMPLE] Example server action
            ├── components/
            │   ├── ExampleView.tsx        # [EXAMPLE] Main feature view (server component)
            │   └── ExampleForm.tsx        # [EXAMPLE] Example form (client component)
            ├── hooks/
            │   └── useExampleForm.ts     # [EXAMPLE] Example feature hook
            ├── schemas/
            │   └── ExampleSchema.ts      # [EXAMPLE] Example Zod schema
            ├── types/
            │   └── index.ts              # [EXAMPLE] Feature-specific types
            └── utils/
                └── example-helpers.ts    # [EXAMPLE] Feature-specific utilities
```

======================================== CONSTRAINTS & REQUIREMENTS ========================================

────────────────────────────────────────
🔒 AUTHENTICATION REQUIREMENTS
────────────────────────────────────────

The authentication system MUST be fully functional out of the box:

  [X] proxy.ts edge middleware verifies JWT tokens using jose library
  [X] 3-layer defense-in-depth: proxy → private layout guard → server action check
  [X] Login flow: LoginForm → loginAction → backend /auth/token → httpOnly cookie
  [X] Logout flow: LogoutButton → clear cookie → redirect to login
  [X] Login schema validates with Zod before submission
  [X] API proxy route forwards cookies and auth headers to backend
  [X] OpenAPI client config handles server-side vs client-side base URL resolution
  [X] Private routes redirect to /login when unauthenticated
  [X] Public routes accessible without authentication
  [X] Environment variables for AUTH_SECRET_KEY, AUTH_ALGORITHM, API_BASE_URL

────────────────────────────────────────
📐 CODE QUALITY STANDARDS
────────────────────────────────────────

All template code MUST follow these standards (from fitness app CODING_STANDARDS.md):

  [X] TypeScript strict mode — no `any`, explicit return types on all functions
  [X] Named exports only (no `export default` except Next.js pages/layouts)
  [X] Discriminated unions for all error/status handling
  [X] Zod schemas as source of truth for all validation
  [X] Comprehensive JSDoc: @module, @param, @returns, @example on all public APIs
  [X] Section headers using // ============ SECTION ============ pattern
  [X] Import ordering: Framework → Third-party → @/core/ → Relative
  [X] Barrel exports with explicit named re-exports (no export *)
  [X] PascalCase for components/types, camelCase for functions/hooks, UPPER_SNAKE_CASE for constants
  [X] No magic numbers or strings — extract to constants with JSDoc
  [X] `as const` assertions on all constant arrays/objects
  [X] `readonly` on response/immutable types

────────────────────────────────────────
🧱 ARCHITECTURAL REQUIREMENTS
────────────────────────────────────────

  [X] Three-layer architecture: app/ (routing) → features/ (business logic) → core/ (shared)
  [X] Feature isolation: features never import from each other
  [X] Server-first rendering: pages are RSC, client components only where needed
  [X] Core layer has zero feature knowledge
  [X] Pages delegate to feature components (thin orchestration layer)
  [X] Error boundaries at global, route group, and feature levels

────────────────────────────────────────
📦 MAKEFILE & DEPENDENCY MANAGEMENT REQUIREMENTS
────────────────────────────────────────

  ⚠️ CRITICAL: The template MUST NOT ship with Next.js or any npm dependencies
  pre-installed or listed in package.json's dependencies/devDependencies sections.
  Instead, the Makefile handles ALL dependency installation and project setup.
  A developer clones the template and runs `make setup` to bootstrap everything.

  [X] Makefile is the single entry point for all project setup and dev commands
  [X] `make help` displays all available commands with descriptions
  [X] `make setup` performs FULL project bootstrap (see Makefile specification below)
  [X] `make dev` starts the development server (Next.js with Turbopack)
  [X] `make build` runs the production build
  [X] `make test` runs Jest tests
  [X] `make lint` runs ESLint
  [X] `make clean` removes node_modules, .next, and build artifacts
  [X] `make docker-dev` starts Docker Compose dev environment
  [X] `make docker-build` builds Docker production image
  [X] `make generate-client` runs OpenAPI client generation from backend spec
  [X] package.json contains ONLY scripts and metadata — NO dependencies or devDependencies
  [X] Makefile installs all dependencies via npm commands during `make setup`
  [X] Colored terminal output matching backend Makefile style

────────────────────────────────────────
🐳 DOCKER & DEPLOYMENT REQUIREMENTS
────────────────────────────────────────

  [X] Multi-stage Dockerfile: base → deps → builder → dev → runner
  [X] Docker Compose for standalone local development
  [X] Standalone output for Vercel production deployment
  [X] Environment variable template (.env.example) with documentation
  [X] WATCHPACK_POLLING support for Docker on Windows

────────────────────────────────────────
🧪 TESTING REQUIREMENTS
────────────────────────────────────────

  [X] Jest configured with jsdom environment
  [X] Babel config for Jest TypeScript support
  [X] At least one example unit test for a utility
  [X] At least one example unit test for a hook
  [X] Test file co-location pattern (__tests__/ directories)

────────────────────────────────────────
📚 DOCUMENTATION REQUIREMENTS
────────────────────────────────────────

  [X] README.md — Quick start guide: clone, configure, run, build
  [X] ARCHITECTURE.md — Generalized version (remove fitness-specific references)
  [X] CODING_STANDARDS.md — Generalized version (all conventions apply to any app)
  [X] CONVENTIONS_AND_BEST_PRACTICES.md — Generalized conventions guide
  [X] SETUP_AND_ONBOARDING.md — Docker, env vars, local dev, Vercel deployment
  [X] TESTING_GUIDE.md — Jest config, test patterns, how to add tests
  [X] AI_AGENT_CONTEXT.md — Quick-start for AI coding assistants working on the project

────────────────────────────────────────
🔐 SECURITY REQUIREMENTS
────────────────────────────────────────

  [X] Security headers in next.config.ts (X-Frame-Options, CSP, HSTS, etc.)
  [X] httpOnly, Secure, SameSite cookies for auth tokens
  [X] JWT algorithm hardcoded (not from env var) to prevent alg:none attacks
  [X] Error message sanitization — never expose raw backend errors to users
  [X] No secrets in client-side code
  [X] Input validation at all boundaries with Zod
  [X] CSRF protection via SameSite cookies
  [X] API proxy with timeout (AbortController) to prevent hung requests

────────────────────────────────────────
⚡ PERFORMANCE REQUIREMENTS
────────────────────────────────────────

  [X] Server-side rendering by default (minimize client JS)
  [X] Turbopack for development builds
  [X] Standalone output for production (minimal Docker image)
  [X] Image optimization with sharp
  [X] Font optimization with next/font

────────────────────────────────────────
♿ ACCESSIBILITY REQUIREMENTS
────────────────────────────────────────

  [X] Semantic HTML elements
  [X] Skip-to-content link in root layout
  [X] Proper ARIA labels on interactive elements
  [X] focus-visible styles for keyboard navigation
  [X] Color contrast compliant with WCAG 2.1 AA

======================================== EXAMPLE FILE SPECIFICATIONS ========================================

────────────────────────────────────────
📝 EXAMPLE FILES — PURPOSE & CONTENT GUIDELINES
────────────────────────────────────────

Example files serve as living documentation showing developers HOW to use the template patterns.
Each example should be minimal but complete — enough to demonstrate the pattern without being
overwhelming. Every example file MUST include:

  1. A module-level JSDoc block explaining what pattern it demonstrates
  2. A "HOW TO USE THIS EXAMPLE" section in comments explaining what to copy/modify
  3. Proper section headers (// ============ SECTION ============)
  4. Full type safety (no any, explicit return types)
  5. Working code that compiles and runs

────────────────────────────────────────
🏗️ EXAMPLE: Server Action (exampleAction.ts)
────────────────────────────────────────

Demonstrate:
  - "use server" directive
  - Auth check (cookie verification) as defense-in-depth
  - Discriminated union response type: { ok: true; data: T } | { ok: false; error: string }
  - Zod schema validation of input
  - OpenAPI client call to backend
  - Centralized logger and error handler usage
  - withRetry wrapper for transient failures
  - User-friendly error messages (never expose raw backend errors)

────────────────────────────────────────
🖥️ EXAMPLE: Feature View Component (ExampleView.tsx)
────────────────────────────────────────

Demonstrate:
  - React Server Component (no "use client")
  - Props interface with JSDoc
  - Named export (not default)
  - Explicit ReactElement return type
  - Delegation from page to feature component pattern
  - Section headers

────────────────────────────────────────
📝 EXAMPLE: Client Form Component (ExampleForm.tsx)
────────────────────────────────────────

Demonstrate:
  - "use client" directive
  - react-hook-form with Zod resolver
  - Form submission calling a server action
  - Loading/error/success state handling with discriminated union
  - Accessible form with labels, aria attributes
  - Mobile-responsive layout with Tailwind

────────────────────────────────────────
🪝 EXAMPLE: Feature Hook (useExampleForm.ts)
────────────────────────────────────────

Demonstrate:
  - "use client" directive
  - react-hook-form useForm hook setup
  - Zod schema resolver integration
  - Submission handler calling server action
  - State management with useState for loading/error
  - Return object with form methods and state

────────────────────────────────────────
📋 EXAMPLE: Zod Schema (ExampleSchema.ts)
────────────────────────────────────────

Demonstrate:
  - Zod schema definition with validation rules
  - Type inference: type ExampleFormData = z.infer<typeof ExampleSchema>
  - Error messages customization
  - Min/max/trim/regex validators
  - Export both schema and inferred type

────────────────────────────────────────
📄 EXAMPLE: Page Component (example-feature/page.tsx)
────────────────────────────────────────

Demonstrate:
  - Default export (Next.js convention)
  - Server-side data fetching (if applicable)
  - Data transformation before passing to feature component
  - Metadata export for SEO
  - Minimal orchestration — page is thin, feature component has logic

────────────────────────────────────────
📦 EXAMPLE: Barrel Export (example-feature/index.ts)
────────────────────────────────────────

Demonstrate:
  - Explicit named re-exports (not export *)
  - Section headers grouping exports by type (components, actions, schemas, types)
  - JSDoc module comment

======================================== MAKEFILE SPECIFICATION ========================================

────────────────────────────────────────
📋 MAKEFILE OVERVIEW
────────────────────────────────────────

The Makefile is the SINGLE ENTRY POINT for all project setup and developer workflow commands.
It follows the same style and conventions as the KriegerDataForge backend Makefile (colored output,
help target, .PHONY declarations). The template MUST NOT ship with any npm dependencies pre-installed
or listed in package.json — the Makefile `setup` target handles everything.

Why a Makefile instead of listing dependencies in package.json?
  - Developers clone a clean template with zero node_modules overhead
  - The Makefile `setup` target guarantees consistent, reproducible installs
  - Dependencies are always installed fresh at the latest compatible versions
  - Matches the backend Makefile pattern for ecosystem consistency
  - Single command (`make setup`) to go from clone → ready-to-develop

────────────────────────────────────────
📦 package.json — SCRIPTS & METADATA ONLY
────────────────────────────────────────

The package.json MUST contain:
  - "name": a generic placeholder (e.g., "kriegerdataforge-app")
  - "version": "0.1.0"
  - "private": true
  - "scripts": all standard scripts (dev, build, start, lint, test, generate-client)

The package.json MUST NOT contain:
  - "dependencies": {} — must be empty or omitted entirely
  - "devDependencies": {} — must be empty or omitted entirely

All dependency installation happens through the Makefile targets.

────────────────────────────────────────
🔧 MAKEFILE TARGETS — REQUIRED
────────────────────────────────────────

The Makefile MUST include the following targets at minimum. Follow the backend Makefile
pattern with colored output, help descriptions (## comments), and .PHONY declarations.

  ┌─────────────────────────┬────────────────────────────────────────────────────────────────────┐
  │ Target                  │ Description                                                        │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ help (default)          │ Display all available commands with descriptions                    │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ setup                   │ FULL project bootstrap:                                             │
  │                         │   1. Verify Node.js is installed (>= 22)                           │
  │                         │   2. Run `npm init -y` or ensure package.json exists               │
  │                         │   3. Install production dependencies via `npm install`:              │
  │                         │      next, react, react-dom, @hookform/resolvers,                   │
  │                         │      your observability client, axios, cookie, jose,                           │
  │                         │      react-hook-form, server-only, sharp, zod,                      │
  │                         │      @next/env, @vercel/analytics, @types/cookie                    │
  │                         │   4. Install dev dependencies via `npm install -D`:                  │
  │                         │      typescript, @types/node, @types/react, @types/react-dom,       │
  │                         │      tailwindcss, @tailwindcss/postcss, eslint, eslint-config-next, │
  │                         │      jest, jest-environment-jsdom, @testing-library/jest-dom,        │
  │                         │      @testing-library/react, babel-jest, @babel/preset-env,          │
  │                         │      @babel/preset-react, @babel/preset-typescript, ts-node,         │
  │                         │      openapi-typescript-codegen,                                     │
  │                         │      @types/testing-library__jest-dom                                │
  │                         │   5. Create .env.development from .env.example if not exists        │
  │                         │   6. Print success message with next steps                          │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ install                 │ Install all dependencies (same as setup steps 3-4, for re-installs)│
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ dev                     │ Start Next.js dev server with Turbopack (`next dev --turbopack`)    │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ build                   │ Run production build (`next build`)                                 │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ start                   │ Start production server (`next start`)                              │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ lint                    │ Run ESLint (`next lint`)                                            │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ test                    │ Run Jest tests (`jest`)                                             │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ test-watch              │ Run Jest in watch mode (`jest --watch`)                             │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ typecheck               │ Run TypeScript type checking only (`npx tsc --noEmit`)              │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ clean                   │ Remove node_modules/, .next/, and build artifacts                   │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ clean-install           │ Clean then install (fresh dependency install)                       │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ generate-client         │ Run OpenAPI client generation from backend spec                     │
  │                         │ (`openapi --input ../kriegerdataforge-backend/openapi.json           │
  │                         │   --output ./src/core/api/generated --client axios`)                │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ docker-dev              │ Start Docker Compose dev environment (`docker compose up`)          │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ docker-build            │ Build Docker production image                                       │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ docker-down             │ Stop and remove Docker Compose containers                           │
  ├─────────────────────────┼────────────────────────────────────────────────────────────────────┤
  │ check-all               │ Run lint + typecheck + test in sequence (CI-style validation)       │
  └─────────────────────────┴────────────────────────────────────────────────────────────────────┘

────────────────────────────────────────
🎨 MAKEFILE STYLE REQUIREMENTS
────────────────────────────────────────

Follow the backend Makefile conventions:

  - Color variables: BLUE, GREEN, YELLOW, RED, NC (No Color) using ANSI escape codes
  - `.PHONY` declarations for all targets
  - `.DEFAULT_GOAL := help`
  - `## Description` comments after each target for auto-generated help text
  - `@printf` for colored output messages
  - Section headers using # ======================================== SECTION
  - Organized into logical groups:
    1. Setup & Installation
    2. Development
    3. Build & Production
    4. Testing & Quality
    5. Docker Commands
    6. Utilities

======================================== GENERALIZATION GUIDELINES ========================================

────────────────────────────────────────
🔄 WHAT TO GENERALIZE
────────────────────────────────────────

When adapting fitness app code to the template:

  1. **App Name:** Replace "Fitness App" with placeholder "{{APP_NAME}}" in comments/docs.
     In actual code, use NEXT_PUBLIC_APP_NAME env var or a generic name like "KriegerDataForge App".

  2. **Feature Names:** Remove fitness-specific features (add-data, tracker, database).
     Replace with the example-feature module and dashboard example.

  3. **API Endpoints:** Remove fitness-specific endpoints. Keep only /auth/token in examples.
     Show placeholder patterns for feature-specific endpoints.

  4. **Constants:** Remove fitness-specific constants (food categories, meal types, nutrition labels).
     Keep auth-related constants. Add generic example constants.

  5. **Types:** Remove fitness-specific types (Food, Meal, NutritionFacts).
     Keep auth types. Add generic example entity types.

  6. **Documentation:** Rewrite docs to be app-agnostic. Keep architectural principles,
     coding standards, and conventions. Remove feature-specific walkthroughs.

  7. **Metadata:** Use generic metadata (title, description) with TODO markers.

  8. **Backend URL:** Use configurable env vars. Default to http://backend:8000 for Docker.

  9. **the error-tracking service DSN:** Keep the error-tracking service integration but with empty/placeholder DSN.

  10. **Vercel Analytics:** Keep the integration but make it optional (feature-flagged).

────────────────────────────────────────
🚫 WHAT NOT TO CHANGE
────────────────────────────────────────

Keep these exactly as they are in the fitness app:

  1. **Auth system** — proxy.ts, loginAction, LoginForm, LogoutButton, LoginSchema
     (only generalize comments/JSDoc, not logic)
  2. **API proxy route** — app/api/[...path]/route.ts
  3. **OpenAPI client config** — core/api/config.ts
  4. **Security headers** — next.config.ts headers section
  5. **Docker multi-stage build** — Dockerfile stages
  6. **TypeScript config** — tsconfig.json strict settings
  7. **ESLint config** — eslint.config.mjs
  8. **Jest config** — jest.config.ts

======================================== BEHAVIORAL GUIDELINES ========================================

When creating this template, follow these guidelines:

  1.  **Study Before Building** — Read the fitness app's ARCHITECTURE.md and CODING_STANDARDS.md
      thoroughly before writing any template code. The template must embody these standards.

  2.  **Functional Out of the Box** — A developer should be able to clone the template, run
      `make setup && make dev`, and see a working login page and dashboard.
      (Docker: `make docker-dev` should also work)

  3.  **Self-Documenting** — Every file should have enough JSDoc and comments that a developer
      can understand its purpose without reading external docs.

  4.  **Example-Driven** — The example feature module is the most important teaching tool.
      Make it complete, realistic, and well-documented.

  5.  **No Dead Code** — Every file in the template should have a purpose. Don't include
      fitness-specific logic that would need to be deleted.

  6.  **Consistent Patterns** — Every file must follow the same coding standards (section
      headers, import ordering, JSDoc, naming). No exceptions for "it's just a template."

  7.  **Security by Default** — The auth system, security headers, and cookie settings should
      be production-ready without any changes needed.

  8.  **Progressive Disclosure** — README.md should get someone running in 5 minutes.
      Detailed docs are in the docs/ directory for deeper understanding.

  9.  **TODO Markers** — Use // TODO: [CUSTOMIZE] markers for things developers must change
      (e.g., metadata, app name, the error-tracking service DSN, backend URL).

  10. **Prove It Compiles** — After generating all files, run `make setup` to install deps,
      then verify that `make lint` and `make build` pass. Fix any type errors before
      considering the task done.

  11. **Test the Auth Flow** — The login flow should work when pointed at a running
      KriegerDataForge backend instance.

  12. **Document Customization** — The README should have a clear "Customizing for Your App"
      section explaining what to rename, replace, and configure.

======================================== TASK BREAKDOWN APPROACH ========================================

Approach this task in the following phases:

────────────────────────────────────────
📋 PHASE 1 — SCAFFOLDING (Project Setup)
────────────────────────────────────────

  1. Create the templates/front-end-application-template/ directory
  2. Set up package.json with scripts and metadata ONLY (no dependencies/devDependencies)
  3. Set up Makefile with all setup, dev, build, test, lint, clean, and Docker commands
  4. Set up configuration files (tsconfig, eslint, jest, next.config, postcss, etc.)
  5. Set up Dockerfile and docker-compose.yml
  6. Set up .env.example and .env.development
  7. Set up .gitignore and .dockerignore

────────────────────────────────────────
📋 PHASE 2 — AUTHENTICATION SYSTEM
────────────────────────────────────────

  1. Copy and generalize proxy.ts (edge middleware)
  2. Copy and generalize features/auth/ (loginAction, LoginForm, LogoutButton, LoginSchema)
  3. Set up app/(private)/layout.tsx with auth guard
  4. Set up app/(public)/layout.tsx
  5. Set up app/(public)/login/page.tsx
  6. Set up app/api/[...path]/route.ts (API proxy)
  7. Set up core/api/config.ts (OpenAPI client config)
  8. Set up core/constants/routes.ts and storage-keys.ts

────────────────────────────────────────
📋 PHASE 3 — CORE INFRASTRUCTURE
────────────────────────────────────────

  1. Set up core/utils/ (logger, api-error-handler, retry, server-action-helpers, etc.)
  2. Set up core/hooks/ with example hooks
  3. Set up core/components/ with example shared components
  4. Set up core/providers/ErrorContextProvider.tsx
  5. Set up core/types/entities.ts
  6. Set up core/config/env/ validation

────────────────────────────────────────
📋 PHASE 4 — APP SHELL
────────────────────────────────────────

  1. Set up app/layout.tsx (root layout with fonts, metadata, providers)
  2. Set up app/page.tsx (landing/redirect)
  3. Set up app/globals.css
  4. Set up app/error.tsx, app/global-error.tsx, app/not-found.tsx
  5. Set up app/(private)/dashboard/page.tsx (example private page)
  6. Set up app/(private)/example-feature/page.tsx

────────────────────────────────────────
📋 PHASE 5 — EXAMPLE FEATURE MODULE
────────────────────────────────────────

  1. Create features/example-feature/ with full standard structure
  2. Write exampleAction.ts showing server action patterns
  3. Write ExampleView.tsx showing RSC patterns
  4. Write ExampleForm.tsx showing client component + form patterns
  5. Write useExampleForm.ts showing hook composition patterns
  6. Write ExampleSchema.ts showing Zod validation patterns
  7. Write barrel export index.ts

────────────────────────────────────────
📋 PHASE 6 — DOCUMENTATION
────────────────────────────────────────

  1. Write README.md (quick start, customization guide)
  2. Generalize ARCHITECTURE.md from fitness app
  3. Generalize CODING_STANDARDS.md from fitness app
  4. Generalize CONVENTIONS_AND_BEST_PRACTICES.md from fitness app
  5. Write SETUP_AND_ONBOARDING.md
  6. Write TESTING_GUIDE.md
  7. Write AI_AGENT_CONTEXT.md
  8. Set up .github/copilot-instructions.md
  9. Set up .github/PULL_REQUEST_TEMPLATE.md

────────────────────────────────────────
📋 PHASE 7 — VALIDATION
────────────────────────────────────────

  1. Run `make setup` to install all dependencies from the Makefile
  2. Verify TypeScript compiles with no errors (`make typecheck`)
  3. Verify ESLint passes (`make lint`)
  4. Verify Jest tests pass (`make test`)
  5. Verify production build succeeds (`make build`)
  6. Verify Docker build succeeds (`make docker-build`)
  7. Verify the app starts with `make dev` and login page renders
  8. Verify `make help` displays all commands correctly
  9. Review all files for consistency with coding standards
  10. Ensure no fitness-specific references remain in template code
  11. Verify package.json has NO dependencies/devDependencies listed

======================================== COMMON CLARIFICATION SCENARIOS ========================================

────────────────────────────────────────
❓ ALWAYS ASK ABOUT
────────────────────────────────────────

  • Whether to include any additional shared components beyond the examples listed
  • Whether the example feature should demonstrate any specific patterns not mentioned
  • Whether the docker-compose.yml should include database and backend services or just the frontend
  • Whether there are additional env vars needed beyond auth and API configuration

────────────────────────────────────────
✅ PROCEED WITHOUT ASKING
────────────────────────────────────────

  • Use the exact same auth flow as the fitness app (it's the ecosystem standard)
  • Use the exact same coding standards (they're non-negotiable)
  • Use the exact same dependency versions as the fitness app (proven stable)
  • Use the three-layer architecture (it's the ecosystem standard)
  • Include the error-tracking service integration (it's standard for all apps)
  • Include Vercel Analytics (it's standard for deployment target)

────────────────────────────────────────
💡 PROACTIVE SUGGESTIONS
────────────────────────────────────────

If you notice opportunities to improve the template beyond what's specified:
  • Suggest them with a brief rationale
  • Mark them clearly as [SUGGESTION] in your response
  • Do NOT implement suggestions without approval
  • Focus suggestions on developer experience and onboarding speed

======================================== SUCCESS CRITERIA & DEFINITION OF DONE ========================================

────────────────────────────────────────
✅ DEFINITION OF DONE CHECKLIST
────────────────────────────────────────

The template is complete when ALL of the following are true:

  [ ] All files from the directory structure above exist and contain appropriate code
  [ ] Makefile exists with all required targets and colored help output
  [ ] package.json contains scripts and metadata ONLY (NO dependencies or devDependencies)
  [ ] `make setup` installs all dependencies successfully
  [ ] `make help` displays all available commands with descriptions
  [ ] TypeScript compiles with zero errors in strict mode (`make typecheck`)
  [ ] ESLint passes with zero warnings (`make lint`)
  [ ] Jest tests pass — example utility test + example hook test (`make test`)
  [ ] Production build succeeds (`make build`)
  [ ] Docker build completes successfully — both dev and prod targets (`make docker-build`)
  [ ] `make dev` starts the app and renders the login page
  [ ] Login form submits to backend /auth/token endpoint
  [ ] Successful login redirects to dashboard
  [ ] Unauthenticated access to private routes redirects to /login
  [ ] Logout clears the cookie and redirects to /login
  [ ] Example feature page renders in private route group
  [ ] All example files have comprehensive JSDoc and section headers
  [ ] All documentation files are generalized (no fitness-specific references)
  [ ] README.md has clear quick-start referencing `make setup` and `make dev`
  [ ] No TODO items remain that would prevent the template from working
  [ ] All coding standards from CODING_STANDARDS.md are followed
  [ ] Security headers are configured in next.config.ts
  [ ] .env.example documents all required environment variables

────────────────────────────────────────
📊 SUCCESS METRICS
────────────────────────────────────────

  • **Time to First Page:** A developer can go from clone → `make setup` → `make dev` → running app in < 5 minutes
  • **Zero Config Auth:** Authentication works out of the box when backend is available
  • **Single Command Setup:** `make setup` handles everything — no manual npm install needed
  • **Pattern Clarity:** Example files make it obvious how to add new features
  • **Doc Completeness:** All architectural decisions are documented
  • **Clean Slate:** No fitness-specific code remains; template is truly generic
  • **Makefile Parity:** Frontend Makefile follows the same style as the backend Makefile

======================================== ERROR RECOVERY & ROLLBACK STRATEGIES ========================================

────────────────────────────────────────
⚠️ COMMON FAILURE POINTS
────────────────────────────────────────

  1. **TypeScript Errors:** If generalization introduces type errors, check that all
     fitness-specific types have been replaced with generic equivalents.

  2. **Missing Imports:** When extracting files, ensure all @/core/ imports resolve
     to files that exist in the template.

  3. **Auth Flow Broken:** If login fails, verify: .env vars match backend config,
     API proxy route is present, cookie settings are correct.

  4. **Docker Build Fails:** Check that the Makefile `setup` target installs all
     required dependencies and the Dockerfile COPY commands reference correct paths.

  5. **ESLint Errors:** The generated/ directory must be in eslint ignores.
     Client components need "use client" directive.

────────────────────────────────────────
🔄 ROLLBACK PROCEDURE
────────────────────────────────────────

If the template is broken beyond repair:
  1. Delete templates/front-end-application-template/
  2. Re-read the fitness app source code
  3. Start from Phase 1 with a fresh scaffold
  4. The fitness app code is the source of truth — it always works

======================================== EXAMPLE USAGE ========================================

────────────────────────────────────────
📝 FULL EXAMPLE — Using This Prompt
────────────────────────────────────────

```
[Paste this entire prompt into your AI coding assistant]

I'm ready to start. Please begin with Phase 1 — create the project scaffolding
in templates/front-end-application-template/ with all configuration files.
Focus on getting the Makefile, package.json (scripts/metadata only, no deps),
tsconfig.json, next.config.ts, Dockerfile, and docker-compose.yml set up first.
```

────────────────────────────────────────
⚡ QUICK START — Phase-by-Phase
────────────────────────────────────────

```
Phase 1: "Create the project scaffolding with Makefile, package.json (no deps), and all config files."
Phase 2: "Set up the authentication system (proxy, login, auth feature)."
Phase 3: "Set up the core infrastructure (utils, hooks, components, providers)."
Phase 4: "Set up the app shell (layouts, pages, error boundaries)."
Phase 5: "Create the example feature module with all example files."
Phase 6: "Write the documentation (README, architecture, coding standards)."
Phase 7: "Validate everything compiles, lints, and tests pass."
```

────────────────────────────────────────
🔧 CUSTOMIZATION — After Template is Created
────────────────────────────────────────

A developer using this template would:

  1. Copy templates/front-end-application-template/ to a new directory
  2. Rename the project in package.json (name field)
  3. Update .env.development with their backend URL
  4. Update AUTH_SECRET_KEY to match their backend
  5. Run `make setup` — this installs all dependencies and bootstraps the project
  6. Run `make dev` to start the development server
  7. Start building their features in src/features/
  8. Follow the patterns shown in features/example-feature/
  9. Remove example-feature/ when they're comfortable with the patterns
  10. Run `make help` to see all available commands

======================================== QUICK START TEMPLATE ========================================

For quick task submission when working on the template:

```
======================================== TEMPLATE TASK ========================================

Phase: [1-7]
Task: [Brief description]
Files to create/modify: [List files]
Reference files from fitness app: [List source files to adapt]

Notes:
[Any specific instructions or constraints]
```
