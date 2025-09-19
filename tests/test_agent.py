# FILE: tests/test_agent.py

import pytest
import requests
from unittest.mock import patch, call

# Import the class we want to test from its specific module
from kansatsu.agent import Kansatsu

# Define a dummy URL that we'll use across tests
DUMMY_URL = "http://localhost:9999/test"

# CRITICAL FIX: We patch 'requests' where it is *used* (inside the agent module),
# not where it is defined.
@patch('kansatsu.agent.requests.post')
def test_log_method_performance_sends_to_dashboard(mock_post):
    """
    Tests that log_method_performance sends the correct payload to the dashboard.
    """
    obs = Kansatsu(service_name="test-service", dashboard_url=DUMMY_URL)
    obs.log_method_performance("my_test_func", 123.45)
    mock_post.assert_called_once_with(
        DUMMY_URL,
        json={"type": "method_performance", "name": "my_test_func", "duration_ms": 123.45},
        timeout=0.5
    )

@patch('kansatsu.agent.requests.post')
def test_monitor_with_llm_sends_two_events(mock_post):
    """
    Tests that a decorated function with track_tokens=True sends both performance and usage events.
    """
    obs = Kansatsu(service_name="test-service", dashboard_url=DUMMY_URL)

    # Mock LLM response object (e.g., from OpenAI)
    class MockUsage:
        prompt_tokens = 100
        completion_tokens = 200
        total_tokens = 300
    class MockLLMResponse:
        usage = MockUsage()

    @obs.monitor(track_tokens=True)
    def llm_call_text():
        return MockLLMResponse()

    llm_call_text()

    # Assert that `post` was called twice
    assert mock_post.call_count == 2

    # Check that both expected call types were made
    call_types = [c.kwargs['json']['type'] for c in mock_post.call_args_list]
    assert 'method_performance' in call_types
    assert 'method_llm_usage' in call_types

@patch('kansatsu.agent.requests.post')
def test_log_quality_feedback_sends_to_dashboard(mock_post):
    """Tests that quality feedback is sent correctly."""
    obs = Kansatsu(service_name="test-service", dashboard_url=DUMMY_URL)
    obs.log_quality_feedback(5)
    mock_post.assert_called_once_with(
        DUMMY_URL,
        json={"type": "quality_feedback", "score": 5},
        timeout=0.5
    )

@patch('kansatsu.agent.requests.post')
def test_error_event_sends_to_dashboard(mock_post):
    """
    Tests that an error logged via the monitor sends both an 'error' event
    and a 'method_performance' event.
    """
    obs = Kansatsu(service_name="test-service", dashboard_url=DUMMY_URL)

    @obs.monitor()
    def function_that_fails():
        raise ValueError("A test error")

    with pytest.raises(ValueError):
        function_that_fails()

    assert mock_post.call_count == 2
    expected_error_call = call(DUMMY_URL, json={"type": "error"}, timeout=0.5)
    assert expected_error_call in mock_post.call_args_list

    found_performance_call = any(
        c.kwargs.get('json', {}).get('type') == 'method_performance'
        for c in mock_post.call_args_list
    )
    assert found_performance_call, "Expected a method_performance call, but it was not found."

@patch('kansatsu.agent.requests.post')
def test_shutdown_sends_to_dashboard(mock_post):
    """Tests that shutdown sends the 'session_end' event."""
    obs = Kansatsu(service_name="test-service", dashboard_url=DUMMY_URL)
    obs.shutdown()
    mock_post.assert_called_once_with(
        DUMMY_URL,
        json={"type": "session_end"},
        timeout=0.5
    )

@patch('kansatsu.agent.requests.post')
def test_no_dashboard_url_prevents_sending(mock_post):
    """
    Ensures that if no dashboard_url is provided, no network calls are made.
    """
    obs = Kansatsu(service_name="test-service", dashboard_url=None)
    obs.log_method_performance("some_func", 100)
    mock_post.assert_not_called()

@patch('kansatsu.agent.requests.post')
def test_dashboard_connection_error_is_handled_gracefully(mock_post, caplog):
    """
    Tests that if the dashboard is down, the agent doesn't crash and a warning is logged once.
    """
    mock_post.side_effect = requests.exceptions.ConnectionError("Test connection failed")
    obs = Kansatsu(service_name="test-service", dashboard_url=DUMMY_URL)

    obs.log_interaction_time(1000)

    assert "Could not connect to dashboard" in caplog.text
    assert "Test connection failed" in caplog.text

    # Call it again to make sure it only logs the warning once
    obs.log_interaction_time(1000)
    assert caplog.text.count("Could not connect to dashboard") == 1