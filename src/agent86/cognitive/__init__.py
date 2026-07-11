"""Tier 3 — Cognitive.

Abstracts model-provider APIs behind one unified ``ModelProvider`` interface so the
orchestrator stays model-agnostic across Anthropic, OpenAI-compatible, Ollama, and
llama.cpp/LM Studio. Owns prompt compilation (templates + dynamic context + history +
tool schemas), token budgeting (sliding window, recursive summarization), and the
tool-emulation shim for local models that lack native function calling.

Modules (Phase 2+):
    base.py               — ModelProvider ABC + unified request/completion types
    anthropic_provider.py — Claude Messages API
    openai_provider.py    — OpenAI + any OpenAI-compatible base_url
    ollama_provider.py    — local Ollama HTTP API
    llamacpp_provider.py  — llama.cpp server / LM Studio
    prompt.py             — prompt compilation
    budget.py             — token budgeting / context compaction
"""
