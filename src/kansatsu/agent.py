# FILE: src/kansatsu/agent.py

import time
import logging
import json
import os
import functools
from typing import Any, Callable, Dict
import threading
import re
import requests
import spacy

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import ConsoleSpanExporter, SimpleSpanProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.trace import Status, StatusCode

logging.basicConfig(format='%(asctime)s -- [%(levelname)s] -- %(message)s', level=logging.INFO)

def is_luhn_valid(card_number: str) -> bool:
    try:
        digits = [int(d) for d in card_number]
        checksum = 0
        for i, digit in enumerate(reversed(digits)):
            if i % 2 == 1:
                digit *= 2
                if digit > 9:
                    digit -= 9
            checksum += digit
        return checksum % 10 == 0
    except (ValueError, TypeError):
        return False

class Kansatsu:
    def __init__(self, service_name: str, service_version: str = "1.0.0", dashboard_url: str = "http://127.0.0.1:8050/update"):
        self.service_name = service_name
        self.service_version = service_version
        self.dashboard_url = dashboard_url

        self._metrics = {
            "total_calls": 0,
            "errors": 0,
            "interaction_count": 0,
            "total_interaction_time_ms": 0.0,
            "llm_total_prompt_tokens": 0,
            "llm_total_completion_tokens": 0,
            "llm_total_tokens": 0,
            "rai_alerts": [],
            "quality_scores": [],
            "method_stats": {}
        }
        self._lock = threading.Lock()
        self._setup_otel()

        try:
            logging.info("Loading spaCy NER model...")
            self.nlp = spacy.load("en_core_web_sm")
            logging.info("✅ spaCy NER model loaded successfully.")
        except OSError:
            logging.error("❌ spaCy model 'en_core_web_sm' not found. Please run 'python -m spacy download en_core_web_sm'")
            self.nlp = None

    def _send_to_dashboard(self, payload: Dict):
        if not self.dashboard_url:
            return
        try:
            requests.post(self.dashboard_url, json=payload, timeout=0.5)
        except requests.exceptions.RequestException as e:
            if not hasattr(self, "_dashboard_error_logged"):
                logging.warning(f"👹 Could not connect to dashboard at {self.dashboard_url}. Is it running? Error: {e}")
                self._dashboard_error_logged = True

    def _setup_otel(self):
        resource = Resource(attributes={
            "service.name": self.service_name,
            "service.version": self.service_version,
        })
        provider = TracerProvider(resource=resource)
        processor = SimpleSpanProcessor(ConsoleSpanExporter())
        provider.add_span_processor(processor)
        trace.set_tracer_provider(provider)
        logging.info(f"💮 OpenTelemetry initialized for service '{self.service_name}'.")

    def get_tracer(self) -> trace.Tracer:
        return trace.get_tracer(self.service_name, self.service_version)

    def log_metric(self, key: str, value: Any):
        with self._lock:
            if isinstance(self._metrics.get(key), list):
                self._metrics[key].append(value)
            else:
                self._metrics[key] = self._metrics.get(key, 0) + value

    def log_quality_feedback(self, score: int):
        with self._lock:
            self._metrics["quality_scores"].append(score)
            self._send_to_dashboard({"type": "quality_feedback", "score": score})

    def log_interaction_time(self, duration_ms: float):
        with self._lock:
            self._metrics["interaction_count"] += 1
            self._metrics["total_interaction_time_ms"] += duration_ms
            self._send_to_dashboard({"type": "interaction_time", "duration_ms": duration_ms})

    def log_method_performance(self, method_name: str, duration_ms: float):
        with self._lock:
            self._metrics["total_calls"] += 1
            if method_name not in self._metrics["method_stats"]:
                self._metrics["method_stats"][method_name] = self._get_default_method_stats()
            stats = self._metrics["method_stats"][method_name]
            stats["calls"] += 1
            stats["total_duration_ms"] += duration_ms
            self._send_to_dashboard({"type": "method_performance", "name": method_name, "duration_ms": duration_ms})

    def log_method_llm_usage(self, method_name: str, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        with self._lock:
            if method_name not in self._metrics["method_stats"]:
                self._metrics["method_stats"][method_name] = self._get_default_method_stats()
            stats = self._metrics["method_stats"][method_name]
            stats["prompt_tokens"] += prompt_tokens
            stats["completion_tokens"] += completion_tokens
            stats["total_tokens"] += total_tokens
            self._metrics["llm_total_prompt_tokens"] += prompt_tokens
            self._metrics["llm_total_completion_tokens"] += completion_tokens
            self._metrics["llm_total_tokens"] += total_tokens
            self._send_to_dashboard({
                "type": "method_llm_usage",
                "name": method_name,
                "tokens": {
                    "prompt": prompt_tokens,
                    "completion": completion_tokens,
                    "total": total_tokens,
                }
            })

    def _get_default_method_stats(self) -> Dict:
        return {
            "calls": 0,
            "total_duration_ms": 0.0,
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
        }

    def print_summary(self):
        print("\n" + "💮" * 35)
        print(" " * 27 + "Observability Summary")
        print("💮" * 35)
        print("\n--- 💹 General Stats ---")
        print(f"・Total Monitored Calls: {self._metrics['total_calls']}")
        print(f"・Total Errors: {self._metrics['errors']}")
        interaction_count = self._metrics.get("interaction_count", 0)
        if interaction_count > 0:
            total_interaction_time = self._metrics['total_interaction_time_ms']
            avg_interaction_time = total_interaction_time / interaction_count
            print(f"・Average End-to-End Interaction Time: {avg_interaction_time:.2f} ms (from {interaction_count} interactions)")
        else:
            print("・Average End-to-End Interaction Time: No full interactions completed.")
        print("\n--- [┐∵]┘ LLM Usage ---")
        print(f"・Prompt Tokens: {self._metrics['llm_total_prompt_tokens']}")
        print(f"・Completion Tokens: {self._metrics['llm_total_completion_tokens']}")
        print(f"・Total Tokens: {self._metrics['llm_total_tokens']}")
        print("\n--- 📜 Quality & Responsible AI ---")
        quality_scores = self._metrics.get("quality_scores", [])
        if quality_scores:
            avg_score = sum(quality_scores) / len(quality_scores)
            print(f"・Average User Quality Score: {avg_score:.2f} / 5.0 (from {len(quality_scores)} ratings)")
        else:
            print("・Average User Quality Score: No ratings provided.")
        rai_alerts = self._metrics.get("rai_alerts", [])
        print(f"・Responsible AI Alerts Found: {len(rai_alerts)}")
        if rai_alerts:
            for i, alert in enumerate(rai_alerts):
                print(f"    {i+1}. Type: {alert['type']}, Details: {alert['details']}")
        print("\n--- 🕒 Method Performance Summary (Sorted by Total Time) ---")
        method_stats = self._metrics.get("method_stats", {})
        if not method_stats:
            print("No methods were monitored.")
        else:
            sorted_stats = sorted(method_stats.items(), key=lambda item: item[1]['total_duration_ms'], reverse=True)
            print(f"{'Method Name':<30} | {'Calls':>5} | {'Avg Time':>12} | {'Total Tokens':>12} | {'Avg Tokens':>12}")
            print("-" * 82)
            for method_name, data in sorted_stats:
                calls = data['calls']
                avg_duration = data['total_duration_ms'] / calls if calls > 0 else 0
                total_tokens = data['total_tokens']
                avg_tokens = total_tokens / calls if calls > 0 else 0
                print(f"{method_name:<30} | {calls:>5} | {avg_duration:>10.2f} ms | {total_tokens:>12} | {avg_tokens:>12.0f}")
        print("💮" * 35 + "\n")

    def monitor(self, span_name: str = None, track_tokens: bool = False, log_io: bool = False):
        def decorator(func: Callable) -> Callable:
            @functools.wraps(func)
            def wrapper(*args, **kwargs) -> Any:
                _span_name = span_name or func.__name__
                tracer = self.get_tracer()
                with tracer.start_as_current_span(_span_name) as span:
                    start_time = time.perf_counter()
                    if log_io:
                        try:
                            func_args = {k: v for k, v in kwargs.items()}
                            if args:
                                func_args['args'] = args[1:] if 'self' in func.__qualname__ else args
                            span.add_event("function_input", {"input": json.dumps(func_args, default=str)[:1000]})
                        except Exception:
                            span.add_event("function_input", {"input": "Could not serialize input."})
                    try:
                        result = func(*args, **kwargs)
                        span.set_status(Status(StatusCode.OK))
                        if track_tokens:
                            prompt_tokens, completion_tokens, total_tokens = 0, 0, 0
                            if hasattr(result, 'usage_metadata'):
                                usage = result.usage_metadata
                                prompt_tokens = usage.prompt_token_count
                                completion_tokens = usage.candidates_token_count
                                total_tokens = usage.total_token_count
                            elif hasattr(result, 'usage') and hasattr(result.usage, 'prompt_tokens'):
                                usage = result.usage
                                prompt_tokens = usage.prompt_tokens
                                completion_tokens = usage.completion_tokens
                                total_tokens = usage.total_tokens
                            elif hasattr(result, 'usage') and hasattr(result.usage, 'input_tokens'):
                                usage = result.usage
                                prompt_tokens = usage.input_tokens
                                completion_tokens = usage.output_tokens
                                total_tokens = prompt_tokens + completion_tokens
                            
                            # Responses API (gpt-4o-mini via client.responses.create)
                            elif hasattr(result, 'usage_metadata'):
                                usage = result.usage_metadata
                                prompt_tokens = getattr(usage, "prompt_token_count", 0)
                                completion_tokens = getattr(usage, "candidates_token_count", 0)
                                total_tokens = getattr(usage, "total_token_count", 0)
                        
                            # Chat/Completion API (legacy)
                            elif hasattr(result, 'usage'):
                                usage = result.usage
                                prompt_tokens = getattr(usage, "prompt_tokens", 0)
                                completion_tokens = getattr(usage, "completion_tokens", 0)
                                total_tokens = getattr(usage, "total_tokens", prompt_tokens + completion_tokens)
                                
                            if total_tokens > 0:
                                self.log_method_llm_usage(_span_name, prompt_tokens, completion_tokens, total_tokens)
                                span.set_attributes({
                                    "llm.usage.prompt_tokens": prompt_tokens,
                                    "llm.usage.completion_tokens": completion_tokens,
                                    "llm.usage.total_tokens": total_tokens,
                                })
                        if log_io:
                            output_text = result.text if hasattr(result, 'text') else str(result)
                            span.add_event("function_output", {"output": output_text[:1000]})
                        return result
                    except Exception as e:
                        self.log_metric("errors", 1)
                        self._send_to_dashboard({"type": "error"})
                        logging.error(f"👹 Error in '{_span_name}': {e}", exc_info=True)
                        span.record_exception(e)
                        span.set_status(Status(StatusCode.ERROR, f"Exception: {e}"))
                        span.set_attribute("error.type", type(e).__name__)
                        raise
                    finally:
                        duration_ms = (time.perf_counter() - start_time) * 1000
                        self.log_method_performance(_span_name, duration_ms)
                        span.set_attribute("duration.ms", duration_ms)
                        logging.info(f"🕒 '{_span_name}' finished in {duration_ms:.2f} ms.")
            return wrapper
        return decorator

    def log_rai_alert(self, alert_type: str, details: str):
        alert_data = {"type": alert_type, "details": details}
        with self._lock:
            self._metrics["rai_alerts"].append(alert_data)
        self._send_to_dashboard({"type": "rai_alert", "alert": alert_data})

    def check_responsible_ai(self, text: str, span: trace.Span) -> Dict:
        findings = []
        claimed_indices = set()
        complex_regex_patterns = {
            "CREDIT_CARD": re.compile(r'\b(?:credit card|card|cc)[\s\w:;#-]*?((?:\d[ -]*?){13,16})\b', re.IGNORECASE),
            "MRN": re.compile(r'\b(mrn|medical record|patient id|medical number|medical id)[\s\w:;#-]*?(\w[\w-]*\w)\b', re.IGNORECASE),
            "DATE_OF_BIRTH": re.compile(r'\b(dob|date of birth|birthday|birth date)[\s\w:;#-]*?(\d{1,2}[-/]\d{1,2}[-/]\d{2,4}|\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s\d{1,2},?\s\d{})\b', re.IGNORECASE),
        }
        for pii_type, pattern in complex_regex_patterns.items():
            for match in pattern.finditer(text):
                start, end = match.span()
                if pii_type == "CREDIT_CARD":
                    card_number_part = match.group(1)
                    cleaned_number = re.sub(r'[\s-]', '', card_number_part)
                    if not is_luhn_valid(cleaned_number):
                        for i in range(start, end):
                            claimed_indices.add(i)
                        logging.info(f"Found a credit-card-like pattern but it failed Luhn check. Blocking indices for spaCy.")
                        continue
                for i in range(start, end):
                    claimed_indices.add(i)
                redacted_text = f"[{pii_type}_REDACTED]"
                finding_details = {"type": pii_type, "details": f"Found pattern matching '{match.group(0)}' at index {match.start()}"}
                findings.append(finding_details)
                self.log_rai_alert(alert_type=pii_type, details=f"Found at index {match.start()}")
                span.add_event("rai_alert", {"type": pii_type, "match_text": redacted_text})

        simple_regex_patterns = {
            "SSN": re.compile(r'\b\d{3}-\d{2}-\d{3}\b'),
            "EMAIL": re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),
            "PHONE_NUMBER_US": re.compile(r'\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b'),
        }
        for pii_type, pattern in simple_regex_patterns.items():
            for match in pattern.finditer(text):
                start, end = match.span()
                if any(i in claimed_indices for i in range(start, end)):
                    continue
                for i in range(start, end):
                    claimed_indices.add(i)
                redacted_text = f"[{pii_type}_REDACTED]"
                finding_details = {"type": pii_type, "details": f"Found pattern matching '{match.group(0)}' at index {match.start()}"}
                findings.append(finding_details)
                self.log_rai_alert(alert_type=pii_type, details=f"Found at index {match.start()}")
                span.add_event("rai_alert", {"type": pii_type, "match_text": redacted_text})

        if self.nlp:
            doc = self.nlp(text)
            spacy_to_pii_map = {"PERSON": "PERSON_NAME", "GPE": "LOCATION", "LOC": "LOCATION", "DATE": "DATE_ENTITY", "ORG": "ORGANIZATION"}
            for ent in doc.ents:
                is_claimed = any(i in claimed_indices for i in range(ent.start_char, ent.end_char))
                if is_claimed:
                    logging.info(f"spaCy entity '{ent.text}' ({ent.label_}) overlaps with a high-precision match. Discarding.")
                    continue
                pii_type = spacy_to_pii_map.get(ent.label_)
                if pii_type:
                    redacted_text = f"[{pii_type}_REDACTED]"
                    finding_details = {"type": pii_type, "details": f"Found '{ent.text}' (redacted as {redacted_text}) at index {ent.start_char}"}
                    findings.append(finding_details)
                    self.log_rai_alert(alert_type=pii_type, details=f"Found at index {ent.start_char}")
                    span.add_event("rai_alert", {"type": pii_type, "original_text": ent.text})

        pii_found = len(findings) > 0
        span.set_attribute("rai.pii_found", pii_found)
        span.set_attribute("rai.findings_count", len(findings))
        return {
            "pii_found": pii_found,
            "findings_count": len(findings),
            "findings": findings
        }

    def shutdown(self):
        logging.info("Shutting down observability and notifying dashboard.")
        self._send_to_dashboard({"type": "session_end"})
        self.print_summary()
