from types import SimpleNamespace

import pytest

from integrations.lite_agent.model_client import _aggregate_stream_response
from integrations.lite_agent.reasoning import observed_reasoning_mode


@pytest.mark.parametrize('message,expected', [
    ({'reasoning': None, 'reasoning_content': 'Inspect the input.'}, 'thinking'),
    ({'reasoning': 'Inspect the input.', 'reasoning_content': None}, 'thinking'),
    ({'reasoning': '', 'reasoning_content': 'Inspect the input.'}, 'thinking'),
    ({'reasoning': None, 'reasoning_content': ''}, 'non_thinking'),
    ({'content': 'done'}, None),
])
def test_observation_reads_both_provider_aliases(message, expected):
    assert observed_reasoning_mode({}, message) == expected


def test_stream_aggregation_keeps_reasoning_content_observable():
    chunks = iter([{'model': 'Qwen3.5-9B', 'choices': [
        {'delta': {'reasoning_content': 'Inspect the input.'}, 'finish_reason': None}]}])
    response = _aggregate_stream_response(chunks)
    assert observed_reasoning_mode(response, response.choices[0].message) == 'thinking'


def test_explicit_provider_mode_still_takes_precedence():
    response = SimpleNamespace(effective_reasoning_mode='non_thinking')
    assert observed_reasoning_mode(response, {'reasoning_content': 'trace'}) == 'non_thinking'
