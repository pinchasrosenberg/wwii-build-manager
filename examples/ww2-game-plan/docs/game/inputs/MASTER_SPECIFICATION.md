# MASTER SPECIFICATION FOR CODEX

## WWII Living Historical Simulation + Deliver-Compatible Capability Economy

### תפקידך

אתה ה־**Lead Architect / Orchestrator** של מערכת חדשה שנבנית מעל WWII Atlas ו־Deliver Architecture.

אינך אמור לבנות לבד את כל התחומים.

התפקיד שלך הוא:

1. להבין את הארכיטקטורה הקיימת.
2. לתכנן ארכיטקטורת משחק וסימולציה מודולרית.
3. לחלק את המערכת ל־capabilities קטנות וברורות.
4. ליצור context boundaries.
5. להאציל משימות לסוכנים ממוקדים.
6. לתת לכל סוכן רק את הקונטקסט שהוא צריך.
7. לחבר את התוצרים דרך contracts יציבים.
8. להכין את המערכת כך שבעתיד אותם agent roles יוכלו להפוך ל־Delivers אמיתיים.
9. לאפשר כבר עכשיו Episode Generation דרך adapter שמדמה Deliver Runtime.
10. לבצע מחקר עדכני לפני קיבוע stack טכנולוגי.

---

# 1. החזון

המוצר הוא פלטפורמת סימולציה היסטורית חיה של מלחמת העולם השנייה.

לא מדובר רק במשחק עם "שלבים".

Episode יכולה להתחיל כ:

```text
20 minute tactical experience
```

ובהמשך להשתפר ל:

```text
hours
days
weeks
months
```

עם:

```text
historical terrain
historical weather
formations
individual soldiers
vehicles
commanders
logistics
communications
AI
LLM NPCs
```

רמת הפירוט עולה בהדרגה ככל שה־Episode וה־Delivers שלה צוברים capital.

---

# 2. עקרון עליון: Progressive Fidelity

גרסה ראשונה של Episode אינה חייבת להיות מדויקת בכל פרט.

אבל היא חייבת:

```text
1. לא לסתור מידע היסטורי חזק.
2. לשמור את מהלך הקרב המרכזי ככל שהוא ידוע.
3. לסמן במפורש reconstruction / uncertainty.
```

בהמשך, Deliver עשיר יותר יכול להשקיע ב:

```text
maps
aerial photographs
historical photographs
war diaries
after-action reports
technical manuals
weather records
terrain reconstruction
3D modelling
animations
physics
voice
LLM NPCs
```

ולשפר את אותה Episode ללא בנייה מחדש.

---

# 3. Historical Truth ≠ Reconstruction ≠ Gameplay

שלוש שכבות אלו חייבות להישאר נפרדות:

```text
HistoricalTruth
Reconstruction
GameplaySimulation
```

## HistoricalTruth

מידע מבוסס evidence.

## Reconstruction

השלמה שהמערכת מבצעת כאשר יש פערים.

## GameplaySimulation

התוצאה הדינמית בזמן משחק.

לעולם אין להפוך reconstruction לעובדה רק משום שהוא נראה סביר.

---

# 4. דוגמת 10,000 החיילים

נניח שמספר מקורות חזקים מצביעים על:

```text
approximately 10,000 soldiers
```

אך היחידות המזוהות במידע הקיים מסבירות רק:

```text
8,400
```

אין צורך להציג רק 8,400.

אפשר להשלים:

```text
1,600 reconstructed personnel
```

בהתבסס על:

```text
organizational structure
known nearby formations
normal unit strength
doctrine
equipment
time
geography
```

אבל:

```text
total_strength = historically supported
exact_unit_assignment = reconstructed
```

והמשתמש יכול לראות זאת בלחיצה.

---

# 5. Historical Accuracy Inspection

כל entity משמעותי צריך לתמוך בבדיקת accuracy.

לדוגמה:

```text
Tank #371

Vehicle type:
VERIFIED

Variant:
HIGH CONFIDENCE

Presence in battle:
VERIFIED

Exact position at 14:10:
RECONSTRUCTED

Camouflage:
PROBABLE

Crew identity:
UNKNOWN
```

המערכת צריכה לתמוך לפחות ב:

```text
DOCUMENTED
VERIFIED
HIGH_CONFIDENCE
PROBABLE
RECONSTRUCTED
SYNTHETIC
UNKNOWN
DISPUTED
```

---

# 6. Battle Macro Fidelity

כל Episode מתחילה מ:

```text
HistoricalBattleSkeleton
```

לפני שמתחילים simulation.

הוא כולל, ככל שידוע:

```text
battle start
major formations
approximate force strengths
major axes
defensive lines
major attacks
counterattacks
breakthroughs
retreats
important locations
important captures
timing windows
command structure
outcome
```

הסימולציה חופשית בעיקר **בין העוגנים**.

---

# 7. Historical Envelope

לא כל אירוע דורש timestamp מומצא.

אם ידוע שעיירה נכבשה בין 16:00–18:00:

```yaml
capture:
  earliest: 16:00
  preferred: 17:00
  latest: 18:00
```

זה עדיף על המצאת:

```text
17:13:42
```

Historical mode צריך לשמור את הסימולציה בתוך historical envelope סביר.

---

# 8. Player Agency

השחקן יכול:

```text
survive
die
save another soldier
destroy a vehicle
miss an objective
choose another path
be promoted
be injured
interact with people
```

אבל פעולה מקומית אינה אמורה אוטומטית לשכתב את כל ההיסטוריה.

יש להפריד:

```text
LocalAgency
MacroHistoricalTrajectory
```

Alternate-history mode יכול בעתיד להיות mode נפרד.

---

# 9. Terrain הוא Historical Asset

המפה אינה backdrop.

יש לשחזר ככל האפשר:

```text
elevation
slopes
rivers
streams
ditches
roads
road widths
railways
bridges
forests
hedgerows
fields
walls
buildings
villages
trenches
bunkers
beaches
coastlines
ground conditions
```

לפי התקופה המדויקת.

---

# 10. אין להעתיק את העולם המודרני

יש להפריד:

```text
ModernGeography
HistoricalGeography
```

כביש שנבנה אחרי המלחמה לא יופיע ב־1944.

יער שנעלם מאז יכול להופיע אם evidence תומך בכך.

עיר שהופצצה משתנה לפי תאריך.

לכן environment הוא:

```text
Place + Time
```

ולא רק Place.

---

# 11. Historical Terrain Pipeline

תכנן pipeline המסוגל בעתיד לשלב:

```text
DEM / elevation
historical military maps
topographic maps
wartime aerial imagery
ground photographs
land-use maps
road maps
railway maps
building records
battle maps
written descriptions
```

ל־:

```text
HistoricalTerrainSnapshot
```

כל layer חייב לשמור provenance.

---

# 12. Weather

Weather צריך להיות historical state ולא cosmetic effect.

תמיכה אפשרית ב:

```text
temperature
rain
snow
wind
clouds
visibility
fog
ground wetness
sea state
sun position
sunrise/sunset
moonlight
```

Weather צריך להשפיע על simulation.

---

# 13. Equipment Historical Fidelity

אין "Tiger" אחד.

יש:

```text
family
model
variant
production period
production block
field modifications
theater availability
unit availability
date availability
```

וה־visual asset חייב להתאים ל־simulation asset.

אסור:

```text
simulation = M4A1
visual = M4A3
```

רק משום ששניהם Sherman.

---

# 14. Historical Lego

המערכת אינה בונה כל Episode מאפס.

היא בונה Lego reusable.

## Primitive examples

```text
Human
Engine
Transmission
Wheel
Track
ArmorPlate
Turret
Gun
Projectile
Optic
Radio
FuelTank
Building
Wall
Bridge
Tree
Road
Trench
```

## Capability examples

```text
HumanMovement
TrackedVehicleMovement
Ballistics
ArmorPenetration
Vision
Hearing
Suppression
Morale
Injury
Fire
Navigation
RadioCommunication
Command
Logistics
Repair
```

## Historical assembly

לדוגמה:

```text
Panzer IV Ausf. H
```

הוא composition של capabilities ו־historical data.

---

# 15. Data, לא hard-coded gameplay

אל תכתוב:

```text
Tiger.damage = 100
Sherman.health = 500
```

כאשר ניתן למדל:

```text
weapon
projectile
velocity
impact angle
armor thickness
armor angle
material
internal components
crew
```

ההתנהגות צריכה לצמוח מה־components ככל האפשר.

---

# 16. Episode הוא Data

Episode חדשה אינה אמורה לדרוש module חדש.

היא צריכה להיטען דרך:

```text
EpisodeSpec
```

הכולל לפחות:

```text
identity
time window
location
terrain snapshot
weather
historical battle skeleton
formations
strength estimates
equipment
player role
initial state
objectives
events
historical anchors
available capabilities
quality targets
budgets
accuracy manifest
```

---

# 17. Game Runtime אינו תלוי ב־Deliver Runtime

צור abstraction:

```text
GameCapabilityProvider
```

לפחות:

```text
LocalCapabilityProvider
DeliverCapabilityProvider
```

בשלב הראשון:

```text
LocalCapabilityProvider
```

מאפשר בנייה מלאה ללא Deliver Runtime.

בהמשך מחליפים provider בלבד.

אסור למנוע המשחק לייבא internals של Deliver Runtime.

---

# 18. Deliver Compatibility מהיום הראשון

אפילו לפני שמערכת ה־Delivers שלמה:

כל בקשת capability צריכה לעבור contract שדומה ל־Deliver העתידי.

לדוגמה:

```text
CapabilityRequest
```

עם:

```text
request_id
episode_id
capability_id
task
work_context_refs
historical_context_refs
budget
quality_target
accuracy_target
deadline
```

ומחזיר:

```text
CapabilityResult
```

עם:

```text
status
artifacts
evidence
provenance
quality
accuracy
cost
new_context
new_work
capability_gaps
```

---

# 19. כלכלת Deliver

Deliver הוא בעל capital.

הוא משלם עבור:

```text
listening
research
model usage
storage
rendering
asset construction
verification
simulation
tools
```

הוא יכול להשקיע רווחים ביכולות עתידיות.

---

# 20. Quote-before-execution

כל paid action מקבלת מחיר לפני execution.

החוזה:

```text
Evaluate
↓
Quote
↓
Reserve
↓
Accept
↓
Execute
↓
ActualCost
↓
Settlement
```

לאחר Accept:

```text
QuotedPrice = immutable
```

Deliver שומר surplus וסופג overrun.

---

# 21. PricingEvaluate

Pricing evaluator צריך להעריך:

```text
expected_cost
cost_uncertainty
P50
P75
P95
risk_reserve

expected_demand
reuse_value
future_revenue
historical_value
player_visibility
quality_gain
accuracy_gain
strategic_value
```

Deliver רשאי:

```text
raise price
discount
subsidize
take temporary loss
```

כאשר expected lifetime return מצדיק זאת.

---

# 22. Fidelity היא השקעה כלכלית

אותה Episode יכולה להשתפר:

```text
v0.1
basic historical reconstruction

v0.4
historical terrain maps

v0.8
accurate buildings

v1.2
aerial imagery

v1.5
better vehicle variants

v2.0
unit diaries

v2.5
individual commanders

v3.0
LLM NPCs + voice + persistent memory
```

אין צורך להחליף את Episode.

---

# 23. הבעיה המרכזית של Context

אסור לסוכן לקבל את כל הידע בפרויקט.

זה גורם:

```text
context pollution
higher token cost
wrong assumptions
domain interference
slower work
```

לדוגמה:

```text
Tank Agent
```

אינו צריך לקבל מידע מפורט על:

```text
destroyer hull physics
naval gunnery
submarine sonar
carrier flight deck
```

אלא אם יש dependency ישיר.

---

# 24. Context Architecture

כל Agent Run יקבל ContextPack מורכב מחמש שכבות בלבד:

```text
GlobalInvariantContext
DomainContext
TaskContext
DependencyContext
EvidenceContext
```

## 24.1 GlobalInvariantContext

קטן מאוד.

כל סוכן מקבל אותו.

מכיל רק עקרונות שאסור להפר:

```text
Historical truth separation
Provenance
Progressive fidelity
No hallucinated certainty
Quote-before-execution
Game/Deliver boundary
Reusable capabilities
Tests/contracts
```

לא יותר מהנדרש.

## 24.2 DomainContext

רק התחום שעליו הסוכן עובד.

לדוגמה:

```text
domain = ground.vehicle.tank
```

יקבל:

```text
tank architecture
tracked vehicle physics
armor model
gun integration
relevant equipment schemas
vehicle asset contracts
```

לא naval domain.

## 24.3 TaskContext

המשימה הנוכחית בלבד.

לדוגמה:

```text
Implement Panther Ausf. G historical variant definition.
```

## 24.4 DependencyContext

רק interfaces שהמשימה תלויה בהם.

לדוגמה Tank Agent עשוי לקבל:

```text
Projectile API
Engine API
Crew API
Asset API
Physics API
```

אבל לא את implementation המלא של כל התחומים.

## 24.5 EvidenceContext

רק המקורות ההיסטוריים הרלוונטיים לישות או לבעיה.

לדוגמה:

```text
Panther technical manual
unit report
period photograph
drawing
production change record
```

---

# 25. ContextManifest

לכל Agent Run צור:

```yaml
context_manifest:

  task_id: ...

  role: tank_variant_builder

  domain:
    - ground.vehicle.tank

  mandatory_global:
    - historical_truth_contract
    - provenance_contract
    - capability_contract

  task_context:
    - ...

  dependencies:
    - ballistics.interface
    - tracked_vehicle.interface
    - asset.interface

  evidence:
    - source_...
    - image_...
    - map_...

  writable_scope:
    - capabilities/ground/tanks/panther/**

  readable_scope:
    - capabilities/shared/ballistics/**
    - schemas/**

  excluded_domains:
    - naval
    - submarine
    - aviation

  expected_output:
    - variant definition
    - validation tests
    - provenance manifest
```

---

# 26. Least Context Principle

ברירת המחדל:

```text
DENY CONTEXT
```

לא:

```text
SEND EVERYTHING
```

Context נוסף נטען רק כאשר:

```text
required by task
required by dependency
required to resolve contradiction
required by validator
```

---

# 27. Progressive Context Disclosure

סוכן רשאי לבקש:

```text
ContextExpansionRequest
```

לדוגמה:

```yaml
need:
  domain: ballistics
  object: kwk42
  reason: projectile compatibility validation
```

ה־orchestrator מחליט אם להוסיף.

אין להעביר מראש encyclopedia שלמה.

---

# 28. Context Graph

תכנן metadata graph שבו:

```text
Capability
AgentRole
Document
Schema
Evidence
Source
Asset
Domain
```

מקושרים באמצעות:

```text
REQUIRES
IMPLEMENTS
REFERENCES
EVIDENCE_FOR
BELONGS_TO_DOMAIN
USES_CAPABILITY
VALIDATES
```

Context Builder יכול להשתמש בגרף כדי להרכיב ContextPack.

בעתיד זו יכולה להפוך ישירות למערכת listener/context של Delivers.

---

# 29. Agent Taxonomy

אל תיצור agent לכל file.

צור roles המבוססים על capabilities.

Baseline מוצע:

```text
/root
├── architecture
├── stack-research
├── historical-reconstruction
├── terrain
├── weather
├── ground-vehicles
├── infantry
├── weapons-ballistics
├── aviation
├── naval
├── buildings-environment
├── simulation-runtime
├── ai-navigation
├── asset-pipeline
├── episode-builder
├── economy-deliver
├── historical-validator
└── integration-review
```

אין חובה ליצור את כולם מיד.

Root מפעיל רק את מי שנדרש.

---

# 30. Agent Hierarchy

אפשר לפרק domain נוסף.

לדוגמה:

```text
ground-vehicles
├── tank-model
├── tracked-physics
├── vehicle-damage
└── vehicle-assets
```

אבל רק אם העבודה באמת מצדיקה subagent.

אל תיצור orchestration overhead ללא צורך.

---

# 31. Shared Kernel

כל התחומים תלויים ב־Shared Kernel מצומצם:

```text
IDs
units of measurement
time
coordinates
provenance
confidence
versioning
capability contracts
serialization
event contracts
budget/quote contracts
```

Shared Kernel צריך להיות קטן ויציב מאוד.

---

# 32. Ownership

לכל capability יש owner domain ברור.

לדוגמה:

```text
ArmorPenetration
owner = weapons-ballistics

TrackedMovement
owner = ground-vehicles

HistoricalWeather
owner = weather
```

Agent אחר אינו משנה implementation ישירות.

אם נדרש שינוי:

```text
CapabilityChangeRequest
```

נשלח ל־owner.

---

# 33. Agents לא עורכים אותם קבצים במקביל

אם שני agents צריכים לערוך אותו bounded context:

Root חייב:

```text
serialize work
```

או:

```text
split ownership
```

אין merge באמצעות תקווה.

---

# 34. Deliver Future Mapping

כל AgentRole שנבנה היום צריך להיות candidate להפוך בעתיד ל:

```text
DeliverCapability
```

לכן שמור לכל role:

```text
input schema
output schema
context requirements
tools
cost profile
quality metrics
evidence policy
failure modes
dependencies
```

---

# 35. Domain Skills

בנה skill/router קטן לכל domain.

לדוגמה:

```text
skills/tank/README.md
```

צריך להיות קצר.

הוא אומר:

```text
Use this skill only for tracked armored vehicle
definitions, simulation, validation and assets.
```

ומתוכו הפניות לפי הצורך ל:

```text
physics.md
historical-data.md
assets.md
validation.md
```

אל תעמיס את הכל במסמך root.

---

# 36. AGENTS.md Root

Root AGENTS.md צריך להכיל רק:

```text
architecture boundaries
critical invariants
where domain docs live
testing permissions
how to request context
how to avoid cross-domain changes
```

לא קטלוג מלא של מלחמת העולם השנייה.

---

# 37. Repository Structure

בדוק את הריפו הקיים לפני יצירת מבנה חדש.

יעד קונספטואלי אפשרי:

```text
/docs
  /architecture
  /domains
  /episodes
  /historical
  /economy

/schemas

/capabilities
  /shared
  /human
  /ground
  /air
  /naval
  /environment
  /weapons

/historical-data

/assets

/episodes

/runtime

/deliver-adapter

/tools

/tests
```

אל תשנה מבנה קיים ללא צורך.

---

# 38. Repository Scanner

לפני עבודה משמעותית:

צור תמונת repository באמצעות הכלים המתאימים ביותר הזמינים.

העדף:

```text
LSP / symbol index
Cargo metadata or ecosystem equivalent
dependency graph
tree-sitter where useful
ripgrep
test discovery
schema discovery
```

אל תקרא באופן עיוור כל file.

צור:

```text
REPO_MAP.md
```

רק אם הוא מספק ערך מתמשך.

---

# 39. Context Indexer

תכנן index שאינו רק semantic embedding.

Context candidate צריך להיבחר לפי שילוב של:

```text
domain match
symbol dependency
capability dependency
historical entity
time
geography
source relevance
task type
past usefulness
cost
```

בעתיד ניתן להעביר את אותו scoring ל־Deliver context listeners.

---

# 40. מחקר Stack מחדש

אל תניח ש־Bevy הוא בהכרח הבחירה.

בצע מחקר עדכני על:

```text
Bevy
Godot
Fyrox
modern Rust game frameworks
modern ECS stacks
wgpu-based solutions
serious emerging engines
```

וכן פתרונות רלוונטיים נוספים.

בדוק במיוחד:

```text
headless simulation
ECS
agent-friendly workflows
CLI/tool automation
large worlds
terrain streaming
physics
navigation
animation
VR
multiplayer
determinism
record/replay
asset pipelines
API stability
community
licensing
```

---

# 41. Stack Decision Rule

חדש אינו בהכרח טוב.

בחר stack שממקסם:

```text
simulation suitability
automation
agent usability
long-term maintainability
performance
ecosystem maturity
future extensibility
```

אם אין יתרון משמעותי לחלופה:

```text
use Bevy/Rust baseline
```

---

# 42. Source Acquisition / Historical Scanner

מערכת המחקר צריכה בעתיד להיות מסוגלת לעבד:

```text
PDF
OCR text
maps
photographs
aerial photographs
tables
technical manuals
war diaries
unit histories
archives
```

אבל extraction ו־verification הם capabilities נפרדים.

אל תכריח agent של vehicle physics לבצע OCR של מפה.

---

# 43. Historical Source Roles

פצל למשל:

```text
SourceDiscoveryAgent
DocumentExtractionAgent
MapGeoreferenceAgent
ImageEvidenceAgent
HistoricalClaimAgent
ContradictionAgent
```

כאשר זה משתלם.

כולם מחזירים structured evidence.

---

# 44. Image Evidence

Photographs ו־aerial images יכולים להוכיח:

```text
building appearance
road layout
vegetation
vehicle variant
unit markings
damage
terrain features
```

ה־Agent צריך לשמור:

```text
image_id
date estimate
location estimate
view direction
objects detected/claimed
confidence
source
```

---

# 45. Map Evidence

Historical map ingestion צריך להיות מסוגל לשמור:

```text
map source
date
scale
projection
georeferencing transform
error estimate
features
confidence
```

מיקום ממפה עם ±150m uncertainty אינו "exact".

---

# 46. Accuracy Budget

Episode צריכה להחזיק FidelityPlanner.

עבור כל candidate investment:

```text
cost
expected_accuracy_gain
visual_gain
simulation_gain
historical_importance
player_visibility
reuse_value
```

אפשר לחשב utility.

לדוגמה:

```text
historical_importance
× uncertainty_reduction
× reuse
× player_visibility
÷ cost
```

הנוסחה אינה חייבת להישאר קבועה.

---

# 47. זול אינו אומר שקרי

Episode זולה יכולה להשתמש ב:

```text
generic building
generic vegetation
approximate troop placement
lower-detail terrain
```

אבל לא:

```text
wrong tank
wrong major unit
wrong battle direction
wrong weather when strongly known
```

רמת תקציב משפיעה על detail/confidence, לא על הרשות לסתור evidence.

---

# 48. Expensive Deliver

Deliver יקר יותר יכול לבצע:

```text
more searches
higher-quality sources
cross-source comparison
map georeferencing
image analysis
manual reconstruction logic
better asset generation
better validation
higher-fidelity simulation
```

ולכן להגיע לדיוק גבוה יותר.

הוא אינו רשאי להעלות confidence בלי evidence.

---

# 49. Simulation LOD

כדי לתמוך באפיזודות ארוכות:

```text
Strategic
Operational
Tactical
Local
```

לדוגמה:

```text
far:
division

closer:
battalion/company

near:
platoon/squad

player vicinity:
individual soldier/vehicle
```

יש לשמר aggregate invariants:

```text
personnel
casualties
equipment
ammo
fuel
morale
orders
position uncertainty
```

---

# 50. HistoricalPerson

מפקדים ואנשים אמיתיים צריכים להיות entities.

הפרד:

```text
WorldTruth
PersonKnowledge
PersonBeliefs
PersonOrders
PersonMemory
```

מפקד אינו omniscient.

---

# 51. LLM NPC

LLM NPC הוא capability אופציונלי ויקר.

רמות אפשריות:

```text
scripted
state machine
small generative
full LLM
LLM + retrieval
LLM + persistent memory
LLM + voice
```

Character context מכיל רק מה שהאדם אמור לדעת.

---

# 52. NPC Context Isolation

NPC commander אינו מקבל:

```text
entire Knowledge Graph
```

אלא:

```text
identity
current time
current location
role
historical personality evidence
known orders
messages received
observations
relationships
memory
allowed historical knowledge
```

אותו עקרון ContextPack חל גם עליו.

---

# 53. Episode Generation Pipeline

כבר בשלב הראשון:

```text
EpisodeIntent
↓
HistoricalResearch
↓
HistoricalBattleSkeleton
↓
Terrain/Weather Reconstruction
↓
CapabilityResolution
↓
MissingCapability detection
↓
EpisodePlan
↓
EpisodeSpec
↓
Validation
↓
Headless simulation
↓
Playable build
```

---

# 54. Capability Gap

אם Episode זקוקה לדבר שאינו קיים:

```text
CapabilityGap
```

לדוגמה:

```text
needs: tracked_vehicle_mud_slippage
available: tracked_vehicle_basic
```

המערכת יכולה:

```text
reuse
extend
build
approximate
defer
```

בעתיד זו החלטת Deliver Economy.

---

# 55. Episode #2 Test

האפיזודה השנייה היא מבחן ארכיטקטורה.

מדוד:

```text
reused capabilities
new capabilities
new code
new assets
new research
context loaded
token cost
```

אם כל Episode היא פרויקט חדש:

ה־Lego design נכשל.

---

# 56. Validation Agents

אל תיתן builder לאשר את עצמו בלבד.

השתמש ב־independent validation roles:

```text
HistoricalValidator
ArchitectureValidator
SimulationValidator
ProvenanceValidator
IntegrationValidator
```

Validator מקבל רק מה שהוא צריך לבדוק.

---

# 57. Historical Validator

בודק:

```text
major timeline
force strengths
formations
equipment
positions
terrain
weather
major events
outcome
confidence correctness
```

הוא לא צריך context של implementation internals אם אינו רלוונטי.

---

# 58. Architecture Validator

בודק:

```text
domain boundaries
dependency direction
duplicate capabilities
schema compatibility
forbidden coupling
context leakage
```

---

# 59. Context Leakage Test

הוסף בדיקות לכך ש־AgentContext אינו מכיל domains שאינם נדרשים.

לדוגמה:

```text
task = Panther model
```

ולא dependency ימי.

הבדיקה יכולה לצפות:

```text
naval_context_count = 0
```

---

# 60. Context Cost Metrics

לכל AgentRun שמור:

```text
context_tokens
context_sources
context_domains
unused_context_estimate
additional_context_requests
task_success
```

כך המערכת יכולה ללמוד בהמשך Context routing טוב יותר.

זה מתאים ישירות לחזון Deliver.

---

# 61. Context Attribution

אם Context item תרם בפועל לתוצאה:

חזק relationship.

אם הוא נטען ולא שימש:

אל תחזק.

בעתיד:

```text
AgentRole
  ──HELPED_BY──>
ContextNode
```

יכול להפוך ל־Deliver listener affinity.

---

# 62. Output של כל Agent

כל agent צריך להחזיר structured summary:

```yaml
task:
status:

changed:
artifacts:

used_context:
used_evidence:

assumptions:

uncertainties:

new_capabilities:

capability_gaps:

cross_domain_requests:

tests:

cost_estimate:

followups:
```

Root אינו צריך לקבל transcript של כל reasoning.

רק תוצאה structured + references.

---

# 63. Root אינו עושה micromanagement

Root אחראי על:

```text
decomposition
contracts
context routing
integration
validation
economic decisions
```

Domain agents אחראים על implementation שלהם.

---

# 64. Root Context

Root רשאי לראות:

```text
system architecture
domain registry
schemas
episode goals
Deliver contracts
summary outputs
open issues
```

אבל אפילו Root אינו צריך לטעון כל technical manual או כל image למסך שלו.

הוא שולח אותם למומחה.

---

# 65. Context Routing Example

משימה:

```text
Create historically accurate Panther Ausf. G
for Normandy, August 1944.
```

Root יוצר:

```text
VehicleHistoricalAgent
```

Context:

```text
Panther documents
August 1944 production changes
Normandy unit availability
technical drawings
relevant photographs
```

ולא:

```text
U-boat sonar documentation
B-17 flight model
Pacific island terrain
```

Vehicle agent מחזיר:

```text
PantherVariantSpec
```

אחר כך:

```text
VehicleSimulationAgent
```

מקבל:

```text
PantherVariantSpec
TrackedMovement interface
Engine interface
Armor interface
```

אחר כך:

```text
VehicleAssetAgent
```

מקבל:

```text
dimensions
drawings
photographs
visual variation requirements
asset contract
```

ולבסוף:

```text
VehicleValidator
```

בודק התאמה.

---

# 66. Episode Example Context

Episode Normandy אינה צריכה לטעון כל WWII Atlas.

ContextPack:

```text
time window
geographic envelope
participating formations
relevant sources
local terrain
local weather
required equipment families
historical anchors
```

זה הכול.

אם במהלך העבודה היא מגלה dependency חדש:

מבקשת expansion.

---

# 67. Files / Docs ליצירה

לאחר scanning ומחקר, בנה לפחות:

```text
docs/game/MASTER_ARCHITECTURE.md
docs/game/CONTEXT_ARCHITECTURE.md
docs/game/AGENT_ROLES.md
docs/game/DOMAIN_REGISTRY.md
docs/game/STACK_EVALUATION.md
docs/game/LEGO_ARCHITECTURE.md
docs/game/HISTORICAL_FIDELITY.md
docs/game/EPISODE_SCHEMA.md
docs/game/DELIVER_INTEGRATION.md
docs/game/ECONOMY_AND_PRICING.md
docs/game/SIMULATION_LOD.md
docs/game/OPEN_PROBLEMS.md
```

אבל אל תיצור מסמכים כפולים אם אפשר לאחד.

---

# 68. Schemas

הגדר schemas ל:

```text
ContextManifest
Capability
CapabilityRequest
CapabilityResult
CapabilityGap

HistoricalClaim
Provenance
EquipmentVariant
HistoricalTerrainSnapshot
HistoricalWeatherSnapshot

EpisodeSpec
HistoricalBattleSkeleton
HistoricalEnvelope
AccuracyManifest

Quote
PricingEvaluation
DeliverInvestment
```

---

# 69. Context Router Prototype

בנה prototype קטן של:

```text
ContextRouter
```

Input:

```text
agent_role
task
domain
entity_ids
time
geography
dependencies
```

Output:

```text
ContextManifest
```

בשלב ראשון deterministic.

בהמשך ניתן לשלב:

```text
embeddings
graph proximity
historical relevance
past usefulness
economic evaluation
```

---

# 70. Local Agent / Deliver Simulator

בנה:

```text
LocalDeliverSimulator
```

שמאפשר להפעיל pipeline לפני שה־Deliver Runtime מושלם.

הוא משתמש באותם contracts.

בעתיד:

```text
LocalDeliverSimulator
        ↓ replace
DeliverRuntimeAdapter
```

בלי שינוי ב־Episode Builder.

---

# 71. קשר ל־Deliver listeners

הארכיטקטורה הקיימת משתמשת ב־work/context state וב־listeners.

לכן Game Context Router צריך להיות מתוכנן כך שבעתיד:

```text
TaskContext
≈ work delta

Evidence/Dependency Context
≈ context delta

AgentRole
≈ Deliver capability

Context subscription
≈ listener
```

אל תעתיק את Runtime עכשיו.

שמור compatibility.

---

# 72. לא לחזור ל־NEXT scheduler

אל תבנה game agents לפי chain קשיח:

```text
TankAgent -> GunAgent -> TerrainAgent
```

אלא לפי:

```text
work
context
capability requirements
listeners / routing
```

כאשר orchestration זמני יכול להיות פשוט יותר.

---

# 73. Deliver Evolution

AgentRole של היום צריך לשמור metrics כדי שבעתיד אפשר יהיה:

```text
observe repeated tasks
discover reusable pattern
create Deliver candidate
shadow test
promote
```

---

# 74. Model Routing

אל תניח שכל משימה דורשת את המודל החזק ביותר.

המערכת צריכה לאפשר בעתיד:

```text
strong model:
architecture
ambiguous research
conflict resolution

medium model:
implementation
structured synthesis

cheap model:
extraction
classification
schema conversion
repetitive validation

deterministic code:
stable repeated operations
```

ה־architecture אינה תלויה בשמות מודלים מסוימים.

---

# 75. Research Agents

כאשר משימה תלויה בטכנולוגיה או מידע עדכני:

השתמש במחקר אינטרנטי ובמקורות רשמיים.

ל־game stack:

```text
official docs
official repos
release notes
issues
roadmaps
real examples
```

לפני blogs כלליים.

---

# 76. Historical Sources

לדיוק היסטורי, תעדף לפי סוג הנתון.

לדוגמה:

```text
primary records
official wartime documents
technical manuals
war diaries
archival maps
aerial photographs
museum/archive collections
high-quality secondary scholarship
```

אבל אל תגדיר hierarchy מוחלטת בלי להתחשב בסוג הטענה.

---

# 77. Evidence Conflict

אם מקורות חולקים:

```text
store both
```

עם:

```text
source
claim
confidence
interpretation
```

אל תכריח false consensus.

---

# 78. Headless First-Class Support

Game stack חייב לאפשר:

```text
load Episode
run simulation
inspect state
run tests
validate history
```

ללא rendering.

זה קריטי ל־agents.

---

# 79. Record / Replay

תכנן:

```text
seeded random
fixed timestep where appropriate
event log
state snapshots
replay
```

כדי שסוכן יוכל לזהות regression.

---

# 80. Testability מעל Demo

אל תבחר architecture שמייצרת screenshot יפה אך קשה לבדיקה.

עדיף:

```text
headless validated simulation
```

על:

```text
beautiful opaque editor state
```

בשלב הראשוני.

---

# 81. MVP

MVP ראשון:

```text
small historical terrain
infantry
one machine gun
one vehicle
basic ballistics
basic suppression
basic injury
basic AI
one weather state
one EpisodeSpec
one reconstructed uncertainty
one Accuracy UI
one CapabilityGap
one Deliver-simulated build request
```

המטרה:

להוכיח architecture.

---

# 82. אל תבנה קודם את כל ה־Lego

בנה Lego הדרוש ל־Episode #1.

אחר כך Episode #2.

אפשר ל־requirements אמיתיים לחשוף את abstraction הנכון.

---

# 83. Definition of Done — Architecture

השלב אינו גמור עד שקיימים:

```text
current architecture scan
stack evaluation
domain boundaries
ContextPack contract
ContextRouter design
AgentRole registry
capability schemas
historical schemas
EpisodeSpec
Deliver compatibility layer
pricing contracts
progressive fidelity model
simulation LOD model
MVP plan
open-problem registry
```

---

# 84. Definition of Done — Context Architecture

צריך להדגים בפועל:

```text
Tank task
```

מקבל:

```text
tank + dependencies + relevant evidence
```

ואינו מקבל:

```text
naval + unrelated aviation + unrelated episodes
```

וכן:

```text
Naval task
```

עובד הפוך.

---

# 85. Definition of Done — First Vertical Slice

Input:

```text
EpisodeIntent
```

Output:

```text
PlayableEpisode
```

דרך:

```text
Context routing
Historical reconstruction
Capability resolution
Lego composition
Deliver-compatible gap handling
Validation
Headless simulation
Playable runtime
```

---

# 86. עבודת Subagents בשלב האפיון

לפני כתיבת האפיון הסופי, ה־Root צריך להאציל לפחות את המחקרים העצמאיים הבאים אם יש מספיק concurrency:

```text
A. Game Stack Research
B. Agent / Context Architecture
C. Historical Reconstruction Pipeline
D. Simulation / ECS / LOD Architecture
```

אחרי קבלת התוצאות:

Root מסנתז.

לאחר מכן הוא יכול לשלוח reviews נפרדים:

```text
Architecture consistency review
Historical fidelity review
Agent-context leakage review
Deliver integration review
```

---

# 87. אל תשלח לכל Subagent את כל ה־Master Spec

לכל subagent:

שלח רק:

```text
its task
relevant global invariants
relevant domain docs
required contracts
expected output
```

ה־Root שומר את התמונה הכוללת.

---

# 88. Completion Instruction

אל תעצור אחרי הצעה ראשונה.

המשך עד שיש:

```text
coherent architecture
cross-checked contracts
documented decisions
explicit uncertainties
stack recommendation
agent/context design
initial schemas
implementation sequence
```

אם subagent מוצא סתירה:

פתור אותה לפני סיום האפיון.

---

# 89. כלל תכנון מרכזי

כל החלטה צריכה לענות על שתי שאלות:

```text
Can this be reused by many Episodes?

Can this become a Deliver later?
```

אם התשובה לשתיהן "לא":

בדוק אם אנחנו בונים משהו Episode-specific מדי.

---

# 90. North Star

המערכת הסופית היא לא:

```text
AI that generates WWII levels
```

אלא:

```text
A historically grounded simulation platform
made of reusable capabilities,
where narrowly scoped agents/Delivers
receive only relevant context,
build and improve reusable Lego,
and where usage funds progressively
more accurate, richer and more expensive
historical reconstruction.
```

זהו היעד הארכיטקטוני.

עכשיו:

1. סרוק את ה־repository ואת מסמכי Deliver הקיימים.
2. זהה מה קיים ומה רק חזון.
3. הפעל subagents ממוקדי-context למחקרים העצמאיים.
4. בדוק מחדש את ה־game stack העדכני.
5. תכנן Context Architecture מפורטת.
6. תכנן Lego/Capability Architecture.
7. תכנן historical reconstruction pipeline.
8. תכנן Deliver compatibility.
9. בצע reviews צולבים.
10. הפק מסמך אפיון סופי וקוהרנטי לפני implementation גדול.