# Harness Engineering Principles

This project will be developed using the harness-engineering principles described in the attached OpenAI article, "Harness engineering: leveraging Codex in an agent-first world."

These principles are the project's engineering philosophy. They are NOT a requirement to reproduce OpenAI's exact implementation. Adapt them to the project's actual requirements and technology.

## 1. Core Operating Philosophy

### Agent-Generated Repository

The goal of this experiment is for the AI agent to generate the repository, including application code, tests, CI configuration, documentation, and internal tooling.

### Humans Steer, Agents Execute

The human developer should primarily work at the level of:

* specifying goals and acceptance criteria
* designing and improving the development environment
* identifying missing capabilities
* creating feedback loops and guardrails
* evaluating outcomes

Human-written code should be avoided as part of this experiment. When something in the repository needs to change, prefer having the agent make the change.

### Depth-First Execution

Large goals should be decomposed into smaller, verifiable building blocks. The agent should establish the foundations needed for increasingly complex tasks rather than attempting the entire system at once.

---

## 2. Context and System of Record

### Repository-Local Knowledge

Important project knowledge should be represented in version-controlled repository artifacts whenever practical.

Information that exists only in conversations or human memory should not be considered reliable project knowledge.

### Map, Not Manual

`CLAUDE.md` should remain concise and primarily act as a map to deeper sources of truth rather than becoming a giant instruction manual.

### Structured Documentation

Use an organized `docs/` directory for durable project knowledge, such as:

* architecture
* design decisions
* product specifications
* execution plans
* generated schemas
* technical debt
* development procedures

Use progressive disclosure: the agent should start with a small amount of context and discover deeper documentation when needed.

### Mechanical Documentation Verification

Where practical, documentation quality should be checked mechanically.

The repository should eventually have automated checks for issues such as:

* broken documentation links
* missing required documentation
* stale generated documentation
* invalid references
* inconsistencies that can be detected mechanically

Do not create elaborate documentation machinery unless it provides a concrete benefit.

---

## 3. Architecture and Invariant Enforcement

### Explicit Architectural Boundaries

The architecture should have clear, predictable boundaries and dependency directions.

Do not blindly copy OpenAI's specific `Types → Config → Repo → Service → Runtime → UI` architecture. First determine an architecture appropriate for this project's domain and technology.

Once established, architectural boundaries should be mechanically enforced wherever practical.

### Invariants Over Micromanagement

Prefer enforcing important invariants instead of prescribing every implementation detail.

For example, enforce:

* valid data at system boundaries
* allowed dependency directions
* structured logging
* naming conventions
* security constraints
* important reliability requirements

Within those boundaries, allow the agent freedom to choose the implementation.

### Actionable Errors

Lint and validation failures should provide useful remediation guidance whenever practical so that the agent can understand and correct failures without requiring human explanation.

### Dependency Legibility

Prefer dependencies and abstractions that are stable, composable, well-understood, and easy for the agent to inspect and reason about.

Do not reimplement third-party functionality merely for ideological reasons. Build internal utilities only when doing so provides a concrete advantage in correctness, observability, integration, or agent legibility.

---

## 4. Agent Legibility and Feedback Loops

### Autonomous Validation

The agent should have direct access to the tools required to build, test, run, inspect, and debug the application.

Where useful, work should be isolated so that the agent can safely make and validate changes.

### Application Legibility

As the project develops, expose useful application state to the agent through appropriate mechanisms such as:

* logs
* metrics
* traces
* CLI diagnostics
* API inspection
* screenshots
* browser automation
* test fixtures

Use the simplest mechanisms that provide useful feedback.

### Visual Validation

For applications with a UI, provide browser automation or equivalent tooling when it materially improves the agent's ability to reproduce and verify UI behavior.

### Self-Contained Iteration

The agent should be able to:

1. understand the task
2. inspect the current state
3. implement a change
4. run validation
5. inspect failures
6. correct the implementation
7. repeat validation

Human intervention should be reserved for decisions requiring human judgment or genuinely blocked situations.

---

## 5. Continuous Quality and Entropy Management

### Golden Principles

Important engineering preferences and quality requirements should eventually be encoded into repository documentation, validation tooling, or tests so they apply consistently to future agent runs.

### Continuous Cleanup

The project should have mechanisms for detecting and reducing:

* duplicated patterns
* architectural drift
* stale documentation
* technical debt
* recurring classes of agent mistakes
* low-quality generated code

Automated cleanup tasks may be introduced when the project becomes large enough for them to provide value.

### Feedback Becomes Infrastructure

When the agent repeatedly makes the same mistake, do not merely tell it to "be more careful."

Instead, determine whether the missing capability should become:

* documentation
* a test
* a lint rule
* a tool
* a hook
* an architectural constraint
* a skill
* a specialized subagent

The objective is to make each solved failure reduce the probability of the same failure occurring again.

### Throughput

Optimize the development loop for rapid agent iteration while retaining meaningful correctness and quality checks.

Do not introduce blocking processes merely for convention. Prefer cheap automated correction where appropriate, while retaining human review for decisions that genuinely require human judgment.

---

# Meta-Rule

The harness itself is part of the experiment.

Whenever the agent struggles, ask:

**"What capability is missing from the environment?"**

Then improve the environment rather than merely adding another instruction to the agent.

The goal is not to create the largest possible harness.

The goal is to create the smallest environment in which the agent can reliably perform increasingly complex engineering work.
