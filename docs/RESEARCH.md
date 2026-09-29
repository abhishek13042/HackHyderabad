# Research behind the design

Recon is a small product. Each idea below comes from published work, and each
row says what we took from it and where it shows up in the code. We cite these
for design reasoning. We don't claim to reproduce their results.

| Work | The idea | What Recon does with it |
|---|---|---|
| **Hindsight** (Vectorize; [arXiv 2512.12818](https://arxiv.org/abs/2512.12818)) | Agent memory as separate networks: world facts, the agent's experiences, observations about entities, and opinions, built through retain, recall and reflect. | We write facts and experiences only (resolutions, outcomes, drift) and let Hindsight form observations about each vendor. Recall asks for all three networks at once. See [HINDSIGHT_USAGE.md](HINDSIGHT_USAGE.md). |
| **Reflexion** (Shinn et al., 2023) | Agents improve by storing verbal feedback about their own mistakes in memory, without changing the model's weights. | The core bet: *the model doesn't learn, the memory does.* The self-check writes "the decision to DEFER was wrong" back to memory. This is also why we don't fine-tune (D1). |
| **ExpeL** (Zhao et al., 2024) | Agents gather experiences across tasks and pull insights from both successes and failures. | Outcomes are retained whether the decision was right *or* wrong, and trust uses both (`learning.trust`). |
| **Generative Agents** (Park et al., 2023) | A memory stream, retrieval by relevance and recency, and reflection into higher-level beliefs. | Business-dated memories (D29) give recall a real timeline. Reflect turns them into the vendor profile and the monthly insights. |
| **MemGPT** (Packer et al., 2023) | Treat the context window like RAM: keep what's needed and page in the rest. | One capped recall per group (`max_tokens=1500`) instead of the whole history, so the prompt stays flat as history grows. E10 measures this. |
| **Lost in the Middle** (Liu et al., 2023) | Models overlook information in the middle of long contexts. | Dumping all history would make answers *worse*, not only more expensive. We send a few targeted memories, labelled `M1`, `M2`, and ask the model to cite them. |
| **LongMemEval** (Wu et al., 2024) | Long-term memory benchmarks need *knowledge updates*: old facts that stop being true. | Reddy Steels is our knowledge-update case. Drift memories say "earlier assumptions should not be trusted", and scenario S1 in the evals checks it. |
| **Learning to Defer** (Madras et al., 2018) | A model should know when to hand a decision to a human. | The trust ladder: suggestions stay with the accountant until a pattern has earned Auto, unsafe actions can never be automatic, and the agent escalates when unsure (D8). |
| **Concept drift** (Gama et al., 2014, survey) | Deployed systems must detect when the world changes and old patterns stop holding. | `learning.detect_drift`: a vendor that misses its usual filing window resets trust, and guardrail G6 forbids deferring. |

## What we chose not to do

- **No fine-tuning.** The knowledge is per firm and changes every month. Memory
  updates in seconds, retraining doesn't, and fine-tuning needs data we don't have.
- **No agent loop with tools.** One structured JSON call per exception group is
  cheaper, easier to check, and more reliable on hosted open models (D4).
- **No model-based matching.** Tax amounts must be exact, so matching is plain
  code (D2).
