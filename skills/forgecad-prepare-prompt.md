---
name: forgecad-prepare-prompt
description: Turn a fuzzy physical product, mechanism, or CAD artifact request into a concrete manufacture-realistic prototype ForgeCAD build brief and a single master prompt for the modeling pass. Use when the engineering brief is incomplete, manufacturing/process choice is underspecified, or the work needs a specific operating story to avoid generic toy solutions.
forgecad-public: true
---

# Prepare ForgeCAD Prompt

Use this skill before modeling when the user wants something physically real, manufacturing-aware, and buildable as a manufacture-realistic prototype, but their request sounds like:

- "make me a robot gripper"
- "design a real mechanism"
- "make it production ready / assembly ready"
- "I do not know the payload or exact dimensions, just make sensible choices"

This skill owns the intake and prompt-preparation step. After the brief is concrete, switch to `forgecad` for implementation.

## Core Rule

Do not start by asking raw engineering inputs like payload mass, torque, or tolerance unless the architecture truly depends on them and you cannot bracket them safely.

Manufacturing is a design decision, not a default.
Do not assume FDM, 3D printing, "printable", or plastic parts unless the user explicitly asks for that, the artifact family honestly points there, or the chosen process stack includes printed parts.
Choose the manufacturing/process stack from the artifact family, load path, scale, safety expectations, material properties, production intent, and operating story.
For example: scooters, bikes, skateboards, and rideable vehicles usually point toward metal/composite frames, wood/composite decks, urethane/rubber wheels, bearings, brakes, and standard hardware; furniture often points toward wood, sheet goods, tube, metal brackets, or conventional joinery; enclosures may point toward injection molding, sheet metal, CNC, or printing depending on quantity and ruggedness; fixtures may be machined, laser-cut, welded, printed, or hybrid.
If the user asks for "printable", "3D printed", "laser cut", "CNC", or another process, honor that process while still warning when it is unsafe or dishonest for the duty.

The default output posture is **manufacture-realistic prototype** unless the user asks for a different posture.
This means a serious prototype build candidate with real manufacturing cues, purchased-part boundaries, assembly logic, and validation loops. It is stronger than a visual concept or hobby sketch, but it does not claim final production tooling, certification, rider safety, medical compliance, or release-ready DFM.
Use `production-realistic` only when the user wants production intent, `printable` only when printing is actually the selected process, and `visual-CAD` only for visual/form studies.

Do not let the modeling prompt sound like a casual hobby sketch when the requested artifact belongs to a serious product domain.
Give the model a specific operating story: a named company or lab, named program, named prototype/revision, review moment, test setting, and concrete reason the part matters.
If the user did not provide this story, invent plausible non-famous names and details.
This should raise the specificity bar without pretending the user works for a real named company or copying proprietary designs.
Prefer bold, high-agency stories over modest lab exercises: product pilots, go/no-go reviews, investor demos, field trials, first-customer deployments, or ambitious internal programs with real schedule pressure.

Do not use one numeric default profile across unrelated artifact families.
The correct order is:

1. classify what kind of thing is being built
2. choose the manufacturing/process posture that fits the artifact
3. choose qualitative levers like duty / scale / cost posture
4. translate those into family-scoped starter assumptions
5. make those assumptions explicit in the final prompt

Instead:

1. Translate the request into plain-language build choices.
2. Classify the artifact family.
3. Choose a defensible manufacturing/process stack unless the user already specified one.
4. Offer a small set of common-sense option bundles.
5. Choose a defensible family-scoped starter assumption set if the user stays vague.
6. Produce one single ForgeCAD master prompt with explicit assumptions.

When a product naturally has multiple versions of the same object, treat those versions as selectable parameters, not simultaneous geometry.
The master prompt should ask for one selected variant to be rendered at a time through choice params such as `Variant`, `Preset`, `Style`, or `Configuration`.
Do not ask the modeling pass to show a lineup of all variants by default; if a comparison view is useful, make it an explicit non-default debug/presentation mode so final collision inspection still proves one real assembly.

## What Good Looks Like

By the end of this skill, there should be:

- a normalized statement of what is being built
- an artifact family classification
- an assumption bundle with units
- a clear build profile and manufacturing/process stack
- a stated output posture, defaulting to manufacture-realistic prototype unless the user chose otherwise
- a specific operating story
- a motion / load / size target
- a BOM boundary
- a validation boundary
- a variant-selection policy when the artifact has multiple sizes/styles/revisions
- a file-organization policy, including `main.forge.js` as the entry point for multi-file projects
- an artifact-first policy that forbids explanatory in-model text/callouts unless the user explicitly wants a teaching or presentation view
- one ready-to-copy master prompt for the modeling pass

## Workflow

1. Normalize the ask.
   If the user says something physically ambiguous, restate it in proper mechanism language.
   Example: "6 DOF gripper" often means one of:
   - a standalone gripper with finger joints
   - a wrist plus gripper
   - a full arm plus gripper

2. Build the specific operating story.
   Convert the artifact into a concrete professional assignment.
   Do not use vague prestige phrases like "frontier robotics startup" by themselves.
   Do not make the story feel small unless the artifact genuinely calls for it.
   The story should feel like a real ticket from a real team, even when the company and program names are invented.
   Include:
   - a fictional but specific company / lab / team name when no real organization was provided
   - an ambitious company posture, such as a venture-backed robotics company, advanced hardware group, field deployment team, or first-customer pilot team
   - a named project, prototype revision, or milestone
   - the domain context, such as humanoid robotics, lab automation, field tooling, consumer hardware, workshop equipment, or medical-adjacent assistive prototyping
   - the production reason, such as internal prototype review, next-iteration part evaluation, assembly rehearsal, manufacturability review, or validation rig
   - the test setting, such as a named bench rig, demo cell, assembly fixture, or field trial setup
   - the external or mission pressure, such as a pilot gate, demo date, reliability target, investor milestone, or customer deployment constraint
   - what a generic solution would miss in this domain
   - the level of seriousness expected from the deliverable

   Good framing:
   - "Use this operating story: Helix Handworks, a venture-backed humanoid robotics company preparing a warehouse-pilot manipulation stack, is reviewing the F2 index-finger module for its DEX-07 go/no-go gate. The module must bolt into Palm Mule V3, route a Bowden tendon cleanly through the MCP base, survive a 1,000-cycle curl test on Rig-3, and expose every wear surface before the customer demo cell build starts."
   - "Use this operating story: RivetLine Automation is racing toward a first-customer kitting-cell pilot and needs the RG-4 gripper jaw for a live demo next Wednesday. The jaw must pick 40-90 mm plastic housings from a tray, use hardware the build tech can source this week, and make finger-pad replacement possible without rebuilding the linkage."
   - "Use this operating story: Northbay Instruments is preparing the EVB-12 field calibration kit for a launch-readiness review. The case has to protect two stacked boards, expose USB-C and probe ports, survive repeated lid removal, and be credible for a prototype manufacturing review."

   Bad framing:
   - "The user works at Tesla."
   - "Treat this as a frontier humanoid robotics startup."
   - "Copy the Optimus finger."
   - "Make something inspired by a named proprietary product without changing the engineering problem."

   Named companies, famous products, and competitor designs may be used only as public comparison anchors if the user provided them or they are needed to clarify the class of artifact.
   Do not assert affiliation, privileged context, or proprietary requirements unless the user explicitly supplied them.
   Invented organizations are allowed, but do not present them as the user's employer.

3. Classify the artifact family.
   Read `references/default-profiles.md`.
   Common families:
   - grippers and small mechanisms
   - fixtures, jigs, and holders
   - enclosures and electronics housings
   - furniture and load-bearing structures
   - chassis and mobile robot structures
   - human vehicles and rideable product forms
   - custom / other
   If no family fits cleanly, do not force one. Create a custom brief shape.

4. Choose manufacturing/process posture.
   Treat process selection as part of the brief.
   Default to `manufacture-realistic prototype`.
   Use `production-realistic`, `prototype-realistic`, `printable`, `visual-CAD`, or a more specific process such as `sheet-metal`, `CNC-machined`, `laser-cut`, `welded tube`, `injection-molded`, `cast`, or `hybrid purchased-hardware` only when the brief justifies that more specific posture.
   Choose the posture that is honest for the artifact rather than the easiest CAD surface to make.

5. Pick qualitative levers, not raw numbers.
   Start from:
   - duty level: `light-duty`, `general-duty`, `sturdy-duty`
   - scale level: `compact`, `medium`, `large`
   - cost posture: `cheapest`, `balanced`, `performance-first`
   Then translate them into numbers only inside the chosen family.

6. Close only the critical gaps.
   Ask at most 3 grouped questions.
   Use choice menus, not blank forms.
   Good grouped questions:
   - for a gripper: object style, opening band, cost/performance posture
   - for a table: use style, span band, load style
   - for an enclosure: electronics size, ruggedness, cooling posture
   - for an underspecified product: manufacture-realistic prototype, production-realistic, printable, or visual-CAD posture

7. Convert choices into an engineering brief.
   The brief must include:
   - target artifact
   - artifact family
   - specific operating story
   - production reason
   - test setting
   - what generic output would miss
   - output posture, defaulting to manufacture-realistic prototype unless changed by the user
   - intended objects / loads
   - rough size envelope
   - motion style and degrees of freedom
   - manufacturing/process stack and material defaults
   - purchased-part boundary
   - validation standard
   - variant-selection policy when multiple versions of the same object are requested
   - file-organization policy: if the implementation needs multiple files, the runnable ForgeCAD entry point must be `main.forge.js`; renderable parts/sub-assemblies belong in neighboring `.forge.js` files, while plain `.js` files are only for pure helpers/constants
   - explicit uncertainty policy

8. Emit one master prompt.
   Start from `references/master-prompt.md`.
   Fill in the placeholders using the chosen profile and assumptions.
   If the requested model is complex enough to split across files, include an explicit instruction that the project must use `main.forge.js` as the runnable entry point.
   Return the finished prompt, not notes about the prompt.

9. If implementation continues immediately, hand off to `forgecad`.
   For moving mechanisms, load:
   - `skills/forgecad/SKILL.md`
   - `docs/permanent/generated/assembly.md`
   - `docs/permanent/generated/output.md`
   - `docs/permanent/guides/joint-design.md`
   - `docs/permanent/CLI.md`

## Question Style

Keep questions short and maker-friendly.

Good:

- "Which target feels closest: a light desk demo, a useful hobby tool, or a sturdier bench mechanism?"
- "Will it mostly handle soft/light things, mixed household parts, or rigid/tool-like objects?"
- "Should we bias for cheapest parts, balanced practicality, or stronger hardware?"
- "Should this be a manufacture-realistic prototype, production-realistic, printable, or just a visual CAD study?"
- "Is this more like a gripper, a fixture, an enclosure, a chassis, or furniture?"
- "Will the table mostly hold decor, laptop-and-books, or workshop abuse?"

Bad:

- "What payload mass?"
- "What torque budget?"
- "What joint backlash can you tolerate?"

## Default Behavior

If the user says "I don't know" or gives only a broad goal:

- infer the nearest artifact family from the request
- invent a specific operating story for the artifact
- infer the manufacturing/process stack from the artifact family and operating story
- default the output posture to `manufacture-realistic prototype`
- choose `general-duty`
- choose `medium`
- choose `balanced`
- use the family-specific starter assumptions from `references/default-profiles.md`
- do not copy assumptions from one family into another
- do not make the artifact printable unless the user asked for it or the chosen process stack includes printed parts

Examples:

- gripper request -> use gripper-specific object mass, opening, and actuator assumptions, plus a named robotics or automation prototype-review story
- table request -> use table-specific span, load, and leg/stiffness assumptions
- enclosure request -> use enclosure-specific board size, wall thickness, and thermal assumptions

Do not promise impossible honesty.
If the request pushes beyond the chosen profile, keep going but downgrade the final claim from "build-ready" to "best-effort build candidate".

## Output Contract

When using this skill, your answer should usually contain:

1. a short interpretation of the user's request
2. the chosen artifact family
3. the specific operating story
4. a compact options menu if truly needed
5. the chosen assumption bundle
6. the single filled ForgeCAD master prompt

Do not bury the prompt beneath long theory.

---

## File: `references/default-profiles.md`

# Scoped Intake Profiles

This file does not define universal defaults.

It defines a safer process:

1. classify the artifact family
2. choose a manufacturing/process posture
3. choose qualitative levers
4. translate those levers into starter assumptions only inside that family

These starter assumptions are not "truth".
They are temporary engineering anchors used only when the user has not provided exact numbers.

## Universal Levers

Use these across families before translating into numbers:

- manufacturing posture: default to `manufacture-realistic prototype` unless specified; common override values are `production-realistic`, `prototype-realistic`, `printable`, and `visual-CAD`
- duty level: `light-duty`, `general-duty`, `sturdy-duty`
- scale level: `compact`, `medium`, `large`
- cost posture: `cheapest`, `balanced`, `performance-first`

Never take a number from one family and silently reuse it for another.

## Manufacturing Selection Rule

Do not use 3D printing as the universal default.
Choose the process stack from the artifact family, load path, scale, safety expectations, material properties, quantity/iteration needs, and operating story.
Only use print defaults when the user explicitly requested printing or the selected process stack includes printed parts.

The default posture is `manufacture-realistic prototype`: a credible prototype build candidate with real materials, real purchased parts, plausible fabrication routes, serviceable interfaces, and validation checks. It should be manufacturable enough for a prototype review, but it should not claim final production tooling, certification, or release readiness unless the user asks for that stronger bar.

Examples:

- rideable vehicles: metal/composite/wood structure, urethane/rubber wheels, bearings, brakes, fasteners, and purchased safety-critical hardware
- furniture: wood, sheet goods, tube, metal brackets, conventional joinery, and printed parts only for honest secondary details
- enclosures: injection molding, sheet metal, CNC, thermoforming, or printing depending on quantity, ruggedness, and serviceability
- fixtures: machined, laser-cut, welded, printed, or hybrid with standard clamps/pins/fasteners
- small mechanisms: hybrid printed/machined/sheet parts plus purchased pivots, shafts, bearings, springs, fasteners, motors, and electronics where appropriate

## Family: Grippers And Small Mechanisms

Use for:

- robot grippers
- articulated fingers
- small pick-and-place tools
- small manipulators and end-effectors

### Family Questions

- What feels closest: delicate handling, mixed general handling, or rigid/tool-like handling?
- Is the size closer to small desk objects, everyday household objects, or larger workshop objects?
- Should we bias for cheapest, balanced, or performance-first hardware?

### Translation To Starter Assumptions

`light-duty`

- object mass band: roughly `0.05-0.15 kg`
- opening / feature band: roughly `30-60 mm`
- hardware posture: small servo / compact mechanism / lightweight prototype members; printed, machined, or laser-cut depending on the selected manufacturing posture

`general-duty`

- object mass band: roughly `0.20-0.50 kg`
- opening / feature band: roughly `60-120 mm`
- hardware posture: standard metal-gear servo or NEMA17-class solution, M3/M4 fasteners, inserts, pins, bearings where honest

`sturdy-duty`

- object mass band: roughly `0.50-1.00 kg`
- opening / feature band: roughly `100-180 mm`
- hardware posture: stronger shafts, bearings, more metal reinforcement, likely downgrade final certainty unless the mechanism remains simple

### Subtype: Dexterous Finger / Humanoid Hand Module

Use when the request is for a robot finger, dexterous finger, anthropomorphic finger, tendon finger, prosthetic-style finger, or one module of a robot hand.

Default specific operating story shape:

- invented organization: a named ambitious robotics company or advanced hardware group, not a famous real company
- named program: a humanoid hand, embodied AI manipulation, warehouse-pilot, or end-effector program with real mission pressure
- named revision: a concrete module/revision like `F2 index finger`, `DIP/PIP tendon mule`, or `Rev-C palm-mount finger`
- review moment: go/no-go gate, customer-demo readiness review, actuator-routing review, palm-integration check, or grasp-demo gate
- test setting: named curl-cycle rig, palm mule, contact-pad wear fixture, or instrumented grasp bench
- stakes: first-customer pilot, investor demo, field-trial gate, reliability target, or deployment schedule

Good story seed:

- "Helix Handworks is preparing the F2 index-finger module for its DEX-07 warehouse-pilot go/no-go review. The finger must bolt into Palm Mule V3, route a Bowden tendon through the MCP base without rubbing the housing wall, survive a 1,000-cycle curl test on Rig-3, and expose pivot/wear surfaces before the customer demo cell is frozen."

Starter assumptions for `general-duty` / `medium` / `balanced`:

- envelope: adult index-finger scale, roughly `95-115 mm` long, `18-24 mm` wide, `16-24 mm` thick
- joints: MCP/PIP/DIP-like flexion chain with hard stops and clearance checks through curl
- motion target: MCP roughly `0-75 deg`, PIP roughly `0-90 deg`, DIP roughly `0-65 deg`
- actuation: tendon or Bowden cable flexion with passive elastic/spring return unless the user asks for independent motors
- hardware posture: metal pivot pins or shoulder screws, bushings or bearing surfaces, serviceable tendon anchor, replaceable fingertip/contact pad, palm mounting datum
- validation: full-range curl sweep, tendon rub check, pivot wear check, fingertip contact load path, base-mount stiffness, and assembly access

### Manufacturing Defaults When Printing Is Selected

- structural printed parts: PETG by default
- prototypes / fit checks: PLA allowed
- sliding or rotating interfaces: prefer pins, bushings, bearings, or sacrificial wear parts over raw printed rubbing

## Family: Fixtures, Jigs, And Holders

Use for:

- drill guides
- work-holding fixtures
- camera / sensor mounts
- brackets and repeatable positioning tools

### Family Questions

- Is it mostly for positioning, clamping, or repeated handling?
- Is the scale closer to palm-size, hand-size, or bench-size?
- Is speed of build more important than stiffness, or vice versa?

### Translation To Starter Assumptions

`light-duty`

- small hand-tool or desktop fixture
- low clamp loads
- simple printed, machined, laser-cut, or bent-sheet geometry acceptable depending on the selected process

`general-duty`

- hand-size or bench-size fixture
- moderate clamp loads
- inserts, metal pins, or off-the-shelf fasteners where wear concentrates

`sturdy-duty`

- repeated clamping or alignment duty
- workshop abuse expected
- printed geometry, if used, should be backed by thicker sections, inserts, metal rails, or replaceable wear faces

## Family: Enclosures And Electronics Housings

Use for:

- PCB enclosures
- instrument cases
- sensor housings
- covers and protective shells

### Family Questions

- Is this for one PCB, a hand-sized electronics stack, or a larger bench device?
- Does it need passive venting, fan support, or mostly dust protection?
- Is aesthetics, serviceability, or ruggedness the main goal?

### Translation To Starter Assumptions

`light-duty`

- single small board or simple module
- easier snap/screw access acceptable
- lighter wall sections

`general-duty`

- multiple boards or connectors
- removable lid / inserts / real fastening
- enough clearance for wiring and service loops

`sturdy-duty`

- rugged transport or workshop environment
- thicker walls, boss reinforcement, connector strain protection, better sealing strategy

## Family: Furniture And Load-Bearing Structures

Use for:

- tables
- shelves
- stands
- stools
- structural frames

### Important Caution

Human-bearing or safety-critical structures should usually end as `BEST-EFFORT BUILD CANDIDATE` unless there is real structural reasoning, conservative geometry, and honest material limits.

### Family Questions

- Is this mostly decorative / light household / real workshop use?
- Is the span closer to side-table size, desk size, or bench size?
- Will it ever support a person, concentrated heavy tools, or repeated impact?

### Translation To Starter Assumptions

`light-duty`

- decor, lamps, light household items
- smaller spans
- simpler joints acceptable

`general-duty`

- laptop, books, normal desk use
- medium spans
- real attention to leg stiffness, racking resistance, and joint reinforcement

`sturdy-duty`

- workshop surfaces, heavier distributed loads, or concentrated tools
- larger spans or more demanding rigidity
- stronger joinery, thicker members, more triangulation / bracing, and often conventional structural reinforcement

### Manufacturing Defaults

- do not assume "fully 3D printed" is the right answer
- for structural furniture, consider wood, sheet goods, tube, or metal hardware as first-class BOM items
- use printed parts mainly where they are honest: brackets, templates, feet, cable features, corner blocks, custom connectors

## Family: Chassis And Mobile Robot Structures

Use for:

- wheeled robot chassis
- tracked platforms
- sensor carts
- mobile bases

Do not use this family for human-ridden scooters, bicycles, skateboards, mobility devices, or other rideable products. Use `Human Vehicles And Rideable Product Forms` instead.

### Family Questions

- Indoor smooth floor, mixed home floor, or rough workshop floor?
- Tiny robot, small rolling base, or larger mobile platform?
- Is runtime / price / ruggedness the main priority?

### Translation To Starter Assumptions

`light-duty`

- small indoor base
- low speeds
- simpler drivetrain packaging

`general-duty`

- home or workshop mixed surfaces
- modest payloads
- stronger wheel mounts, motor mounts, and battery restraint

`sturdy-duty`

- rougher surfaces or heavier payloads
- more metal shafts / bearings / real fastening
- increased skepticism about fully printed load paths

## Family: Human Vehicles And Rideable Product Forms

Use for:

- kick scooters
- bicycles and balance bikes
- skateboards and longboards
- carts, strollers, dollies, or mobility-adjacent platforms with human interaction
- any artifact where a person stands on, rides, steers, brakes, or leans on the structure

### Important Caution

Human-ridden or safety-critical vehicles should usually end as `BEST-EFFORT BUILD CANDIDATE` unless there is real structural analysis, conservative geometry, braking/steering reasoning, and explicit test limitations.
Do not present a rider-rated design as safe without validation.
Do not make rideable load paths printed by default.

### Family Questions

- Is this a visual/product CAD study, a manufacture-realistic prototype build candidate, or a specifically printable toy/model?
- Is it for child-scale, adult-scale, display-scale, or cargo/utility scale?
- Does it need steering, braking, folding, suspension, or only static product form?

### Translation To Starter Assumptions

`light-duty`

- display-scale, toy-scale, or non-ridden study
- simplified load paths acceptable if clearly labeled
- printed or lightweight prototype parts may be acceptable for cosmetic/non-critical features

`general-duty`

- adult product form or manufacture-realistic prototype scooter/bike/cart architecture
- aluminum or steel tube/frame members, machined or cast fork/dropout-like features, wood/composite/aluminum deck where appropriate
- urethane/rubber wheels, real bearings, axles, fasteners, spacers, grip tape, grips, and purchased brake/steering hardware where appropriate

`sturdy-duty`

- repeated riding, rougher surfaces, heavier loads, cargo, impact, or braking/steering duty
- conservative metal/composite structure, triangulation, large bearing interfaces, replaceable wear parts, and no printed primary load paths unless the user explicitly requested a printed demonstration model
- downgrade final certainty unless structural checks and real-world test plan are explicit

### Manufacturing Defaults

- primary load paths: aluminum/steel tube, plate, extrusion, wood/composite deck, or equivalent conventional structural members
- rolling interfaces: purchased wheels, bearings, axles, spacers, and bushings
- contact/wear interfaces: urethane/rubber, grip tape, replaceable pads, bushings, bearings
- printed parts: cosmetic covers, cable guides, templates, fit-check models, brackets for low-load accessories, or explicit printable-model requests

## If No Family Fits

Do not force a nearby family just because it is available.

Instead:

- say the nearest family
- explain the mismatch
- create a custom intake brief with 2-4 artifact-specific levers

## When Printing Is Selected

Only use when the artifact actually includes printed parts:

- nozzle: `0.4 mm`
- layer height: `0.2 mm`
- threaded service joints: use heat-set inserts where repeated opening is expected
- wear-heavy interfaces: do not trust raw printed friction unless the task is intentionally low-duty

---

## File: `references/master-prompt.md`

# ForgeCAD Manufacture-Realistic Prototype Master Prompt

Fill the placeholders and return the finished prompt as one block.

```text
You are producing a ForgeCAD manufacture-realistic prototype package, not a concept sketch.

Treat this as a serious product-team prototype assignment.
The goal is to produce a credible internal engineering package for a real prototype build candidate, not a generic maker example.
Use the specific operating story below to drive engineering choices; do not flatten it into a vague domain label.

Target artifact:
- artifact: {artifact}
- request summary: {request_summary}
- normalized interpretation: {normalized_interpretation}

Specific operating story:
- organization / team: {organization_team}
- project / prototype revision: {project_revision}
- milestone / review moment: {milestone_review}
- domain context: {domain_context}
- production reason: {production_reason}
- test setting: {test_setting}
- generic-output failure mode to avoid: {generic_failure_mode}
- benchmark class / public comparison anchor, if useful: {benchmark_class}

Chosen intake classification:
- output posture: manufacture-realistic prototype unless the user explicitly selected another posture
- artifact family: {artifact_family}
- duty level: {duty_level}
- scale level: {scale_level}
- cost posture: {cost_posture}
- job style: {job_style}
- manufacturing / process stack: {manufacturing_process_stack}
- budget posture: {budget_posture}

Working assumptions chosen to close missing inputs:
- these assumptions are provisional and family-scoped
- they apply to `{artifact_family}`, not as universal defaults
- {assumption_1}
- {assumption_2}
- {assumption_3}
- {assumption_4}

Hard constraints:
- use ForgeCAD
- if the mechanism has moving parts, use a real `assembly()` from iteration 1
- define real joints, limits, axes, and intended operating ranges
- choose manufacturing/processes that fit the artifact, load path, scale, safety expectations, and operating story
- default to manufacture-realistic prototype: real prototype materials, fabrication cues, purchased parts, assembly logic, serviceability, and validation without pretending to be production-certified or release-ready
- do not assume FDM, 3D printing, or "printable" unless the user explicitly asked for it or the chosen process stack includes printed parts
- include realistic process-appropriate clearances and mechanically honest interfaces
- include manufactured, printed, and purchased parts only where each is an honest choice
- include a BOM that is concrete enough to buy and assemble from
- prefer metal shafts, bearings, fasteners, inserts, pins, tubes, sheet goods, castings, molded parts, machined parts, or composite/wood members where they are the honest choice
- model the physical artifact, not an educational diagram
- do not add explanatory text labels, floating callouts, arrows, legends, coordinate axes, section-title plaques, or part-name slabs to CAD geometry unless the user explicitly asks for a teaching or presentation view
- include product markings only when they would exist on the real artifact, such as serial plates, connector labels, gauge ticks, keyboard legends, alignment marks, scale marks, warning marks, service arrows, branding, or molded icons
- keep real markings sparse, process-appropriate, and light enough that text geometry does not dominate runtime or exact export behavior
- do not hide uncertainty; choose defaults and continue
- do not claim the user works for a named company unless the user explicitly said so
- if an organization/team name appears only in the operating story, treat it as a design scenario, not as a factual claim about the user
- do not clone proprietary named products; use public domain patterns and first-principles engineering to create an original design

Acceptable final states:
1. `BUILD-READY`
2. `BEST-EFFORT BUILD CANDIDATE`

`BUILD-READY` means the output is specific enough that a competent builder could start fabricating, machining, printing selected printed parts, buying parts, assembling, and testing the prototype immediately without inventing missing details.

`BEST-EFFORT BUILD CANDIDATE` means you still provide the strongest concrete design possible, but you explicitly name the smallest unavoidable validation loop that remains.

Non-negotiable rules:
- Do not answer with a high-level concept, vision, or wishlist.
- Do not produce a generic category solution that could have been written without the professional context.
- Do not use placeholders like "appropriate motor", "standard hardware", or "adjust as needed".
- If a number is missing, choose a defensible value, state it, and continue.
- Prefer a complete best-effort design over an incomplete discussion.
- If the user's wording is physically confused, normalize it and proceed.
- Do not import numeric assumptions from unrelated artifact families.
- Do not ask follow-up questions unless the architecture would materially change and no safe assumption bundle exists.
- Do not make the CAD understandable by labeling every part; make the part boundaries, hardware, interfaces, and materials physically legible.

Required outputs:

0. Specific operating story and anti-generic bar
- State the organization/team, project revision, milestone, and test setting you are designing for.
- Name the generic failure mode you are avoiding.
- Identify the domain-specific details that must appear for the design to be credible.

1. Problem normalization
- Restate exactly what is being built, what it should do, and what "done" means in physical terms.

2. Assumption bundle
- State all chosen assumptions with units and why they are reasonable for this request.

3. Architecture choice
- Pick one mechanism architecture.
- Briefly mention the main rejected alternatives and why they lost.

4. Detailed mechanical design
- Give exact dimensions or dimension formulas for the major parts.
- Define subassemblies, interfaces, motion ranges, stops, and load paths.
- If this is a gripper or articulated mechanism, specify finger/link/jaw geometry and all joints concretely.

5. Actuation and transmission
- Specify the actuator class, approximate required torque/force, transmission approach, and why they fit the chosen profile.

6. Manufacturing package
- For each critical part: material, manufacturing process, prototype setup/orientation/tooling/finish assumptions, serviceability notes, and features sensitive to process accuracy.
- If the selected process includes printed parts, include print orientation, likely support strategy, and print-sensitive features for those parts.

7. Bill of materials
- Include manufactured parts, printed parts if any, and purchased parts.
- For each line item give: name, exact spec or part class, quantity, why needed, and important dimensions or ratings.

8. Assembly package
- Provide the assembly order, jointing method, insert/bearing/pin usage, fastening notes, and likely failure-prone assembly steps.

9. Validation package
- Check motion range, likely collisions, stiffness risks, load risks, manufacturability, tolerance-stack risks, and wear points.
- Check printability only for parts whose selected process is printing.
- If moving parts are present, describe how the design should be checked through its operating range rather than only at rest pose.

10. ForgeCAD implementation package
- Produce the actual ForgeCAD file structure you would write.
- If you are operating in a writable workspace, write the `.forge.js` files instead of stopping at prose.
- Use `bom()` / assembly metadata where appropriate.
- Make the design compatible with `forgecad run`.
- If relevant, make it exportable in process-appropriate formats such as STEP, STL, 3MF, DXF, SVG, or report output.

11. Final verdict
- End with exactly one of:
  - `BUILD-READY`
  - `BEST-EFFORT BUILD CANDIDATE`

ForgeCAD-specific quality bar:
- Any moving mechanism must use `assembly()` from the start, not manual transform hacks.
- Use ForgeCAD's joint/collision workflow mentally and structurally: joints, limits, sweeps, collisions, and BOM are part of the deliverable.
- Do not claim a hinge or sliding joint works unless cavity / clearance logic is physically honest.
- A pretty static pose is not success.
```
