# Historical Design Records

These documents are **historical development records**, preserved for engineering
context. They were written incrementally as the system was built and are named
after the development milestones ("phases") in which each domain was added.

They capture the schema and architecture decisions (and the rationale behind
them) for individual domains at the time those domains were implemented. Several
are still referenced from source comments where they explain a non-obvious design
choice (e.g. the payment/order boundary, inventory event ordering).

They are **not** the current system description. For an accurate, up-to-date
overview of the architecture, modules, and capabilities, see the top-level
[`README.md`](../../README.md). Where a historical record and the top-level
README disagree, the README (and the code) is authoritative.

| Document | Domain covered |
|---|---|
| `phase4_schema_decision.md` | AI catalog draft schema |
| `phase5_schema_decision.md` | Inventory & stock movement |
| `phase6_architecture_decision.md` | Conversational AI |
| `phase7_schema_decision.md` | Customer & order |
| `phase8_schema_decision.md` | Payment |
| `phase9_schema_decision.md` | Invoice |
| `phase10_architecture_decision.md` | Notifications, analytics & dashboard |
| `phase10_schema_decision.md` | Notifications schema |
