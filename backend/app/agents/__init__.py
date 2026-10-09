"""Multi-agent pipeline.

Each agent owns one stage of production, reads its own config/prompt, and calls
the provider router for the capability it needs. Agents are registered by stage
and run by the orchestrator.
"""
