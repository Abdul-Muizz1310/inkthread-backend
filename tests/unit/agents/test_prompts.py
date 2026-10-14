"""Spec 05 § 5: prompt files, frontmatter and their hash."""

from __future__ import annotations

import pytest

from inkthread.agents.prompts import load_prompt, parse_prompt, prompts_hash


@pytest.mark.parametrize(
    ("task", "role"), [("classify", "producer"), ("relate", "producer"), ("verify", "verifier")]
)
def test_prompts_load_with_frontmatter(task: str, role: str) -> None:
    p = load_prompt(task)
    assert (p.task, p.role, p.version) == (task, role, 1)
    assert 0.0 <= p.temperature <= 1.0
    assert p.max_tokens > 0
    assert p.body.strip()
    assert "---" not in p.body.splitlines()[0]
    assert p.raw.startswith(b"---")


def test_classify_prompt_lists_every_role() -> None:
    from inkthread.domain.model import Role

    body = load_prompt("classify").body
    for role in Role:
        assert f"`{role.value}`" in body


def test_prompts_hash_is_stable_hex() -> None:
    assert prompts_hash() == prompts_hash()
    assert len(prompts_hash()) == 64


@pytest.mark.parametrize(
    "raw",
    [
        b"no frontmatter",
        b"---\ntask: x\n---\nbody",
        b"---\ntask: x\nversion: one\nrole: producer\ntemperature: 0\nmax_tokens: 9\n---\nb",
        b"---\ntask: x\nversion: 1\nrole: judge\ntemperature: 0\nmax_tokens: 9\n---\nb",
        b"---\ntask: x\nversion: 1\nrole: producer\ntemperature: 0\nmax_tokens: 9\n---\n",
    ],
)
def test_bad_prompt_files_are_refused(raw: bytes) -> None:
    with pytest.raises(ValueError, match="prompt"):
        parse_prompt(raw)
