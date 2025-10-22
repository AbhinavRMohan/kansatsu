# FILE: README.md

# 💮 Kansatsu Observability Toolkit

Demo: https://youtu.be/JTCl-0H8EOI

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python Version](https://img.shields.io/badge/python-3.8+-blue.svg)](https://www.python.org/downloads/)

Kansatsu (観察, Japanese for "observation") is a lightweight, end-to-end observability toolkit designed specifically for monitoring the performance, usage, cost, and quality of LLM-powered applications. It provides a simple decorator-based agent and a real-time web dashboard.

## Features

-   **Simple Integration**: Wrap any function with the `@kansatsu.monitor()` decorator to start collecting data.
-   **Live Dashboard**: Run `kansatsu-dashboard` to get a real-time view of your application's health.
-   **Performance Metrics**: Automatically tracks execution time, call counts, and errors for each monitored function.
-   **LLM Cost Tracking**: Automatically parses token usage from OpenAI, Google (Gemini), and Anthropic API responses.
-   **Quality & RAI**: Includes helpers for logging user feedback and a built-in PII/PHI scanner to detect sensitive data.
-   **OpenTelemetry Backend**: Built on OpenTelemetry, providing standardized console logs that can be easily integrated with platforms like Google Cloud Logging, Datadog, etc.

## Installation

1.  **Install from GitHub**

    You can install the library directly from your GitHub repository using `pip`.

    ```bash
    pip install git+https://github.com/AbhinavRMohan/kansatsu.git
    ```

2.  **Download SpaCy Model**

    Kansatsu uses the SpaCy library for its PII/PHI detection feature. You need to download the English model manually.

    ```bash
    python -m spacy download en_core_web_sm
    ```

## Quickstart Guide

Using Kansatsu is a two-step process: launch the dashboard, then instrument your application code.

### Step 1: Run the Dashboard

Open a new terminal and run the following command. This will start a web server on `http://127.0.0.1:9999` by default.

```bash
kansatsu-dashboard
```

You can specify a different host or port:

```bash
kansatsu-dashboard --host 0.0.0.0 --port 9000
```

### Step 2: Instrument your App

In your Python application, import and initialize the ```Kansatsu``` agent. Then use the ```@kansatsu.monitor()``` decorator on the functions you want to observe. Here is a complete exampls:

```python
# ez_example.py
import time
import random
from kansatsu import Kansatsu

# http://127.0.0.1:9999/update
kansatsu = Kansatsu(service_name="my-llm-app", service_version="1.0.1")

# A mock class to simulate an LLM API response
class MockLLMResponse:
    def __init__(self, text, prompt_tokens, completion_tokens):
        self.text = text
        # Simulate OpenAI's usage object
        class Usage:
            def __init__(self, p_tokens, c_tokens):
                self.prompt_tokens = p_tokens
                self.completion_tokens = c_tokens
                self.total_tokens = p_tokens + c_tokens
        self.usage = Usage(prompt_tokens, completion_tokens)

@kansatsu.monitor(span_name="llm_call_to_provider", track_tokens=True, log_io=True)
def call_llm(prompt: str):
    print(f"Calling LLM with prompt: '{prompt}'")
    time.sleep(random.uniform(0.5, 1.5)) # Simulate network latency
    # Simulate a response with PII
    response_text = "The patient's name is John Doe and his MRN is 12345. Call him at 555-867-5309."
    return MockLLMResponse(
        text=response_text,
        prompt_tokens=len(prompt.split()),
        completion_tokens=len(response_text.split())
    )

@kansatsu.monitor(span_name="database_query")
def query_database(query: str):
    print(f"Querying DB with: '{query}'")
    time.sleep(random.uniform(0.1, 0.3))
    return {"status": "success", "rows": random.randint(1, 100)}

if __name__ == "__main__":
    try:
        for i in range(10):
            print(f"\n--- Interaction {i+1} ---")
            start_time = time.perf_counter()

            # The decorators will automatically log performance and tokens
            llm_response = call_llm(prompt=f"This is my prompt number {i}")
            db_result = query_database(query="SELECT * FROM users;")

            # Check the LLM output for PII
            rai_results = kansatsu.check_responsible_ai(llm_response.text, kansatsu.get_tracer().get_current_span())
            if rai_results["pii_found"]:
                print(f"👺 PII Found: {rai_results['findings']}")

            # Log end-to-end interaction time and user feedback
            end_time = time.perf_counter()
            kansatsu.log_interaction_time((end_time - start_time) * 1000)
            kansatsu.log_quality_feedback(random.randint(3, 5)) # Simulate a user rating of 3, 4, or 5

            time.sleep(2) # Wait before the next interaction

    finally:
        kansatsu.shutdown()
```

Now open your browser to ```http://127.0.0.1:9999``` and watch the metrics update in real-time as your application runs!
