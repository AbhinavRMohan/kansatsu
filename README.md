# FILE: README.md

# 💮 Kansatsu Observability Toolkit

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
    # Replace with your GitHub username and repository name
    pip install git+https://github.com/your-username/kansatsu.git
    ```

2.  **Download SpaCy Model**

    Kansatsu uses the SpaCy library for its PII/PHI detection feature. You need to download the English model manually.

    ```bash
    python -m spacy download en_core_web_sm
    ```

## Quickstart Guide

Using Kansatsu is a two-step process: launch the dashboard, then instrument your application code.

### Step 1: Run the Dashboard

Open a new terminal and run the following command. This will start a web server on `http://127.0.0.1:9000` by default.

```bash
kansatsu-dashboard