## 🛠️ Performance & Design Patterns

*   **Async Everywhere**: Both Backend and Bot use asychronous programming (`asyncio`) for high concurrency.
*   **SkillOps**: New capabilities can be added by dropping a python file into `backend/app/services/tools/`.
*   **Risk-Based Approvals**: Significant actions (like modifying a recurring goal) are held in a queue until a human confirms, preventing LLM hallucinations from causing data loss.