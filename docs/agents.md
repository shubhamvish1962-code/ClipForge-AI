# ClipForge AI — Agent Specifications

Every AI agent in ClipForge AI follows a modular, schema-enforced structure inheriting from `BaseAgent`.

---

## BaseAgent Contract

```python
class AgentResult(BaseModel):
    agent_name: str
    status: Literal["success", "failed", "skipped"]
    confidence: float          # 0.0 – 1.0
    reasoning: str             # Concise, human-readable summary for UI/logging
    output: dict               # Agent-specific payload
    started_at: datetime
    completed_at: datetime
    duration_ms: int
    retry_count: int
    provider: str
    model: Optional[str]
    error: Optional[str]
```

---

## Virality Checking Ensemble (7 Judge Agents)

| Agent Name | Weight | Focus Area | Key Evaluated Signals |
|------------|--------|------------|------------------------|
| `HookJudgeAgent` | 20 pts | Opening 1–5s | Curiosity gap, counterintuitive claims, question opens, no preamble ("hey guys") |
| `StoryJudgeAgent` | 15 pts | Narrative completeness | Setup, conflict, resolution, self-contained story arc |
| `EmotionJudgeAgent` | 10 pts | Emotional trajectory | Excitement, surprise, curiosity, peak moment identification |
| `ClarityJudgeAgent` | 10 pts | Independent clarity | Topic clear in 8s, no undefined pronoun references, clear audio |
| `PacingJudgeAgent` | 10 pts | Information flow | Speech rate (WPM), filler word %, dead air ratio |
| `ShareabilityJudgeAgent` | 10 pts | Viral triggers | Quotable lines, debate triggers, actionable advice, relatability |
| `VisualJudgeAgent` | 10 pts | Framing & Crop | Speaker framing, face detection, lighting, 9:16 safe zone compliance |

### Virality Score Formula
$$\text{Total Score} = \sum (\text{Judge Score}) + \text{Curiosity Bonus (max 15)} - \text{QA Penalties}$$

---

## Quality Control (6 QA Agents)

1. `TranscriptQA`: Caption accuracy threshold ≥ 95%.
2. `TimingQA`: Caption timestamp drift ≤ 150ms.
3. `ContextQA`: Standalone comprehension test.
4. `AudioQA`: Loudness normalization (-16 to -12 LUFS), clipping check.
5. `VisualQA`: Speaker framing & subject centering.
6. `HookQA`: Post-edit opening strength re-validation.
7. `PlatformQA`: Aspect ratio (9:16), resolution (1080x1920), duration limit (≤60s).
