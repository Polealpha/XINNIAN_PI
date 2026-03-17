# Activation Identity Design

## Goal

After a user logs in for the first time, the system should confirm who this person is before normal conversation starts accumulating long-term memory.

This solves two problems:

- normal chat is noisy and should not be treated as durable identity truth
- robot voice onboarding needs a stable, structured identity card that can scale to more users and more devices later

## Current flow

1. Client logs in.
2. If `activation_required=true`, client opens `/activate` or calls the activation APIs.
3. The first voice transcript can be sent to `POST /api/activation/identity/infer`.
4. Backend calls OpenClaw with a strict extraction prompt and expects JSON only.
5. User confirms or edits the extracted identity card.
6. Client sends the final card to `POST /api/activation/complete`.
7. Backend stores the profile in `user_activation_profiles` and mirrors a summary into the OpenClaw workspace memory.

## Why this scales better

- identity facts live in a dedicated table instead of being buried inside chat logs
- onboarding inference uses a dedicated activation session instead of contaminating ordinary chat sessions
- JSON extraction makes it easier to support desktop, mobile, WeCom, and robot voice with the same contract
- the backend can later evolve from one owner to multiple household members without rewriting the whole chat layer

## Prompt design rules used here

- Ask high-information questions first.
- Separate long-term identity facts from ephemeral conversation.
- Use explicit uncertainty markers such as "待确认".
- Require strict structured output for machine-readable extraction.
- Keep role and relation labels bounded by a stable enum set.

## External references used for this design

- OpenAI Prompting Guide: <https://platform.openai.com/docs/guides/prompt-engineering>
- OpenAI Structured Outputs: <https://platform.openai.com/docs/guides/structured-outputs>
- OpenAI Models Overview: <https://platform.openai.com/docs/models>
- OpenAI GPT-5 Prompting Guide: <https://platform.openai.com/docs/guides/gpt-5>

## Current defaults

- preferred mode: `cli`
- preferred high-tier model hint: `gpt-5.4`

These are product-side preferences, not a forced override of the underlying OpenClaw runtime model registry.
