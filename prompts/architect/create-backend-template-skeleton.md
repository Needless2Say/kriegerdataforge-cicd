======================================== KRIEGERDATAFORGE BACK END TEMPLATE SKELETON — ARCHITECT TEMPLATE ========================================

Subject or Topic: KriegerDataForge Ecosystem — Create a Reusable FastAPI Back End Template Skeleton

You are an expert software architect specializing in FastAPI, Python, SQLAlchemy, SQLModel, and PostgreSQL application scaffolding. Your mission is to create a production-ready back-end template skeleton that any developer can copy and immediately begin building a new application module within the KriegerDataForge ecosystem.

The template is based on the proven architecture of the Fitness App backend (api/fitness_app/) — the first application module built in this ecosystem. You will extract, generalize, and templatize its service layer, routing, models, schemas, validation, exception handling, and documentation patterns into a reusable skeleton.

======================================== 📚 REFERENCE APPLICATION ========================================

⚠️ IMPORTANT: The Fitness App backend (kriegerdataforge-backend/api/fitness_app/) is the reference implementation.
Before scaffolding the template, study these files and docs to understand the patterns being extracted:

────────────────────────────────────────
📂 Reference Source Code (api/fitness_app/)
────────────────────────────────────────

MUST READ (core module structure — every file is a pattern to templatize):
  • api/fitness_app/__init__.py       — Empty init; module discovery via router inclusion in main.py
  • api/fitness_app/constants.py      — Router metadata, endpoint paths, OpenAPI response dicts
  • api/fitness_app/dependencies.py   — FastAPI Depends() functions for DI (profile get-or-create)
  • api/fitness_app/enums.py          — (str, Enum) classes for all domain enums (JSON-serializable)
  • api/fitness_app/exceptions.py     — Typed exception hierarchy inheriting AppException
  • api/fitness_app/models.py         — SQLModel ORM models with sa_column for advanced features
  • api/fitness_app/router.py         — APIRouter with endpoints, response models, error handling
  • api/fitness_app/schemas.py        — Pydantic v2 schemas for request/response validation
  • api/fitness_app/service.py        — Service class inheriting BaseDatabaseService for all CRUD
  • api/fitness_app/utils.py          — Pure stateless utility functions (computation, access checks)
  • api/fitness_app/validation.py     — Final[type] validation constants (MIN/MAX lengths, ranges)
  • api/fitness_app/validators.py     — Shared field-validator helpers for Pydantic schemas

────────────────────────────────────────
📂 Reference Shared Infrastructure (api/core/, api/database/)
────────────────────────────────────────

READ FOR CONTEXT (shared functionality the template depends on):
  • api/core/exceptions.py            — AppException base class, to_http_exception() helper
  • api/core/responses.py             — COMMON_200_OK, COMMON_400_BAD_REQUEST, etc. (shared OpenAPI response dicts)
  • api/core/schemas.py               — MessageResponse and other shared Pydantic schemas
  • api/core/validators.py            — validate_optional_url() and other cross-module validators
  • api/core/middleware.py             — SecurityHeadersMiddleware
  • api/core/email.py                 — EmailService (if module needs email)
  • api/database/base_service.py      — BaseDatabaseService (session lifecycle, _get_session, _session_scope)
  • api/database/config.py            — get_database_settings(), engine factory
  • api/database/dependencies.py      — db_dependency (Annotated[Session, Depends(get_session)])
  • api/database/mixins.py            — Shared model mixins (timestamp patterns documented)

────────────────────────────────────────
📂 Reference Authentication (api/auth/)
────────────────────────────────────────

READ FOR INTEGRATION (auth dependency used by all modules):
  • api/auth/dependencies.py          — get_current_user dependency (returns KDFUser)
  • api/auth/models.py                — KDFUser model (referenced by all module models via ForeignKey)
  • api/auth/enums.py                 — UserGlobalPermissionRole (admin checks in utils.py)
  • api/auth/constants.py             — CORS constants used in main.py

────────────────────────────────────────
📂 Reference Entry Point (api/main.py)
────────────────────────────────────────

  • api/main.py                       — Shows how routers are included: app.include_router(fitness_app_router)

────────────────────────────────────────
📂 Reference Tests
────────────────────────────────────────

  • unit_tests/fitness_app/           — Unit test structure for service, router, schemas, enums, exceptions
  • integration_tests/                — Integration test patterns

======================================== TASK SPECIFICATION ========================================

────────────────────────────────────────
📋 TASK OVERVIEW
────────────────────────────────────────

Task Name: Create Back End Template Skeleton

One-Sentence Summary:
Create a fully structured, generalized FastAPI backend module template skeleton in templates/back-end-application-template/ that any developer can copy into api/ and immediately begin building a new application module with routes, models, schemas, service layer, enums, exceptions, validation, and tests — all following the same patterns as the fitness_app module.

────────────────────────────────────────
📏 TASK SIZE
────────────────────────────────────────

[X] 🔴 EXTRA LARGE - Cross-cutting, 1000+ lines, full day+

This task involves:
  - Extracting and generalizing ~12 module files from the fitness_app directory
  - Creating example CRUD feature workflow documentation within the template
  - Writing example models, schemas, enums, validation constants, and service methods
  - Providing a step-by-step guide for the route creation workflow
  - Setting up example unit test files
  - Ensuring the template is self-documenting and ready to use

────────────────────────────────────────
🏗️ TASK TYPE
────────────────────────────────────────

[X] 🏛️ Architecture — Template/scaffold creation for ecosystem reuse

────────────────────────────────────────
🎯 SCOPE
────────────────────────────────────────

[X] 🏢 Enterprise — Organization-wide template for all future back-end application modules

======================================== KRIEGERDATAFORGE ECOSYSTEM CONTEXT ========================================

────────────────────────────────────────
🌐 ECOSYSTEM OVERVIEW
────────────────────────────────────────

KriegerDataForge is a personal ecosystem of web applications that share a common backend. Every application module in the ecosystem:

  1. Lives inside the **same FastAPI backend** repository (kriegerdataforge-backend/) as a sub-package under api/
  2. Uses the **same tech stack**: FastAPI, Python 3.12+, SQLModel, SQLAlchemy, PostgreSQL, Pydantic v2
  3. Follows the **same architectural patterns**: service layer, typed exceptions, validation constants, enum-driven schemas
  4. Adheres to the **same coding standards**: modern Python typing (X | None, built-in list/dict), Final constants, lazy % logging, comprehensive docstrings
  5. Shares **common infrastructure** via api/core/ (exceptions, responses, schemas, validators, email) and api/database/ (base service, dependencies, config)
  6. Authenticates users via the **shared auth module** (api/auth/) using JWT tokens
  7. Is registered in **api/main.py** via app.include_router()
  8. Deploys via **Docker** (development) and **Vercel** (production)

The first module built on this ecosystem is the **Fitness App** (api/fitness_app/) — a nutrition tracking module. This template extracts the reusable architectural patterns from that module.

────────────────────────────────────────
🔐 SHARED AUTHENTICATION SYSTEM
────────────────────────────────────────

All modules authenticate using the shared auth dependency:

  • **Auth Dependency:** get_current_user from api.auth.dependencies (returns KDFUser model)
  • **User Model:** KDFUser from api.auth.models (all module models ForeignKey to KDFUser.id)
  • **Permission Check:** UserGlobalPermissionRole from api.auth.enums (admin role checks)
  • **Pattern:** Endpoints that require auth use Depends(get_current_user) or a module-specific
    dependency that wraps it (e.g., get_or_create_fitness_profile wraps get_current_user)

────────────────────────────────────────
🎯 CORE PHILOSOPHY (10 Architectural Commandments)
────────────────────────────────────────

These principles govern ALL modules in the ecosystem:

  1.  **Module Isolation** — Each api/ sub-package is self-contained. Cross-module imports go through api/core/ only.
  2.  **Service Layer** — All business logic and database operations live in a service class inheriting BaseDatabaseService.
  3.  **Typed Exceptions** — Every error is a domain-specific exception class with HTTP status, error code, and suggestions.
  4.  **Validation Constants** — All MIN/MAX lengths, ranges, and allowed values are Final constants in validation.py.
  5.  **Enum-Driven** — All categorical data uses (str, Enum) classes for JSON serialization and type safety.
  6.  **Schema Separation** — Pydantic schemas (schemas.py) are separate from SQLModel models (models.py).
  7.  **Import Hierarchy** — enums.py → validation.py → validators.py → schemas.py → models.py → constants.py (no cycles).
  8.  **Explicit Exports** — Every module has __all__ with explicitly listed public names.
  9.  **Lazy Logging** — All logger calls use lazy % formatting, never f-strings.
  10. **Modern Python** — X | None (not Optional[X]), built-in list/dict (not List/Dict), Final[type] for all constants.

======================================== TECHNOLOGY STACK ========================================

────────────────────────────────────────
📦 CORE STACK (Template Defaults)
────────────────────────────────────────

| Layer              | Technology                   | Version   | Purpose                                      |
|--------------------|------------------------------|-----------|----------------------------------------------|
| **Framework**      | FastAPI                      | 0.115+    | API routing, dependency injection, OpenAPI    |
| **Language**       | Python                       | 3.12+     | Modern typing syntax, performance             |
| **ORM**            | SQLModel                     | 0.0.22+   | Model definitions combining SQLAlchemy+Pydantic|
| **SQL Toolkit**    | SQLAlchemy                   | 2.0+      | Advanced queries, relationships, indexes      |
| **Validation**     | Pydantic                     | 2.0+      | Request/response schemas, field validators    |
| **Database**       | PostgreSQL                   | 16+       | Persistent data storage, JSONB support        |
| **Migrations**     | Alembic                      | 1.14+     | Database schema migrations                    |
| **Testing**        | pytest                       | 8.0+      | Unit and integration testing                  |
| **HTTP Server**    | Uvicorn                      | 0.34+     | ASGI server for FastAPI                       |
| **Container**      | Docker                       | Alpine    | Development and production builds             |

────────────────────────────────────────
🔗 SHARED INFRASTRUCTURE DEPENDENCIES
────────────────────────────────────────

| Component              | Location                         | Purpose                                   |
|------------------------|----------------------------------|-------------------------------------------|
| Base Exception         | api/core/exceptions.py           | AppException base class, to_http_exception|
| Common Responses       | api/core/responses.py            | Shared OpenAPI response dicts             |
| Shared Schemas         | api/core/schemas.py              | MessageResponse, etc.                     |
| Shared Validators      | api/core/validators.py           | validate_optional_url, validate_country   |
| Base Database Service  | api/database/base_service.py     | Session lifecycle, _get_session, _session_scope|
| DB Dependencies        | api/database/dependencies.py     | db_dependency (Session injection)         |
| DB Config              | api/database/config.py           | get_database_settings, engine factory     |
| Auth Dependencies      | api/auth/dependencies.py         | get_current_user (JWT auth)               |
| User Model             | api/auth/models.py               | KDFUser (ForeignKey target)               |
| Auth Enums             | api/auth/enums.py                | UserGlobalPermissionRole                  |

======================================== TEMPLATE PROJECT STRUCTURE ========================================

────────────────────────────────────────
📁 TARGET OUTPUT LOCATION
────────────────────────────────────────

templates/back-end-application-template/

────────────────────────────────────────
📁 COMPLETE TEMPLATE DIRECTORY STRUCTURE
────────────────────────────────────────

The template skeleton MUST produce the following structure. Files marked with
[EXAMPLE] are illustrative placeholders showing developers how to use the pattern.
Files marked with [TEMPLATE] are generalized from the fitness app. Files marked
[GUIDE] are instructional markdown documents. Files marked [WORKFLOW] document
step-by-step processes.

```
templates/back-end-application-template/
│
├── README.md                                     # [GUIDE] Quick start, copy instructions, customization guide
│
├── docs/
│   ├── ARCHITECTURE.md                           # [GUIDE] Module architecture patterns, import hierarchy, design decisions
│   ├── CODING_STANDARDS.md                       # [GUIDE] Python/FastAPI coding standards followed by all modules
│   ├── ROUTE_CREATION_WORKFLOW.md                # [WORKFLOW] Step-by-step guide: how to add a new route end-to-end
│   ├── FEATURE_CREATION_WORKFLOW.md              # [WORKFLOW] Step-by-step guide: how to add a new entity/feature
│   └── TESTING_GUIDE.md                          # [GUIDE] Unit test patterns, fixtures, mocking, test organization
│
├── api/
│   └── {{module_name}}/                          # The module directory (developer renames this)
│       ├── __init__.py                           # [TEMPLATE] Empty — module discovery via router in main.py
│       ├── constants.py                          # [TEMPLATE] Router tags/prefix, endpoint paths, OpenAPI response dicts
│       ├── dependencies.py                       # [TEMPLATE] FastAPI Depends() functions (auth wrappers, profile get-or-create)
│       ├── enums.py                              # [TEMPLATE] (str, Enum) classes for domain categories/statuses
│       ├── exceptions.py                         # [TEMPLATE] Typed exception hierarchy (ModuleException → entity-specific)
│       ├── models.py                             # [TEMPLATE] SQLModel ORM models with relationships and indexes
│       ├── router.py                             # [TEMPLATE] APIRouter with CRUD endpoints and error handling
│       ├── schemas.py                            # [TEMPLATE] Pydantic v2 schemas (Create, Update, Response per entity)
│       ├── service.py                            # [TEMPLATE] Service class (BaseDatabaseService) with CRUD methods
│       ├── utils.py                              # [TEMPLATE] Pure stateless utility functions
│       ├── validation.py                         # [TEMPLATE] Final[type] validation constants (MIN/MAX, ranges, allowed values)
│       └── validators.py                         # [TEMPLATE] Shared field-validator helpers for Pydantic schemas
│
├── unit_tests/
│   └── {{module_name}}/                          # Unit test directory (mirrors api/{{module_name}}/)
│       ├── __init__.py                           # [TEMPLATE] Empty init for test discovery
│       ├── conftest.py                           # [TEMPLATE] Shared fixtures (mock session, mock user, service instance)
│       ├── test_constants.py                     # [EXAMPLE] Tests for constant values and response dict structure
│       ├── test_enums.py                         # [EXAMPLE] Tests for enum value stability, member count, serialization
│       ├── test_exceptions.py                    # [EXAMPLE] Tests for exception hierarchy, status codes, error codes
│       ├── test_models.py                        # [EXAMPLE] Tests for model field defaults, constraints, relationships
│       ├── test_schemas.py                       # [EXAMPLE] Tests for schema validation, field constraints, edge cases
│       ├── test_service.py                       # [EXAMPLE] Tests for service CRUD methods with mocked DB
│       ├── test_router.py                        # [EXAMPLE] Tests for endpoint responses, status codes, auth
│       ├── test_utils.py                         # [EXAMPLE] Tests for utility functions
│       └── test_validators.py                    # [EXAMPLE] Tests for field-validator helpers
│
└── integration_tests/
    └── {{module_name}}/                          # Integration test directory
        ├── __init__.py                           # [TEMPLATE] Empty init
        └── test_api.py                           # [EXAMPLE] End-to-end API tests with real DB
```

======================================== IMPORT HIERARCHY & DEPENDENCY RULES ========================================

────────────────────────────────────────
📐 IMPORT HIERARCHY (Critical — No Circular Imports)
────────────────────────────────────────

The module files MUST follow this strict import order. Each file may only import
from files above it in the hierarchy (plus stdlib and third-party):

```
  enums.py              ← stdlib only (enum, no local imports)
      ↓
  validation.py         ← imports enums.py (for enum-derived constants)
      ↓
  validators.py         ← imports validation.py (for constant values)
      ↓
  schemas.py            ← imports enums.py, validation.py, validators.py
      ↓
  models.py             ← imports schemas.py (base classes), enums.py, validation.py
      ↓
  exceptions.py         ← imports enums.py (for error code enums)
      ↓
  utils.py              ← imports models.py, schemas.py, validation.py, exceptions.py
      ↓
  service.py            ← imports models.py, schemas.py, exceptions.py
      ↓
  dependencies.py       ← imports models.py, api/auth/dependencies.py
      ↓
  constants.py          ← imports schemas.py (for response model references), api/core/responses.py
      ↓
  router.py             ← imports everything above (service, schemas, constants, enums, etc.)
```

Rules:
  - enums.py NEVER imports from any local module (stdlib only)
  - validation.py imports ONLY from enums.py
  - schemas.py NEVER imports from models.py (models inherit from schemas)
  - constants.py is at the bottom because it references schema classes for OpenAPI response dicts
  - router.py is the only file that touches all other module files

────────────────────────────────────────
🔗 CROSS-MODULE IMPORT RULES
────────────────────────────────────────

  ✅ ALLOWED:
  - Any module file → api/core/* (exceptions, responses, schemas, validators)
  - Any module file → api/database/* (base_service, dependencies, config)
  - dependencies.py, utils.py, service.py → api/auth/dependencies.py, api/auth/models.py
  - router.py → api/core/email.py (if module sends emails)

  ❌ FORBIDDEN:
  - Any module file → another module's files (e.g., api/fitness_app/ → api/other_module/)
  - schemas.py → models.py (reverse dependency — models inherit from schemas)
  - enums.py → any local module file
  - validation.py → schemas.py or models.py

======================================== CONSTRAINTS & REQUIREMENTS ========================================

────────────────────────────────────────
📐 CODE QUALITY STANDARDS
────────────────────────────────────────

All template code MUST follow these standards (from the fitness_app reference):

  [X] Modern Python 3.12+ typing: X | None (not Optional[X]), built-in list/dict (not List/Dict)
  [X] All constants use Final[type] annotations
  [X] All enums use (str, Enum) base for JSON serialization
  [X] Lazy % formatting in all logger calls (never f-strings)
  [X] Logger per module: logger = logging.getLogger(__name__)
  [X] Comprehensive docstrings with Args/Returns/Raises sections on all public functions
  [X] Module-level docstring explaining purpose, usage examples, and import hierarchy
  [X] Explicit __all__ export list in every file
  [X] Section separators using # ======== SECTION ======== pattern for major sections
  [X] Import ordering: stdlib → third-party → api/core/ → api/database/ → api/auth/ → local module
  [X] PascalCase for classes, snake_case for functions/variables, UPPER_SNAKE_CASE for constants
  [X] No magic numbers or strings — extract to validation.py constants
  [X] No bare except: clauses — always catch specific exceptions
  [X] TYPE_CHECKING imports for forward references that would cause circular imports

────────────────────────────────────────
🧱 ARCHITECTURAL REQUIREMENTS
────────────────────────────────────────

  [X] Service Layer Pattern — all DB operations via service class inheriting BaseDatabaseService
  [X] Typed Exception Hierarchy — base ModuleException → entity-specific exceptions
  [X] Schema Separation — Pydantic schemas separate from SQLModel models
  [X] Validation Constants — single source of truth in validation.py
  [X] Enum-Driven Schemas — all categorical fields use (str, Enum) types
  [X] Dependency Injection — FastAPI Depends() for auth, session, and module-specific deps
  [X] RESTful Endpoints — noun-based paths, plural collections, path params for specific resources
  [X] OpenAPI Documentation — response models, descriptions, and tags on every endpoint
  [X] Error Handling — domain exceptions → to_http_exception() → HTTPException in router

────────────────────────────────────────
🔐 SECURITY REQUIREMENTS
────────────────────────────────────────

  [X] All mutating endpoints require authentication via get_current_user
  [X] Resource access checks: owner-or-admin pattern (see utils.py can_access_resource)
  [X] No raw SQL strings — always use SQLModel/SQLAlchemy query builders
  [X] No secrets in code — environment variables for all sensitive configuration
  [X] Input validation at API boundary via Pydantic schemas with field constraints
  [X] IntegrityError handling for race conditions (see dependencies.py pattern)
  [X] Error messages never expose internal details to clients
  [X] Debug logs never serialize full request payloads

────────────────────────────────────────
🗄️ DATABASE REQUIREMENTS
────────────────────────────────────────

  [X] SQLModel for ORM model definitions (combining SQLAlchemy + Pydantic)
  [X] Use sa_column=Column(...) for advanced SQLAlchemy features (JSONB, custom types)
  [X] Use Field() for simple constraints (ge, le, min_length, max_length)
  [X] Never mix Field() and sa_column for the same field
  [X] Indexes on commonly filtered/queried columns
  [X] ForeignKey to KDFUser.id with ondelete="CASCADE" for user-owned data
  [X] Relationship() for SQLAlchemy ORM relationships (with back_populates)
  [X] created_at/updated_at timestamps with server_default=func.now()
  [X] Link tables for many-to-many relationships

────────────────────────────────────────
🧪 TESTING REQUIREMENTS
────────────────────────────────────────

  [X] conftest.py with shared fixtures (mock session, mock user, service with mock session)
  [X] At least one example test per module file (constants, enums, exceptions, models, schemas, service, router, utils, validators)
  [X] Tests use pytest fixtures and parametrize where appropriate
  [X] Service tests mock the database session
  [X] Router tests use FastAPI TestClient
  [X] Schema tests verify validation accepts valid data and rejects invalid data
  [X] Enum tests verify value stability and JSON serialization
  [X] Exception tests verify status codes, error codes, and to_http_exception conversion

────────────────────────────────────────
📚 DOCUMENTATION REQUIREMENTS
────────────────────────────────────────

  [X] README.md — Quick start: copy, rename, register in main.py, start coding
  [X] ARCHITECTURE.md — Module architecture, import hierarchy, design patterns
  [X] CODING_STANDARDS.md — Python/FastAPI coding standards for the ecosystem
  [X] ROUTE_CREATION_WORKFLOW.md — Step-by-step: add a new endpoint from constants to router
  [X] FEATURE_CREATION_WORKFLOW.md — Step-by-step: add a new entity/feature to the module
  [X] TESTING_GUIDE.md — Test patterns, fixtures, mocking strategies, running tests

======================================== DETAILED FILE SPECIFICATIONS ========================================

This section specifies what each template file MUST contain. Example code uses a generic
"Item" entity (like a todo item, bookmark, or note) to demonstrate patterns without being
tied to any specific domain.

────────────────────────────────────────
📄 __init__.py
────────────────────────────────────────

  - Empty file (module discovery happens via router inclusion in main.py)
  - Optional: single-line docstring with module name

────────────────────────────────────────
📄 enums.py — Domain Enums
────────────────────────────────────────

Demonstrate:
  - Module docstring explaining purpose, (str, Enum) pattern, and that this file has NO local imports
  - __all__ export list
  - At least 2 example enum classes with (str, Enum) base:
    • ItemStatus — Example status enum (draft, published, archived)
    • ItemCategory — Example category enum with grouped values
    • ModuleErrorCode — Error code enum used by exceptions.py
  - Descriptive docstring on every enum class
  - Section separators grouping related enums
  - Human-readable, lowercase, snake_case enum values

────────────────────────────────────────
📄 validation.py — Validation Constants
────────────────────────────────────────

Demonstrate:
  - Module docstring with import hierarchy explanation
  - __all__ export list
  - All constants as Final[type] with descriptive names
  - MIN/MAX pairing pattern for string lengths:
    • MIN_ITEM_NAME_LENGTH / MAX_ITEM_NAME_LENGTH
    • MIN_ITEM_DESCRIPTION_LENGTH / MAX_ITEM_DESCRIPTION_LENGTH
  - Numeric range constants:
    • MIN_ITEM_QUANTITY / MAX_ITEM_QUANTITY
  - Enum-derived tuple constants:
    • ITEM_STATUSES = tuple(s.value for s in ItemStatus)
  - Section separators grouping by entity (item, category, etc.)
  - Comment explaining usage: "Import directly from validation.py, not constants.py"

────────────────────────────────────────
📄 validators.py — Shared Field Validators
────────────────────────────────────────

Demonstrate:
  - Module docstring with import hierarchy
  - __all__ export list
  - Re-export of api/core/validators.py helpers (validate_optional_url)
  - At least 2 validator functions:
    • normalize_name(v: str | None, field_label: str) → str | None — strip, title-case
    • validate_positive_number(v: float | None, field_label: str) → float | None
  - Each function: pure, stateless, with Args/Returns/Raises docstring
  - Constants imported from validation.py (not hardcoded)
  - Usage example in docstring showing @field_validator integration

────────────────────────────────────────
📄 schemas.py — Pydantic Schemas
────────────────────────────────────────

Demonstrate:
  - Module docstring explaining schema separation from models
  - __all__ export list
  - Import pattern: enums, validation constants, validators
  - Mixin pattern:
    • MixinTimestamp — created_at/updated_at fields
  - Base schema pattern:
    • BaseItem — shared fields between Create/Update/Response
  - CRUD schema trio per entity:
    • CreateItem — fields required for creation (validates input)
    • UpdateItem — all fields optional (partial update)
    • ResponseItem — fields returned to client (includes id, timestamps)
  - Field() with min_length, max_length, ge, le from validation.py constants
  - @field_validator using helpers from validators.py
  - ConfigDict(from_attributes=True) for ORM compatibility
  - Enum fields using the enum type directly (Pydantic v2 validates automatically)
  - Example of a list response wrapper or pagination schema
  - TypeVar/Generic pattern if used
  - NamedTuple for structured query results (e.g., FilteringRow)

────────────────────────────────────────
📄 models.py — SQLModel ORM Models
────────────────────────────────────────

Demonstrate:
  - Module docstring with Field() vs sa_column rules
  - Import pattern: schemas (base classes), enums, validation constants
  - TYPE_CHECKING import for KDFUser (avoids circular import)
  - Main entity model inheriting from a base schema:
    • Item(BaseItem, table=True) — with id, user_id ForeignKey, timestamps
  - created_at / updated_at with server_default=func.now()
  - ForeignKey to KDFUser with ondelete="CASCADE"
  - Relationship() with back_populates
  - Index() on commonly filtered columns
  - sa_column=Column() for advanced types (JSONB, custom defaults)
  - Link table for many-to-many:
    • ItemTagLink(SQLModel, table=True) — composite ForeignKeys
  - Lookup/reference table:
    • Tag(BaseTag, table=True) — simple name+description entity
  - Field validators on models (if needed beyond schema validation)

────────────────────────────────────────
📄 exceptions.py — Exception Hierarchy
────────────────────────────────────────

Demonstrate:
  - Module docstring with usage examples
  - Import from api/core/exceptions (AppException, to_http_exception, etc.)
  - Import ModuleErrorCode from enums.py
  - Base module exception:
    • ModuleException(AppException) — default detail, status_code, error_code
  - Entity-specific exceptions (at least 4):
    • ItemNotFound — 404, suggestions list
    • ItemAlreadyExists — 409, suggestions list
    • InvalidItemData — 400, suggestions list
    • ItemAccessDenied — 403, suggestions list
  - Factory function pattern (if applicable):
    • create_not_found_exception(entity_name: str, entity_id: int) → ModuleException
  - Each exception: class docstring, default detail, status_code, error_code, suggestions
  - Show how to raise: raise to_http_exception(ItemNotFound())
  - Show custom detail: raise to_http_exception(ItemNotFound(detail="Item #42 not found"))

────────────────────────────────────────
📄 constants.py — Router & Response Constants
────────────────────────────────────────

Demonstrate:
  - Module docstring explaining that this file is LAST in import hierarchy
  - Import from api/core/responses (COMMON_200_OK, COMMON_400_BAD_REQUEST, etc.)
  - Import MessageResponse from api/core/schemas
  - Router management constants:
    • MODULE_TAG: Final[str] — OpenAPI tag name
    • MODULE_ROUTER_PREFIX: Final[str] — URL prefix (e.g., "/my-module")
    • MODULE_ROUTER_TAGS: Final[tuple[str, ...]] — tag tuple
  - RESTful endpoint path constants:
    • ITEMS_ENDPOINT: Final[str] = "/items"
    • ITEM_BY_ID_ENDPOINT: Final[str] = "/items/{item_id}"
    • Comments showing HTTP methods per endpoint
  - Success response dicts for OpenAPI:
    • HTTP_200_ITEM_RETRIEVED, HTTP_201_ITEM_CREATED, HTTP_204_ITEM_DELETED
  - RESTful naming convention comment block (nouns, plural, kebab-case)

────────────────────────────────────────
📄 dependencies.py — FastAPI Dependencies
────────────────────────────────────────

Demonstrate:
  - Module docstring explaining dependency injection pattern
  - Import get_current_user from api/auth/dependencies
  - Import db_dependency from api/database/dependencies
  - Module-specific profile/context dependency:
    • get_or_create_module_profile(user, session) → ModuleUserProfile
  - Private helper function: _find_existing_profile()
  - Annotated type alias for the dependency:
    • ModuleProfileDep = Annotated[ModuleUserProfile, Depends(get_or_create_module_profile)]
  - IntegrityError handling for race conditions
  - Logging on profile creation
  - Docstring with usage example showing endpoint signature

────────────────────────────────────────
📄 service.py — Database Service Class
────────────────────────────────────────

Demonstrate:
  - Module docstring with two usage modes (FastAPI DI and CLI)
  - Service class inheriting BaseDatabaseService:
    • ModuleService(BaseDatabaseService)
  - Constructor: __init__(self, session: Session | None = None)
  - CRUD methods for the example entity (at least 5):
    • get_item(item_id: int, user: KDFUser) → Item
    • get_items(user: KDFUser, ...) → list[Item] (with filtering/pagination)
    • create_item(data: CreateItem, user: KDFUser) → Item
    • update_item(item_id: int, data: UpdateItem, user: KDFUser) → Item
    • delete_item(item_id: int, user: KDFUser) → None
  - Domain exception raising (ItemNotFound, ItemAccessDenied, etc.)
  - Session management: _get_session(), session.commit(), session.rollback()
  - Access control checks using utils.can_access_resource()
  - Lazy % logging throughout
  - Relationship handling (e.g., creating/updating tags on an item)
  - Atomic transactions with flush + single commit pattern

────────────────────────────────────────
📄 utils.py — Pure Utility Functions
────────────────────────────────────────

Demonstrate:
  - Module docstring listing main exports
  - __all__ export list
  - Access control function:
    • can_access_resource(resource, user: KDFUser) → bool — owner-or-admin check
  - At least 1-2 domain computation functions:
    • calculate_something(items: list[...]) → dict — stateless computation
  - Logger configuration: logger = logging.getLogger(__name__)
  - No database access, no session management
  - Comprehensive docstrings with Args/Returns/Raises
  - Type annotations on all parameters and return values

────────────────────────────────────────
📄 router.py — API Router & Endpoints
────────────────────────────────────────

Demonstrate:
  - Module docstring with endpoint summary
  - APIRouter with prefix and tags from constants.py
  - At minimum 5 example endpoints covering full CRUD:
    • GET  /items          — List items (with query params for filtering)
    • POST /items          — Create item (returns 201)
    • GET  /items/{id}     — Get single item
    • PATCH /items/{id}    — Update item (partial update)
    • DELETE /items/{id}   — Delete item (returns 204)
  - Each endpoint with:
    • response_model from schemas.py
    • responses dict from constants.py (success + error response docs)
    • status_code appropriate for the operation
    • summary and description strings
    • Depends() for auth (get_current_user) and session (db_dependency)
    • Service instantiation: service = ModuleService(session=db)
    • Try/except with to_http_exception for domain exceptions
    • Proper re-raise of HTTPException (not swallowing 403/500 as 404)
    • Lazy % logging for request/response tracking
  - Pattern for Query() parameters with alias (preserving API contract)
  - Pattern for Body() parameters
  - Pattern for Path() parameters with description

======================================== WORKFLOW DOCUMENTATION SPECIFICATIONS ========================================

────────────────────────────────────────
📄 docs/ROUTE_CREATION_WORKFLOW.md
────────────────────────────────────────

This document MUST walk a developer through adding a new endpoint step-by-step:

  **Step 1: Define the Endpoint Path (constants.py)**
  - Add a new Final[str] endpoint constant
  - Follow RESTful naming conventions
  - Show the exact code to add

  **Step 2: Create/Update Schema (schemas.py)**
  - Define request schema (Create/Update) with Field() constraints
  - Define response schema with ConfigDict(from_attributes=True)
  - Add @field_validator if needed
  - Update __all__

  **Step 3: Create/Update Model (models.py)** (if new entity)
  - Define SQLModel with table=True
  - Add ForeignKey, Relationship, Index
  - Add timestamps
  - Run Alembic migration: alembic revision --autogenerate -m "add X table"

  **Step 4: Add Exception (exceptions.py)** (if new error case)
  - Create new exception class inheriting ModuleException
  - Set detail, status_code, error_code, suggestions
  - Update __all__

  **Step 5: Add Enum (enums.py)** (if new categorical data)
  - Create (str, Enum) class
  - Add enum-derived constants to validation.py
  - Update __all__ in both files

  **Step 6: Add Service Method (service.py)**
  - Implement the business logic in ModuleService
  - Use domain exceptions for error cases
  - Handle session commit/rollback

  **Step 7: Add Validation Constants (validation.py)** (if new constraints)
  - Add MIN/MAX constants
  - Update __all__

  **Step 8: Add OpenAPI Response Dict (constants.py)**
  - Create HTTP_200_X_RETRIEVED or similar constant
  - Reference schema model if applicable

  **Step 9: Wire Up the Endpoint (router.py)**
  - Add the route decorator with all metadata
  - Call service method
  - Handle exceptions with to_http_exception
  - Add logging

  **Step 10: Add Tests**
  - Unit test for the service method (test_service.py)
  - Unit test for schema validation (test_schemas.py)
  - Router test with TestClient (test_router.py)

  **Step 11: Register Module (api/main.py)** (first time only)
  - Import router: from api.{{module_name}}.router import router as {{module_name}}_router
  - Include: app.include_router({{module_name}}_router)

────────────────────────────────────────
📄 docs/FEATURE_CREATION_WORKFLOW.md
────────────────────────────────────────

This document MUST walk a developer through adding an entirely new entity/feature:

  **Phase 1: Design**
  - Define the entity's fields, relationships, and constraints
  - Decide on enum values for categorical fields
  - Plan the CRUD endpoints needed
  - Identify validation rules

  **Phase 2: Implementation (follow import hierarchy order)**
  - 2a. enums.py — Add enum classes
  - 2b. validation.py — Add MIN/MAX constants, enum-derived tuples
  - 2c. validators.py — Add any new validator helpers
  - 2d. schemas.py — Add Base, Create, Update, Response schemas
  - 2e. models.py — Add SQLModel with table=True, relationships
  - 2f. exceptions.py — Add entity-specific exceptions
  - 2g. utils.py — Add any computation helpers
  - 2h. service.py — Add CRUD methods to the service class
  - 2i. constants.py — Add endpoint paths and response dicts
  - 2j. router.py — Wire up endpoints

  **Phase 3: Migration**
  - Run: alembic revision --autogenerate -m "add {{entity}} tables"
  - Review the generated migration
  - Run: alembic upgrade head

  **Phase 4: Testing**
  - Add unit tests for each file
  - Add integration test for the full endpoint flow
  - Verify all existing tests still pass

======================================== EXAMPLE ENTITY SPECIFICATION ========================================

────────────────────────────────────────
📋 EXAMPLE ENTITY: Item
────────────────────────────────────────

The template uses a generic "Item" entity to demonstrate all patterns. It should be
realistic enough to show real-world patterns without being tied to any specific domain.

  Entity: Item (a generic user-owned resource)
  Fields:
    - id: int (primary key, auto-increment)
    - user_id: int (ForeignKey to KDFUser.id, CASCADE)
    - name: str (min 2, max 100 chars)
    - description: str | None (optional, max 500 chars)
    - status: ItemStatus enum (draft, published, archived)
    - category: ItemCategory enum
    - quantity: int (min 1, max 10000)
    - is_public: bool (default False)
    - metadata_json: dict[str, Any] | None (JSONB column)
    - created_at: datetime (server default)
    - updated_at: datetime (server default, auto-update)

  Relationships:
    - Item → KDFUser (many-to-one via user_id)
    - Item ↔ Tag (many-to-many via ItemTagLink)
    - User has back_populates to items list

  Lookup Table: Tag
    - id: int (primary key)
    - name: str (unique, min 1, max 50)
    - description: str | None (max 200)

  Link Table: ItemTagLink
    - item_id: int (ForeignKey to Item.id, CASCADE)
    - tag_id: int (ForeignKey to Tag.id, CASCADE)
    - Primary key: (item_id, tag_id)

  CRUD Endpoints:
    GET    /items              — List user's items (filter by status, category)
    POST   /items              — Create new item
    GET    /items/{item_id}    — Get item by ID
    PATCH  /items/{item_id}    — Update item (partial)
    DELETE /items/{item_id}    — Delete item
    GET    /items/names        — Get item names for autocomplete
    GET    /tags               — Get all tags

────────────────────────────────────────
📋 EXAMPLE ENTITY: ModuleUserProfile (optional per-module profile)
────────────────────────────────────────

  Entity: ModuleUserProfile (per-module user settings, lazy-created)
  Fields:
    - user_id: int (primary key, ForeignKey to KDFUser.id)
    - display_name: str | None
    - preferences_json: dict[str, Any] | None (JSONB)
    - created_at: datetime
    - updated_at: datetime

  Purpose: Demonstrates the get_or_create dependency pattern from fitness_app

======================================== BEHAVIORAL GUIDELINES ========================================

When creating this template, follow these guidelines:

  1.  **Study Before Building** — Read every file in api/fitness_app/ thoroughly before
      writing any template code. The template must embody these exact patterns.

  2.  **Copy Structure, Generalize Content** — The file structure, import patterns, class
      hierarchies, and coding conventions must match fitness_app exactly. Only the
      domain-specific content (food, meal, nutrition) gets replaced with generic Item examples.

  3.  **Self-Documenting** — Every file should have enough docstrings and comments that a
      developer can understand its purpose without reading external docs.

  4.  **Example-Driven** — The example Item entity and full CRUD flow are the most important
      teaching tools. Make them complete, realistic, and well-documented.

  5.  **No Dead Code** — Every file in the template should have a purpose. Don't include
      fitness-specific logic that would need to be deleted.

  6.  **Consistent Patterns** — Every file must follow the same coding standards (section
      separators, import ordering, docstrings, naming). No exceptions for "it's just a template."

  7.  **Security by Default** — Auth dependencies, access control checks, and input validation
      should be production-ready patterns without any changes needed.

  8.  **Progressive Disclosure** — README.md should get someone copying and running in 5 minutes.
      Detailed workflow docs are in the docs/ directory for deeper understanding.

  9.  **TODO Markers** — Use # TODO: [CUSTOMIZE] markers for things developers must change
      (e.g., module name, endpoint paths, entity names, enum values).

  10. **Import Hierarchy Compliance** — Every import statement must strictly follow the
      import hierarchy documented above. Circular imports are a blocking defect.

  11. **Prove It Works** — After generating all files, verify that the template code has no
      syntax errors, all imports resolve correctly, and the example tests pass conceptually.

  12. **Match the Reference** — When in doubt about a pattern, copy what fitness_app does.
      The fitness_app module is the source of truth for how things should be structured.

  13. **Workflow Documentation is Key** — The ROUTE_CREATION_WORKFLOW.md and
      FEATURE_CREATION_WORKFLOW.md documents are critically important. They should be
      detailed enough that a developer who has never seen the codebase can follow them
      step-by-step to add a new endpoint or feature.

======================================== TASK BREAKDOWN APPROACH ========================================

Approach this task in the following phases:

────────────────────────────────────────
📋 PHASE 1 — SCAFFOLDING (Directory & Base Files)
────────────────────────────────────────

  1. Create the templates/back-end-application-template/ directory structure
  2. Create all __init__.py files
  3. Create the placeholder {{module_name}} directories

────────────────────────────────────────
📋 PHASE 2 — FOUNDATION FILES (Import Hierarchy Order)
────────────────────────────────────────

Following the import hierarchy strictly:
  1. Create enums.py with example enums (ItemStatus, ItemCategory, ModuleErrorCode)
  2. Create validation.py with Final[type] constants for Item entity
  3. Create validators.py with shared field-validator helpers
  4. Create schemas.py with Base/Create/Update/Response schemas for Item
  5. Create models.py with Item, Tag, ItemTagLink, ModuleUserProfile models
  6. Create exceptions.py with ModuleException hierarchy

────────────────────────────────────────
📋 PHASE 3 — BUSINESS LOGIC FILES
────────────────────────────────────────

  1. Create utils.py with can_access_resource and example computation
  2. Create service.py with ModuleService class and full CRUD methods
  3. Create dependencies.py with get_or_create_module_profile
  4. Create constants.py with router metadata, endpoints, and response dicts
  5. Create router.py with full CRUD endpoint wiring

────────────────────────────────────────
📋 PHASE 4 — UNIT TESTS
────────────────────────────────────────

  1. Create conftest.py with shared fixtures
  2. Create test files for each module file (test_enums.py, test_schemas.py, etc.)
  3. Include at least 2-3 meaningful tests per file
  4. Demonstrate parametrize, fixtures, mocking patterns

────────────────────────────────────────
📋 PHASE 5 — INTEGRATION TESTS
────────────────────────────────────────

  1. Create test_api.py with end-to-end examples
  2. Show TestClient setup with auth headers
  3. Demonstrate create → read → update → delete flow

────────────────────────────────────────
📋 PHASE 6 — DOCUMENTATION
────────────────────────────────────────

  1. Write README.md (quick start, copy instructions, customization guide)
  2. Write ARCHITECTURE.md (module patterns, import hierarchy, design decisions)
  3. Write CODING_STANDARDS.md (Python/FastAPI standards for the ecosystem)
  4. Write ROUTE_CREATION_WORKFLOW.md (step-by-step endpoint addition)
  5. Write FEATURE_CREATION_WORKFLOW.md (step-by-step entity addition)
  6. Write TESTING_GUIDE.md (test patterns, fixtures, running tests)

────────────────────────────────────────
📋 PHASE 7 — VALIDATION & REVIEW
────────────────────────────────────────

  1. Verify all imports follow the hierarchy (no circular imports)
  2. Verify all __all__ exports are accurate
  3. Verify all docstrings are complete
  4. Verify all Final constants are used correctly
  5. Verify all TODO: [CUSTOMIZE] markers are present where needed
  6. Verify no fitness-specific references remain in template code
  7. Review for consistency with fitness_app coding standards

======================================== COMMON CLARIFICATION SCENARIOS ========================================

────────────────────────────────────────
❓ ALWAYS ASK ABOUT
────────────────────────────────────────

  • Whether the example Item entity fields are appropriate or should be adjusted
  • Whether additional example entities beyond Item and Tag are needed
  • Whether the template should include seed data examples
  • Whether Alembic migration examples should be included in the template

────────────────────────────────────────
✅ PROCEED WITHOUT ASKING
────────────────────────────────────────

  • Use the exact same file structure as fitness_app (it's the ecosystem standard)
  • Use the exact same coding standards (they're non-negotiable)
  • Use the exact same import hierarchy (it's battle-tested)
  • Use BaseDatabaseService as the service base class
  • Use AppException as the exception base class
  • Use (str, Enum) for all enum classes
  • Use Final[type] for all constants
  • Include the get_or_create profile dependency pattern

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
  [ ] Every .py file has a module-level docstring
  [ ] Every .py file has an __all__ export list (where applicable)
  [ ] Every public function/class has a docstring with Args/Returns/Raises
  [ ] All imports follow the documented import hierarchy (no circular imports)
  [ ] All constants use Final[type] annotations
  [ ] All enums use (str, Enum) base class
  [ ] All typing uses modern Python 3.12+ syntax (X | None, list, dict)
  [ ] All logger calls use lazy % formatting
  [ ] All section separators follow the # ======== SECTION ======== pattern
  [ ] Example Item CRUD flow works end-to-end conceptually
  [ ] ROUTE_CREATION_WORKFLOW.md covers all 11 steps with code examples
  [ ] FEATURE_CREATION_WORKFLOW.md covers all 4 phases with code examples
  [ ] README.md has clear copy-and-start instructions
  [ ] No fitness-specific references remain in template code
  [ ] TODO: [CUSTOMIZE] markers are present for all developer-specific values
  [ ] Unit test examples demonstrate pytest patterns (fixtures, parametrize, mocking)
  [ ] Integration test example demonstrates TestClient with auth
  [ ] All documentation is clear, complete, and actionable

────────────────────────────────────────
📊 SUCCESS METRICS
────────────────────────────────────────

  • **Time to First Endpoint:** A developer can copy the template and have a working
    CRUD endpoint in < 30 minutes
  • **Pattern Clarity:** Example files make it obvious how to add new entities and routes
  • **Import Safety:** Zero circular import risks when following the documented hierarchy
  • **Doc Completeness:** All architectural decisions and workflows are documented
  • **Clean Slate:** No fitness-specific code remains; template is truly generic
  • **Consistency:** Every file follows the exact same standards as the fitness_app reference

======================================== ERROR RECOVERY & ROLLBACK STRATEGIES ========================================

────────────────────────────────────────
⚠️ COMMON FAILURE POINTS
────────────────────────────────────────

  1. **Circular Imports:** If imports fail, verify the import hierarchy is respected.
     Most common mistake: schemas.py importing from models.py (must be the reverse).

  2. **Missing Base Classes:** Ensure api/core/exceptions.py (AppException) and
     api/database/base_service.py (BaseDatabaseService) exist before the template
     code tries to import them.

  3. **Auth Integration:** If auth dependencies fail, verify the import path to
     api/auth/dependencies.py and that KDFUser model is accessible.

  4. **SQLModel Quirks:** Remember that Optional["ForwardRef"] must stay as-is for
     SQLModel Relationship resolution — don't convert these to X | None.

  5. **Alembic Detection:** New models must be imported somewhere that Alembic's
     env.py can discover them (usually via the module's __init__.py or explicit
     import in the Alembic env).

────────────────────────────────────────
🔄 ROLLBACK PROCEDURE
────────────────────────────────────────

If the template is broken beyond repair:
  1. Delete templates/back-end-application-template/
  2. Re-read the api/fitness_app/ source code
  3. Start from Phase 1 with a fresh scaffold
  4. The fitness_app code is the source of truth — it always works

======================================== EXAMPLE USAGE ========================================

────────────────────────────────────────
📝 FULL EXAMPLE — Using This Prompt
────────────────────────────────────────

```
[Paste this entire prompt into your AI coding assistant]

I'm ready to start. Please begin with Phase 1 — create the directory scaffolding
in templates/back-end-application-template/ with all __init__.py files.
Then proceed to Phase 2 — create the foundation files following the import hierarchy.
```

────────────────────────────────────────
⚡ QUICK START — Phase-by-Phase
────────────────────────────────────────

```
Phase 1: "Create the directory scaffolding with all __init__.py files."
Phase 2: "Create the foundation files: enums, validation, validators, schemas, models, exceptions."
Phase 3: "Create the business logic files: utils, service, dependencies, constants, router."
Phase 4: "Create the unit test files with example tests and shared fixtures."
Phase 5: "Create the integration test files."
Phase 6: "Write all documentation (README, architecture, coding standards, workflows, testing)."
Phase 7: "Validate import hierarchy, exports, docstrings, and consistency."
```

────────────────────────────────────────
🔧 CUSTOMIZATION — After Template is Created
────────────────────────────────────────

A developer using this template would:

  1. Copy templates/back-end-application-template/api/{{module_name}}/ to api/{{their_module_name}}/
  2. Copy templates/back-end-application-template/unit_tests/{{module_name}}/ to unit_tests/{{their_module_name}}/
  3. Rename all {{module_name}} references to their module name
  4. Replace the example Item entity with their domain entity
  5. Update enums, validation constants, and schemas for their domain
  6. Update exception classes for their entity names
  7. Update service methods for their business logic
  8. Update router endpoints for their API contract
  9. Register their router in api/main.py:
     from api.{{their_module}}.router import router as {{their_module}}_router
     app.include_router({{their_module}}_router)
  10. Run Alembic migration: alembic revision --autogenerate -m "add {{their_module}} tables"
  11. Follow the patterns shown in the example code
  12. Remove example TODOs as they customize each file

======================================== QUICK START TEMPLATE ========================================

For quick task submission when working on the template:

```
======================================== TEMPLATE TASK ========================================

Phase: [1-7]
Task: [Brief description]
Files to create/modify: [List files]
Reference files from fitness_app: [List source files to study]

Notes:
[Any specific instructions or constraints]
```
